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
