#!/usr/bin/env python3
"""Validate the NX30 Pro firmware source lock and the built configuration.

The helper is the single place that knows what a build ready firmware lock
looks like. It refuses a lock that does not pin the source commit and the
feed revisions, that names the rejected Galaxian base or another repository,
that names another device profile, that does not match the partition contract
of the boot loader, whose hard gate packages are still unproven candidates,
whose package dependency no locked feed provides, or that hand edits the
build readiness flag without the evidence behind it.

A lock that is not build ready stops with the repository wide build not ready
status 3, the same code `uboot_lock.py` and `tools/manifest.py` use, and no
build plan is rendered for it: nothing may download or compile a source that
failed this gate.

The configuration check runs against the final .config that the build
produced, never against the fragment that was fed into it. `merge-config`
merges the config layers in the repository precedence common -> distribution
-> device, so the merge that produces that fragment is testable without a
source tree and cannot drop a hyphenated device layer override again.

Two further checks read the patched source tree instead of the lock alone:
`verify-device-tree` compares the NMBM partition table of the ported 112M
device tree with the partition contract, and `verify-image-rules` compares the
`Device/h3c_nx30pro_112M` block of the image rules with the locked profile,
image limit and image roles. Both compare exact values, so a profile of
another board, the stock 64M table or an approximate size fails.
"""

import argparse
import fnmatch
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path


# The repository wide build not ready status. A lock that fails this gate must
# not be distinguishable from an unresolved manifest target: both stop with 3.
BUILD_NOT_READY = 3
# The verdict of an authorized `make defconfig` probe whose hard gates did not
# all survive. It is distinct from a blocked lock so that a caller can tell
# "this candidate is unproven" from "this candidate was proven and failed".
PROBE_FOUND_MISSING_GATES = 4

COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")

# The only source repository this device may be built from. The lock records
# the rejected bases in source.rejected_sources; naming one of them, or any
# other tree, stops the build here.
ALLOWED_SOURCE_REPOSITORY = "https://github.com/hanwckf/immortalwrt-mt798x"

PACKAGE_STATUSES = ("candidate", "available", "partial", "unavailable", "UNRESOLVED")
UNPROVEN_STATUSES = ("unavailable", "UNRESOLVED")

EXPECTED_PROFILE = "h3c_nx30pro_112M"
EXPECTED_PROFILE_SYMBOL = "CONFIG_TARGET_mediatek_mt7981_DEVICE_h3c_nx30pro_112M=y"
EXPECTED_TARGET = "mediatek"
EXPECTED_SUBTARGET = "mt7981"

EXPECTED_PARTITIONS = [
    ("BL2", 0x000000, 0x100000),
    ("u-boot-env", 0x100000, 0x080000),
    ("Factory", 0x180000, 0x200000),
    ("FIP", 0x380000, 0x200000),
    ("ubi", 0x580000, 0x7000000),
]

# The partition contract is an NMBM logical one: the table has to hang off the
# NMBM mapping node of the pinned source, never off the raw spi-nand chip.
NMBM_NODE = "nmbm_spim_nand"
NMBM_BINDING = (
    'compatible = "generic,nmbm";',
    "lower-mtd-device = <&spi_nand>;",
    "forced-create;",
)

PARTITION_RE = re.compile(
    r"partition@([0-9a-fA-F]+)\s*\{\s*"
    r'label\s*=\s*"([^"]+)";\s*'
    r"reg\s*=\s*<\s*([^>]+?)\s*>;\s*\};",
    re.S,
)

DEVICE_BLOCK_RE = re.compile(r"^define Device/(\S+)\n(.*?)^endef\n", re.S | re.M)
DEVICE_FIELD_RE = re.compile(r"^\s*([A-Za-z0-9_.$()/+-]+)\s*(:=|\+=)\s*(.*?)\s*$")

REQUIRED_FEEDS = ("packages", "luci", "routing", "telephony")


class LockError(Exception):
    """The source lock is not build ready."""


class ConfigError(Exception):
    """The built configuration does not match the lock."""


class ArtifactError(Exception):
    """The build produced no publishable firmware candidate."""


# A ubinize image starts with the erase counter header of the first physical
# erase block, whose magic is the four ASCII bytes `UBI#` (mtd-utils
# libubigen, UBI_EC_HDR_MAGIC 0x55424923). A sysupgrade image of this profile
# is a POSIX tar archive (`sysupgrade-tar`), whose format magic sits at offset
# 257. Both facts make the two image roles distinguishable by content, so a
# file can never be published under the other role.
UBI_MAGIC = b"UBI#"
TAR_MAGIC = b"ustar"
TAR_MAGIC_OFFSET = 257

# The metadata trailer `append-metadata` writes with `fwtool -I` is the JSON of
# `metadata_json` (include/image-commands.mk of the pinned source), which names
# `metadata_version` and the `supported_devices` of the profile.
METADATA_VERSION_KEY = b'"metadata_version"'

# Secret and deployment value detection. The spellings mirror the ones
# tests/structure/test_nx30pro_firmware_contract.py uses for the committed
# overlay: the build gate scans the overlay that is really copied into the
# image, the contract test scans the one that is committed.
OVERLAY_IPV4 = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")
OVERLAY_PRIVATE_KEY = re.compile(r"BEGIN [A-Z ]*PRIVATE KEY")
OVERLAY_TOKEN = re.compile(
    r"(?<![A-Za-z0-9+/=.-])[A-Za-z0-9+/=]{24,}(?![A-Za-z0-9+/=.-])"
)
OVERLAY_MAC = re.compile(r"\b(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}\b")
OVERLAY_MAC_PLACEHOLDER = "aa:bb:cc:dd:ee:ff"
OVERLAY_ASSIGNMENT = re.compile(
    r"""(?xim)
    (?:
        ^\s*(?P<shell>[A-Za-z_][\w]*)\s*=
      | \buci[^\n]*\bset\s+\S*\.(?P<uci>\w+)\s*=
      | ^\s*(?:option|list)\s+(?P<config>\w+)
      | ^\s*(?P<yaml>[A-Za-z_][\w-]*)\s*:
    )
    (?P<value>[^\n]*)
    """,
)
OVERLAY_DEPLOYMENT_OPTIONS = frozenset(
    (
        "token",
        "secret",
        "password",
        "passwd",
        "passphrase",
        "key",
        "psk",
        "private_key",
        "credentials_file",
        "origincert",
        "account",
        "api_key",
        "subscription",
        "domain",
        "lookup_host",
        "username",
        "server_addr",
        "ssid",
        "mac",
        "ipaddr",
    )
)
# Address literals that carry no deployment information: the unspecified and
# the loopback address, netmasks and the two broadcast forms.
OVERLAY_IPV4_ALLOWED = frozenset(
    (
        "0.0.0.0",
        "127.0.0.1",
        "255.255.255.0",
        "255.255.255.255",
    )
)
# An assignment value that switches something off carries no secret.
OVERLAY_EMPTY_VALUES = frozenset(("", "''", '""', "0", "'0'", '"0"', "off", "false"))


