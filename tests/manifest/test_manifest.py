from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.manifest import ManifestError, load_catalog, list_targets, main, validate_catalog


class ManifestTests(unittest.TestCase):
    def test_repository_catalog_loads_initial_devices(self) -> None:
        catalog = load_catalog(ROOT)

        self.assertEqual(
            {"tr3000", "x86-64", "raspberry-pi", "nx30pro"},
            {device.id for device in catalog.devices},
        )
        self.assertEqual([], validate_catalog(catalog, ROOT))

    def test_targets_are_listed_deterministically(self) -> None:
        catalog = load_catalog(ROOT)

        pairs = [(target.distribution_id, target.device_id) for target in list_targets(catalog)]

        self.assertEqual(
            [
                ("immortalwrt", "raspberry-pi"),
                ("immortalwrt", "tr3000"),
                ("immortalwrt", "x86-64"),
                ("immortalwrt-mt798x", "nx30pro"),
                ("openwrt", "raspberry-pi"),
                ("openwrt", "tr3000"),
                ("openwrt", "x86-64"),
            ],
            pairs,
        )

    def test_invalid_json_raises_manifest_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "manifests/devices").mkdir(parents=True)
            (root / "manifests/sources.json").write_text("{not-json", encoding="utf-8")

            with self.assertRaisesRegex(ManifestError, "invalid JSON"):
                load_catalog(root)

    def test_duplicate_ids_are_reported(self) -> None:
        with self.catalog_fixture() as root:
            sources = json.loads((root / "manifests/sources.json").read_text(encoding="utf-8"))
            sources["sources"].append(dict(sources["sources"][0]))
            self.write_json(root / "manifests/sources.json", sources)
            catalog = load_catalog(root)

            errors = validate_catalog(catalog, root)

            self.assertIn("duplicate source id: openwrt", errors)

    def test_unknown_distribution_is_reported(self) -> None:
        with self.catalog_fixture() as root:
            device_path = root / "manifests/devices/router.json"
            device = json.loads(device_path.read_text(encoding="utf-8"))
            device["supported_distributions"] = ["missing-source"]
            self.write_json(device_path, device)
            catalog = load_catalog(root)

            errors = validate_catalog(catalog, root)

            self.assertIn("device router references unknown distribution: missing-source", errors)

    def test_missing_and_escaping_layer_paths_are_reported(self) -> None:
        with self.catalog_fixture() as root:
            device_path = root / "manifests/devices/router.json"
            device = json.loads(device_path.read_text(encoding="utf-8"))
            device["config_layers"] = ["configs/missing.config", "../outside.config"]
            self.write_json(device_path, device)
            catalog = load_catalog(root)

            errors = validate_catalog(catalog, root)

            self.assertIn("device router references missing layer: configs/missing.config", errors)
            self.assertIn("device router layer escapes repository: ../outside.config", errors)

    def test_resolve_rejects_unsupported_pair(self) -> None:
        with self.catalog_fixture() as root:
            stderr = StringIO()

            with redirect_stderr(stderr):
                exit_code = main(
                    ["--root", str(root), "resolve", "--distribution", "immortalwrt", "--device", "router"]
                )

            self.assertEqual(2, exit_code)
            self.assertIn("unsupported distribution/device pair", stderr.getvalue())

    def test_build_readiness_rejects_unresolved_revision_and_profile(self) -> None:
        with self.catalog_fixture() as root:
            stdout = StringIO()
            stderr = StringIO()

            with redirect_stdout(stdout), redirect_stderr(stderr):
                exit_code = main(
                    [
                        "--root",
                        str(root),
                        "resolve",
                        "--distribution",
                        "openwrt",
                        "--device",
                        "router",
                        "--require-build-ready",
                    ]
                )

            self.assertEqual(3, exit_code)
            self.assertEqual("", stdout.getvalue())
            self.assertIn("source revision is UNRESOLVED", stderr.getvalue())
            self.assertIn("device profile is UNRESOLVED", stderr.getvalue())

    def catalog_fixture(self):
        return CatalogFixture()

    @staticmethod
    def write_json(path: Path, value: object) -> None:
        path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


class CatalogFixture:
    def __enter__(self) -> Path:
        self._temporary_directory = tempfile.TemporaryDirectory()
        root = Path(self._temporary_directory.name)
        (root / "manifests/devices").mkdir(parents=True)
        (root / "configs").mkdir()
        (root / "configs/base.config").write_text("# base\n", encoding="utf-8")
        ManifestTests.write_json(
            root / "manifests/sources.json",
            {
                "schema_version": 1,
                "sources": [
                    {
                        "id": "openwrt",
                        "repository": "https://github.com/openwrt/openwrt.git",
                        "revision": "UNRESOLVED",
                    },
                    {
                        "id": "immortalwrt",
                        "repository": "https://github.com/immortalwrt/immortalwrt.git",
                        "revision": "UNRESOLVED",
                    },
                ],
            },
        )
        ManifestTests.write_json(
            root / "manifests/devices/router.json",
            {
                "schema_version": 1,
                "id": "router",
                "display_name": "Test Router",
                "supported_distributions": ["openwrt"],
                "target": "test-target",
                "subtarget": "test-subtarget",
                "profile": "UNRESOLVED",
                "config_layers": ["configs/base.config"],
                "feed_layers": [],
                "patch_layers": [],
                "overlay_layers": [],
                "artifact_patterns": [],
                "notes": [],
            },
        )
        return root

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self._temporary_directory.cleanup()


if __name__ == "__main__":
    unittest.main()
