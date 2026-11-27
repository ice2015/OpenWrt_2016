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
import hashlib
import json
import re
import sys
from pathlib import Path


# The repository wide build not ready status. A lock that fails this gate must
# not be distinguishable from an unresolved manifest target: both stop with 3.
BUILD_NOT_READY = 3

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


def validate_readiness(lock, errors):
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
    if unproven:
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


def validate_lock(lock):
    """Return the list of reasons why the lock is not build ready."""
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
    validate_readiness(lock, errors)

    return errors


def render_plan(lock):
    source = lock["source"]
    return {
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
    """Summarise the symbols of one package entry of the lock."""
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


def verify_config(text, lock):
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

    if errors:
        raise ConfigError("; ".join(errors))
    return {
        "profile": EXPECTED_PROFILE,
        "hard_gates": hard_gates,
        "optional": optional,
        "excluded": excluded,
        "symbols": audited,
    }


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
    errors = validate_lock(lock)
    if errors:
        for error in errors:
            print("Error: %s" % error, file=sys.stderr)
        # No plan is rendered for a blocked lock: the caller must not receive
        # anything it could feed to a download or a compile step.
        return BUILD_NOT_READY
    print(json.dumps(render_plan(lock), indent=2, sort_keys=True))
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
    report = verify_config(text, lock)
    print(json.dumps(report, indent=2, sort_keys=True))
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


def command_report(args):
    lock = load_lock(args.lock)
    errors = validate_lock(lock)
    if errors:
        for error in errors:
            print("Error: %s" % error, file=sys.stderr)
        return BUILD_NOT_READY
    artifacts = []
    for spec in args.artifact:
        role, path = spec.split(":", 1)
        artifacts.append({"role": role, "path": path})
    build_env = json.loads(args.build_env) if args.build_env else {}
    extra = {}
    if args.packages:
        extra["package_list"] = Path(args.packages).read_text(encoding="utf-8")
    if args.final_config:
        extra["final_config"] = Path(args.final_config).read_text(encoding="utf-8")
    report = build_report(lock, artifacts, build_env, extra)
    Path(args.out).write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    check = subparsers.add_parser("check", help="validate the source lock")
    check.add_argument("--lock", required=True)
    check.set_defaults(handler=command_check)

    verify = subparsers.add_parser(
        "verify-config", help="check the configuration the build produced"
    )
    verify.add_argument("--lock", required=True)
    verify.add_argument("--config", required=True)
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

    report = subparsers.add_parser("report", help="write the build report")
    report.add_argument("--lock", required=True)
    report.add_argument("--out", required=True)
    report.add_argument("--build-env", default="")
    report.add_argument("--artifact", action="append", default=[], help="role:path")
    report.add_argument("--packages", default="")
    report.add_argument("--final-config", default="")
    report.set_defaults(handler=command_report)

    args = parser.parse_args(argv)
    try:
        return args.handler(args)
    except LockError as error:
        print("Error: %s" % error, file=sys.stderr)
        return BUILD_NOT_READY
    except ConfigError as error:
        print("Error: %s" % error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
