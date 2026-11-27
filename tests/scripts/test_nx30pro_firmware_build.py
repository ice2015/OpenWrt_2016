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
import re
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


PATCHES = ROOT / "devices" / "nx30pro" / "patches"
PROFILE_PATCH = PATCHES / "0001-mediatek-add-nx30pro-112m-profile.patch"
DEVICE_TREE_FILE = (
    "target/linux/mediatek/files-5.4/arch/arm64/boot/dts/mediatek/"
    "mt7981-h3c-nx30pro-112M.dts"
)
IMAGE_RULES_FILE = "target/linux/mediatek/image/mt7981.mk"

# The stock 64M table of the pinned source: the same first four partitions, a
# 64 MiB UBI area and the two pdt_data partitions the 112M layout absorbed.
STOCK_DEVICE_TREE = """/dts-v1/;
#include "mt7981.dtsi"

/ {
    nmbm_spim_nand {
        compatible = "generic,nmbm";
        lower-mtd-device = <&spi_nand>;
        forced-create;

        partitions {
            compatible = "fixed-partitions";
            #address-cells = <1>;
            #size-cells = <1>;

            partition@0 {
                label = "BL2";
                reg = <0x00 0x100000>;
            };

            partition@100000 {
                label = "u-boot-env";
                reg = <0x100000 0x80000>;
            };

            partition@180000 {
                label = "Factory";
                reg = <0x180000 0x200000>;
            };

            partition@380000 {
                label = "FIP";
                reg = <0x380000 0x200000>;
            };

            partition@580000 {
                label = "ubi";
                reg = <0x580000 0x4000000>;
            };

            partition@4580000 {
                label = "pdt_data";
                reg = <0x4580000 0x0600000>;
            };

            partition@4b80000 {
                label = "pdt_data_1";
                reg = <0x4b80000 0x0600000>;
            };
        };
    };
};
"""

# The profile of another board of the same subtarget. It is a valid mt7981
# profile, so a verifier that only looks for "a" profile would accept it.
ANOTHER_PROFILE_RULES = """define Device/cmcc_rax3000m
  DEVICE_VENDOR := CMCC
  DEVICE_MODEL := RAX3000M
  DEVICE_DTS := mt7981-cmcc-rax3000m
  DEVICE_DTS_DIR := $(DTS_DIR)/mediatek
  SUPPORTED_DEVICES := cmcc,rax3000m
  UBINIZE_OPTS := -E 5
  BLOCKSIZE := 128k
  PAGESIZE := 2048
  IMAGE_SIZE := 116736k
  KERNEL_IN_UBI := 1
  IMAGES += factory.bin
  IMAGE/factory.bin := append-ubi | check-size $$$$(IMAGE_SIZE)
  IMAGE/sysupgrade.bin := sysupgrade-tar | append-metadata
endef
TARGET_DEVICES += cmcc_rax3000m
"""


def patched_source(patch_text, source_path):
    """Reconstruct one patched source file out of the port patch.

    The ported device tree is a new file, so its added lines are its whole
    content. The image rules are the profile block the patch adds, which is
    what the verifier has to select out of a file full of other profiles.
    """
    chunks = re.split(r"^diff --git ", patch_text, flags=re.M)[1:]
    for chunk in chunks:
        if not chunk.splitlines()[0].endswith(" b/%s" % source_path):
            continue
        return "\n".join(
            line[1:]
            for line in chunk.splitlines()
            if line.startswith("+") and not line.startswith("+++")
        )
    raise AssertionError("the port patch does not touch %s" % source_path)


