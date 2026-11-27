#!/usr/bin/env python3
"""Validate the NX30 Pro U-Boot source lock and inspect boot loader images.

The helper is the only place that knows what a build ready source lock looks
like. It refuses a lock that does not pin a full upstream commit, that names
another board or another vendored tree, that carries a partition layout other
than the 112M layout of the selected system, or that does not confirm both
image types.

Artifacts are classified by their content. The ATF FIP package is recognised
by its table of contents header and its BL31 and BL33 entries, the MediaTek
BL2 preloader by the SPI-NAND boot header that the U-Boot itself checks.
"""

import argparse
import fnmatch
import hashlib
import json
import re
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path


COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")

# The status code the repository uses for a target that is not build ready,
# the same code tools/manifest.py returns for an unresolved manifest.
BUILD_NOT_READY = 3

EXPECTED_REPOSITORY = "https://github.com/Yuzhii0718/bl-mt798x-dhcpd"
REJECTED_REPOSITORY = "https://github.com/hanwckf/bl-mt798x"
EXPECTED_SOC = "mt7981"
EXPECTED_BOARD = "h3c_magic-nx30-pro"

# The trees that the pinned upstream build script really builds for VERSION=SP1.
EXPECTED_UBOOT_TREE = "uboot-mtk-20250711"
EXPECTED_ATF_TREE = "atf-20240117-bacca82a8"
EXPECTED_VERSION = "SP1"

# Host tools the pinned build script requires before it compiles anything.
REQUIRED_HOST_PACKAGES = (
    "build-essential",
    "python3",
    "gcc-aarch64-linux-gnu",
    "npm",
)

# The partition contract of the selected system, from the device tree of
# jerryhan77/immortalwrt-mt798x at the locked commit. The offsets are NMBM
# logical addresses, not physical NAND addresses.
EXPECTED_PARTITIONS = [
    ("BL2", 0x000000, 0x100000),
    ("u-boot-env", 0x100000, 0x080000),
    ("Factory", 0x180000, 0x200000),
    ("FIP", 0x380000, 0x200000),
    ("ubi", 0x580000, 0x7000000),
]

EXPECTED_MTDPARTS = (
    "nmbm0:1024k(bl2),512k(u-boot-env),2048k(Factory),2048k(fip),114688k(ubi)"
)

# The two layouts the pinned upstream device tree offers for this board. The
# whitelist is exactly this set: a third label is a partition table nobody
# verified, and the stock layout must never become the default.
EXPECTED_DEFAULT_LAYOUT = "immortalwrt-112m"
EXPECTED_LAYOUT_LABELS = ("immortalwrt-112m", "default")
EXPECTED_LAYOUT_MTDIDS = "nmbm0=nmbm0"
EXPECTED_LAYOUT_MTDPARTS = {
    "immortalwrt-112m": (
        "nmbm0:1024k(bl2),512k(u-boot-env),2048k(Factory),2048k(fip),112M(ubi)"
    ),
    "default": (
        "nmbm0:1024k(bl2),512k(u-boot-env),2048k(Factory),2048k(fip),"
        "65536k(ubi),6144k(pdt_data),6144k(pdt_data_1),1024k(exp),38400k(plugin)"
    ),
}

SIZE_SUFFIXES = {"k": 1024, "m": 1024 * 1024, "g": 1024 ** 3}

# The feature set of the restricted recovery boot loader. Only the effective
# configuration is checked against it, never the environment of the build.
REQUIRED_EFFECTIVE_SYMBOLS = (
    "CONFIG_MEDIATEK_MULTI_MTD_LAYOUT",
    "CONFIG_MTK_FIXED_MTD_MTDPARTS",
    "CONFIG_ENABLE_NAND_NMBM",
    "CONFIG_MTK_DHCPD",
    "CONFIG_MTK_WEB_FAILSAFE",
    "CONFIG_MTK_WEB_FAILSAFE_AFTER_BOOT_FAILURE",
    "CONFIG_WEBUI_FAILSAFE",
    "CONFIG_WEBUI_FAILSAFE_BACKUP",
    "CONFIG_MTK_UBI_SUPPORT",
    "CONFIG_MTK_UPGRADE_BL2_VERIFY",
    "CONFIG_CMD_TFTPPUT",
    "CONFIG_DEBUG_UART",
    "CONFIG_MTK_SERIAL",
)
FORBIDDEN_EFFECTIVE_SYMBOLS = (
    "CONFIG_WEBUI_FAILSAFE_FACTORY",
    "CONFIG_WEBUI_FAILSAFE_FLASH",
    "CONFIG_WEBUI_FAILSAFE_NAND_RAW",
    "CONFIG_WEBUI_FAILSAFE_CONSOLE",
    "CONFIG_WEBUI_FAILSAFE_ENV",
    "CONFIG_WEBUI_FAILSAFE_ENV_CUSTOM_ENV",
    "CONFIG_WEBUI_FAILSAFE_SIMG",
    "CONFIG_WEBUI_FAILSAFE_UBI",
    "CONFIG_WEBUI_FAILSAFE_GPT",
    "CONFIG_MTK_TELNETD",
)
# The upstream defaults enable these, so the device patch has to turn every one
# of them off explicitly instead of relying on a missing line.
FORBIDDEN_PATCH_SYMBOLS = (
    "CONFIG_WEBUI_FAILSAFE_FACTORY",
    "CONFIG_WEBUI_FAILSAFE_FLASH",
    "CONFIG_WEBUI_FAILSAFE_CONSOLE",
    "CONFIG_WEBUI_FAILSAFE_ENV",
    "CONFIG_WEBUI_FAILSAFE_SIMG",
    "CONFIG_WEBUI_FAILSAFE_UBI",
    "CONFIG_MTK_TELNETD",
)
DEFAULT_LAYOUT_SYMBOL = "CONFIG_MTK_DEFAULT_MTD_LAYOUT"
STOCK_LAYOUT_MARKER = "65536k(ubi)"
OVERCLOCK_SYMBOL_RE = re.compile(
    r"^CONFIG_[A-Z0-9_]*(OVERCLOCK|(CPU|DDR|DRAM)[A-Z0-9_]*(FREQ|SPEED|OVERCLOCK))[A-Z0-9_]*="
)

