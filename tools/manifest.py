#!/usr/bin/env python3
"""Load, validate, list, and resolve firmware build manifests."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import sys
from typing import Sequence


UNRESOLVED = "UNRESOLVED"
LAYER_FIELDS = ("config_layers", "feed_layers", "patch_layers", "overlay_layers")


class ManifestError(ValueError):
    """Raised when manifest files cannot be parsed into the catalog model."""


@dataclass(frozen=True)
class Source:
    id: str
    repository: str
    revision: str
    config_layers: tuple[str, ...] = ()
    feed_layers: tuple[str, ...] = ()
    patch_layers: tuple[str, ...] = ()
    overlay_layers: tuple[str, ...] = ()


@dataclass(frozen=True)
class Device:
    id: str
    display_name: str
    supported_distributions: tuple[str, ...]
    target: str
    subtarget: str
    profile: str
    config_layers: tuple[str, ...] = ()
    feed_layers: tuple[str, ...] = ()
    patch_layers: tuple[str, ...] = ()
    overlay_layers: tuple[str, ...] = ()
    artifact_patterns: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class Target:
    distribution_id: str
    device_id: str
    display_name: str
    build_ready: bool
    unresolved: tuple[str, ...]


@dataclass(frozen=True)
class Catalog:
    sources: tuple[Source, ...]
    devices: tuple[Device, ...]
    common_layers: dict[str, tuple[str, ...]]


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ManifestError(f"invalid JSON in {path}: {error.msg}") from error
    except OSError as error:
        raise ManifestError(f"cannot read manifest {path}: {error}") from error
    if not isinstance(value, dict):
        raise ManifestError(f"manifest root must be an object: {path}")
    return value


def _strings(value: object, field: str, path: Path) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ManifestError(f"{field} must be an array of strings: {path}")
    return tuple(value)


def _required_string(value: dict, field: str, path: Path) -> str:
    result = value.get(field)
    if not isinstance(result, str) or not result:
        raise ManifestError(f"{field} must be a non-empty string: {path}")
    return result


def _source(value: dict, path: Path) -> Source:
    return Source(
        id=_required_string(value, "id", path),
        repository=_required_string(value, "repository", path),
        revision=_required_string(value, "revision", path),
        **{field: _strings(value.get(field, []), field, path) for field in LAYER_FIELDS},
    )


def _device(value: dict, path: Path) -> Device:
    return Device(
        id=_required_string(value, "id", path),
        display_name=_required_string(value, "display_name", path),
        supported_distributions=_strings(value.get("supported_distributions"), "supported_distributions", path),
        target=_required_string(value, "target", path),
        subtarget=_required_string(value, "subtarget", path),
        profile=_required_string(value, "profile", path),
        **{field: _strings(value.get(field, []), field, path) for field in LAYER_FIELDS},
        artifact_patterns=_strings(value.get("artifact_patterns", []), "artifact_patterns", path),
        notes=_strings(value.get("notes", []), "notes", path),
    )


def load_catalog(root: Path) -> Catalog:
    root = root.resolve()
    sources_path = root / "manifests/sources.json"
    sources_value = _read_json(sources_path)
    if sources_value.get("schema_version") != 1:
        raise ManifestError(f"unsupported schema_version in {sources_path}")
    raw_sources = sources_value.get("sources")
    if not isinstance(raw_sources, list) or not all(isinstance(item, dict) for item in raw_sources):
        raise ManifestError(f"sources must be an array of objects: {sources_path}")
    common_value = sources_value.get("common_layers", {})
    if not isinstance(common_value, dict):
        raise ManifestError(f"common_layers must be an object: {sources_path}")
    common_layers = {
        field: _strings(common_value.get(field, []), f"common_layers.{field}", sources_path)
        for field in LAYER_FIELDS
    }

    devices: list[Device] = []
    device_dir = root / "manifests/devices"
    for device_path in sorted(device_dir.glob("*.json")):
        device_value = _read_json(device_path)
        if device_value.get("schema_version") != 1:
            raise ManifestError(f"unsupported schema_version in {device_path}")
        devices.append(_device(device_value, device_path))

    return Catalog(
        sources=tuple(_source(item, sources_path) for item in raw_sources),
        devices=tuple(devices),
        common_layers=common_layers,
    )


def _duplicate_ids(values: Sequence[Source] | Sequence[Device], label: str) -> list[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value.id in seen:
            duplicates.add(value.id)
        seen.add(value.id)
    return [f"duplicate {label} id: {identifier}" for identifier in sorted(duplicates)]


def _validate_layer(owner: str, layer: str, root: Path) -> list[str]:
    candidate = Path(layer)
    if candidate.is_absolute():
        return [f"{owner} layer escapes repository: {layer}"]
    resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        return [f"{owner} layer escapes repository: {layer}"]
    if not resolved.exists():
        return [f"{owner} references missing layer: {layer}"]
    return []


def validate_catalog(catalog: Catalog, root: Path) -> list[str]:
    root = root.resolve()
    errors = _duplicate_ids(catalog.sources, "source")
    errors.extend(_duplicate_ids(catalog.devices, "device"))
    source_ids = {source.id for source in catalog.sources}

    for field in LAYER_FIELDS:
        for layer in catalog.common_layers.get(field, ()):
            errors.extend(_validate_layer("common", layer, root))
    for source in catalog.sources:
        for field in LAYER_FIELDS:
            for layer in getattr(source, field):
                errors.extend(_validate_layer(f"source {source.id}", layer, root))
    for device in catalog.devices:
        for distribution in device.supported_distributions:
            if distribution not in source_ids:
                errors.append(f"device {device.id} references unknown distribution: {distribution}")
        for field in LAYER_FIELDS:
            for layer in getattr(device, field):
                errors.extend(_validate_layer(f"device {device.id}", layer, root))
    return sorted(errors)


def _unresolved(source: Source, device: Device, revision_override: str | None = None) -> tuple[str, ...]:
    unresolved: list[str] = []
    if (revision_override or source.revision) == UNRESOLVED:
        unresolved.append("source revision is UNRESOLVED")
    for field in ("target", "subtarget", "profile"):
        if getattr(device, field) == UNRESOLVED:
            unresolved.append(f"device {field} is UNRESOLVED")
    return tuple(unresolved)


def list_targets(catalog: Catalog) -> list[Target]:
    sources = {source.id: source for source in catalog.sources}
    targets = []
    for device in catalog.devices:
        for distribution in device.supported_distributions:
            source = sources.get(distribution)
            unresolved = _unresolved(source, device) if source else ("unknown distribution",)
            targets.append(
                Target(
                    distribution_id=distribution,
                    device_id=device.id,
                    display_name=device.display_name,
                    build_ready=not unresolved,
                    unresolved=unresolved,
                )
            )
    return sorted(targets, key=lambda target: (target.distribution_id, target.device_id))


def _resolved_payload(catalog: Catalog, source: Source, device: Device, revision: str | None) -> dict:
    return {
        "distribution": source.id,
        "device": device.id,
        "display_name": device.display_name,
        "repository": source.repository,
        "revision": revision or source.revision,
        "target": device.target,
        "subtarget": device.subtarget,
        "profile": device.profile,
        "config_layers": [
            *catalog.common_layers.get("config_layers", ()),
            *source.config_layers,
            *device.config_layers,
        ],
        "feed_layers": [
            *catalog.common_layers.get("feed_layers", ()),
            *source.feed_layers,
            *device.feed_layers,
        ],
        "patch_layers": [
            *catalog.common_layers.get("patch_layers", ()),
            *source.patch_layers,
            *device.patch_layers,
        ],
        "overlay_layers": [
            *catalog.common_layers.get("overlay_layers", ()),
            *source.overlay_layers,
            *device.overlay_layers,
        ],
        "artifact_patterns": list(device.artifact_patterns),
        "notes": list(device.notes),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("validate", help="validate all manifest references")
    subparsers.add_parser("list", help="list supported distribution/device pairs")
    resolve = subparsers.add_parser("resolve", help="resolve one distribution/device pair")
    resolve.add_argument("--distribution", required=True)
    resolve.add_argument("--device", required=True)
    resolve.add_argument("--revision")
    resolve.add_argument("--require-build-ready", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        catalog = load_catalog(args.root)
    except ManifestError as error:
        print(error, file=sys.stderr)
        return 2
    errors = validate_catalog(catalog, args.root)
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 2

    if args.command == "validate":
        print("Manifest catalog is valid.")
        return 0
    if args.command == "list":
        for target in list_targets(catalog):
            state = "ready" if target.build_ready else "unresolved"
            print(f"{target.distribution_id}\t{target.device_id}\t{state}\t{target.display_name}")
        return 0

    sources = {source.id: source for source in catalog.sources}
    devices = {device.id: device for device in catalog.devices}
    source = sources.get(args.distribution)
    device = devices.get(args.device)
    if source is None or device is None or args.distribution not in device.supported_distributions:
        print(
            f"unsupported distribution/device pair: {args.distribution}/{args.device}",
            file=sys.stderr,
        )
        return 2
    unresolved = _unresolved(source, device, args.revision)
    if args.require_build_ready and unresolved:
        print("\n".join(unresolved), file=sys.stderr)
        return 3
    print(json.dumps(_resolved_payload(catalog, source, device, args.revision), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

