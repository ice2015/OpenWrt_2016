"""Exercise actual configuration consumers and their repository boundaries."""
from dataclasses import replace
from contextlib import redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

from tools.manifest import load_catalog, validate_catalog, main
from tests.scripts.test_scripts import (
    full_base_config, lite_base_config, run_full_configure, run_lite_configure,
)

ROOT = Path(__file__).resolve().parents[2]
DEVICE = ROOT / "devices/tr3000"


class DeviceIsolationTests(unittest.TestCase):
    def test_device_directory_layers_cannot_include_the_device_container(self):
        catalog = load_catalog(ROOT)
        original = next(d for d in catalog.devices if d.id == "tr3000")
        for field in ("config_layers", "feed_layers", "patch_layers", "overlay_layers"):
            for layer in (".", "devices", "devices/tr3000/.."):
                device = replace(original, **{field: (layer,)})
                fixture = replace(catalog, devices=(device,))
                self.assertTrue(validate_catalog(fixture, ROOT), (field, layer))

    @unittest.skipIf(os.name == "nt", "direct POSIX execution is verified under Linux")
    def test_legacy_executable_modes_support_direct_invocation(self):
        evidence = json.loads((ROOT / "docs/superpowers/plans/2026-11-25-device-directory-reorganization-inputs.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as temp:
            for record in evidence["files"]:
                if record["source"].startswith("scripts/") and record["git_mode"] == "100755":
                    command = ROOT / record["source"]
                    self.assertTrue(os.access(command, os.X_OK), str(command))
                    result = subprocess.run([str(command), "--help"], cwd=temp, capture_output=True, text=True)
                    self.assertEqual(0, result.returncode, result.stderr)
                    self.assertIn("Usage:", result.stdout)

    @unittest.skipIf(os.name == "nt", "POSIX source aliases are verified under Linux")
    def test_legacy_libraries_can_be_sourced_from_posix_callers(self):
        libraries = ["lite-common.sh", *[p.name for p in (DEVICE / "lite/runtime").glob("*-lib.sh")],
                     *[p.name for p in (DEVICE / "full/runtime").glob("*-lib.sh")]]
        with tempfile.TemporaryDirectory(prefix="source aliases ") as temp:
            for library in libraries:
                path = ROOT / "scripts" / library
                for shell in ("sh", "bash"):
                    result = subprocess.run([shell, "-c", '. "$1"', "library-caller", str(path)],
                                            cwd=temp, capture_output=True, text=True)
                    self.assertEqual(0, result.returncode, (shell, library, result.stderr))

    def test_actions_preserve_everything_except_migrated_paths(self):
        evidence = json.loads((ROOT / "docs/superpowers/plans/2026-11-25-device-directory-reorganization-inputs.json").read_text(encoding="utf-8"))
        for relative, expected in evidence["workflow_sha256"].items():
            text = (ROOT / relative).read_text(encoding="utf-8")
            for record in sorted(evidence["files"], key=lambda r: -len(r["target"])):
                text = text.replace(record["target"], record["source"])
            self.assertEqual(expected, hashlib.sha256(text.encode()).hexdigest(), relative)

    def test_actions_use_real_entries_and_nonempty_variant_cache_inputs(self):
        groups = []
        for variant in ("lite", "full"):
            text = (ROOT / f".github/workflows/build-{variant}.yml").read_text(encoding="utf-8")
            self.assertIn(f"sh devices/tr3000/build/build-{variant}.sh", text)
            self.assertIn(f"tr3000-{variant}/ccache", text)
            groups.append(re.search(r"(?m)^  group: (.+)$", text).group(1))
            hashes = re.findall(r"hashFiles\(([^)]*)\)", text)
            self.assertTrue(hashes)
            for expression in hashes:
                for relative in re.findall(r"'([^']+)'", expression):
                    self.assertTrue(list(ROOT.glob(relative)), relative)
                    self.assertTrue(relative.startswith(f"devices/tr3000/{variant}/"), relative)
        self.assertEqual(2, len(set(groups)))
        uboot = (ROOT / ".github/workflows/build-uboot.yml").read_text(encoding="utf-8")
        self.assertIn("sh devices/tr3000/build/build-uboot.sh", uboot)

    def test_actual_configure_consumers_isolate_variants(self):
        with tempfile.TemporaryDirectory(prefix="variant inputs ") as temp:
            repo = Path(temp)
            shutil.copytree(DEVICE, repo / "devices/tr3000")
            shutil.copytree(ROOT / "scripts", repo / "scripts")
            def configured():
                snapshots = {}
                for name, configure, base in (("lite", run_lite_configure, lite_base_config),
                                               ("full", run_full_configure, full_base_config)):
                    result, config, assets = configure(base(), repo_root=repo)
                    self.assertEqual(0, result.returncode, result.stderr)
                    snapshots[name] = (config, assets)
                return snapshots
            before = configured()
            network = repo / "devices/tr3000/lite/files/etc/config/network"
            network.write_text(network.read_text(encoding="utf-8") + "\n# isolation fixture\n", encoding="utf-8")
            lite_changed = configured()
            self.assertNotEqual(before["lite"], lite_changed["lite"])
            self.assertEqual(before["full"], lite_changed["full"])
            shared = repo / "devices/tr3000/shared/files/etc/isolation-fixture"
            shared.write_text("fixture", encoding="utf-8")
            shared_changed = configured()
            for variant in ("lite", "full"):
                self.assertNotEqual(lite_changed[variant], shared_changed[variant])

    def test_resolved_device_input_hashes_do_not_include_other_devices(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "manifests/devices").mkdir(parents=True)
            def write(path, value):
                p = root / path
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(json.dumps(value) if isinstance(value, dict) else value, encoding="utf-8")
            write("manifests/sources.json", {
                "schema_version": 1,
                "common_layers": {"config_layers": ["configs/common.config"]},
                "sources": [{"id": "fixture", "repository": "https://example.invalid/source.git", "revision": "UNRESOLVED",
                             "config_layers": ["configs/distribution.config"]}],
            })
            write("configs/common.config", "# common\n")
            write("configs/distribution.config", "# distribution\n")
            for device in ("tr3000", "a6s", "nx30pro"):
                write(f"devices/{device}/config.config", "# fixture\n")
                write(f"manifests/devices/{device}.json", {
                    "schema_version": 1, "id": device, "display_name": device,
                    "supported_distributions": ["fixture"], "target": "UNRESOLVED",
                    "subtarget": "UNRESOLVED", "profile": "UNRESOLVED",
                    "config_layers": [f"devices/{device}/config.config"],
                })
            def hashes():
                result = {}
                for device in ("tr3000", "a6s", "nx30pro"):
                    output = io.StringIO()
                    with redirect_stdout(output):
                        self.assertEqual(0, main(["--root", str(root), "resolve", "--distribution", "fixture", "--device", device]))
                    layers = json.loads(output.getvalue())["config_layers"]
                    self.assertEqual(["configs/common.config", "configs/distribution.config", f"devices/{device}/config.config"], layers)
                    result[device] = hashlib.sha256(b"".join(p.encode() + (root / p).read_bytes() for p in layers)).hexdigest()
                return result
            for changed in ("tr3000", "a6s", "nx30pro"):
                before = hashes()
                write(f"devices/{changed}/config.config", "# changed\n")
                after = hashes()
                for device in before:
                    self.assertEqual(device == changed, before[device] != after[device])

    def test_configured_images_match_the_pre_migration_baseline(self):
        evidence = json.loads((ROOT / "docs/superpowers/plans/2026-11-25-device-directory-reorganization-inputs.json").read_text(encoding="utf-8"))
        for variant, configure, base in (
            ("lite", run_lite_configure, lite_base_config),
            ("full", run_full_configure, full_base_config),
        ):
            result, config, assets = configure(base())
            self.assertEqual(0, result.returncode, result.stderr)
            expected = evidence["configured_baseline"][variant]
            self.assertEqual(expected["config_sha256"], hashlib.sha256(config.encode()).hexdigest())
            self.assertEqual(expected["asset_sha256"], {
                path: hashlib.sha256(text.encode()).hexdigest() for path, text in assets.items()
            })

    def test_installed_runtime_scripts_are_real_device_scripts(self):
        for variant, configure, base in (
            ("lite", run_lite_configure, lite_base_config),
            ("full", run_full_configure, full_base_config),
        ):
            result, _, assets = configure(base())
            self.assertEqual(0, result.returncode, result.stderr)
            source = DEVICE / variant / "runtime" / f"tr3000-{variant}-wifi.sh"
            self.assertEqual(source.read_text(encoding="utf-8"), assets[f"files/usr/sbin/tr3000-{variant}-wifi"])
            self.assertEqual(
                (DEVICE / "shared/runtime/lite-common.sh").read_text(encoding="utf-8"),
                assets["files/usr/sbin/lite-common.sh"],
            )
            for path, text in assets.items():
                if path.startswith(("files/usr/", "files/root/scripts/")):
                    self.assertNotIn("devices/tr3000/", text, path)

    def test_old_build_commands_work_outside_repository_and_with_spaces(self):
        with tempfile.TemporaryDirectory(prefix="device entry ") as temp:
            repo = Path(temp) / "repo with spaces"
            shutil.copytree(ROOT / "scripts", repo / "scripts")
            shutil.copytree(DEVICE, repo / "devices/tr3000")
            for name in ("build-lite", "build-full", "configure-lite", "configure-full", "build-uboot", "verify-image"):
                old = repo / "scripts" / (name + ".sh")
                real = repo / "devices/tr3000/build" / (name + ".sh")
                for argument in ("--help", "--invalid-reorganization-option"):
                    results = [subprocess.run(["sh", str(p), argument], cwd=temp,
                                              capture_output=True, text=True) for p in (old, real)]
                    self.assertEqual(results[0].returncode, results[1].returncode, name)
                    self.assertEqual(argument == "--help", results[0].returncode == 0, name)
                    self.assertIn("Usage:" if argument == "--help" else "unknown", results[0].stdout + results[0].stderr)

    def test_device_layers_reject_other_devices_and_symlink_aliases(self):
        catalog = load_catalog(ROOT)
        device = next(d for d in catalog.devices if d.id == "tr3000")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for relative in ("devices/tr3000/input", "devices/a6s/input", "configs/shared"):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("fixture")
            alias = root / "configs/alias"
            alias.symlink_to(root / "devices/a6s/input")
            (root / "configs/device-container").symlink_to(root / "devices", target_is_directory=True)
            (root / "configs/repository-container").symlink_to(root, target_is_directory=True)
            for field in ("config_layers", "feed_layers", "patch_layers", "overlay_layers"):
                for layer in ("devices/a6s/input", "configs/alias", "devices/a6s/../tr3000/input",
                              "configs/device-container", "configs/repository-container"):
                    changed = replace(device, **{name: () for name in ("config_layers", "feed_layers", "patch_layers", "overlay_layers")})
                    changed = replace(changed, **{field: (layer,)})
                    fixture = replace(catalog, devices=(changed,), common_layers={}, sources=tuple(
                        replace(s, config_layers=(), feed_layers=(), patch_layers=(), overlay_layers=()) for s in catalog.sources
                    ))
                    errors = validate_catalog(fixture, root)
                    self.assertTrue(any("another device" in error for error in errors), (field, layer, errors))

    def test_migrated_inputs_retain_baseline_bytes(self):
        evidence = json.loads((ROOT / "docs/superpowers/plans/2026-11-25-device-directory-reorganization-inputs.json").read_text(encoding="utf-8"))
        for record in evidence["files"]:
            # Build implementations and relocated documentation need relative reference updates.
            if record["source"].startswith(("docs/", "configs/devices/TR3000/")) or "/build/" in record["target"]:
                continue
            path = ROOT / record["target"]
            data = path.readlink().as_posix().encode() if path.is_symlink() else path.read_bytes()
            self.assertEqual(record["sha256"], hashlib.sha256(data).hexdigest(), record["target"])