MTDPART_ENTRY_RE = re.compile(r"^(\d+[kKmMgG]?)(?:@\d+[kKmMgG]?)?\(([^)]+)\)")
DTS_LAYOUT_NODE_RE = re.compile(r"(layout@[0-9a-fA-F]+)\s*\{(.*?)\n\s*\};", re.S)
DTS_STRING_RE = lambda name: re.compile(r'%s\s*=\s*"([^"]*)"' % name)


TOC_HEADER_NAME = 0xAA640001
TOC_HEADER = struct.Struct("<IIQ")
TOC_ENTRY = struct.Struct("<16sQQQ")
BL31_UUID = bytes.fromhex("47d4086d4cfe98469b952950cbbd5a00")
BL33_UUID = bytes.fromhex("d6d0eea7fcead54b97829934f234b6e4")
SPIM_NAND_HEADER = b"SPINAND!"
# The boot loader checks the first eight bytes of the header, the full header
# of the preloader image is sixteen bytes long.
BL2_HEADER_SIZE = 16
UBOOT_MARKER = b"U-Boot "


class LockError(Exception):
    """The source lock is not build ready."""


class ArtifactError(Exception):
    """A produced image does not match the expected boot loader image."""


def sha256_of(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_output(command):
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as error:
        return "UNRESOLVED (%s)" % error
    if result.returncode != 0:
        return "UNRESOLVED"
    return result.stdout.strip()


def load_lock(path):
    try:
        lock = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise LockError("the source lock cannot be read: %s" % error)
    if not isinstance(lock, dict):
        raise LockError("the source lock is not a JSON object")
    return lock


def parse_size(text):
    """Convert one mtdparts size such as 112M into bytes."""
    text = text.strip()
    suffix = text[-1].lower()
    if suffix in SIZE_SUFFIXES:
        return int(text[:-1]) * SIZE_SUFFIXES[suffix]
    return int(text)


def parse_mtdparts(mtdparts):
    """Split an mtdparts string into its device and its partition list."""
    device, _, remainder = str(mtdparts).partition(":")
    if not remainder:
        raise LockError("the partition table %r names no partitions" % (mtdparts,))
    partitions = []
    offset = 0
    for item in remainder.split(","):
        match = MTDPART_ENTRY_RE.match(item.strip())
        if not match:
            raise LockError(
                "the partition table entry %r of %r cannot be parsed" % (item, mtdparts)
            )
        size = parse_size(match.group(1))
        partitions.append(
            {"label": match.group(2), "offset": offset, "size": size}
        )
        offset += size
    return device.strip(), partitions, offset


def validate_layout_entries(lock, errors):
    """Check the locked layout whitelist against itself."""
    layouts = lock.get("layouts") or {}
    entries = layouts.get("entries") or {}

    if layouts.get("default_label") != EXPECTED_DEFAULT_LAYOUT:
        errors.append(
            "the default layout must be %s, the lock selects %r"
            % (EXPECTED_DEFAULT_LAYOUT, layouts.get("default_label"))
        )
    if set(entries) != set(EXPECTED_LAYOUT_LABELS):
        errors.append(
            "the layout whitelist must be exactly %s, the lock carries %s"
            % (
                " and ".join(EXPECTED_LAYOUT_LABELS),
                ", ".join(sorted(entries)) or "nothing",
            )
        )
    if layouts.get("mtdids") != EXPECTED_LAYOUT_MTDIDS:
        errors.append(
            "the layouts must be addressed through %s, the lock records %r"
            % (EXPECTED_LAYOUT_MTDIDS, layouts.get("mtdids"))
        )

    parsed = {}
    for label in EXPECTED_LAYOUT_LABELS:
        entry = entries.get(label)
        if not isinstance(entry, dict):
            continue
        expected_table = EXPECTED_LAYOUT_MTDPARTS[label]
        if entry.get("mtdparts") != expected_table:
            errors.append(
                "the layout %s must carry the table %s, the lock carries %r"
                % (label, expected_table, entry.get("mtdparts"))
            )
            continue
        if entry.get("mtdids") != EXPECTED_LAYOUT_MTDIDS:
            errors.append(
                "the layout %s must be addressed through %s, the lock records %r"
                % (label, EXPECTED_LAYOUT_MTDIDS, entry.get("mtdids"))
            )
        device, partitions, end = parse_mtdparts(expected_table)
        if device != "nmbm0":
            errors.append(
                "the layout %s is addressed on %s, not on the nmbm logical device"
                % (label, device)
            )
        declared = [
            (item.get("label"), item.get("offset"), item.get("size"))
            for item in entry.get("partitions") or []
        ]
        actual = [(item["label"], item["offset"], item["size"]) for item in partitions]
        if declared != actual:
            errors.append(
                "the declared partitions of the layout %s do not follow its table"
                % (label,)
            )
        if entry.get("end_offset") not in (None, end):
            errors.append(
                "the layout %s ends at %r, its table ends at %d"
                % (label, entry.get("end_offset"), end)
            )
        parsed[label] = actual

    if set(parsed) == set(EXPECTED_LAYOUT_LABELS):
        if parsed["immortalwrt-112m"][:4] != parsed["default"][:4]:
            errors.append(
                "the two layouts must share the bl2, u-boot-env, Factory and fip "
                "offsets and sizes"
            )
        contract = [
            (
                str(item.get("label", "")).lower(),
                item.get("offset"),
                item.get("size"),
            )
            for item in (lock.get("partition_contract") or {}).get("partitions") or []
        ]
        lowered = [
            (label.lower(), offset, size) for label, offset, size in parsed["immortalwrt-112m"]
        ]
        if contract and contract != lowered:
            errors.append(
                "the partition contract is not the immortalwrt-112m layout of the "
                "locked whitelist"
            )
    return parsed


def verify_layout_source(lock, dts_text):
    """Check the pinned device tree text against the locked layout whitelist.

    The verifier reads the source, it never synthesises a layout. A device tree
    that carries another label, another table or physical NAND addressing makes
    the build stop before anything is compiled.
    """
    text = str(dts_text)
    errors = []
    entries = (lock.get("layouts") or {}).get("entries") or {}

    if "mtd-layout" not in text:
        raise LockError(
            "the device tree has no mtd-layout node, so it offers no layout whitelist"
        )

    found = {}
    for node, body in DTS_LAYOUT_NODE_RE.findall(text):
        label_match = DTS_STRING_RE("label").search(body)
        ids_match = DTS_STRING_RE("mtdids").search(body)
        parts_match = DTS_STRING_RE("mtdparts").search(body)
        if not label_match or not ids_match or not parts_match:
            errors.append(
                "the device tree layout %s does not carry label, mtdids and mtdparts"
                % node
            )
            continue
        found[label_match.group(1)] = {
            "node": node,
            "mtdids": ids_match.group(1),
            "mtdparts": parts_match.group(1),
        }

    expected = set(EXPECTED_LAYOUT_LABELS)
    for label in sorted(set(found) - expected):
        errors.append(
            "the device tree offers the layout %s, which is not in the locked "
            "whitelist %s" % (label, " and ".join(EXPECTED_LAYOUT_LABELS))
        )
    for label in sorted(expected - set(found)):
        errors.append(
            "the device tree does not carry the locked layout %s" % (label,)
        )

    for label in EXPECTED_LAYOUT_LABELS:
        entry = found.get(label)
        if not entry:
            continue
        if entry["mtdids"] != EXPECTED_LAYOUT_MTDIDS:
            errors.append(
                "the layout %s is addressed with %r, the locked layouts are addressed "
                "through the nmbm logical device %s"
                % (label, entry["mtdids"], EXPECTED_LAYOUT_MTDIDS)
            )
            continue
        if entry["mtdparts"] != EXPECTED_LAYOUT_MTDPARTS[label]:
            errors.append(
                "the layout %s of the device tree carries the table %r, the lock "
                "requires %s"
                % (label, entry["mtdparts"], EXPECTED_LAYOUT_MTDPARTS[label])
            )
            continue
        device, partitions, _end = parse_mtdparts(entry["mtdparts"])
        if device != "nmbm0":
            errors.append(
                "the layout %s is addressed on %s, not on the nmbm logical device"
                % (label, device)
            )
        declared = entries.get(label, {}).get("partitions") or []
        source_labels = [item["label"] for item in partitions]
        locked_labels = [item.get("label") for item in declared]
        for missing in [item for item in locked_labels if item not in source_labels]:
            errors.append(
                "the device tree layout %s does not carry the partition %s"
                % (label, missing)
            )
        for extra in [item for item in source_labels if item not in locked_labels]:
            errors.append(
                "the device tree layout %s carries the partition %s, which the lock "
                "does not describe" % (label, extra)
            )
        for item in partitions:
            match = [
                other for other in declared if other.get("label") == item["label"]
            ]
            if not match:
                continue
            other = match[0]
            if other.get("offset") != item["offset"] or other.get("size") != item["size"]:
                errors.append(
                    "the device tree layout %s places the partition %s at %d with "
                    "size %d, the lock records offset %r and size %r"
                    % (
                        label,
                        item["label"],
                        item["offset"],
                        item["size"],
                        other.get("offset"),
                        other.get("size"),
                    )
                )

    if errors:
        raise LockError("; ".join(errors))
    return {
        "default_label": (lock.get("layouts") or {}).get("default_label"),
        "layouts": sorted(found),
        "address_space": "nmbm-logical",
    }


def validate_features(lock, errors):
    """Check the locked recovery feature set against the required contract."""
    features = lock.get("features") or {}
    if features.get("status") != "locked":
        errors.append(
            "the feature set of the recovery boot loader is not locked, it is %r"
            % (features.get("status"),)
        )

    selector = features.get("selector") or {}
    if selector.get("default_label") != EXPECTED_DEFAULT_LAYOUT:
        errors.append(
            "the layout selector must default to %s, the lock selects %r"
            % (EXPECTED_DEFAULT_LAYOUT, selector.get("default_label"))
        )
    if list(selector.get("labels") or []) != list(EXPECTED_LAYOUT_LABELS):
        errors.append(
            "the layout selector must offer exactly %s, the lock offers %s"
            % (
                " and ".join(EXPECTED_LAYOUT_LABELS),
                ", ".join(selector.get("labels") or []) or "nothing",
            )
        )
    for key in ("free_form_mtdparts", "environment_editing"):
        if selector.get(key) is not False:
            errors.append(
                "the layout selector must not allow %s, the lock records %r"
                % (key, selector.get(key))
            )

    enabled = {item.get("symbol"): item for item in features.get("enabled") or []}
    disabled = {item.get("symbol"): item for item in features.get("disabled") or []}
    for symbol in REQUIRED_EFFECTIVE_SYMBOLS:
        if symbol not in enabled:
            errors.append("the lock does not require the recovery feature %s" % symbol)
        elif not str(enabled[symbol].get("purpose", "")).strip():
            errors.append("the lock does not say what %s is needed for" % symbol)
    for symbol in FORBIDDEN_EFFECTIVE_SYMBOLS:
        if symbol not in disabled:
            errors.append("the lock does not forbid %s" % symbol)
        elif not str(disabled[symbol].get("reason", "")).strip():
            errors.append("the lock does not say why %s is forbidden" % symbol)
    default_layout = (enabled.get(DEFAULT_LAYOUT_SYMBOL) or {}).get("value")
    if default_layout != EXPECTED_DEFAULT_LAYOUT:
        errors.append(
            "the lock must select %s=%s, it selects %r"
            % (DEFAULT_LAYOUT_SYMBOL, EXPECTED_DEFAULT_LAYOUT, default_layout)
        )

    overclock = features.get("overclock") or {}
    if overclock.get("enabled") is not False:
        errors.append("overclocking must stay disabled, the lock records %r" % (overclock.get("enabled"),))
    if not str(overclock.get("note", "")).strip():
        errors.append("the lock does not record how the overclock settings were checked")

    patches = (lock.get("source") or {}).get("patches") or []
    if len(patches) != 1:
        errors.append(
            "the lock must record exactly one device patch, it records %d" % len(patches)
        )
    tree = (lock.get("source") or {}).get("uboot_tree")
    for record in patches:
        if record.get("applies_to_commit") != (lock.get("source") or {}).get("commit"):
            errors.append(
                "the device patch %s is not recorded for the pinned commit"
                % (record.get("path"),)
            )
        if not str(record.get("purpose", "")).strip():
            errors.append(
                "the device patch %s does not say what it restricts" % (record.get("path"),)
            )
        for path in record.get("upstream_files") or []:
            if tree and not str(path).startswith(tree + "/"):
                errors.append(
                    "the device patch %s touches %s outside the locked %s tree"
                    % (record.get("path"), path, tree)
                )


def validate_lock(lock):
    """Return the list of reasons why the lock is not build ready."""
    errors = []
    source = lock.get("source") or {}
    build_env = source.get("build_env") or {}

    commit = source.get("commit")
    if not isinstance(commit, str) or not COMMIT_RE.match(commit):
        errors.append(
            "the source commit must be a full 40 character commit id, got %r"
            % (commit,)
        )
    repository = source.get("repository")
    if repository != EXPECTED_REPOSITORY:
        errors.append(
            "the source repository must be %s, got %r" % (EXPECTED_REPOSITORY, repository)
        )

    if source.get("uboot_tree") != EXPECTED_UBOOT_TREE:
        errors.append(
            "the U-Boot tree must be the tree the pinned build script uses (%s), got %r"
            % (EXPECTED_UBOOT_TREE, source.get("uboot_tree"))
        )
    if source.get("atf_tree") != EXPECTED_ATF_TREE:
        errors.append(
            "the ATF tree must be the tree the pinned build script uses (%s), got %r"
            % (EXPECTED_ATF_TREE, source.get("atf_tree"))
        )

    board = build_env.get("BOARD")
    if board != EXPECTED_BOARD:
        errors.append(
            "board mismatch: the lock selects board %r, this build only supports %s"
            % (board, EXPECTED_BOARD)
        )
    if build_env.get("SOC") != EXPECTED_SOC:
        errors.append(
            "board mismatch: the lock selects SoC %r, this build only supports %s"
            % (build_env.get("SOC"), EXPECTED_SOC)
        )
    if str(build_env.get("FIXED_MTDPARTS")) != "1":
        errors.append(
            "the build must use fixed mtd parts, the lock sets FIXED_MTDPARTS=%r"
            % (build_env.get("FIXED_MTDPARTS"),)
        )
    if str(build_env.get("MULTI_LAYOUT")) != "1":
        errors.append(
            "the locked layout whitelist needs the multi layout defconfig, "
            "the lock sets MULTI_LAYOUT=%r" % (build_env.get("MULTI_LAYOUT"),)
        )

    version = source.get("version")
    if version == "UNRESOLVED":
        errors.append(
            "the boot loader version is UNRESOLVED: select 2025, SP1 or SP2 from "
            "evidence before the build may start"
        )
    elif version != EXPECTED_VERSION:
        errors.append(
            "the lock selects boot loader version %r, the trees it names are "
            "built by version %s" % (version, EXPECTED_VERSION)
        )
    if build_env.get("VERSION") != version:
        errors.append(
            "the build environment selects version %r, the lock records %r"
            % (build_env.get("VERSION"), version)
        )
    selection = source.get("version_selection") or {}
    if selection.get("selected") != version:
        errors.append(
            "the recorded version selection does not select %r" % (version,)
        )
    if selection.get("atf_tree") != EXPECTED_ATF_TREE:
        errors.append(
            "the version selection does not name the ATF tree %s"
            % (EXPECTED_ATF_TREE,)
        )
    if selection.get("uboot_tree") != EXPECTED_UBOOT_TREE:
        errors.append(
            "the version selection does not name the U-Boot tree %s"
            % (EXPECTED_UBOOT_TREE,)
        )

    board = lock.get("board") or {}
    if board.get("soc") != EXPECTED_SOC or board.get("name") != EXPECTED_BOARD:
        errors.append(
            "board mismatch: the lock describes board %r/%r, this build only "
            "supports %s/%s"
            % (board.get("soc"), board.get("name"), EXPECTED_SOC, EXPECTED_BOARD)
        )
    for key in ("defconfig", "multi_layout_defconfig", "dts"):
        if not board.get(key):
            errors.append("the board description does not name its %s" % key)

    contract = lock.get("partition_contract") or {}
    actual = [
        (entry.get("label"), entry.get("offset"), entry.get("size"))
        for entry in contract.get("partitions") or []
    ]
    if actual != EXPECTED_PARTITIONS:
        errors.append(
            "the partition layout does not match the 112M contract of the selected system"
        )

    compatibility = lock.get("compatibility") or {}
    patch = compatibility.get("minimal_device_patch") or {}
    if patch.get("action") != "none-required-for-the-partition-tables":
        errors.append(
            "the pinned device tree already carries both locked layout tables, so "
            "the lock must not describe a partition patch, got %r"
            % (patch.get("action"),)
        )
    if patch.get("value") != EXPECTED_MTDPARTS:
        errors.append(
            "the lock does not record the 112M partition table %r"
            % (patch.get("value"),)
        )
    if compatibility.get("layout_matches_upstream_stock") is not False:
        errors.append(
            "the lock must record that the upstream stock layout does not match"
        )

    validate_layout_entries(lock, errors)
    validate_features(lock, errors)

    artifacts = lock.get("artifacts") or {}
    for kind, suffix in (("fip", ".bin"), ("bl2", ".img")):
        entry = artifacts.get(kind) or {}
        pattern = entry.get("pattern") if isinstance(entry, dict) else None
        if not pattern:
            errors.append("image type not confirmed: the lock names no %s artifact" % kind.upper())
            continue
        if not pattern.endswith(suffix):
            errors.append(
                "image type not confirmed: the %s artifact pattern %r is not a %s file"
                % (kind.upper(), pattern, suffix)
            )
        if "*" not in pattern:
            errors.append(
                "image type not confirmed: the %s artifact pattern %r does not account "
                "for the build digest the upstream build script embeds in the name"
                % (kind.upper(), pattern)
            )
        if EXPECTED_BOARD not in pattern:
            errors.append(
                "image type not confirmed: the %s artifact pattern %r is not an artifact "
                "of this board" % (kind.upper(), pattern)
            )

    host_packages = lock.get("host_packages") or []
    missing = [package for package in REQUIRED_HOST_PACKAGES if package not in host_packages]
    if missing:
        errors.append(
            "the lock does not record the host packages the pinned build script "
            "requires: %s" % ", ".join(missing)
        )

    toolchain = lock.get("toolchain") or {}
    if toolchain.get("package") != "gcc-aarch64-linux-gnu":
        errors.append(
            "the toolchain package must be gcc-aarch64-linux-gnu, got %r"
            % (toolchain.get("package"),)
        )
    if not toolchain.get("prefix"):
        errors.append("the toolchain prefix is not recorded")

    return errors


def artifact_pattern(lock, kind):
    """Return the locked name pattern of one boot loader artifact."""
    artifacts = lock.get("artifacts") or {}
    entry = artifacts.get(kind) or {}
    if not isinstance(entry, dict) or not entry.get("pattern"):
        raise LockError("the lock names no %s artifact" % kind.upper())
    return entry["pattern"]


def match_artifact_name(lock, kind, filename):
    """Resolve one produced file name against the locked artifact pattern.

    The upstream build script embeds the md5 of the image in its name, so the
    lock records a pattern. A name that does not match is either an artifact of
    another board, version or variant, or a system image that must never be
    published as a boot loader image.
    """
    pattern = artifact_pattern(lock, kind)
    name = Path(str(filename)).name
    if not fnmatch.fnmatchcase(name, pattern):
        raise ArtifactError(
            "the produced %s image %r does not match the locked artifact pattern %r"
            % (kind.upper(), name, pattern)
        )
    return name


def render_plan(lock):
    source = lock["source"]
    contract = lock["partition_contract"]
    return {
        "device": lock.get("device"),
        "status": lock.get("status"),
        "source_repository": source.get("repository"),
        "source_commit": source.get("commit"),
        "atf_tree": source.get("atf_tree"),
        "uboot_tree": source.get("uboot_tree"),
        "version": source.get("version"),
        "build_env": source.get("build_env"),
        "board": lock.get("board"),
        "layouts": lock.get("layouts"),
        "toolchain": lock.get("toolchain"),
        "host_packages": lock.get("host_packages"),
        "partition_table": contract.get("partitions"),
        "artifacts": lock.get("artifacts"),
    }


def parse_effective_config(text):
    """Parse a .config into its enabled symbols and its explicit 'is not set'."""
    enabled = {}
    disabled = set()
    for line in str(text).splitlines():
        line = line.strip()
        if not line:
            continue
        match = re.match(r"^# ([A-Za-z0-9_-]+) is not set$", line)
        if match:
            disabled.add(match.group(1))
            continue
        match = re.match(r"^([A-Za-z0-9_-]+)=(.*)$", line)
        if match:
            value = match.group(2)
            if value.startswith('"') and value.endswith('"'):
                value = value[1:-1]
            enabled[match.group(1)] = value
    return enabled, disabled


def verify_effective_config(text, lock):
    """Check the boot loader configuration that was really compiled.

    Requested environment variables are not evidence: olddefconfig drops a
    symbol that no Kconfig knows, and a dangerous page that survives here is
    compiled into the image. Only this file proves the feature set.
    """
    enabled, disabled = parse_effective_config(text)
    errors = []

    if enabled.get("CONFIG_TARGET_MT7981") != "y":
        errors.append("the effective configuration does not target MT7981")
    if enabled.get("CONFIG_DEFAULT_DEVICE_TREE") != "%s-%s" % (EXPECTED_SOC, EXPECTED_BOARD):
        errors.append(
            "the effective configuration does not use the %s device tree, it uses %r"
            % (EXPECTED_BOARD, enabled.get("CONFIG_DEFAULT_DEVICE_TREE"))
        )

    for symbol in REQUIRED_EFFECTIVE_SYMBOLS:
        if enabled.get(symbol) != "y":
            errors.append(
                "the effective configuration does not enable %s, the recovery "
                "feature it carries is missing" % symbol
            )
    for symbol in FORBIDDEN_EFFECTIVE_SYMBOLS:
        if symbol in enabled:
            errors.append(
                "the effective configuration enables %s, which this device must "
                "not offer" % symbol
            )

    default_layout = enabled.get(DEFAULT_LAYOUT_SYMBOL)
    if default_layout != EXPECTED_DEFAULT_LAYOUT:
        errors.append(
            "the effective configuration defaults to the layout %r, it must default "
            "to %s" % (default_layout, EXPECTED_DEFAULT_LAYOUT)
        )

    mtdparts_default = enabled.get("CONFIG_MTDPARTS_DEFAULT")
    if mtdparts_default is not None:
        if STOCK_LAYOUT_MARKER in mtdparts_default:
            errors.append(
                "the effective configuration carries the stock partition table %s, "
                "the build fell back to the single layout defconfig"
                % (STOCK_LAYOUT_MARKER,)
            )
        else:
            errors.append(
                "the effective configuration fixes CONFIG_MTDPARTS_DEFAULT to %r "
                "instead of reading the layout whitelist from the device tree"
                % (mtdparts_default,)
            )

    for symbol in sorted(enabled):
        if OVERCLOCK_SYMBOL_RE.match(symbol + "="):
            errors.append(
                "the effective configuration enables the overclock setting %s"
                % symbol
            )

    if errors:
        raise LockError("; ".join(errors))
    return {
        "default_layout": default_layout,
        "enabled": sorted(
            symbol for symbol in REQUIRED_EFFECTIVE_SYMBOLS if symbol in enabled
        ),
        "disabled": sorted(symbol for symbol in FORBIDDEN_EFFECTIVE_SYMBOLS if symbol in disabled),
        "mtdparts_default": mtdparts_default,
    }


def verify_patch(patch_text, lock, source_dir=None):
    """Check the device patch against the recovery contract of this device.

    The patch is the only place that may restrict the upstream recovery UI, so
    it may not grow into a second partition editor, an environment editor or a
    third layout, and it has to keep the 112M layout as the default.
    """
    text = str(patch_text)
    entries = (lock.get("source") or {}).get("patches") or []
    if not entries:
        raise LockError("the lock records no device patch")
    record = entries[0]
    if record.get("applies_to_commit") != lock["source"]["commit"]:
        raise LockError(
            "the device patch is recorded for commit %r, the lock pins %s"
            % (record.get("applies_to_commit"), lock["source"]["commit"])
        )

    tree = lock["source"]["uboot_tree"]
    files = re.findall(r"^diff --git a/(\S+) b/(\S+)$", text, re.M)
    if not files:
        raise LockError("the device patch is not a git diff")
    paths = []
    for left, right in files:
        if left != right:
            raise LockError("the device patch renames %s, a rename is not a restriction" % left)
        if not left.startswith(tree + "/"):
            raise LockError(
                "the device patch touches %s, which is not part of the locked %s tree "
                "of this device" % (left, tree)
            )
        paths.append(left)

    expected_files = sorted(record.get("upstream_files") or [])
    if sorted(paths) != expected_files:
        raise LockError(
            "the device patch touches %s, the lock records %s"
            % (", ".join(sorted(paths)) or "nothing", ", ".join(expected_files) or "nothing")
        )

    added = [
        line[1:] for line in text.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    ]
    errors = []
    default_layout = None
    disabled = []
    warns = False
    confirms = False

    for line in added:
        stripped = line.strip()
        match = re.match(r"^CONFIG_[A-Za-z0-9_]*LAYOUT[A-Za-z0-9_]*=\"([^\"]*)\"$", stripped)
        if match and match.group(1) not in EXPECTED_LAYOUT_LABELS:
            errors.append(
                "the device patch selects the layout %r, only %s may be selected"
                % (match.group(1), " and ".join(EXPECTED_LAYOUT_LABELS))
            )
        match = re.match(r"^label\s*=\s*\"([^\"]*)\"", stripped)
        if match and match.group(1) not in EXPECTED_LAYOUT_LABELS:
            errors.append(
                "the device patch adds the layout label %r, only %s may be selected"
                % (match.group(1), " and ".join(EXPECTED_LAYOUT_LABELS))
            )
        if DEFAULT_LAYOUT_SYMBOL + '=' in stripped:
            match = re.match(r'^%s="([^"]*)"$' % DEFAULT_LAYOUT_SYMBOL, stripped)
            if match:
                default_layout = match.group(1)
        if "mtd_layout_custom" in stripped or stripped.startswith("CONFIG_MTDPARTS_DEFAULT="):
            errors.append(
                "the device patch exposes a free form mtdparts input, the selector may "
                "only offer the locked layout whitelist"
            )
        if "env_set(" in stripped or "setenv " in stripped:
            errors.append(
                "the device patch writes the environment, generic environment editing "
                "is disabled on this device"
            )
        match = re.match(r"^CONFIG_([A-Za-z0-9_]+)=", stripped)
        if match and ("CONFIG_" + match.group(1)) in FORBIDDEN_EFFECTIVE_SYMBOLS:
            errors.append(
                "the device patch enables %s, which this device must not offer"
                % ("CONFIG_" + match.group(1))
            )
        match = re.match(r"^# (CONFIG_[A-Za-z0-9_]+) is not set$", stripped)
        if match and match.group(1) in FORBIDDEN_EFFECTIVE_SYMBOLS:
            disabled.append(match.group(1))
        if "confirm(" in stripped:
            confirms = True
        if "pdt_data" in stripped:
            warns = True

    if default_layout != EXPECTED_DEFAULT_LAYOUT:
        errors.append(
            "the device patch does not make %s the default layout, it selects %r"
            % (EXPECTED_DEFAULT_LAYOUT, default_layout)
        )
    missing = [symbol for symbol in FORBIDDEN_PATCH_SYMBOLS if symbol not in disabled]
    if missing:
        errors.append(
            "the device patch does not disable %s, the upstream defaults enable them"
            % ", ".join(sorted(missing))
        )
    if not (confirms and warns):
        errors.append(
            "the device patch does not warn before a switch away from the stock layout: "
            "it has to name the reclaimed OEM partitions and ask for a confirmation"
        )

    if errors:
        raise LockError("; ".join(errors))

    if source_dir is not None:
        apply_device_patch_file(text, source_dir, check_only=True)

    return {
        "applies_to_commit": record["applies_to_commit"],
        "files": sorted(paths),
        "default_layout": default_layout,
        "disabled": sorted(set(disabled)),
        "warns_before_switch": True,
    }


def apply_device_patch_file(patch_text, source_dir, check_only=False):
    """Apply one device patch inside the pinned checkout with git apply."""
    source_dir = Path(source_dir)
    with tempfile.TemporaryDirectory() as tmp:
        patch_file = Path(tmp) / "device.patch"
        patch_file.write_text(str(patch_text), encoding="utf-8")
        command = ["git", "-C", str(source_dir), "apply", "--verbose"]
        if check_only:
            command.append("--check")
        command.append(str(patch_file))
        result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise LockError(
            "the device patch does not apply to %s: %s"
            % (source_dir, (result.stderr or result.stdout).strip())
        )
    return result.stderr.strip() or result.stdout.strip()


def apply_device_patches(lock, source_dir, repo_root=None):
    """Verify and apply every recorded device patch in lock order."""
    entries = (lock.get("source") or {}).get("patches") or []
    root = Path(repo_root) if repo_root else Path(__file__).resolve().parents[3]
    applied = []
    for record in sorted(entries, key=lambda item: item.get("order", 0)):
        path = root / record["path"]
        if not path.is_file():
            raise LockError("the recorded device patch is missing: %s" % path)
        text = path.read_text(encoding="utf-8")
        verify_patch(text, lock)
        output = apply_device_patch_file(text, source_dir)
        applied.append(
            {
                "patch": record["path"],
                "files": sorted(
                    set(re.findall(r"^diff --git a/(\S+) b/", text, re.M))
                ),
                "git_apply": output,
            }
        )
    return applied


def upstream_build_trees(source_dir):
    """Return the trees that the pinned build script really builds."""
    build_script = Path(source_dir) / "build.sh"
    if not build_script.is_file():
        raise LockError("the pinned build script is missing: %s" % build_script)
    text = build_script.read_text(encoding="utf-8")
    uboot = re.search(r"^UBOOT_DIR=(\S+)$", text, re.M)
    atf = re.search(r"^ATF_DIR=(\S+)$", text, re.M)
    if not uboot or not atf:
        raise LockError("the pinned build script does not name its trees")
    return uboot.group(1), atf.group(1)


def check_worktree_clean(source_dir, allow_paths=()):
    """Fail when the checkout carries changes that are not the device patch."""
    source_dir = Path(source_dir)
    result = subprocess.run(
        ["git", "-C", str(source_dir), "status", "--porcelain"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise LockError("the source directory is not a usable git checkout")
    changed = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        path = line[3:].strip()
        if path.startswith('"') and path.endswith('"'):
            path = path[1:-1]
        changed.append(path)
    unexpected = [path for path in changed if path not in allow_paths]
    if unexpected:
        raise LockError(
            "the source checkout carries local changes: %s" % ", ".join(sorted(unexpected))
        )
    return changed


def check_output_dir_empty(source_dir, output_name="output"):
    """Fail when the build directory already holds output of an earlier run."""
    output = Path(source_dir) / output_name
    if not output.exists():
        return None
    if not output.is_dir():
        raise LockError("the build output path is not a directory: %s" % output)
    entries = sorted(entry.name for entry in output.iterdir())
    if entries:
        raise LockError(
            "the build output directory already holds files (%s). Build in a clean "
            "checkout so that an earlier result cannot be reported as this build."
            % ", ".join(entries)
        )
    return output


def require_toolchain(lookup=shutil.which, prefix="aarch64-linux-gnu-"):
    """Fail when the cross compiler is not installed."""
    compiler = lookup(prefix + "gcc")
    if not compiler:
        raise LockError(
            "the cross compiler %sgcc is not installed. The upstream build script "
            "exits successfully when the compiler is missing, so the build has to "
            "be stopped before it runs." % prefix
        )
    return compiler


def toolchain_identity(lookup=shutil.which, prefix="aarch64-linux-gnu-"):
    """Record the identity of the toolchain that produced the images."""
    compiler = require_toolchain(lookup=lookup, prefix=prefix)
    version = run_output([compiler, "--version"]).splitlines()
    identity = {
        "compiler": compiler,
        "version": version[0] if version else "UNRESOLVED",
        "compiler_sha256": sha256_of(compiler),
        "package": "gcc-aarch64-linux-gnu",
        "package_version": run_output(
            ["dpkg-query", "-W", "-f=${Version}", "gcc-aarch64-linux-gnu"]
        )
        or "UNRESOLVED",
        "package_candidate": run_output(
            ["apt-cache", "policy", "gcc-aarch64-linux-gnu"]
        )
        or "UNRESOLVED",
    }
    return identity


def inspect_fip(path, max_size=None):
    """Classify an ATF FIP package by its table of contents."""
    path = Path(path)
    data = path.read_bytes()
    if max_size is not None and len(data) > max_size:
        raise ArtifactError(
            "the FIP image is %d bytes and does not fit its %d byte partition"
            % (len(data), max_size)
        )
    if len(data) < TOC_HEADER.size:
        raise ArtifactError("the FIP image is too short to hold a table of contents")
    name, serial_number, _flags = TOC_HEADER.unpack_from(data, 0)
    if name != TOC_HEADER_NAME:
        raise ArtifactError(
            "the image does not start with an ATF FIP table of contents header"
        )

    components = []
    offset = TOC_HEADER.size
    terminated = False
    while offset + TOC_ENTRY.size <= len(data):
        uuid, entry_offset, size, _entry_flags = TOC_ENTRY.unpack_from(data, offset)
        offset += TOC_ENTRY.size
        if uuid == b"\x00" * 16:
            terminated = True
            break
        if size == 0:
            raise ArtifactError(
                "the FIP package holds an entry without payload, it is truncated"
            )
        if entry_offset + size > len(data):
            raise ArtifactError(
                "the FIP package holds an entry that reaches past the end of the file"
            )
        payload = data[entry_offset:entry_offset + size]
        if uuid == BL31_UUID:
            name = "BL31"
            marker = None
        elif uuid == BL33_UUID:
            name = "BL33"
            marker = "U-Boot" if UBOOT_MARKER in payload else None
            if marker is None:
                raise ArtifactError(
                    "the BL33 entry does not contain a U-Boot image, the package is "
                    "not a boot loader package for this board"
                )
        else:
            name = "unknown-%s" % uuid.hex()
            marker = None
        components.append(
            {
                "name": name,
                "uuid": uuid.hex(),
                "offset": entry_offset,
                "size": size,
                "marker": marker,
            }
        )

    if not terminated:
        raise ArtifactError("the FIP table of contents is not terminated")
    names = [component["name"] for component in components]
    if "BL31" not in names or "BL33" not in names:
        raise ArtifactError(
            "the FIP package does not carry both BL31 and BL33, it carries %s"
            % (", ".join(names) if names else "no entries")
        )

    return {
        "kind": "atf-fip",
        "file": path.name,
        "size": len(data),
        "sha256": sha256_of(path),
        "serial_number": serial_number,
        "components": components,
    }


def inspect_bl2(path, max_size=None, expected_header=SPIM_NAND_HEADER):
    """Classify a MediaTek BL2 preloader by its boot medium header."""
    path = Path(path)
    data = path.read_bytes()
    if max_size is not None and len(data) > max_size:
        raise ArtifactError(
            "the BL2 image is %d bytes and does not fit its %d byte partition"
            % (len(data), max_size)
        )
    if len(data) < BL2_HEADER_SIZE:
        raise ArtifactError(
            "the BL2 image is only %d bytes long and carries no preloader payload"
            % len(data)
        )
    header = data[: len(expected_header)]
    if header != expected_header:
        raise ArtifactError(
            "the image does not carry the %r boot header this board expects"
            % expected_header.decode("ascii", "replace")
        )
    return {
        "kind": "atf-bl2",
        "file": path.name,
        "size": len(data),
        "sha256": sha256_of(path),
        "header": expected_header.decode("ascii", "replace"),
        "components": [
            {
                "name": "BL2",
                "size": len(data),
                "marker": expected_header.decode("ascii", "replace"),
            }
        ],
    }


def build_report(lock, artifacts, toolchain, build_env):
    """Assemble the build report of one candidate boot loader build."""
    partition_table = [
        {
            "label": entry["label"],
            "offset": entry["offset"],
            "size": entry["size"],
            "offset_hex": "0x%06x" % entry["offset"],
            "size_hex": "0x%x" % entry["size"],
            "address_space": "nmbm-logical",
        }
        for entry in lock["partition_contract"]["partitions"]
    ]
    reported = []
    for artifact in artifacts:
        path = Path(artifact["path"])
        if artifact["kind"] == "fip":
            info = inspect_fip(path, max_size=artifact.get("partition_size"))
        elif artifact["kind"] == "bl2":
            info = inspect_bl2(path, max_size=artifact.get("partition_size"))
        else:
            raise ArtifactError("unknown image kind %r" % (artifact["kind"],))
        info["partition"] = artifact.get("partition")
        info["partition_size"] = artifact.get("partition_size")
        info["file"] = artifact.get("file") or path.name
        reported.append(info)
    return {
        "device": lock.get("device"),
        "product": lock.get("product"),
        "status": "candidate-not-verified-on-device",
        "source_repository": lock["source"]["repository"],
        "source_commit": lock["source"]["commit"],
        "atf_tree": lock["source"]["atf_tree"],
        "uboot_tree": lock["source"]["uboot_tree"],
        "toolchain": dict(toolchain or {}),
        "build_parameters": dict(build_env or {}),
        "partition_table": partition_table,
        "artifacts": reported,
        "notes": [
            "The images are boot loader candidates. They are not system images and "
            "no image has been verified on hardware.",
            "The partition offsets are NMBM logical addresses, not physical NAND "
            "addresses.",
        ],
    }


def preflight(lock, source_dir):
    """Run every check that has to pass before the build may start."""
    errors = validate_lock(lock)
    if errors:
        raise LockError("; ".join(errors))

    source_dir = Path(source_dir)
    commit = lock["source"]["commit"]
    result = subprocess.run(
        ["git", "-C", str(source_dir), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise LockError("the source directory is not a usable git checkout")
    actual = result.stdout.strip()
    if actual != commit:
        raise LockError(
            "the source checkout is at %s, the lock pins %s" % (actual, commit)
        )

    uboot_tree, atf_tree = upstream_build_trees(source_dir)
    if uboot_tree != lock["source"]["uboot_tree"]:
        raise LockError(
            "the pinned build script builds the tree %s, the lock names %s"
            % (uboot_tree, lock["source"]["uboot_tree"])
        )
    if atf_tree != lock["source"]["atf_tree"]:
        raise LockError(
            "the pinned build script builds the ATF tree %s, the lock names %s"
            % (atf_tree, lock["source"]["atf_tree"])
        )

    check_worktree_clean(source_dir)
    check_output_dir_empty(source_dir)
    compiler = require_toolchain()
    return {
        "source_commit": actual,
        "uboot_tree": uboot_tree,
        "atf_tree": atf_tree,
        "cross_compiler": compiler,
    }


def report_lock_errors(errors):
    for error in errors:
        print("Error: %s" % error, file=sys.stderr)
    return BUILD_NOT_READY


def command_check(args):
    lock = load_lock(args.lock)
    errors = validate_lock(lock)
    if errors:
        return report_lock_errors(errors)
    print(json.dumps(render_plan(lock), indent=2, sort_keys=True))
    return 0


def command_verify_layout_source(args):
    lock = load_lock(args.lock)
    errors = validate_lock(lock)
    if errors:
        return report_lock_errors(errors)
    result = verify_layout_source(lock, Path(args.dts).read_text(encoding="utf-8"))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def command_preflight(args):
    lock = load_lock(args.lock)
    result = preflight(lock, args.source_dir)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def command_patch(args):
    lock = load_lock(args.lock)
    errors = validate_lock(lock)
    if errors:
        return report_lock_errors(errors)
    result = apply_device_patches(lock, args.source_dir, repo_root=args.repo_root)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def command_verify_patch(args):
    lock = load_lock(args.lock)
    errors = validate_lock(lock)
    if errors:
        return report_lock_errors(errors)
    text = Path(args.patch).read_text(encoding="utf-8")
    result = verify_patch(text, lock, source_dir=args.source_dir)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def command_effective_config(args):
    lock = load_lock(args.lock)
    text = Path(args.config).read_text(encoding="utf-8")
    result = verify_effective_config(text, lock)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def command_inspect(args):
    if args.kind == "fip":
        info = inspect_fip(args.path, max_size=args.max_size)
    elif args.kind == "bl2":
        info = inspect_bl2(args.path, max_size=args.max_size)
    else:
        raise ArtifactError("unknown image kind %r" % (args.kind,))
    print(json.dumps(info, indent=2, sort_keys=True))
    return 0


def command_toolchain(args):
    identity = toolchain_identity()
    Path(args.out).write_text(
        json.dumps(identity, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0


def command_report(args):
    lock = load_lock(args.lock)
    errors = validate_lock(lock)
    if errors:
        return report_lock_errors(errors)
    artifacts = []
    for spec in args.artifact:
        kind, path, partition, size = spec.split(":", 3)
        artifacts.append(
            {
                "kind": kind,
                "path": path,
                "partition": partition,
                "partition_size": int(size),
            }
        )
    build_env = json.loads(args.build_env) if args.build_env else {}
    toolchain = {}
    if args.toolchain_file:
        toolchain = json.loads(Path(args.toolchain_file).read_text(encoding="utf-8"))
    report = build_report(lock, artifacts, toolchain, build_env)
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

    layout_source = subparsers.add_parser(
        "verify-layout-source",
        help="check the pinned device tree against the locked layout whitelist",
    )
    layout_source.add_argument("--lock", required=True)
    layout_source.add_argument("--dts", required=True)
    layout_source.set_defaults(handler=command_verify_layout_source)

    preflight = subparsers.add_parser(
        "preflight", help="run every check that has to pass before the build"
    )
    preflight.add_argument("--lock", required=True)
    preflight.add_argument("--source-dir", required=True)
    preflight.set_defaults(handler=command_preflight)

    patch = subparsers.add_parser("patch", help="apply the device patches to a build copy")
    patch.add_argument("--lock", required=True)
    patch.add_argument("--source-dir", required=True)
    patch.add_argument("--repo-root", default="")
    patch.set_defaults(handler=command_patch)

    verify_patch_parser = subparsers.add_parser(
        "verify-patch", help="check a device patch against the recovery contract"
    )
    verify_patch_parser.add_argument("--lock", required=True)
    verify_patch_parser.add_argument("--patch", required=True)
    verify_patch_parser.add_argument("--source-dir", default=None)
    verify_patch_parser.set_defaults(handler=command_verify_patch)

    effective = subparsers.add_parser(
        "verify-config", help="check the configuration the build produced"
    )
    effective.add_argument("--lock", required=True)
    effective.add_argument("--config", required=True)
    effective.set_defaults(handler=command_effective_config)

    inspect = subparsers.add_parser("inspect", help="classify one image by its content")
    inspect.add_argument("--kind", required=True, choices=("fip", "bl2"))
    inspect.add_argument("--path", required=True)
    inspect.add_argument("--max-size", type=int, default=None)
    inspect.set_defaults(handler=command_inspect)

    toolchain = subparsers.add_parser("toolchain", help="record the toolchain identity")
    toolchain.add_argument("--out", required=True)
    toolchain.set_defaults(handler=command_toolchain)

    report = subparsers.add_parser("report", help="write the build report")
    report.add_argument("--lock", required=True)
    report.add_argument("--out", required=True)
    report.add_argument("--toolchain-file", default="")
    report.add_argument("--build-env", default="")
    report.add_argument(
        "--artifact",
        action="append",
        default=[],
        help="kind:path:partition:partition_size",
    )
    report.set_defaults(handler=command_report)

    args = parser.parse_args(argv)
    try:
        return args.handler(args)
    except (LockError, ArtifactError) as error:
        print("Error: %s" % error, file=sys.stderr)
        return BUILD_NOT_READY


if __name__ == "__main__":
    sys.exit(main())
