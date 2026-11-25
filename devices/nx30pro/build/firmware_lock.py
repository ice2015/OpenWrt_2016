#!/usr/bin/env python3
"""Validate the NX30 Pro firmware source lock and the built configuration.

The helper is the single place that knows what a build ready firmware lock
looks like. It refuses a lock that does not pin the source commit and the
feed revisions, that names another device profile, that does not match the
partition contract of the boot loader, or that does not confirm the packages
of the requirement table.

The configuration check runs against the final .config that the build
produced, never against the fragment that was fed into it.
"""

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path


COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")

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


def validate_lock(lock):
    """Return the list of reasons why the lock is not build ready."""
    errors = []
    source = lock.get("source") or {}
    revision = source.get("revision")
    if not isinstance(revision, str) or not COMMIT_RE.match(revision):
        errors.append(
            "the source revision must be a full 40 character commit id, got %r"
            % (revision,)
        )
    repository = source.get("repository")
    if not repository or not repository.startswith("https://"):
        errors.append("the source repository is missing or not a https url")

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

    packages = lock.get("packages") or []
    if not packages:
        errors.append("the lock has no package table")
    for entry in packages:
        if not entry.get("package"):
            errors.append("a package table entry has no package name")
        if entry.get("status") not in ("available", "partial", "unavailable"):
            errors.append(
                "the package %s has an unknown status %r"
                % (entry.get("package"), entry.get("status"))
            )

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


def verify_device_tree(text, lock):
    """Check that the device tree carries the partition contract of the lock."""
    pattern = re.compile(
        r"partition@\w+\s*\{\s*label\s*=\s*\"([^\"]+)\";\s*reg\s*=\s*<([^>]+)>;\s*\};",
        re.S,
    )
    actual = []
    for label, register in pattern.findall(text):
        values = register.split()
        if len(values) != 2:
            continue
        try:
            actual.append((label, int(values[0], 0), int(values[1], 0)))
        except ValueError:
            continue
    expected = [
        (entry["label"], entry["offset"], entry["size"])
        for entry in lock["partition_contract"]["partitions"]
    ]
    if actual != expected:
        raise ConfigError(
            "the device tree does not carry the partition contract of the lock: %s"
            % actual
        )
    return actual


def verify_config(text, lock):
    """Check the configuration that the build really produced."""
    symbols = config_symbols(text)
    errors = []

    if symbols.get("CONFIG_TARGET_mediatek_mt7981_DEVICE_h3c_nx30pro_112M") != "y":
        errors.append("the configuration does not select the NX30 Pro 112M profile")
    profiles = [
        name
        for name, value in symbols.items()
        if name.startswith("CONFIG_TARGET_mediatek_mt7981_DEVICE_") and value == "y"
    ]
    if len(profiles) != 1:
        errors.append(
            "the configuration selects %d device profiles, exactly one is required"
            % len(profiles)
        )

    for entry in lock.get("packages") or []:
        if entry.get("status") != "available":
            continue
        symbol = entry.get("symbol")
        if not symbol:
            continue
        for name in [part.strip() for part in symbol.split(",")]:
            if not name:
                continue
            key = name.split("=")[0].strip()
            if symbols.get(key) != "y":
                errors.append(
                    "the required package %s of %s is not enabled"
                    % (key, entry.get("requirement"))
                )

    for entry in lock.get("excluded_packages") or []:
        name = entry.get("package")
        if not name:
            continue
        if symbols.get("CONFIG_PACKAGE_%s" % name) == "y":
            errors.append(
                "the excluded package %s stayed enabled: %s"
                % (name, entry.get("reason"))
            )

    if errors:
        raise ConfigError("; ".join(errors))
    return symbols


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
        return 1
    print(json.dumps(render_plan(lock), indent=2, sort_keys=True))
    return 0


def command_verify_config(args):
    lock = load_lock(args.lock)
    text = Path(args.config).read_text(encoding="utf-8")
    verify_config(text, lock)
    print("The built configuration matches the source lock.")
    return 0


def command_verify_device_tree(args):
    lock = load_lock(args.lock)
    text = Path(args.dts).read_text(encoding="utf-8")
    verify_device_tree(text, lock)
    print("The device tree carries the partition contract of the lock.")
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

    verify_tree = subparsers.add_parser(
        "verify-device-tree", help="check the partition contract of the device tree"
    )
    verify_tree.add_argument("--lock", required=True)
    verify_tree.add_argument("--dts", required=True)
    verify_tree.set_defaults(handler=command_verify_device_tree)

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
    except (LockError, ConfigError) as error:
        print("Error: %s" % error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
