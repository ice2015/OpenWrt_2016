#!/usr/bin/env python3
"""Validate the NX30 Pro U-Boot source lock and inspect boot loader images.

The helper is the only place that knows what a build ready source lock looks
like. It refuses a lock that does not pin a full upstream commit, that names
another board, that carries a partition layout other than the 112M layout of
the selected system, or that does not confirm both image types.

Artifacts are classified by their content. The ATF FIP package is recognised
by its table of contents header and its BL31 and BL33 entries, the MediaTek
BL2 preloader by the SPI-NAND boot header that the U-Boot itself checks.
"""

import argparse
import hashlib
import json
import re
import struct
import sys
from pathlib import Path


COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")

EXPECTED_REPOSITORY = "https://github.com/hanwckf/bl-mt798x"
EXPECTED_SOC = "mt7981"
EXPECTED_BOARD = "h3c_magic-nx30-pro"

# The partition contract of the selected system, from the device tree of
# jerryhan77/immortalwrt-mt798x at the locked commit.
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

EXPECTED_FIP_ARTIFACT = "mt7981_h3c_magic-nx30-pro-fip-fixed-parts.bin"
EXPECTED_BL2_ARTIFACT = "mt7981_h3c_magic-nx30-pro-bl2.bin"

TOC_HEADER_NAME = 0xAA640001
TOC_HEADER = struct.Struct("<IIQ")
TOC_ENTRY = struct.Struct("<16sQQQ")
BL31_UUID = bytes.fromhex("47d4086d4cfe98469b952950cbbd5a00")
BL33_UUID = bytes.fromhex("d6d0eea7fcead54b97829934f234b6e4")
SPIM_NAND_HEADER = b"SPINAND!"
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


def load_lock(path):
    try:
        lock = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise LockError("the source lock cannot be read: %s" % error)
    if not isinstance(lock, dict):
        raise LockError("the source lock is not a JSON object")
    return lock


def validate_lock(lock):
    """Return the list of reasons why the lock is not build ready."""
    errors = []
    source = lock.get("source") or {}
    build_env = lock.get("source", {}).get("build_env") or source.get("build_env") or {}

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
    if str(build_env.get("MULTI_LAYOUT")) != "0":
        errors.append(
            "this board has no multi layout defconfig, the lock sets MULTI_LAYOUT=%r"
            % (build_env.get("MULTI_LAYOUT"),)
        )

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
    if patch.get("value") != EXPECTED_MTDPARTS:
        errors.append(
            "the minimal device patch does not produce the 112M partition table %r"
            % (patch.get("value"),)
        )
    if compatibility.get("layout_matches_upstream_stock") is not False:
        errors.append(
            "the lock must record that the upstream stock layout does not match"
        )

    artifacts = lock.get("artifacts") or {}
    if not artifacts.get("fip"):
        errors.append("image type not confirmed: the lock names no FIP artifact")
    elif EXPECTED_FIP_ARTIFACT not in str(artifacts["fip"]):
        errors.append(
            "image type not confirmed: the lock names an unexpected FIP artifact %r"
            % (artifacts["fip"],)
        )
    if not artifacts.get("bl2"):
        errors.append("image type not confirmed: the lock names no BL2 artifact")
    elif EXPECTED_BL2_ARTIFACT not in str(artifacts["bl2"]):
        errors.append(
            "image type not confirmed: the lock names an unexpected BL2 artifact %r"
            % (artifacts["bl2"],)
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
        "build_env": source.get("build_env"),
        "toolchain": lock.get("toolchain"),
        "partition_table": contract.get("partitions"),
        "artifacts": lock.get("artifacts"),
    }


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
    while offset + TOC_ENTRY.size <= len(data):
        uuid, entry_offset, size, _entry_flags = TOC_ENTRY.unpack_from(data, offset)
        offset += TOC_ENTRY.size
        if uuid == b"\x00" * 16:
            break
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

    names = [component["name"] for component in components]
    if "BL31" not in names or "BL33" not in names:
        raise ArtifactError(
            "the FIP package does not carry both BL31 and BL33, it carries %s"
            % ", ".join(names) if names else "no entries"
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


def build_report(lock, artifacts, toolchain_version, build_env):
    """Assemble the build report of one candidate boot loader build."""
    partition_table = [
        {
            "label": entry["label"],
            "offset": entry["offset"],
            "size": entry["size"],
            "offset_hex": "0x%06x" % entry["offset"],
            "size_hex": "0x%x" % entry["size"],
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
        "toolchain_package": lock["toolchain"]["package"],
        "toolchain_version": toolchain_version,
        "build_parameters": dict(build_env or {}),
        "partition_table": partition_table,
        "artifacts": reported,
        "notes": [
            "The images are boot loader candidates. They are not system images and "
            "no image has been verified on hardware.",
        ],
    }


def apply_device_patch(source_dir, lock):
    """Apply the minimal device patch to the boot loader build copy."""
    source_dir = Path(source_dir)
    tree = lock["source"]["uboot_tree"]
    target = source_dir / tree / "configs" / (
        "%s_%s_defconfig" % (EXPECTED_SOC, EXPECTED_BOARD)
    )
    if not target.is_file():
        raise LockError("the boot loader defconfig is missing: %s" % target)
    value = lock["compatibility"]["minimal_device_patch"]["value"]
    lines = target.read_text(encoding="utf-8").splitlines(keepends=True)
    replaced = False
    old_value = None
    for index, line in enumerate(lines):
        if line.startswith("CONFIG_MTDPARTS_DEFAULT="):
            old_value = line.strip()
            lines[index] = 'CONFIG_MTDPARTS_DEFAULT="%s"\n' % value
            replaced = True
    if not replaced:
        raise LockError(
            "the boot loader defconfig has no CONFIG_MTDPARTS_DEFAULT to replace"
        )
    target.write_text("".join(lines), encoding="utf-8")
    return {
        "file": str(target),
        "old": old_value,
        "new": 'CONFIG_MTDPARTS_DEFAULT="%s"' % value,
    }


def command_check(args):
    lock = load_lock(args.lock)
    errors = validate_lock(lock)
    if errors:
        for error in errors:
            print("Error: %s" % error, file=sys.stderr)
        return 1
    print(json.dumps(render_plan(lock), indent=2, sort_keys=True))
    return 0


def command_patch(args):
    lock = load_lock(args.lock)
    errors = validate_lock(lock)
    if errors:
        for error in errors:
            print("Error: %s" % error, file=sys.stderr)
        return 1
    result = apply_device_patch(args.source_dir, lock)
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


def command_report(args):
    lock = load_lock(args.lock)
    errors = validate_lock(lock)
    if errors:
        for error in errors:
            print("Error: %s" % error, file=sys.stderr)
        return 1
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
    report = build_report(lock, artifacts, args.toolchain_version, build_env)
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

    patch = subparsers.add_parser("patch", help="apply the device patch to a build copy")
    patch.add_argument("--lock", required=True)
    patch.add_argument("--source-dir", required=True)
    patch.set_defaults(handler=command_patch)

    inspect = subparsers.add_parser("inspect", help="classify one image by its content")
    inspect.add_argument("--kind", required=True, choices=("fip", "bl2"))
    inspect.add_argument("--path", required=True)
    inspect.add_argument("--max-size", type=int, default=None)
    inspect.set_defaults(handler=command_inspect)

    report = subparsers.add_parser("report", help="write the build report")
    report.add_argument("--lock", required=True)
    report.add_argument("--out", required=True)
    report.add_argument("--toolchain-version", default="UNRESOLVED")
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
        return 1


if __name__ == "__main__":
    sys.exit(main())