def sha256_of(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_lock(path):
    try:
        lock = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise LockError("the source lock cannot be read: %s" % error)
    if not isinstance(lock, dict):
        raise LockError("the source lock is not a JSON object")
    return lock


def locked_revisions(lock):
    """Map every feed id plus the base tree to the commit that provides it."""
    revisions = {"base": (lock.get("source") or {}).get("revision")}
    for feed in lock.get("feeds") or []:
        revisions[feed.get("id")] = feed.get("revision")
    return revisions


def validate_source(lock, errors):
    source = lock.get("source") or {}
    revision = source.get("revision")
    if not isinstance(revision, str) or not COMMIT_RE.match(revision):
        errors.append(
            "the source revision must be a full 40 character commit id, got %r"
            % (revision,)
        )
    repository = source.get("repository")
    if repository != ALLOWED_SOURCE_REPOSITORY:
        errors.append(
            "the source repository must be %s, got %r"
            % (ALLOWED_SOURCE_REPOSITORY, repository)
        )
    for entry in source.get("rejected_sources") or []:
        if entry.get("status") != "rejected-evidence-only":
            errors.append(
                "the rejected source %r must stay rejected-evidence-only"
                % (entry.get("repository"),)
            )
            continue
        if (
            repository == entry.get("repository")
            or revision == entry.get("commit")
        ):
            errors.append(
                "the source %s at %s is recorded as rejected-evidence-only and "
                "must never be the active build base: %s"
                % (repository, revision, entry.get("reason"))
            )


def validate_packages(lock, errors):
    """Check the package table and the dependency index it resolves against."""
    revisions = locked_revisions(lock)
    index = lock.get("dependency_index") or {}

    for name, entry in index.items():
        provider = entry.get("provider")
        if provider not in revisions:
            errors.append(
                "the dependency %s names the unknown provider %r"
                % (name, provider)
            )
            continue
        if entry.get("revision") != revisions[provider]:
            errors.append(
                "the dependency %s is pinned to %r, not to the locked %s commit %r"
                % (name, entry.get("revision"), provider, revisions[provider])
            )
        if not entry.get("path"):
            errors.append("the dependency %s has no provider path" % name)

    packages = lock.get("packages") or []
    if not packages:
        errors.append("the lock has no package table")
    for entry in packages:
        name = entry.get("package") or "<unnamed>"
        status = entry.get("status")
        if status not in PACKAGE_STATUSES:
            errors.append(
                "the package %s has an unknown status %r" % (name, status)
            )
            continue
        for dependency in entry.get("dependencies") or []:
            if dependency not in index:
                errors.append(
                    "the package %s depends on %s, which no locked feed provides"
                    % (name, dependency)
                )
        if entry.get("version_pinned") and (
            not entry.get("version")
            or "PKG_VERSION" not in (entry.get("version_evidence") or "")
        ):
            errors.append(
                "the package %s pins a version without PKG_VERSION evidence"
                % name
            )
        elif entry.get("version") and not entry.get("version_evidence"):
            errors.append(
                "the package %s records a version without its evidence" % name
            )
        if status in UNPROVEN_STATUSES:
            if entry.get("feed_revision") is not None:
                errors.append(
                    "the package %s is %s but still pins the feed commit %r"
                    % (name, status, entry.get("feed_revision"))
                )
            continue
        provider = entry.get("feed")
        if provider not in revisions:
            errors.append(
                "the package %s names the unknown provider %r" % (name, provider)
            )
        elif entry.get("feed_revision") != revisions[provider]:
            errors.append(
                "the package %s is pinned to %r, not to the locked %s commit %r"
                % (
                    name,
                    entry.get("feed_revision"),
                    provider,
                    revisions[provider],
                )
            )
        if not entry.get("provider_path"):
            errors.append("the package %s has no provider path" % name)
        if entry.get("gate") == "hard" and not (entry.get("symbols") or []):
            errors.append(
                "the hard gate package %s names no config symbol" % name
            )
        if status == "available" and not entry.get("defconfig_evidence"):
            errors.append(
                "the package %s is marked available without `make defconfig` "
                "evidence from the final .config" % name
            )


def validate_readiness(lock, errors, allow_probe=False):
    """Recompute build_readiness from the package table.

    The flag is derived, never trusted: a hard gate that is still a candidate
    keeps the lock build blocked, and a hand edited ready=true is itself an
    error. This is what stops a candidate from being promoted by editing JSON.
    """
    readiness = lock.get("build_readiness")
    if not isinstance(readiness, dict):
        errors.append("the lock has no build_readiness record")
        return
    unproven = [
        entry.get("package")
        for entry in lock.get("packages") or []
        if entry.get("gate") == "hard"
        and (
            entry.get("status") != "available"
            or not entry.get("defconfig_evidence")
        )
    ]
    if readiness.get("ready"):
        if unproven:
            errors.append(
                "build_readiness claims the lock is ready while %d hard gate "
                "packages are still unproven: %s"
                % (len(unproven), ", ".join(str(name) for name in unproven))
            )
        return
    if not readiness.get("blocking"):
        errors.append(
            "build_readiness is not ready but lists no blocking reason"
        )
    if "defconfig" not in (readiness.get("required_evidence") or ""):
        errors.append(
            "build_readiness must name the `make defconfig` evidence it needs"
        )
    if unproven and not allow_probe:
        errors.append(
            "the hard gate packages %s are candidates: no authorized "
            "`make defconfig` probe proved them in the final .config yet, so "
            "the lock stays build blocked"
            % ", ".join(str(name) for name in unproven)
        )


def validate_device_port(lock, errors):
    """Check the record of the device port against the pinned source.

    The record is what ties the two patch files to the commit they were
    derived for: a patch that is recorded for another commit, a port that
    claims to come from anywhere but the recorded reference tree, or a patch
    list whose numbering is not deterministic all fail here. The content of
    the patches is checked by verify-device-tree and verify-image-rules
    against the patched source tree.
    """
    port = lock.get("device_port")
    source = lock.get("source") or {}
    if not isinstance(port, dict):
        errors.append("the lock has no device_port record")
        return
    if port.get("applies_to") != source.get("revision"):
        errors.append(
            "the device port is recorded for %r, the lock pins the source %r"
            % (port.get("applies_to"), source.get("revision"))
        )
    reference = (source.get("port_reference") or {}).get("revision")
    if port.get("derived_from") != reference:
        errors.append(
            "the device port claims to be derived from %r, the lock records the "
            "port reference %r" % (port.get("derived_from"), reference)
        )
    entries = port.get("patches") or []
    if not entries:
        errors.append("the device port records no patch")
    numbers = []
    for entry in entries:
        path = entry.get("path") or ""
        name = Path(path).name
        match = re.match(r"^(\d{4})-[a-z0-9-]+\.patch$", name)
        if not match:
            errors.append("the device patch %r is not deterministically numbered" % path)
        else:
            numbers.append(match.group(1))
        if not path.startswith("devices/nx30pro/patches/"):
            errors.append(
                "the device patch %r is not part of the device patch layer" % path
            )
        if entry.get("applies_to_commit") != source.get("revision"):
            errors.append(
                "the device patch %s is recorded for commit %r, the lock pins %r"
                % (name, entry.get("applies_to_commit"), source.get("revision"))
            )
        if not entry.get("upstream_files"):
            errors.append("the device patch %s names no upstream file" % name)
        if not entry.get("purpose"):
            errors.append("the device patch %s records no purpose" % name)
    if numbers != sorted(numbers) or len(set(numbers)) != len(numbers):
        errors.append(
            "the device patch numbering %s is not a deterministic order"
            % ", ".join(numbers)
        )


def validate_lock(lock, allow_probe=False):
    """Return the list of reasons why the lock is not build ready.

    `allow_probe` relaxes exactly one thing: a lock whose hard gates are still
    candidates is allowed, because proving them is what an authorized
    `make defconfig` probe is for. Every structural requirement still holds, a
    hand edited `ready: true` is still an error, and a probe never promotes a
    package to `available`.
    """
    errors = []
    validate_source(lock, errors)

    feeds = {}
    for feed in lock.get("feeds") or []:
        feeds[feed.get("id")] = feed
    for feed_id in REQUIRED_FEEDS:
        feed = feeds.get(feed_id)
        if not feed:
            errors.append("the feed %s is not locked" % feed_id)
            continue
        if not isinstance(feed.get("revision"), str) or not COMMIT_RE.match(
            feed["revision"]
        ):
            errors.append(
                "the feed %s must pin a full 40 character commit id, got %r"
                % (feed_id, feed.get("revision"))
            )
        if not feed.get("repository"):
            errors.append("the feed %s has no repository" % feed_id)

    target = lock.get("target") or {}
    if target.get("target") != EXPECTED_TARGET:
        errors.append(
            "the target must be %s, got %r" % (EXPECTED_TARGET, target.get("target"))
        )
    if target.get("subtarget") != EXPECTED_SUBTARGET:
        errors.append(
            "the subtarget must be %s, got %r"
            % (EXPECTED_SUBTARGET, target.get("subtarget"))
        )
    if target.get("profile") != EXPECTED_PROFILE:
        errors.append(
            "the profile must be %s, got %r"
            % (EXPECTED_PROFILE, target.get("profile"))
        )

    contract = lock.get("partition_contract") or {}
    actual = [
        (entry.get("label"), entry.get("offset"), entry.get("size"))
        for entry in contract.get("partitions") or []
    ]
    if actual != EXPECTED_PARTITIONS:
        errors.append(
            "the partition layout does not match the 112M contract of the boot loader"
        )

    validate_packages(lock, errors)
    validate_device_port(lock, errors)
    validate_readiness(lock, errors, allow_probe=allow_probe)

    return errors


def render_plan(lock, probe=False):
    source = lock["source"]
    return {
        "probe": bool(probe),
        "build_readiness": lock.get("build_readiness"),
        "device": lock.get("device"),
        "product": lock.get("product"),
        "status": lock.get("status"),
        "source_repository": source.get("repository"),
        "source_revision": source.get("revision"),
        "kernel": source.get("kernel"),
        "feeds": [
            {"id": feed["id"], "revision": feed["revision"]}
            for feed in lock.get("feeds") or []
        ],
        "target": lock.get("target"),
        "image": lock.get("image"),
        "partition_table": lock.get("partition_contract", {}).get("partitions"),
    }


def config_symbols(text):
    symbols = {}
    for line in text.splitlines():
        match = re.match(r"^(CONFIG_[A-Za-z0-9_-]+)=(.*)$", line)
        if match:
            symbols[match.group(1)] = match.group(2)
            continue
        match = re.match(r"^# (CONFIG_[A-Za-z0-9_-]+) is not set$", line)
        if match:
            symbols[match.group(1)] = None
    return symbols


# The merge regex may not narrow the symbol alphabet again: OpenWrt package
# symbols carry hyphens (`luci-i18n-base-zh-cn`, `dnsmasq-full`), and a merge
# that only accepted letters, digits and underscores silently dropped the
# device layer override of exactly those packages.
CONFIG_ASSIGNMENT_RE = re.compile(r"^(CONFIG_[A-Za-z0-9_-]+)=")
CONFIG_NOT_SET_RE = re.compile(r"^# (CONFIG_[A-Za-z0-9_-]+) is not set$")


def config_key(line):
    """Return the symbol a config line assigns, or None for any other line.

    An explicit `# CONFIG_x is not set` override is an assignment: it has to
    win over the `CONFIG_x=y` of an earlier layer exactly like a value does.
    """
    match = CONFIG_NOT_SET_RE.match(line)
    if match:
        return match.group(1)
    match = CONFIG_ASSIGNMENT_RE.match(line)
    if match:
        return match.group(1)
    return None


def merge_config_layers(layers):
    """Merge config layer texts in precedence order, the last layer wins.

    `layers` is ordered common -> distribution -> device. A symbol keeps the
    position of its first appearance so the comments of the layer that
    introduced it stay next to it; only its value is replaced.
    """
    merged = []
    position = {}
    for text in layers:
        for line in (text or "").splitlines():
            key = config_key(line)
            if key is None:
                merged.append(line)
                continue
            if key in position:
                merged[position[key]] = line
            else:
                position[key] = len(merged)
                merged.append(line)
    if not merged:
        return ""
    return "\n".join(merged) + "\n"


def symbol_state(symbols, name):
    """Classify one symbol of a final configuration.

    `absent` and `disabled` are kept apart: `make defconfig` writes the
    `is not set` override itself when it drops a package whose dependency is
    unmet, and that decision is evidence, not a missing line.
    """
    if name not in symbols:
        return "absent"
    value = symbols[name]
    if value is None:
        return "disabled"
    if value == "y":
        return "enabled"
    if value == "m":
        return "module"
    return "value:%s" % value


def entry_state(symbols, names):
    """Summarise the symbols of one package entry of the lock.

    An entry that names no symbol cannot be proven either way, so it is
    reported as `unsymbolled` instead of vacuously passing as enabled.
    """
    if not names:
        return {
            "state": "unsymbolled",
            "enabled_symbols": [],
            "missing_symbols": [],
        }
    states = {name: symbol_state(symbols, name) for name in names}
    enabled = sorted(name for name, state in states.items() if state == "enabled")
    missing = sorted(name for name, state in states.items() if state != "enabled")
    if not missing:
        state = "enabled"
    elif not enabled:
        off = [states[name] for name in missing]
        state = "disabled" if set(off) == {"disabled"} else "absent"
    else:
        state = "partial"
    return {
        "state": state,
        "enabled_symbols": enabled,
        "missing_symbols": [
            {"symbol": name, "state": states[name]} for name in missing
        ],
    }


def package_symbol(dependency):
    """The config symbol of a package the dependency index names."""
    return "CONFIG_PACKAGE_%s" % dependency


def device_tree_partitions(text):
    """Return (label, offset, size) of every partition node, in file order.

    A node whose unit address disagrees with the offset of its `reg` is a
    contradiction the preprocessor would still compile, so it is refused here
    instead of being silently normalized.
    """
    partitions = []
    for unit, label, register in PARTITION_RE.findall(text):
        values = register.split()
        if len(values) != 2:
            raise ConfigError(
                "the reg of the partition %s is not one <offset size> pair: %s"
                % (label, register)
            )
        try:
            offset, size = int(values[0], 0), int(values[1], 0)
        except ValueError as error:
            raise ConfigError(
                "the reg of the partition %s is not numeric: %s" % (label, error)
            )
        if int(unit, 16) != offset:
            raise ConfigError(
                "the partition %s is named partition@%s but starts at %#x"
                % (label, unit, offset)
            )
        partitions.append((label, offset, size))
    return partitions


def verify_device_tree(text, lock):
    """Check that the device tree carries the partition contract of the lock.

    The comparison is exact: every locked (label, offset, size) tuple has to
    appear in the locked order and nothing else may. The stock 64M table, an
    approximate UBI size, a renamed label or a table that is not bound to the
    NMBM logical device all fail.
    """
    errors = []
    contract = lock.get("partition_contract") or {}
    expected = [
        (entry["label"], entry["offset"], entry["size"])
        for entry in contract.get("partitions") or []
    ]
    if not expected:
        raise LockError("the lock carries no partition contract")

    node = text.find(NMBM_NODE)
    if node < 0:
        errors.append(
            "the device tree has no %s node, so the partition contract would "
            "not be an NMBM logical one" % NMBM_NODE
        )
    else:
        for token in NMBM_BINDING:
            if token not in text[node:]:
                errors.append(
                    "the %s node does not carry %s, the partitions would not be "
                    "bound to the NMBM logical device" % (NMBM_NODE, token)
                )
    if text.count("partitions {") != 1:
        errors.append(
            "the device tree carries %d partition tables, exactly one NMBM "
            "table is allowed" % text.count("partitions {")
        )

    actual = device_tree_partitions(text)
    if actual != expected:
        errors.append(
            "the device tree partitions %s are not the locked contract %s"
            % (actual, expected)
        )
    end_offset = contract.get("ubi_end_offset")
    if isinstance(end_offset, int) and actual:
        covered = actual[-1][1] + actual[-1][2]
        if covered != end_offset:
            errors.append(
                "the partition table ends at %#x, the locked UBI end offset is %#x"
                % (covered, end_offset)
            )
    if errors:
        raise ConfigError("; ".join(errors))
    return actual


def parse_device_blocks(text):
    """Return {profile: {field: value}} of every `define Device/<profile>`."""
    blocks = {}
    for profile, body in DEVICE_BLOCK_RE.findall(text):
        fields = {}
        for line in body.splitlines():
            match = DEVICE_FIELD_RE.match(line)
            if not match:
                continue
            key, operator, value = match.groups()
            if operator == "+=" and key in fields:
                fields[key] = "%s %s" % (fields[key], value)
            else:
                fields[key] = value
        blocks[profile] = fields
    return blocks


def verify_image_rules(text, lock):
    """Check the ported profile of the image rules against the lock.

    Only the block of the locked profile is read; a file full of other boards
    is normal. Every field is compared as an exact string, so a profile copied
    from another board, an approximate image limit or swapped factory and
    sysupgrade roles fail instead of passing a loose pattern.
    """
    target = lock.get("target") or {}
    image = lock.get("image") or {}
    profile = target.get("profile")
    if not profile:
        raise LockError("the lock names no target profile")

    blocks = parse_device_blocks(text)
    if profile not in blocks:
        raise ConfigError(
            "the image rules do not define the profile %s, they define %s"
            % (profile, ", ".join(sorted(blocks)) or "nothing")
        )
    fields = blocks[profile]

    expected = {
        "DEVICE_DTS": target.get("device_tree"),
        "SUPPORTED_DEVICES": target.get("supported_devices"),
        "IMAGE_SIZE": image.get("image_size"),
        "BLOCKSIZE": image.get("blocksize"),
        "PAGESIZE": image.get("pagesize"),
        "UBINIZE_OPTS": image.get("ubinize_opts"),
        "KERNEL_IN_UBI": None
        if image.get("kernel_in_ubi") is None
        else ("1" if image.get("kernel_in_ubi") else "0"),
        "IMAGE/%s" % image.get("factory_image"): image.get("factory_rule"),
        "IMAGE/%s" % image.get("sysupgrade_image"): image.get("sysupgrade_rule"),
    }
    errors = []
    for key, value in expected.items():
        if value is None:
            errors.append("the lock records no %s for the profile %s" % (key, profile))
            continue
        actual = fields.get(key)
        if actual != str(value):
            errors.append(
                "the profile %s sets %s to %r, the lock requires %r"
                % (profile, key, actual, str(value))
            )

    images = (fields.get("IMAGES") or "").split()
    factory_image = image.get("factory_image")
    sysupgrade_image = image.get("sysupgrade_image")
    default_images = image.get("images_default")
    if factory_image and factory_image not in images:
        errors.append(
            "the profile %s does not add %s to IMAGES, it adds %s"
            % (profile, factory_image, images or "nothing")
        )
    # The subtarget default already builds the sysupgrade image; a profile only
    # adds the factory one. Which image that default is comes from the lock, so
    # a changed subtarget default cannot pass unnoticed.
    if sysupgrade_image and sysupgrade_image != default_images:
        errors.append(
            "the lock records %r as the default image of the subtarget, not the "
            "sysupgrade image %r, so the profile would not build it"
            % (default_images, sysupgrade_image)
        )
    factory_rule = expected["IMAGE/%s" % factory_image]
    sysupgrade_rule = expected["IMAGE/%s" % sysupgrade_image]
    if factory_rule and factory_rule == sysupgrade_rule:
        errors.append(
            "the lock records the same rule for the factory and the sysupgrade "
            "image, the two roles must stay distinct"
        )
    if "check-size" not in (factory_rule or ""):
        errors.append(
            "the lock records a factory rule without check-size, the image "
            "limit would not be enforced"
        )
    if errors:
        raise ConfigError("; ".join(errors))
    return fields


def verify_config(text, lock, probe=False):
    """Audit the configuration the build really produced.

    The input is a final `.config`, the output of a real `make defconfig`,
    never the seed fragment that was merged into it. Three groups are audited
    separately and returned as one report:

    * hard gates - every symbol of every hard gate package has to be `=y`,
      and so has every dependency the lock enumerates for it. This gate does
      not depend on the `status` of the lock entry: an unproven candidate is
      exactly the configuration a probe produces, and a hard gate that
      `defconfig` dropped has to fail before anything is compiled.
    * optional packages - reported with their lock status. A package recorded
      `available` has to be enabled, a package recorded `unavailable` or
      `UNRESOLVED` may not be, and a candidate is simply reported.
    * exclusions - never enabled. An exclusion that names `replaced_by` also
      requires the replacement to be enabled, so a documented rootfs clash
      may not be resolved by losing both variants.

    Every miss is collected, so one report names the whole group that
    disappeared instead of only its first member.
    """
    symbols = config_symbols(text)
    errors = []
    audited = {}

    def audit(name):
        audited[name] = symbols.get(name)

    profile_symbol = EXPECTED_PROFILE_SYMBOL.split("=")[0]
    audit(profile_symbol)
    if symbols.get(profile_symbol) != "y":
        errors.append(
            "the configuration does not select the NX30 Pro 112M profile %s"
            % EXPECTED_PROFILE_SYMBOL
        )
    profiles = sorted(
        name
        for name, value in symbols.items()
        if name.startswith("CONFIG_TARGET_mediatek_mt7981_DEVICE_") and value == "y"
    )
    for name in profiles:
        audit(name)
    if len(profiles) != 1:
        errors.append(
            "the configuration selects %d device profiles (%s), exactly one is "
            "required" % (len(profiles), ", ".join(profiles) or "none")
        )

    hard_gates = []
    optional = []
    for entry in lock.get("packages") or []:
        name = entry.get("package") or "<unnamed>"
        requirement = entry.get("requirement") or name
        status = entry.get("status")
        names = entry.get("symbols") or []
        for symbol in names:
            audit(symbol)
        summary = entry_state(symbols, names)
        record = {
            "package": name,
            "requirement": requirement,
            "status": status,
            "symbols": names,
            "state": summary["state"],
            "enabled_symbols": summary["enabled_symbols"],
            "missing_symbols": summary["missing_symbols"],
        }
        if entry.get("gate") == "hard":
            hard_gates.append(record)
            for miss in summary["missing_symbols"]:
                errors.append(
                    "the hard gate %s is not enabled in the final "
                    "configuration: %s is %s (requirement: %s)"
                    % (name, miss["symbol"], miss["state"], requirement)
                )
            for dependency in entry.get("dependencies") or []:
                symbol = package_symbol(dependency)
                audit(symbol)
                state = symbol_state(symbols, symbol)
                if state not in ("enabled", "module"):
                    errors.append(
                        "the dependency %s of the hard gate %s is %s in the "
                        "final configuration, so the feed that indexes %s does "
                        "not provide its closure (requirement: %s)"
                        % (dependency, name, state, name, requirement)
                    )
            continue
        optional.append(record)
        if status == "available" and summary["state"] != "enabled":
            errors.append(
                "the package %s is recorded available with `make defconfig` "
                "evidence but is %s in this final configuration"
                % (name, summary["state"])
            )
        elif status in UNPROVEN_STATUSES and summary["enabled_symbols"]:
            errors.append(
                "the package %s is recorded %s and may not enter the image, "
                "but %s is enabled"
                % (name, status, ", ".join(summary["enabled_symbols"]))
            )

    excluded = []
    for entry in lock.get("excluded_packages") or []:
        name = entry.get("package")
        if not name:
            continue
        symbol = package_symbol(name)
        audit(symbol)
        state = symbol_state(symbols, symbol)
        replacement = entry.get("replaced_by")
        if replacement:
            audit(replacement)
        excluded.append(
            {
                "package": name,
                "state": state,
                "reason": entry.get("reason"),
                "replaced_by": replacement,
                "replacement_state": symbol_state(symbols, replacement)
                if replacement
                else None,
            }
        )
        if state == "enabled":
            errors.append(
                "the excluded package %s stayed enabled: %s" % (name, entry.get("reason"))
            )
        if replacement and symbol_state(symbols, replacement) != "enabled":
            errors.append(
                "the excluded package %s is replaced by %s, but that "
                "replacement is %s in the final configuration, so the image "
                "would lose %s entirely"
                % (
                    name,
                    replacement,
                    symbol_state(symbols, replacement),
                    name,
                )
            )

    report = {
        "profile": EXPECTED_PROFILE,
        "hard_gates": hard_gates,
        "optional": optional,
        "excluded": excluded,
        "symbols": audited,
    }
    if errors:
        if not probe:
            raise ConfigError("; ".join(errors))
        # A probe reports the whole verdict instead of raising on the first
        # miss; the key exists only then, so the shape of a passing audit of a
        # normal build is unchanged.
        report["errors"] = errors
    return report


def git_head(path):
    """Return the commit a checkout is at."""
    result = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise LockError(
            "%s is not a git checkout: %s" % (path, result.stderr.strip())
        )
    return result.stdout.strip()


def git_status(path):
    """Return the local changes of a checkout, one line per path."""
    result = subprocess.run(
        ["git", "-C", str(path), "status", "--porcelain"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise LockError(
            "%s cannot be inspected for local changes: %s"
            % (path, result.stderr.strip())
        )
    return [line for line in result.stdout.splitlines() if line.strip()]


def patch_applies(source_dir, patch_path):
    """Dry run one device patch against the checkout."""
    result = subprocess.run(
        ["git", "-C", str(source_dir), "apply", "--check", str(patch_path)],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0, (result.stderr or "").strip()


def locked_patches(lock, repo_root):
    """Return the recorded device patches in their locked application order."""
    port = lock.get("device_port") or {}
    records = port.get("patches") or []
    if not records:
        raise LockError("the lock records no device patch")
    ordered = sorted(records, key=lambda entry: Path(entry.get("path", "")).name)
    resolved = []
    for entry in ordered:
        path = Path(repo_root) / entry["path"]
        if not path.is_file():
            raise LockError("the lock names a device patch that is missing: %s" % path)
        applies_to = entry.get("applies_to_commit")
        if applies_to and applies_to != lock["source"]["revision"]:
            raise LockError(
                "the device patch %s is recorded for %s, the lock pins %s"
                % (path.name, applies_to, lock["source"]["revision"])
            )
        resolved.append({"path": path, "record": entry})
    return resolved


def untracked_output(source_dir, name):
    """Return the entries of a build directory that git does not track.

    The pinned base TRACKS a `dl` directory with pre-downloaded vendor blobs
    even though its .gitignore lists `/dl/*`, so a pristine checkout has one.
    Existence alone therefore proves nothing: only content that git does not
    track is the output of an earlier build. Ignored files never appear in
    `git status`, which is why the dirty tree check cannot catch them.
    """
    directory = Path(source_dir) / name
    if not directory.exists():
        return []
    result = subprocess.run(
        ["git", "-C", str(source_dir), "ls-files", "--", name],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise LockError(
            "the tracked content of %s cannot be listed, so an earlier build "
            "output cannot be told apart from the pinned source" % name
        )
    tracked = {
        line.split("/")[1] for line in result.stdout.splitlines()
        if line.strip() and "/" in line
    }
    actual = {entry.name for entry in directory.iterdir()}
    return sorted(actual - tracked)


def preflight(lock, source_dir, feed_dir, repo_root=None, allow_probe=False):
    """Run every check that has to pass before anything is downloaded.

    The gate covers the checkout identity, a dirty tree, the output of an
    earlier build, the revision of every pinned feed and the applicability of
    every recorded device patch. It only reads; the patches are applied by
    configure.sh, which runs after this gate and before `make download`.
    """
    errors = validate_lock(lock, allow_probe=allow_probe)
    if errors:
        raise LockError("; ".join(errors))

    repo_root = Path(repo_root) if repo_root else Path(__file__).resolve().parents[3]
    source_dir = Path(source_dir)
    feed_dir = Path(feed_dir)
    revision = lock["source"]["revision"]

    if not (source_dir / ".git").exists():
        raise LockError("the source directory is not a git checkout: %s" % source_dir)
    head = git_head(source_dir)
    if head != revision:
        raise LockError(
            "the source checkout is at %s, the lock pins %s" % (head, revision)
        )
    dirty = git_status(source_dir)
    if dirty:
        raise LockError(
            "the source checkout carries local changes: %s" % ", ".join(dirty[:5])
        )
    for leftover in ("bin", "build_dir", "staging_dir", "dl"):
        untracked = untracked_output(source_dir, leftover)
        if untracked:
            raise LockError(
                "the source directory holds output of an earlier build: %s (%s)"
                % (leftover, ", ".join(untracked[:5]))
            )

    feeds = []
    for feed in lock.get("feeds") or []:
        path = feed_dir / feed["id"]
        if not path.is_dir():
            raise LockError("the pinned feed %s is missing: %s" % (feed["id"], path))
        actual = git_head(path)
        if actual != feed["revision"]:
            raise LockError(
                "the feed %s is at %s, the lock pins %s"
                % (feed["id"], actual, feed["revision"])
            )
        feeds.append(
            {
                "id": feed["id"],
                "repository": feed["repository"],
                "locked_revision": feed["revision"],
                "checked_out_revision": actual,
            }
        )

    # The two recorded patches touch disjoint files (the lock states that in
    # device_port.order_note), so each one is dry run against the pristine
    # tree; configure.sh applies them in the same order for real.
    patches = []
    for entry in locked_patches(lock, repo_root):
        applies, detail = patch_applies(source_dir, entry["path"])
        if not applies:
            raise LockError(
                "the device patch does not apply to the locked source: %s (%s)"
                % (entry["path"].name, detail or "git apply --check failed")
            )
        patches.append(
            {
                "path": str(entry["path"].relative_to(repo_root)),
                "upstream_files": entry["record"].get("upstream_files") or [],
                "applies": True,
            }
        )

    return {
        "source_revision": revision,
        "checked_out_revision": head,
        "feeds": feeds,
        "patches": patches,
    }


def overlay_findings(overlay_dir):
    """Return every secret or deployment value one overlay file carries."""
    overlay_dir = Path(overlay_dir)
    findings = []
    for path in sorted(overlay_dir.rglob("*")):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            findings.append(
                {
                    "file": str(path.relative_to(overlay_dir)),
                    "finding": "a binary file cannot be scanned for secrets",
                }
            )
            continue
        relative = str(path.relative_to(overlay_dir))
        if OVERLAY_PRIVATE_KEY.search(text):
            findings.append(
                {"file": relative, "finding": "private key material"}
            )
        for literal in OVERLAY_MAC.findall(text):
            if literal.lower() != OVERLAY_MAC_PLACEHOLDER:
                findings.append(
                    {"file": relative, "finding": "a MAC address: %s" % literal}
                )
        for literal in OVERLAY_IPV4.findall(text):
            if literal not in OVERLAY_IPV4_ALLOWED:
                findings.append(
                    {"file": relative, "finding": "an address literal: %s" % literal}
                )
        for match in OVERLAY_ASSIGNMENT.finditer(text):
            name = (match.group("shell") or match.group("uci")
                    or match.group("config") or match.group("yaml") or "")
            value = (match.group("value") or "").strip().strip("'\"")
            if name.lower() not in OVERLAY_DEPLOYMENT_OPTIONS:
                continue
            if value.strip("'\"") in OVERLAY_EMPTY_VALUES:
                continue
            findings.append(
                {
                    "file": relative,
                    "finding": "the deployment option %s carries the value %r"
                    % (name, value),
                }
            )
        for literal in OVERLAY_TOKEN.findall(text):
            findings.append({"file": relative, "finding": "a token shaped literal"})
            break
    return findings


def verify_overlay(overlay_dir):
    """Refuse an overlay that would put a secret into the image."""
    overlay_dir = Path(overlay_dir)
    if not overlay_dir.is_dir():
        raise LockError("the overlay directory is missing: %s" % overlay_dir)
    findings = overlay_findings(overlay_dir)
    files = sum(1 for path in overlay_dir.rglob("*") if path.is_file())
    if findings:
        raise LockError(
            "the overlay carries deployment data and must not enter the image: "
            + "; ".join(
                "%s: %s" % (item["file"], item["finding"]) for item in findings[:8]
            )
        )
    return {"overlay_dir": str(overlay_dir), "files": files, "findings": []}


def artifact_roles(lock):
    """Return the resolution pattern of every firmware image role.

    The final prefix of an image name is `$(IMG_PREFIX)-$(1)-$(2)` and
    IMG_PREFIX carries build time version variables, so the exact names are
    UNRESOLVED in the lock and only the role suffix plus the profile segment
    are known. A role is therefore resolved by the pattern
    `*<profile_segment>-<suffix>`, which is the same wildcard the device
    manifest records in `artifact_patterns`.
    """
    image = lock.get("image") or {}
    naming = image.get("artifact_naming") or {}
    profile = naming.get("profile_segment") or (lock.get("target") or {}).get("profile")
    if not profile:
        raise LockError("the lock names no profile segment for the artifact names")
    roles = {}
    for role in ("factory", "sysupgrade"):
        suffix = naming.get("%s_suffix" % role) or image.get("%s_image" % role)
        if not suffix:
            raise LockError("the lock names no %s image suffix" % role)
        roles[role] = {
            "suffix": suffix,
            "pattern": "*%s-%s" % (profile, suffix),
            "rule": image.get("%s_rule" % role),
            "role": image.get("%s_role" % role),
        }
    if roles["factory"]["pattern"] == roles["sysupgrade"]["pattern"]:
        raise LockError("the two image roles resolve to the same pattern")
    return roles


def image_dir_for(lock, source_dir):
    """The buildroot output directory of the locked target and subtarget."""
    target = (lock.get("target") or {}).get("target")
    subtarget = (lock.get("target") or {}).get("subtarget")
    if not target or not subtarget:
        raise LockError("the lock names no target or subtarget")
    return Path(source_dir) / "bin" / "targets" / target / subtarget


def read_head(path, length):
    with open(path, "rb") as handle:
        return handle.read(length)


def has_tar_magic(path):
    return read_head(path, TAR_MAGIC_OFFSET + len(TAR_MAGIC))[
        TAR_MAGIC_OFFSET:TAR_MAGIC_OFFSET + len(TAR_MAGIC)
    ] == TAR_MAGIC


def inspect_factory_image(path, max_size, blocksize_kib):
    """Classify one candidate as the raw UBI image of the ubi partition."""
    size = path.stat().st_size
    if size == 0:
        raise ArtifactError("the factory image %s is empty" % path.name)
    if size > max_size:
        raise ArtifactError(
            "the factory image %s is %d bytes and exceeds the %d byte image limit"
            % (path.name, size, max_size)
        )
    if read_head(path, len(UBI_MAGIC)) != UBI_MAGIC:
        raise ArtifactError(
            "the factory image %s does not start with the UBI erase counter magic, "
            "so it is not the raw UBI image of the ubi partition" % path.name
        )
    if has_tar_magic(path):
        raise ArtifactError(
            "the factory image %s is a sysupgrade tar archive, the two image "
            "roles are swapped" % path.name
        )
    block = blocksize_kib * 1024
    if size % block:
        raise ArtifactError(
            "the factory image %s is %d bytes and not a multiple of the %d byte "
            "erase block" % (path.name, size, block)
        )
    return {"image": "factory", "size": size, "sha256": sha256_of(path), "ubi": True}


def inspect_sysupgrade_image(path, max_size, supported_devices):
    """Classify one candidate as the sysupgrade tar with its metadata."""
    size = path.stat().st_size
    if size == 0:
        raise ArtifactError("the sysupgrade image %s is empty" % path.name)
    if size > max_size:
        raise ArtifactError(
            "the sysupgrade image %s is %d bytes and exceeds the %d byte image limit"
            % (path.name, size, max_size)
        )
    if read_head(path, len(UBI_MAGIC)) == UBI_MAGIC:
        raise ArtifactError(
            "the sysupgrade image %s is a raw UBI image, the two image roles "
            "are swapped" % path.name
        )
    if not has_tar_magic(path):
        raise ArtifactError(
            "the sysupgrade image %s is not a sysupgrade tar archive" % path.name
        )
    blob = path.read_bytes()
    if METADATA_VERSION_KEY not in blob:
        raise ArtifactError(
            "the sysupgrade image %s carries no append-metadata trailer" % path.name
        )
    for device in supported_devices or []:
        if device.encode("utf-8") not in blob:
            raise ArtifactError(
                "the sysupgrade image %s metadata does not support %s"
                % (path.name, device)
            )
    return {
        "image": "sysupgrade",
        "size": size,
        "sha256": sha256_of(path),
        "metadata_version": True,
        "supported_devices": list(supported_devices or []),
    }


def resolve_artifacts(lock, image_dir):
    """Resolve and inspect both firmware image roles before anything is copied.

    A missing, empty, ambiguous, oversized or wrongly typed image stops the
    build here, and the two roles are told apart by their content, so the
    factory image can never be published as the sysupgrade image or the other
    way round.
    """
    image_dir = Path(image_dir)
    if not image_dir.is_dir():
        raise ArtifactError(
            "the build produced no image directory: %s, so there is no factory "
            "image and no sysupgrade image to publish" % image_dir
        )
    roles = artifact_roles(lock)
    image = lock["image"]
    max_size = int(image["image_size_kib"]) * 1024
    blocksize_kib = parse_size_kib(image.get("blocksize"))
    supported = (lock.get("target") or {}).get("supported_devices") or ""
    supported_devices = [item for item in supported.split() if item]

    candidates = sorted(path for path in image_dir.iterdir() if path.is_file())
    resolved = []
    for role in ("factory", "sysupgrade"):
        entry = roles[role]
        matches = [
            path for path in candidates
            if fnmatch.fnmatchcase(path.name, entry["pattern"])
        ]
        if not matches:
            raise ArtifactError(
                "the build produced no %s image matching %s in %s"
                % (role, entry["pattern"], image_dir)
            )
        if len(matches) > 1:
            raise ArtifactError(
                "the %s pattern %s is ambiguous, the image directory holds %s. "
                "Build in a clean checkout so an earlier image cannot be published "
                "as this one."
                % (role, entry["pattern"], ", ".join(path.name for path in matches))
            )
        path = matches[0]
        if path.stat().st_size == 0:
            raise ArtifactError("the %s image %s is empty" % (role, path.name))
        if role == "factory":
            info = inspect_factory_image(path, max_size, blocksize_kib)
        else:
            info = inspect_sysupgrade_image(path, max_size, supported_devices)
        info["role"] = role
        info["kind"] = role
        info["name"] = path.name
        info["file"] = path.name
        info["path"] = str(path)
        info["pattern"] = entry["pattern"]
        info["size_limit"] = max_size
        resolved.append(info)
    return resolved


def parse_size_kib(text):
    """Read a buildroot size such as `128k` as kibibytes."""
    match = re.match(r"^(\d+)k$", str(text or ""), re.I)
    if not match:
        raise LockError("the lock records no parseable block size: %r" % (text,))
    return int(match.group(1))


def feed_lock_evidence(lock, feed_dir):
    """Record the revision every feed really was checked out at."""
    evidence = []
    for feed in lock.get("feeds") or []:
        path = Path(feed_dir) / feed["id"]
        if not path.is_dir():
            raise ArtifactError(
                "the feed %s the build used is gone: %s" % (feed["id"], path)
            )
        actual = git_head(path)
        if actual != feed["revision"]:
            raise ArtifactError(
                "the feed %s moved to %s, the lock pins %s"
                % (feed["id"], actual, feed["revision"])
            )
        evidence.append(
            {
                "id": feed["id"],
                "repository": feed["repository"],
                "locked_revision": feed["revision"],
                "built_revision": actual,
            }
        )
    return evidence


def image_roles_text(lock):
    """The human readable statement of what the two published images are."""
    image = lock["image"]
    return """These files are firmware candidates built from the pinned source. They
were not verified on hardware and they are not boot loader images.

factory image: %s
  %s
sysupgrade image: %s
  %s

The exact file name prefix is resolved by the buildroot at build time and is
recorded as UNRESOLVED in the lock, so both images are resolved by their role
suffix and profile segment instead of by a hard coded name.

The boot loader images (BL2 and FIP) are built by
devices/nx30pro/build/build-uboot.sh and are not part of this build. The
partition offsets of the boot loader contract are NMBM logical addresses, not
physical NAND addresses. No command in this artifact directory writes to a
flash device.
""" % (
        image.get("factory_image"),
        image.get("factory_role"),
        image.get("sysupgrade_image"),
        image.get("sysupgrade_role"),
    )


def require_evidence(path, what, non_empty=True):
    """Refuse to publish an evidence bundle with a missing member.

    A log has to exist but may legitimately be short, while the final
    configuration and the package manifest carry the evidence themselves and
    are refused when they are empty.
    """
    path = Path(path)
    if not path.is_file():
        raise ArtifactError("the evidence bundle has no %s: %s" % (what, path))
    if non_empty and path.stat().st_size == 0:
        raise ArtifactError("the %s of the evidence bundle is empty: %s" % (what, path))
    return path


REQUIRED_LOGS = (
    "build-plan.json",
    "preflight.json",
    "configure.log",
    "download.log",
    "build.log",
    "artifacts.json",
)


def publish_candidate(
    lock,
    artifact_dir,
    image_dir,
    source_dir,
    feed_dir,
    build_env,
    packages,
    logs_dir,
):
    """Publish the inspected images together with their provenance.

    Packaging is the last stage and it re-reads the evidence instead of
    trusting the earlier exit codes: a successful configuration alone can never
    be published as a candidate build, because the images, the final
    configuration audit, the package manifest, the feed revisions, the hashes
    and the logs are all required here.
    """
    artifact_dir = Path(artifact_dir)
    source_dir = Path(source_dir)
    artifacts = resolve_artifacts(lock, image_dir)

    final_config = require_evidence(source_dir / ".config", "final .config")
    audit = verify_config(final_config.read_text(encoding="utf-8"), lock)
    package_list = require_evidence(packages, "package manifest")
    logs_dir = Path(logs_dir)
    logs = {
        name: str(
            require_evidence(
                logs_dir / name, "build log %s" % name, non_empty=False
            )
        )
        for name in REQUIRED_LOGS
    }
    feeds = feed_lock_evidence(lock, feed_dir)

    images = artifact_dir / "images"
    images.mkdir(parents=True, exist_ok=True)
    sums = []
    for item in artifacts:
        target = images / item["name"]
        shutil.copyfile(item["path"], target)
        target.chmod(0o644)
        sums.append("%s  %s" % (item["sha256"], item["name"]))
    (images / "SHA256SUMS").write_text(
        "\n".join(sorted(sums)) + "\n", encoding="utf-8"
    )

    shutil.copyfile(final_config, artifact_dir / "final.config")
    shutil.copyfile(package_list, artifact_dir / "packages.txt")
    (artifact_dir / "feeds-lock.json").write_text(
        json.dumps(feeds, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    report = build_report(
        lock,
        artifacts,
        build_env,
        {
            "config_audit": audit,
            "package_list": package_list.read_text(encoding="utf-8"),
            "feeds_checked_out": feeds,
            "evidence": {
                "final_config": "final.config",
                "packages": "packages.txt",
                "feed_lock": "feeds-lock.json",
                "image_hashes": "images/SHA256SUMS",
                "logs": sorted(logs),
            },
        },
    )
    (artifact_dir / "build-report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (artifact_dir / "IMAGE-ROLES.txt").write_text(
        image_roles_text(lock), encoding="utf-8"
    )
    return report


def build_report(lock, artifacts, build_env, extra=None):
    """Assemble the build report of one firmware build."""
    reported = []
    for artifact in artifacts:
        path = Path(artifact["path"])
        reported.append(
            {
                "file": artifact.get("file") or path.name,
                "role": artifact.get("role"),
                "size": path.stat().st_size,
                "sha256": sha256_of(path),
            }
        )
    report = {
        "device": lock.get("device"),
        "product": lock.get("product"),
        "status": "candidate-not-verified-on-device",
        "source_repository": lock["source"]["repository"],
        "source_revision": lock["source"]["revision"],
        "kernel": lock["source"].get("kernel"),
        "feeds": [
            {"id": feed["id"], "revision": feed["revision"]}
            for feed in lock.get("feeds") or []
        ],
        "target": lock.get("target"),
        "image": lock.get("image"),
        "build_parameters": dict(build_env or {}),
        "partition_table": lock.get("partition_contract", {}).get("partitions"),
        "package_table": lock.get("packages"),
        "excluded_packages": lock.get("excluded_packages"),
        "artifacts": reported,
        "notes": [
            "The images are firmware candidates. They were not verified on hardware.",
            "The partition offsets are NMBM logical addresses, not physical NAND addresses.",
        ],
    }
    if extra:
        report.update(extra)
    return report


def command_check(args):
    lock = load_lock(args.lock)
    allow_probe = bool(getattr(args, "allow_probe", False))
    errors = validate_lock(lock, allow_probe=allow_probe)
    if errors:
        for error in errors:
            print("Error: %s" % error, file=sys.stderr)
        # No plan is rendered for a blocked lock: the caller must not receive
        # anything it could feed to a download or a compile step.
        return BUILD_NOT_READY
    print(json.dumps(render_plan(lock, probe=allow_probe), indent=2, sort_keys=True))
    return 0


def locked_source_path(lock, kind):
    """Return the source tree path of the device tree or the image rules."""
    if kind == "device-tree":
        path = (lock.get("target") or {}).get("device_tree_file")
    elif kind == "image-rules":
        path = (lock.get("image") or {}).get("rules_file")
    else:
        raise LockError("unknown source file kind %r" % (kind,))
    if not path:
        raise LockError("the lock records no %s path" % kind)
    return path


def read_locked_source(lock, kind, explicit, source_dir):
    """Read one file of the patched source tree.

    Either the caller names the file directly or it names the patched source
    tree and the lock says where the file lives inside it. Reading it from the
    lock keeps a moved upstream path from being silently accepted.
    """
    if explicit:
        path = Path(explicit)
    elif source_dir:
        path = Path(source_dir) / locked_source_path(lock, kind)
    else:
        raise LockError("the %s check needs --source-dir or an explicit path" % kind)
    if not path.is_file():
        raise LockError("the %s source file is missing: %s" % (kind, path))
    return path.read_text(encoding="utf-8")


def command_verify_config(args):
    lock = load_lock(args.lock)
    path = Path(args.config)
    if not path.is_file():
        raise LockError("the final configuration is missing: %s" % path)
    text = path.read_text(encoding="utf-8")
    probe = bool(getattr(args, "probe", False))
    report = verify_config(text, lock, probe=probe)
    print(json.dumps(report, indent=2, sort_keys=True))
    if report.get("errors"):
        for error in report["errors"]:
            print("Error: %s" % error, file=sys.stderr)
        # A probe reports what `make defconfig` really did to the hard gates;
        # the evidence is on stdout, the verdict is this distinct status.
        return PROBE_FOUND_MISSING_GATES if probe else BUILD_NOT_READY
    return 0


def command_merge_config(args):
    layers = []
    for path in args.layer:
        layer = Path(path)
        if not layer.is_file():
            raise LockError("the configuration layer is missing: %s" % layer)
        layers.append(layer.read_text(encoding="utf-8"))
    if not layers:
        raise LockError("merge-config needs at least one configuration layer")
    merged = merge_config_layers(layers)
    out = Path(args.out)
    out.write_text(merged, encoding="utf-8")
    print(
        "Merged %d configuration layers into %s; the last layer wins."
        % (len(layers), out)
    )
    return 0


def command_verify_device_tree(args):
    lock = load_lock(args.lock)
    text = read_locked_source(
        lock, "device-tree", args.dts, args.source_dir
    )
    partitions = verify_device_tree(text, lock)
    print(
        json.dumps(
            {
                "profile": (lock.get("target") or {}).get("profile"),
                "address_space": (lock.get("partition_contract") or {}).get(
                    "address_space"
                ),
                "partitions": [
                    {"label": label, "offset": offset, "size": size}
                    for label, offset, size in partitions
                ],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def command_verify_image_rules(args):
    lock = load_lock(args.lock)
    text = read_locked_source(
        lock, "image-rules", args.image_rules, args.source_dir
    )
    fields = verify_image_rules(text, lock)
    print(
        json.dumps(
            {"profile": (lock.get("target") or {}).get("profile"), "fields": fields},
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def command_preflight(args):
    lock = load_lock(args.lock)
    report = preflight(
        lock, args.source_dir, args.feed_dir, repo_root=args.repo_root or None,
        allow_probe=bool(getattr(args, "allow_probe", False)),
    )
    write_json(report, args.out)
    return 0


def command_verify_overlay(args):
    report = verify_overlay(args.overlay_dir)
    write_json(report, args.out)
    return 0


def command_artifacts(args):
    lock = load_lock(args.lock)
    image_dir = args.image_dir or (
        str(image_dir_for(lock, args.source_dir)) if args.source_dir else ""
    )
    if not image_dir:
        raise ArtifactError("the artifact check needs --image-dir or --source-dir")
    artifacts = resolve_artifacts(lock, image_dir)
    write_json({"image_dir": image_dir, "artifacts": artifacts}, args.out)
    return 0


def command_publish(args):
    lock = load_lock(args.lock)
    errors = validate_lock(lock)
    if errors:
        for error in errors:
            print("Error: %s" % error, file=sys.stderr)
        return BUILD_NOT_READY
    image_dir = args.image_dir or image_dir_for(lock, args.source_dir)
    build_env = json.loads(args.build_env) if args.build_env else {}
    report = publish_candidate(
        lock,
        args.artifact_dir,
        image_dir,
        args.source_dir,
        args.feed_dir,
        build_env,
        args.packages,
        args.logs_dir,
    )
    Path(args.artifact_dir, "source-lock.json").write_text(
        Path(args.lock).read_text(encoding="utf-8"), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "artifacts": [
                    {"role": item["role"], "file": item["file"], "sha256": item["sha256"]}
                    for item in report["artifacts"]
                ],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def write_json(report, out=""):
    """Print one evidence report and copy it into the log directory."""
    text = json.dumps(report, indent=2, sort_keys=True)
    print(text)
    if out:
        path = Path(out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    check = subparsers.add_parser("check", help="validate the source lock")
    check.add_argument("--lock", required=True)
    check.add_argument(
        "--allow-probe",
        action="store_true",
        help="accept a lock whose hard gates are still candidates, for an "
        "authorized `make defconfig` probe only",
    )
    check.set_defaults(handler=command_check)

    verify = subparsers.add_parser(
        "verify-config", help="check the configuration the build produced"
    )
    verify.add_argument("--lock", required=True)
    verify.add_argument("--config", required=True)
    verify.add_argument(
        "--probe",
        action="store_true",
        help="report every missing hard gate instead of raising on the first "
        "one, and answer with the probe verdict status",
    )
    verify.set_defaults(handler=command_verify_config)

    merge = subparsers.add_parser(
        "merge-config",
        help="merge config layers in precedence order, the last layer wins",
    )
    merge.add_argument("--out", required=True)
    merge.add_argument("layer", nargs="+", help="common, distribution, device")
    merge.set_defaults(handler=command_merge_config)

    verify_tree = subparsers.add_parser(
        "verify-device-tree", help="check the partition contract of the device tree"
    )
    verify_tree.add_argument("--lock", required=True)
    verify_tree.add_argument("--dts", default="")
    verify_tree.add_argument(
        "--source-dir",
        default="",
        help="the patched source tree; the lock names the device tree inside it",
    )
    verify_tree.set_defaults(handler=command_verify_device_tree)

    verify_rules = subparsers.add_parser(
        "verify-image-rules", help="check the ported profile of the image rules"
    )
    verify_rules.add_argument("--lock", required=True)
    verify_rules.add_argument("--image-rules", default="")
    verify_rules.add_argument(
        "--source-dir",
        default="",
        help="the patched source tree; the lock names the image rules inside it",
    )
    verify_rules.set_defaults(handler=command_verify_image_rules)

    report = subparsers.add_parser(
        "preflight", help="verify the checkout, the feeds and the device patches"
    )
    report.add_argument("--lock", required=True)
    report.add_argument("--source-dir", required=True)
    report.add_argument("--feed-dir", required=True)
    report.add_argument("--repo-root", default="")
    report.add_argument("--out", default="")
    report.add_argument(
        "--allow-probe",
        action="store_true",
        help="accept a lock whose hard gates are still candidates, for an "
        "authorized `make defconfig` probe only",
    )
    report.set_defaults(handler=command_preflight)

    overlay = subparsers.add_parser(
        "verify-overlay", help="refuse an overlay that carries a secret"
    )
    overlay.add_argument("--overlay-dir", required=True)
    overlay.add_argument("--out", default="")
    overlay.set_defaults(handler=command_verify_overlay)

    artifacts = subparsers.add_parser(
        "artifacts", help="resolve and inspect both firmware image roles"
    )
    artifacts.add_argument("--lock", required=True)
    artifacts.add_argument("--image-dir", default="")
    artifacts.add_argument(
        "--source-dir", default="", help="the lock names the image directory inside it"
    )
    artifacts.add_argument("--out", default="")
    artifacts.set_defaults(handler=command_artifacts)

    publish = subparsers.add_parser(
        "publish", help="package the inspected images and their evidence"
    )
    publish.add_argument("--lock", required=True)
    publish.add_argument("--artifact-dir", required=True)
    publish.add_argument("--source-dir", required=True)
    publish.add_argument("--feed-dir", required=True)
    publish.add_argument("--image-dir", default="")
    publish.add_argument("--packages", required=True)
    publish.add_argument("--logs-dir", required=True)
    publish.add_argument("--build-env", default="")
    publish.set_defaults(handler=command_publish)

    args = parser.parse_args(argv)
    try:
        return args.handler(args)
    except (LockError, ArtifactError) as error:
        print("Error: %s" % error, file=sys.stderr)
        return BUILD_NOT_READY
    except ConfigError as error:
        print("Error: %s" % error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