def run_verifier(command, *args):
    return subprocess.run(
        [sys.executable, str(HELPER), command, *args],
        capture_output=True,
        text=True,
    )


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
    """verify-config audits the FINAL .config, never the seed fragment.

    A hard gate that the real `make defconfig` dropped has to fail here,
    before anything is compiled, and the failure has to name the requirement
    it breaks. The gate reads the package table of the lock, so it applies
    while the lock is still an unproven candidate as well: `check` decides
    whether a build may start, `verify-config` decides whether the
    configuration a build produced is the contracted one.
    """

    def setUp(self):
        self.helper = load_helper()
        self.lock = proven_lock()

    def good_config(self, lock=None):
        """A final configuration that carries the whole contract.

        Hard gates are selected with the dependencies the lock enumerates for
        them, optional tools are selected unless the lock records them as
        unproven, and the excluded packages are switched off explicitly.
        """
        lock = self.lock if lock is None else lock
        lines = [
            "CONFIG_TARGET_mediatek=y",
            "CONFIG_TARGET_mediatek_mt7981=y",
            "CONFIG_TARGET_mediatek_mt7981_DEVICE_h3c_nx30pro_112M=y",
            "CONFIG_LUCI_LANG_zh_Hans=y",
        ]
        for entry in lock["packages"]:
            if entry["status"] in ("unavailable", "UNRESOLVED"):
                lines.extend(
                    "# %s is not set" % symbol
                    for symbol in entry.get("symbols") or []
                )
                continue
            if entry["gate"] != "hard" and entry["gate"] != "optional":
                continue
            for symbol in entry.get("symbols") or []:
                lines.append("%s=y" % symbol)
            for dependency in entry.get("dependencies") or []:
                lines.append("CONFIG_PACKAGE_%s=y" % dependency)
        for entry in lock["excluded_packages"]:
            lines.append("# CONFIG_PACKAGE_%s is not set" % entry["package"])
        return "\n".join(lines) + "\n"

    def without(self, text, *lines):
        for line in lines:
            self.assertIn(line + "\n", text, line)
            text = text.replace(line + "\n", "")
        return text

    def test_configuration_with_the_profile_and_the_packages_is_accepted(self):
        report = self.helper.verify_config(self.good_config(), self.lock)
        self.assertEqual(
            "y",
            report["symbols"]["CONFIG_TARGET_mediatek_mt7981_DEVICE_h3c_nx30pro_112M"],
        )
        self.assertEqual("y", report["symbols"]["CONFIG_PACKAGE_luci-app-passwall"])

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
        with self.assertRaises(Exception) as caught:
            self.helper.verify_config(text, self.lock)
        self.assertIn("CONFIG_PACKAGE_luci-app-passwall", str(caught.exception))
        self.assertIn(
            hard_gate_entry(self.lock, "luci-app-passwall")["requirement"],
            str(caught.exception),
        )

    def test_every_missing_hard_gate_symbol_is_reported_with_its_requirement(self):
        """Each hard gate symbol is tested on its own.

        The old Action lost whole groups of packages, so a gate that only
        reports the first miss would hide the rest. Every symbol is removed
        independently and the failure has to name the requirement behind it.
        """
        base = self.good_config()
        for entry in self.lock["packages"]:
            if entry["gate"] != "hard":
                continue
            for symbol in entry["symbols"]:
                with self.subTest(package=entry["package"], symbol=symbol):
                    text = self.without(base, "%s=y" % symbol)
                    with self.assertRaises(Exception) as caught:
                        self.helper.verify_config(text, self.lock)
                    message = str(caught.exception)
                    self.assertIn(symbol, message)
                    self.assertIn(entry["requirement"], message)

    def test_hard_gates_are_gated_while_the_lock_is_still_a_candidate(self):
        """The real lock has no defconfig evidence yet and must still gate.

        `verify-config` is the gate that runs after an authorized probe; if it
        only checked packages already marked `available` it would audit nothing
        at all before the very run that is supposed to produce the evidence.
        """
        candidate = real_lock()
        for entry in candidate["packages"]:
            self.assertNotEqual("available", entry["status"], entry["package"])
        self.helper.verify_config(self.good_config(candidate), candidate)
        text = self.without(
            self.good_config(candidate), "CONFIG_PACKAGE_cloudflared=y"
        )
        with self.assertRaises(Exception) as caught:
            self.helper.verify_config(text, candidate)
        self.assertIn("cloudflared", str(caught.exception).lower())

    def test_the_old_failure_mode_names_every_dropped_requirement(self):
        """PassWall, DDNS, ZeroTier, Docker and Argon disappeared together.

        That is the failure the incompatible feeds produced: the packages were
        indexed but dropped by `defconfig`. One report has to name all of them,
        otherwise the operator only sees the first and reruns into the rest.
        """
        dropped = (
            "CONFIG_PACKAGE_luci-app-passwall",
            "CONFIG_PACKAGE_ddns-scripts",
            "CONFIG_PACKAGE_zerotier",
            "CONFIG_PACKAGE_dockerd",
            "CONFIG_PACKAGE_luci-theme-argon",
        )
        text = self.without(self.good_config(), *("%s=y" % item for item in dropped))
        with self.assertRaises(Exception) as caught:
            self.helper.verify_config(text, self.lock)
        message = str(caught.exception)
        for symbol in dropped:
            self.assertIn(symbol, message)
        for requirement in (
            hard_gate_entry(self.lock, "luci-app-passwall")["requirement"],
            hard_gate_entry(self.lock, "ddns-scripts")["requirement"],
            hard_gate_entry(self.lock, "zerotier")["requirement"],
            hard_gate_entry(self.lock, "dockerd")["requirement"],
            hard_gate_entry(self.lock, "luci-theme-argon")["requirement"],
        ):
            self.assertIn(requirement, message)

    def test_an_explicit_is_not_set_override_of_a_hard_gate_is_rejected(self):
        """`# CONFIG_... is not set` is a decision, not a missing line.

        defconfig writes the override itself when a dependency cannot be met,
        so it has to be refused exactly like an absent symbol.
        """
        text = self.good_config().replace(
            "CONFIG_PACKAGE_luci-theme-argon=y\n",
            "# CONFIG_PACKAGE_luci-theme-argon is not set\n",
        )
        with self.assertRaises(Exception) as caught:
            self.helper.verify_config(text, self.lock)
        self.assertIn("CONFIG_PACKAGE_luci-theme-argon", str(caught.exception))

    def test_a_hard_gate_whose_dependency_is_missing_is_rejected(self):
        """A feed that indexes a package but not its dependencies is rejected.

        The dependency closure of luci-app-passwall, dockerd and
        luci-ssl-openssl is enumerated in the lock, so the final config has to
        carry it. The failure names both the dependency and the gate it broke.
        """
        text = self.without(self.good_config(), "CONFIG_PACKAGE_chinadns-ng=y")
        with self.assertRaises(Exception) as caught:
            self.helper.verify_config(text, self.lock)
        message = str(caught.exception)
        self.assertIn("chinadns-ng", message)
        self.assertIn("luci-app-passwall", message)

    def test_a_dependency_switched_off_is_rejected_but_a_module_is_accepted(self):
        text = self.good_config().replace(
            "CONFIG_PACKAGE_chinadns-ng=y\n",
            "# CONFIG_PACKAGE_chinadns-ng is not set\n",
        )
        with self.assertRaises(Exception):
            self.helper.verify_config(text, self.lock)
        module = self.good_config().replace(
            "CONFIG_PACKAGE_chinadns-ng=y\n", "CONFIG_PACKAGE_chinadns-ng=m\n"
        )
        self.helper.verify_config(module, self.lock)

    def test_hyphenated_package_symbols_survive_the_configuration_parse(self):
        text = self.good_config()
        self.assertIn("CONFIG_PACKAGE_dnsmasq-full=y", text)
        report = self.helper.verify_config(text, self.lock)
        self.assertEqual("y", report["symbols"]["CONFIG_PACKAGE_dnsmasq-full"])
        self.assertEqual(
            "y", report["symbols"]["CONFIG_PACKAGE_luci-i18n-base-zh-cn"]
        )

    def test_configuration_with_an_excluded_package_is_rejected(self):
        text = self.good_config() + "CONFIG_PACKAGE_luci-app-openclash=y\n"
        with self.assertRaises(Exception):
            self.helper.verify_config(text, self.lock)

    def test_configuration_with_the_excluded_package_switched_off_is_accepted(self):
        report = self.helper.verify_config(self.good_config(), self.lock)
        self.assertIsNone(
            report["symbols"].get("CONFIG_PACKAGE_luci-app-openclash")
        )

    def test_an_unproven_package_may_not_be_enabled(self):
        """UNRESOLVED and unavailable are not permissions.

        WireGuard stays UNRESOLVED on Linux 5.4 and sing-box is absent from
        the pinned packages feed. If either one shows up enabled anyway, the
        lock and the image disagree and the candidate is refused.
        """
        for symbol in hard_gate_entry(self.lock, "wireguard")["symbols"]:
            with self.subTest(symbol=symbol):
                text = self.good_config().replace(
                    "# %s is not set\n" % symbol, "%s=y\n" % symbol
                )
                with self.assertRaises(Exception) as caught:
                    self.helper.verify_config(text, self.lock)
                self.assertIn(symbol, str(caught.exception))
                self.assertIn("UNRESOLVED", str(caught.exception))

    def test_an_optional_package_recorded_available_must_be_enabled(self):
        lock = proven_lock()
        entry = hard_gate_entry(lock, "mtr")
        entry["status"] = "available"
        entry["defconfig_evidence"] = "final .config of the authorized probe run"
        text = self.without(self.good_config(lock), "CONFIG_PACKAGE_mtr=y")
        with self.assertRaises(Exception) as caught:
            self.helper.verify_config(text, lock)
        self.assertIn("mtr", str(caught.exception))
        self.assertIn("available", str(caught.exception))

    def test_a_clash_pair_without_either_variant_is_rejected(self):
        """The documented rootfs clash may not be resolved by losing both.

        tcpdump-mini replaces tcpdump and dnsmasq-full replaces dnsmasq. If
        defconfig drops the replacement while the baseline variant stays
        excluded, the image would silently lose the tool, so that fails.
        """
        for provider, replacement in (
            ("tcpdump", "tcpdump-mini"),
            ("dnsmasq", "dnsmasq-full"),
        ):
            with self.subTest(provider=provider):
                text = self.without(
                    self.good_config(), "CONFIG_PACKAGE_%s=y" % replacement
                )
                with self.assertRaises(Exception) as caught:
                    self.helper.verify_config(text, self.lock)
                message = str(caught.exception)
                self.assertIn(provider, message)
                self.assertIn(replacement, message)

    def test_the_tcpdump_clash_itself_is_rejected(self):
        text = self.good_config().replace(
            "# CONFIG_PACKAGE_tcpdump is not set\n", "CONFIG_PACKAGE_tcpdump=y\n"
        )
        with self.assertRaises(Exception) as caught:
            self.helper.verify_config(text, self.lock)
        self.assertIn("tcpdump", str(caught.exception))

    def test_the_report_separates_hard_gates_optional_status_and_exclusions(self):
        report = self.helper.verify_config(self.good_config(), self.lock)
        self.assertEqual(
            sorted(entry["package"] for entry in report["hard_gates"]),
            sorted(
                entry["package"]
                for entry in self.lock["packages"]
                if entry["gate"] == "hard"
            ),
        )
        for entry in report["hard_gates"]:
            self.assertEqual("enabled", entry["state"], entry["package"])
            self.assertEqual(sorted(entry["symbols"]), entry["enabled_symbols"])
            self.assertEqual([], entry["missing_symbols"])
            self.assertIn("requirement", entry)
        optional = {entry["package"]: entry for entry in report["optional"]}
        self.assertEqual("candidate", optional["mtr"]["status"])
        self.assertEqual("enabled", optional["mtr"]["state"])
        self.assertEqual("UNRESOLVED", optional["wireguard"]["status"])
        self.assertEqual("disabled", optional["wireguard"]["state"])
        excluded = {entry["package"]: entry for entry in report["excluded"]}
        self.assertEqual("disabled", excluded["luci-app-openclash"]["state"])
        self.assertIn("reason", excluded["luci-app-openclash"])

    def test_the_command_line_refuses_a_configuration_that_lost_a_hard_gate(self):
        text = self.without(self.good_config(), "CONFIG_PACKAGE_tailscale=y")
        with tempfile.TemporaryDirectory() as tmp:
            lock_path = write_lock(tmp, self.lock)
            config_path = Path(tmp) / ".config"
            config_path.write_text(text, encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(HELPER),
                    "verify-config",
                    "--lock",
                    str(lock_path),
                    "--config",
                    str(config_path),
                ],
                capture_output=True,
                text=True,
            )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("CONFIG_PACKAGE_tailscale", result.stderr)
        self.assertIn(hard_gate_entry(self.lock, "tailscale")["requirement"], result.stderr)

    def test_the_command_line_reports_the_final_config_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock_path = write_lock(tmp, self.lock)
            config_path = Path(tmp) / ".config"
            config_path.write_text(self.good_config(), encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(HELPER),
                    "verify-config",
                    "--lock",
                    str(lock_path),
                    "--config",
                    str(config_path),
                ],
                capture_output=True,
                text=True,
            )
        self.assertEqual(0, result.returncode, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(
            ("excluded", "hard_gates", "optional", "profile", "symbols"),
            tuple(sorted(report)),
        )
        self.assertEqual(18, len(report["hard_gates"]))


class Nx30ProConfigMergeTests(unittest.TestCase):
    """The layer merge is where hyphenated symbols used to be dropped.

    The repository documents a merge regex that accepted letters, digits and
    underscores only, so `CONFIG_PACKAGE_luci-i18n-base-zh-cn` and
    `CONFIG_PACKAGE_luci-app-openclash` never got overridden by the device
    layer. The merge is a helper function now, so it is testable without a
    source tree, and precedence stays common -> distribution -> device.
    """

    def setUp(self):
        self.helper = load_helper()

    def merge(self, *layers):
        return self.helper.merge_config_layers(list(layers))

    def test_the_device_layer_wins_over_common_and_distribution(self):
        text = self.merge(
            "# common\nCONFIG_PACKAGE_luci=m\n",
            "# distribution\nCONFIG_PACKAGE_luci=y\nCONFIG_PACKAGE_curl=m\n",
            "# device\nCONFIG_PACKAGE_luci=y\nCONFIG_PACKAGE_cloudflared=y\n",
        )
        symbols = self.helper.config_symbols(text)
        self.assertEqual("y", symbols["CONFIG_PACKAGE_luci"])
        self.assertEqual("m", symbols["CONFIG_PACKAGE_curl"])
        self.assertEqual("y", symbols["CONFIG_PACKAGE_cloudflared"])
        self.assertEqual(1, text.count("CONFIG_PACKAGE_luci="))

    def test_hyphenated_symbols_are_overridden_by_the_device_layer(self):
        text = self.merge(
            "CONFIG_PACKAGE_luci-i18n-base-zh-cn=m\n"
            "CONFIG_PACKAGE_tcpdump=y\n"
            "CONFIG_PACKAGE_luci-app-openclash=y\n",
            "CONFIG_PACKAGE_luci-i18n-base-zh-cn=y\n"
            "# CONFIG_PACKAGE_tcpdump is not set\n"
            "# CONFIG_PACKAGE_luci-app-openclash is not set\n",
        )
        symbols = self.helper.config_symbols(text)
        self.assertEqual("y", symbols["CONFIG_PACKAGE_luci-i18n-base-zh-cn"])
        self.assertIsNone(symbols["CONFIG_PACKAGE_tcpdump"])
        self.assertIsNone(symbols["CONFIG_PACKAGE_luci-app-openclash"])
        self.assertNotIn("CONFIG_PACKAGE_tcpdump=y", text)
        self.assertNotIn("CONFIG_PACKAGE_luci-app-openclash=y", text)

    def test_an_earlier_layer_cannot_re_enable_a_device_override(self):
        text = self.merge(
            "# CONFIG_PACKAGE_dnsmasq is not set\n",
            "CONFIG_PACKAGE_dnsmasq=y\n# CONFIG_PACKAGE_dnsmasq is not set\n",
        )
        self.assertIsNone(self.helper.config_symbols(text)["CONFIG_PACKAGE_dnsmasq"])

    def test_symbols_only_an_earlier_layer_names_survive(self):
        text = self.merge(
            "CONFIG_TARGET_mediatek=y\nCONFIG_BUSYBOX_CUSTOM=y\n",
            "CONFIG_PACKAGE_luci=y\n",
        )
        symbols = self.helper.config_symbols(text)
        self.assertEqual("y", symbols["CONFIG_TARGET_mediatek"])
        self.assertEqual("y", symbols["CONFIG_BUSYBOX_CUSTOM"])
        self.assertEqual("y", symbols["CONFIG_PACKAGE_luci"])

    def test_the_merge_command_writes_the_seed_in_layer_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            common = Path(tmp) / "common.config"
            common.write_text("CONFIG_PACKAGE_tcpdump=y\n", encoding="utf-8")
            device = Path(tmp) / "device.config"
            device.write_text(
                "# CONFIG_PACKAGE_tcpdump is not set\n",
                encoding="utf-8",
            )
            out = Path(tmp) / "seed.config"
            result = subprocess.run(
                [
                    sys.executable,
                    str(HELPER),
                    "merge-config",
                    "--out",
                    str(out),
                    str(common),
                    str(device),
                ],
                capture_output=True,
                text=True,
            )
            merged = out.read_text(encoding="utf-8")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIsNone(self.helper.config_symbols(merged)["CONFIG_PACKAGE_tcpdump"])


class Nx30ProConfigureScriptTests(unittest.TestCase):
    """configure.sh owns the layer merge, the patches and the config gate.

    It must merge the repository layers in order, apply the device patches
    before it verifies the source files they create, and audit the final
    `.config` after the real `make defconfig`. It never compiles.
    """

    def setUp(self):
        self.text = CONFIGURE_SCRIPT.read_text(encoding="utf-8")
        # The header comment names the stages too, so the assertions anchor on
        # the indented command lines and not on the first mention of a stage.
        self.defconfig = self.text.index("\tmake defconfig")

    def test_it_merges_the_layers_the_manifest_names_in_order(self):
        self.assertIn("tools/manifest.py", self.text)
        self.assertIn("config_layers", self.text)
        self.assertIn("merge-config", self.text)
        self.assertLess(self.text.index("merge-config --out"), self.defconfig)
        self.assertLess(
            self.text.index("common -> distribution -> device"), self.defconfig
        )

    def test_it_verifies_the_device_tree_after_the_patches_are_applied(self):
        self.assertLess(
            self.text.index('apply "$patch"'),
            self.text.index("verify-device-tree"),
            "the ported device tree only exists after the patch loop",
        )
        self.assertLess(
            self.text.index('apply "$patch"'),
            self.text.index("verify-image-rules"),
        )

    def test_it_audits_the_final_config_and_never_the_seed(self):
        verify = self.text.index("verify-config --lock")
        self.assertLess(self.defconfig, verify)
        self.assertIn('verify-config --lock "$LOCK" --config "$SOURCE_DIR/.config"', self.text)
        self.assertNotIn('verify-config --lock "$LOCK" --config "$DEVICE_CONFIG"', self.text)

    def test_it_compiles_nothing(self):
        for forbidden in ("make -j", "make target", "make package/", "make download"):
            self.assertNotIn(forbidden, self.text)

    def test_it_stops_on_the_lock_gate_first(self):
        self.assertLess(self.text.index("check --lock"), self.defconfig)


class Nx30ProFirmwareDevicePortVerifierTests(unittest.TestCase):
    """verify-device-tree and verify-image-rules read the patched source.

    Both compare the patched source tree with the lock. Neither may accept the
    profile of another device, the stock 64M table, or an approximate
    partition size or image limit.
    """

    def setUp(self):
        self.helper = load_helper()
        self.lock = real_lock()
        patch_text = PROFILE_PATCH.read_text(encoding="utf-8")
        self.device_tree = patched_source(patch_text, DEVICE_TREE_FILE)
        self.profile_rules = patched_source(patch_text, IMAGE_RULES_FILE)
        self.image_rules = ANOTHER_PROFILE_RULES + "\n" + self.profile_rules

    def test_verify_device_tree_accepts_the_ported_device_tree(self):
        found = self.helper.verify_device_tree(self.device_tree, self.lock)
        self.assertEqual(
            [
                (entry["label"], entry["offset"], entry["size"])
                for entry in self.lock["partition_contract"]["partitions"]
            ],
            found,
        )

    def test_verify_device_tree_rejects_the_stock_64m_table(self):
        with self.assertRaises(Exception) as caught:
            self.helper.verify_device_tree(STOCK_DEVICE_TREE, self.lock)
        self.assertIn("partition", str(caught.exception).lower())

    def test_verify_device_tree_rejects_an_approximate_partition_size(self):
        for size in ("0x6FFFFFF", "0x7000001", "0x6FFF000"):
            text = self.device_tree.replace(
                "reg = <0x580000 0x7000000>;", "reg = <0x580000 %s>;" % size
            )
            self.assertNotEqual(self.device_tree, text, size)
            with self.assertRaises(Exception, msg=size):
                self.helper.verify_device_tree(text, self.lock)

    def test_verify_device_tree_rejects_a_moved_partition(self):
        text = self.device_tree.replace(
            "partition@380000 {", "partition@3c0000 {"
        ).replace("reg = <0x380000 0x200000>;", "reg = <0x3c0000 0x200000>;")
        self.assertNotEqual(self.device_tree, text)
        with self.assertRaises(Exception):
            self.helper.verify_device_tree(text, self.lock)

    def test_verify_device_tree_rejects_a_missing_partition(self):
        start = self.device_tree.index("partition@380000 {")
        end = self.device_tree.index("};", self.device_tree.index("0x380000", start))
        missing = self.device_tree[:start] + self.device_tree[end + 3 :]
        self.assertNotEqual(self.device_tree, missing)
        self.assertNotIn("FIP", missing)
        with self.assertRaises(Exception):
            self.helper.verify_device_tree(missing, self.lock)

    def test_verify_device_tree_rejects_an_extra_partition(self):
        extra = re.sub(
            r'(label = "ubi";\s*reg = <0x580000 0x7000000>;\s*\};)',
            r'\1\n\n            partition@7580000 {\n'
            r'                label = "pdt_data_1";\n'
            r"                reg = <0x7580000 0x600000>;\n"
            r"            };",
            self.device_tree,
            count=1,
        )
        self.assertNotEqual(self.device_tree, extra)
        self.assertIn("pdt_data_1", extra)
        with self.assertRaises(Exception):
            self.helper.verify_device_tree(extra, self.lock)

    def test_verify_device_tree_rejects_a_renamed_partition(self):
        text = self.device_tree.replace('label = "FIP";', 'label = "fip";')
        with self.assertRaises(Exception):
            self.helper.verify_device_tree(text, self.lock)

    def test_verify_device_tree_rejects_a_table_that_is_not_bound_to_nmbm(self):
        for token in (
            'compatible = "generic,nmbm";',
            "forced-create;",
            "lower-mtd-device = <&spi_nand>;",
        ):
            text = self.device_tree.replace(token, "")
            self.assertNotEqual(self.device_tree, text, token)
            with self.assertRaises(Exception, msg=token) as caught:
                self.helper.verify_device_tree(text, self.lock)
            self.assertIn("nmbm", str(caught.exception).lower())

    def test_verify_device_tree_rejects_a_unit_address_that_disagrees(self):
        text = self.device_tree.replace("partition@580000 {", "partition@5c0000 {")
        with self.assertRaises(Exception):
            self.helper.verify_device_tree(text, self.lock)

    def test_verify_image_rules_accepts_the_ported_profile(self):
        found = self.helper.verify_image_rules(self.image_rules, self.lock)
        self.assertEqual("110592k", found["IMAGE_SIZE"])
        self.assertEqual("mt7981-h3c-nx30pro-112M", found["DEVICE_DTS"])
        self.assertEqual("h3c,nx30pro", found["SUPPORTED_DEVICES"])
        self.assertEqual(
            "append-ubi | check-size $$$$(IMAGE_SIZE)", found["IMAGE/factory.bin"]
        )
        self.assertEqual(
            "sysupgrade-tar | append-metadata", found["IMAGE/sysupgrade.bin"]
        )

    def test_verify_image_rules_rejects_the_profile_of_another_device(self):
        with self.assertRaises(Exception) as caught:
            self.helper.verify_image_rules(ANOTHER_PROFILE_RULES, self.lock)
        self.assertIn("h3c_nx30pro_112M", str(caught.exception))

    def test_verify_image_rules_rejects_the_stock_profile_as_the_112m_one(self):
        stock = (
            self.profile_rules.replace("h3c_nx30pro_112M", "h3c_nx30pro")
            .replace("mt7981-h3c-nx30pro-112M", "mt7981-h3c-nx30pro")
            .replace("NX30PRO (with 112M ubi)", "NX30PRO")
            .replace("110592k", "65536k")
        )
        with self.assertRaises(Exception):
            self.helper.verify_image_rules(stock, self.lock)

    def test_verify_image_rules_rejects_an_approximate_image_limit(self):
        for size in ("110000k", "110593k", "112M", "110592K"):
            text = self.image_rules.replace(
                "IMAGE_SIZE := 110592k", "IMAGE_SIZE := %s" % size
            )
            self.assertNotEqual(self.image_rules, text, size)
            with self.assertRaises(Exception, msg=size):
                self.helper.verify_image_rules(text, self.lock)

    def test_verify_image_rules_rejects_swapped_image_roles(self):
        text = self.image_rules.replace(
            "IMAGE/factory.bin := append-ubi | check-size $$$$(IMAGE_SIZE)",
            "IMAGE/factory.bin := sysupgrade-tar | append-metadata",
        ).replace(
            "IMAGE/sysupgrade.bin := sysupgrade-tar | append-metadata",
            "IMAGE/sysupgrade.bin := append-ubi | check-size $$$$(IMAGE_SIZE)",
        )
        self.assertNotEqual(self.image_rules, text)
        with self.assertRaises(Exception):
            self.helper.verify_image_rules(text, self.lock)

    def test_verify_image_rules_rejects_a_factory_image_without_a_size_check(self):
        text = self.image_rules.replace(
            "IMAGE/factory.bin := append-ubi | check-size $$$$(IMAGE_SIZE)",
            "IMAGE/factory.bin := append-ubi",
        )
        with self.assertRaises(Exception) as caught:
            self.helper.verify_image_rules(text, self.lock)
        self.assertIn("factory", str(caught.exception).lower())

    def test_verify_image_rules_rejects_a_missing_factory_image(self):
        text = self.image_rules.replace("  IMAGES += factory.bin\n", "")
        self.assertNotEqual(self.image_rules, text)
        with self.assertRaises(Exception):
            self.helper.verify_image_rules(text, self.lock)

    def test_verify_image_rules_rejects_a_wrong_device_tree_or_board(self):
        for old, new in (
            (
                "DEVICE_DTS := mt7981-h3c-nx30pro-112M",
                "DEVICE_DTS := mt7981-cmcc-rax3000m",
            ),
            ("SUPPORTED_DEVICES := h3c,nx30pro", "SUPPORTED_DEVICES := cmcc,rax3000m"),
            ("BLOCKSIZE := 128k", "BLOCKSIZE := 64k"),
            ("PAGESIZE := 2048", "PAGESIZE := 4096"),
            ("UBINIZE_OPTS := -E 5", "UBINIZE_OPTS := -E 4"),
            ("KERNEL_IN_UBI := 1", "KERNEL_IN_UBI := 0"),
        ):
            text = self.image_rules.replace(old, new)
            self.assertNotEqual(self.image_rules, text, old)
            with self.assertRaises(Exception, msg=old):
                self.helper.verify_image_rules(text, self.lock)

    def test_verifier_commands_read_the_patched_source_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            tree = Path(tmp) / "source"
            for relative, content in (
                (DEVICE_TREE_FILE, self.device_tree),
                (IMAGE_RULES_FILE, self.image_rules),
            ):
                target = tree / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
            result = run_verifier(
                "verify-device-tree", "--lock", str(LOCK), "--source-dir", str(tree)
            )
            self.assertEqual(0, result.returncode, result.stderr)
            result = run_verifier(
                "verify-image-rules", "--lock", str(LOCK), "--source-dir", str(tree)
            )
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn("h3c_nx30pro_112M", result.stdout)
            # A tree that still carries the stock table and a foreign profile
            # fails both commands.
            (tree / DEVICE_TREE_FILE).write_text(STOCK_DEVICE_TREE, encoding="utf-8")
            (tree / IMAGE_RULES_FILE).write_text(
                ANOTHER_PROFILE_RULES, encoding="utf-8"
            )
            result = run_verifier(
                "verify-device-tree", "--lock", str(LOCK), "--source-dir", str(tree)
            )
            self.assertNotEqual(0, result.returncode)
            result = run_verifier(
                "verify-image-rules", "--lock", str(LOCK), "--source-dir", str(tree)
            )
            self.assertNotEqual(0, result.returncode)
            self.assertIn("h3c_nx30pro_112M", result.stderr)

    def test_the_device_port_does_not_make_the_lock_build_ready(self):
        result = run_check(LOCK)
        self.assertEqual(BUILD_NOT_READY, result.returncode, result.stdout)
        self.assertEqual("", result.stdout.strip())
        self.assertIn("defconfig", result.stderr)


if __name__ == "__main__":
    unittest.main()
