"""Tests for the NX30 Pro firmware build entry point.

The build must refuse to start when the source lock is not complete: an
unpinned commit, an unpinned feed, another profile or a partition layout that
does not match the boot loader all stop the build before any source is
fetched. The configuration check runs against the final configuration that
the build produced, not against the fragment that was fed into it.
"""

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BUILD_DIR = ROOT / "devices" / "nx30pro" / "build"
HELPER = BUILD_DIR / "firmware_lock.py"
BUILD_SCRIPT = BUILD_DIR / "build.sh"
CONFIGURE_SCRIPT = BUILD_DIR / "configure.sh"
LOCK = ROOT / "devices" / "nx30pro" / "source-lock.json"


def load_helper():
    spec = importlib.util.spec_from_file_location("nx30pro_firmware_lock", HELPER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_lock(directory, **changes):
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    for path, value in changes.items():
        keys = path.split(".")
        target = lock
        for key in keys[:-1]:
            target = target[key]
        if value is None:
            target.pop(keys[-1], None)
        else:
            target[keys[-1]] = value
    target_path = Path(directory) / "lock.json"
    target_path.write_text(json.dumps(lock, indent=2), encoding="utf-8")
    return target_path


def run_check(lock_path):
    return subprocess.run(
        [sys.executable, str(HELPER), "check", "--lock", str(lock_path)],
        capture_output=True,
        text=True,
    )


class Nx30ProFirmwareLockGateTests(unittest.TestCase):
    def test_locked_source_lock_is_build_ready(self):
        result = run_check(LOCK)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("h3c_nx30pro_112M", result.stdout)
        self.assertIn("78cf22edddf07443d8f0506c9f361d3498475189", result.stdout)

    def test_missing_commit_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock = write_lock(tmp, **{"source.revision": None})
            result = run_check(lock)
        self.assertNotEqual(0, result.returncode)
        self.assertIn("revision", result.stderr)

    def test_branch_instead_of_commit_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock = write_lock(tmp, **{"source.revision": "nx30pro-112m"})
            result = run_check(lock)
        self.assertNotEqual(0, result.returncode)
        self.assertIn("revision", result.stderr)

    def test_unpinned_feed_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock = json.loads(LOCK.read_text(encoding="utf-8"))
            lock["feeds"][0]["revision"] = "openwrt-21.02"
            path = Path(tmp) / "lock.json"
            path.write_text(json.dumps(lock, indent=2), encoding="utf-8")
            result = run_check(path)
        self.assertNotEqual(0, result.returncode)
        self.assertIn("feed", result.stderr)

    def test_wrong_profile_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock = write_lock(tmp, **{"target.profile": "h3c_nx30pro"})
            result = run_check(lock)
        self.assertNotEqual(0, result.returncode)
        self.assertIn("profile", result.stderr)

    def test_layout_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock = write_lock(
                tmp,
                **{
                    "partition_contract.partitions": [
                        {"label": "BL2", "offset": 0, "size": 1048576},
                        {"label": "u-boot-env", "offset": 1048576, "size": 524288},
                        {"label": "Factory", "offset": 1572864, "size": 2097152},
                        {"label": "FIP", "offset": 3670016, "size": 2097152},
                        {"label": "ubi", "offset": 5767168, "size": 67108864},
                    ]
                },
            )
            result = run_check(lock)
        self.assertNotEqual(0, result.returncode)
        self.assertIn("layout", result.stderr.lower())

    def test_build_scripts_refuse_to_flash_anything(self):
        for script in (BUILD_SCRIPT, CONFIGURE_SCRIPT):
            text = script.read_text(encoding="utf-8")
            for forbidden in ("flashwrite", "nandwrite", "mtd write", "dd if=", "/dev/mtd"):
                self.assertNotIn(forbidden, text, script.name)


class Nx30ProFirmwareConfigTests(unittest.TestCase):
    def setUp(self):
        self.helper = load_helper()
        self.lock = json.loads(LOCK.read_text(encoding="utf-8"))

    def good_config(self):
        lines = [
            "CONFIG_TARGET_mediatek=y",
            "CONFIG_TARGET_mediatek_mt7981=y",
            "CONFIG_TARGET_mediatek_mt7981_DEVICE_h3c_nx30pro_112M=y",
        ]
        for entry in self.lock["packages"]:
            if entry["status"] != "available" or not entry.get("symbol"):
                continue
            for symbol in [part.strip() for part in entry["symbol"].split(",")]:
                if symbol:
                    lines.append("%s=y" % symbol.split("=")[0].strip())
        return "\n".join(lines) + "\n"

    def test_configuration_with_the_profile_and_the_packages_is_accepted(self):
        symbols = self.helper.verify_config(self.good_config(), self.lock)
        self.assertEqual(
            "y",
            symbols["CONFIG_TARGET_mediatek_mt7981_DEVICE_h3c_nx30pro_112M"],
        )

    def test_configuration_without_the_profile_is_rejected(self):
        text = self.good_config().replace(
            "CONFIG_TARGET_mediatek_mt7981_DEVICE_h3c_nx30pro_112M=y\n", ""
        )
        with self.assertRaises(Exception):
            self.helper.verify_config(text, self.lock)

    def test_configuration_with_two_profiles_is_rejected(self):
        text = self.good_config() + "CONFIG_TARGET_mediatek_mt7981_DEVICE_other=y\n"
        with self.assertRaises(Exception):
            self.helper.verify_config(text, self.lock)

    def test_configuration_without_a_required_package_is_rejected(self):
        text = self.good_config().replace("CONFIG_PACKAGE_luci-app-passwall=y\n", "")
        with self.assertRaises(Exception):
            self.helper.verify_config(text, self.lock)

    def test_configuration_with_an_excluded_package_is_rejected(self):
        text = self.good_config() + "CONFIG_PACKAGE_luci-app-openclash=y\n"
        with self.assertRaises(Exception):
            self.helper.verify_config(text, self.lock)

    def test_configuration_with_the_excluded_package_switched_off_is_accepted(self):
        text = self.good_config() + "# CONFIG_PACKAGE_luci-app-openclash is not set\n"
        symbols = self.helper.verify_config(text, self.lock)
        self.assertIsNone(symbols.get("CONFIG_PACKAGE_luci-app-openclash"))


if __name__ == "__main__":
    unittest.main()
