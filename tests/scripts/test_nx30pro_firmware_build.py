"""Tests for the NX30 Pro firmware lock gate and final configuration check.

The gate must refuse to let a build start while the source lock is a
candidate: an unpinned commit, an unpinned feed, the rejected Galaxian base,
another profile, a partition layout that does not match the boot loader, a
hard gate without a proven defconfig, or a package whose dependency no locked
feed provides all stop the build before any source is fetched. The status code
is the repository wide build-not-ready code, the same one `uboot_lock.py` and
`tools/manifest.py` use.

The configuration check runs against the final configuration that the build
produced, never against the fragment that was fed into it.
"""

import copy
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

SOURCE_REPOSITORY = "https://github.com/hanwckf/immortalwrt-mt798x"
REJECTED_REPOSITORY = "https://github.com/jerryhan77/immortalwrt-mt798x.git"
REJECTED_REVISION = "78cf22edddf07443d8f0506c9f361d3498475189"
BUILD_NOT_READY = 3


def load_helper():
    spec = importlib.util.spec_from_file_location("nx30pro_firmware_lock", HELPER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def real_lock():
    return json.loads(LOCK.read_text(encoding="utf-8"))


def proven_lock(lock=None):
    """The same lock after an authorized defconfig probe proved every gate."""
    lock = copy.deepcopy(lock if lock is not None else real_lock())
    for entry in lock["packages"]:
        if entry.get("gate") == "hard" and entry["status"] == "candidate":
            entry["status"] = "available"
            entry["defconfig_evidence"] = "final .config of the authorized probe run"
    lock["build_readiness"]["ready"] = True
    lock["build_readiness"]["blocking"] = []
    return lock


def write_lock(directory, lock):
    path = Path(directory) / "lock.json"
    path.write_text(json.dumps(lock, indent=2), encoding="utf-8")
    return path


def run_check(lock_path):
    return subprocess.run(
        [sys.executable, str(HELPER), "check", "--lock", str(lock_path)],
        capture_output=True,
        text=True,
    )


def check_lock(lock):
    with tempfile.TemporaryDirectory() as tmp:
        return run_check(write_lock(tmp, lock))


def hard_gate_entry(lock, package):
    for entry in lock["packages"]:
        if entry["package"] == package:
            return entry
    raise AssertionError("no package entry for %s" % package)


class Nx30ProFirmwareLockGateTests(unittest.TestCase):
    def test_candidate_lock_is_build_blocked_with_the_repository_status(self):
        result = run_check(LOCK)
        self.assertEqual(BUILD_NOT_READY, result.returncode, result.stdout)
        self.assertIn("defconfig", result.stderr)
        self.assertIn("hard gate", result.stderr.lower())
        self.assertNotIn("build ready", result.stdout)

    def test_candidate_lock_never_renders_a_build_plan(self):
        result = run_check(LOCK)
        self.assertEqual("", result.stdout.strip())

    def test_proven_lock_is_accepted(self):
        result = check_lock(proven_lock())
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("h3c_nx30pro_112M", result.stdout)
        self.assertIn(SOURCE_REPOSITORY, result.stdout)

    def test_missing_commit_is_rejected(self):
        lock = proven_lock()
        del lock["source"]["revision"]
        result = check_lock(lock)
        self.assertEqual(BUILD_NOT_READY, result.returncode)
        self.assertIn("revision", result.stderr)

    def test_branch_instead_of_commit_is_rejected(self):
        lock = proven_lock()
        lock["source"]["revision"] = "openwrt-21.02"
        result = check_lock(lock)
        self.assertEqual(BUILD_NOT_READY, result.returncode)
        self.assertIn("revision", result.stderr)

    def test_the_rejected_galaxian_source_is_refused(self):
        lock = proven_lock()
        lock["source"]["repository"] = REJECTED_REPOSITORY
        lock["source"]["revision"] = REJECTED_REVISION
        result = check_lock(lock)
        self.assertEqual(BUILD_NOT_READY, result.returncode)
        self.assertIn("rejected", result.stderr.lower())

    def test_another_source_repository_is_refused(self):
        lock = proven_lock()
        lock["source"]["repository"] = "https://github.com/immortalwrt/immortalwrt"
        result = check_lock(lock)
        self.assertEqual(BUILD_NOT_READY, result.returncode)
        self.assertIn("repository", result.stderr.lower())

    def test_unpinned_feed_is_rejected(self):
        lock = proven_lock()
        lock["feeds"][0]["revision"] = "openwrt-21.02"
        result = check_lock(lock)
        self.assertEqual(BUILD_NOT_READY, result.returncode)
        self.assertIn("feed", result.stderr.lower())

    def test_a_missing_feed_is_rejected(self):
        lock = proven_lock()
        lock["feeds"] = [feed for feed in lock["feeds"] if feed["id"] != "telephony"]
        result = check_lock(lock)
        self.assertEqual(BUILD_NOT_READY, result.returncode)
        self.assertIn("telephony", result.stderr)

    def test_wrong_profile_is_rejected(self):
        lock = proven_lock()
        lock["target"]["profile"] = "h3c_nx30pro"
        result = check_lock(lock)
        self.assertEqual(BUILD_NOT_READY, result.returncode)
        self.assertIn("profile", result.stderr.lower())

    def test_layout_mismatch_is_rejected(self):
        lock = proven_lock()
        # The stock 64 MiB UBI table of the boot loader `default` layout.
        lock["partition_contract"]["partitions"][4]["size"] = 67108864
        result = check_lock(lock)
        self.assertEqual(BUILD_NOT_READY, result.returncode)
        self.assertIn("layout", result.stderr.lower())

    def test_a_hard_gate_without_a_feed_commit_is_rejected(self):
        lock = proven_lock()
        hard_gate_entry(lock, "xray-core")["feed_revision"] = None
        result = check_lock(lock)
        self.assertEqual(BUILD_NOT_READY, result.returncode)
        self.assertIn("xray-core", result.stderr)

    def test_a_hard_gate_whose_feed_commit_is_not_the_locked_one_is_rejected(self):
        lock = proven_lock()
        hard_gate_entry(lock, "xray-core")["feed_revision"] = "0" * 40
        result = check_lock(lock)
        self.assertEqual(BUILD_NOT_READY, result.returncode)
        self.assertIn("xray-core", result.stderr)

    def test_a_hard_gate_without_symbols_is_rejected(self):
        lock = proven_lock()
        hard_gate_entry(lock, "cloudflared")["symbols"] = []
        result = check_lock(lock)
        self.assertEqual(BUILD_NOT_READY, result.returncode)
        self.assertIn("cloudflared", result.stderr)

    def test_a_package_whose_dependency_no_feed_provides_is_rejected(self):
        """The old Action failure: a feed indexes a package but not its deps."""
        lock = proven_lock()
        entry = hard_gate_entry(lock, "luci-app-passwall")
        entry["dependencies"] = list(entry["dependencies"]) + ["chinadns-ng-missing"]
        result = check_lock(lock)
        self.assertEqual(BUILD_NOT_READY, result.returncode)
        self.assertIn("chinadns-ng-missing", result.stderr)

    def test_a_dependency_index_entry_off_a_locked_commit_is_rejected(self):
        lock = proven_lock()
        lock["dependency_index"]["curl"]["revision"] = "0" * 40
        result = check_lock(lock)
        self.assertEqual(BUILD_NOT_READY, result.returncode)
        self.assertIn("curl", result.stderr)

    def test_available_without_defconfig_evidence_is_rejected(self):
        lock = proven_lock()
        entry = hard_gate_entry(lock, "tailscale")
        entry["defconfig_evidence"] = ""
        result = check_lock(lock)
        self.assertEqual(BUILD_NOT_READY, result.returncode)
        self.assertIn("tailscale", result.stderr)
        self.assertIn("defconfig", result.stderr.lower())

    def test_an_unproven_hard_gate_blocks_even_when_readiness_is_claimed(self):
        lock = proven_lock()
        hard_gate_entry(lock, "dockerd")["status"] = "candidate"
        result = check_lock(lock)
        self.assertEqual(BUILD_NOT_READY, result.returncode)
        self.assertIn("dockerd", result.stderr)

    def test_a_hand_edited_readiness_flag_is_rejected(self):
        lock = real_lock()
        lock["build_readiness"]["ready"] = True
        lock["build_readiness"]["blocking"] = []
        result = check_lock(lock)
        self.assertEqual(BUILD_NOT_READY, result.returncode)
        self.assertIn("build_readiness", result.stderr)

    def test_an_unknown_package_status_is_rejected(self):
        lock = proven_lock()
        hard_gate_entry(lock, "mtr" if any(
            entry["package"] == "mtr" for entry in lock["packages"]
        ) else "iperf3")["status"] = "probably-fine"
        result = check_lock(lock)
        self.assertEqual(BUILD_NOT_READY, result.returncode)
        self.assertIn("status", result.stderr.lower())

    def test_a_pinned_version_without_evidence_is_rejected(self):
        lock = proven_lock()
        entry = hard_gate_entry(lock, "luci-app-passwall")
        entry["version_evidence"] = ""
        result = check_lock(lock)
        self.assertEqual(BUILD_NOT_READY, result.returncode)
        self.assertIn("luci-app-passwall", result.stderr)

    def test_build_scripts_refuse_to_flash_anything(self):
        for script in (BUILD_SCRIPT, CONFIGURE_SCRIPT):
            text = script.read_text(encoding="utf-8")
            for forbidden in (
                "flashwrite",
                "nandwrite",
                "mtd write",
                "dd if=",
                "/dev/mtd",
            ):
                self.assertNotIn(forbidden, text, script.name)

    def test_build_script_stops_on_the_lock_gate_before_it_downloads(self):
        text = BUILD_SCRIPT.read_text(encoding="utf-8")
        gate = text.index('check --lock')
        self.assertLess(gate, text.index("git clone"), "the gate must come first")
        self.assertLess(gate, text.index("make download"), "the gate must come first")


class Nx30ProFirmwareConfigTests(unittest.TestCase):
    def setUp(self):
        self.helper = load_helper()
        self.lock = proven_lock()

    def good_config(self):
        lines = [
            "CONFIG_TARGET_mediatek=y",
            "CONFIG_TARGET_mediatek_mt7981=y",
            "CONFIG_TARGET_mediatek_mt7981_DEVICE_h3c_nx30pro_112M=y",
        ]
        for entry in self.lock["packages"]:
            if entry["status"] != "available":
                continue
            for symbol in entry.get("symbols") or []:
                lines.append("%s=y" % symbol)
        return "\n".join(lines) + "\n"

    def test_configuration_with_the_profile_and_the_packages_is_accepted(self):
        symbols = self.helper.verify_config(self.good_config(), self.lock)
        self.assertEqual(
            "y",
            symbols["CONFIG_TARGET_mediatek_mt7981_DEVICE_h3c_nx30pro_112M"],
        )
        self.assertEqual("y", symbols["CONFIG_PACKAGE_luci-app-passwall"])

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

    def test_hyphenated_package_symbols_survive_the_configuration_parse(self):
        text = self.good_config() + "CONFIG_PACKAGE_dnsmasq-full=y\n"
        symbols = self.helper.verify_config(text, self.lock)
        self.assertEqual("y", symbols["CONFIG_PACKAGE_dnsmasq-full"])

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
