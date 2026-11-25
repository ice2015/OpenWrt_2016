"""Contract for the NX30 Pro U-Boot source lock and compatibility record.

The source lock is the only thing that ties a boot loader build to a
verified upstream revision. These tests keep it pinned to a full commit,
keep the partition table equal to the 112 MiB UBI layout selected for this
device, and keep the mismatch against the upstream stock layout recorded
instead of silently accepted.
"""

import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
LOCK = ROOT / "devices" / "nx30pro" / "uboot" / "uboot-source-lock.json"
COMPATIBILITY_DOC = (
    ROOT / "devices" / "nx30pro" / "docs" / "nx30pro-uboot-compatibility.md"
)

COMMIT = re.compile(r"^[0-9a-f]{40}$")

# The partition contract comes from the device tree of the selected
# nx30pro-112m system, not from the boot loader project.
EXPECTED_PARTITIONS = [
    ("BL2", 0x000000, 0x100000),
    ("u-boot-env", 0x100000, 0x080000),
    ("Factory", 0x180000, 0x200000),
    ("FIP", 0x380000, 0x200000),
    ("ubi", 0x580000, 0x7000000),
]


class Nx30ProUbootSourceLockTests(unittest.TestCase):
    def load_lock(self):
        self.assertTrue(LOCK.is_file(), "missing NX30 Pro U-Boot source lock: %s" % LOCK)
        return json.loads(LOCK.read_text(encoding="utf-8"))

    def test_lock_pins_a_full_upstream_commit_and_the_real_board_name(self):
        lock = self.load_lock()
        source = lock["source"]
        self.assertEqual("https://github.com/hanwckf/bl-mt798x", source["repository"])
        self.assertRegex(source["commit"], COMMIT)
        self.assertEqual("mt7981", source["build_env"]["SOC"])
        self.assertEqual("h3c_magic-nx30-pro", source["build_env"]["BOARD"])
        self.assertEqual("1", source["build_env"]["FIXED_MTDPARTS"])
        self.assertEqual("0", source["build_env"]["MULTI_LAYOUT"])
        self.assertTrue(source["atf_tree"])
        self.assertTrue(source["uboot_tree"])
        for tree in (source["atf_tree"], source["uboot_tree"]):
            self.assertIn(tree, source["vendored_trees"])
            self.assertEqual(source["commit"], source["vendored_trees"][tree]["revision"])

    def test_lock_partition_contract_matches_the_112m_layout(self):
        lock = self.load_lock()
        contract = lock["partition_contract"]
        actual = [
            (entry["label"], entry["offset"], entry["size"])
            for entry in contract["partitions"]
        ]
        self.assertEqual(EXPECTED_PARTITIONS, actual)
        self.assertEqual(0x7580000, contract["ubi_end_offset"])
        self.assertEqual(
            "jerryhan77/immortalwrt-mt798x",
            contract["source_repository"],
        )
        self.assertRegex(contract["source_commit"], COMMIT)

    def test_lock_records_the_stock_layout_mismatch_and_the_minimal_patch(self):
        lock = self.load_lock()
        compatibility = lock["compatibility"]
        self.assertFalse(compatibility["layout_matches_upstream_stock"])
        self.assertIn(
            "nmbm0:1024k(bl2),512k(u-boot-env),2048k(Factory),2048k(fip)",
            compatibility["upstream_stock_mtdparts"],
        )
        self.assertIn("65536k(ubi)", compatibility["upstream_stock_mtdparts"])

        mismatched = {entry["partition"]: entry for entry in compatibility["mismatches"]}
        self.assertEqual(0x7000000, mismatched["ubi"]["required_size_bytes"])
        self.assertEqual(0x4000000, mismatched["ubi"]["upstream_stock_size_bytes"])
        for removed in ("pdt_data", "pdt_data_1", "exp", "plugin"):
            self.assertIn(removed, mismatched)
            self.assertEqual(0, mismatched[removed]["required_size_bytes"])

        patch = compatibility["minimal_device_patch"]
        self.assertEqual(
            "nmbm0:1024k(bl2),512k(u-boot-env),2048k(Factory),2048k(fip),114688k(ubi)",
            patch["value"],
        )
        self.assertIn("mt7981_h3c_magic-nx30-pro_defconfig", patch["target"])

    def test_lock_keeps_nmbm_geometry_and_web_failsafe_facts(self):
        lock = self.load_lock()
        nmbm = lock["nmbm"]
        self.assertTrue(nmbm["enabled"])
        self.assertEqual(1, nmbm["max_ratio"])
        self.assertEqual(256, nmbm["max_reserved_blocks"])
        self.assertTrue(nmbm["geometry_matches_across_bootloader_and_system"])

        failsafe = lock["web_failsafe"]
        self.assertTrue(failsafe["enabled"])
        self.assertEqual("http://192.168.1.1/", failsafe["url"])
        self.assertEqual(80, failsafe["port"])
        self.assertEqual(["bl2", "fip"], sorted(failsafe["bootloader_uploads"]))
        self.assertEqual(["firmware", "initramfs"], sorted(failsafe["system_uploads"]))
        self.assertEqual("fip", failsafe["fip_target_partition"])
        self.assertEqual("bl2", failsafe["bl2_target_partition"])

    def test_lock_does_not_guess_toolchain_or_hardware_facts(self):
        lock = self.load_lock()
        toolchain = lock["toolchain"]
        self.assertEqual("gcc-aarch64-linux-gnu", toolchain["package"])
        self.assertEqual("aarch64-linux-gnu-", toolchain["prefix"])
        for field in ("version", "checksum"):
            value = toolchain[field]
            self.assertTrue(value, "toolchain %s must be recorded or UNRESOLVED" % field)
            if value == "UNRESOLVED":
                continue
            self.assertNotEqual("unknown", value.lower())
        self.assertIn("build-essential", lock["host_packages"])
        self.assertIn("device-tree-compiler", lock["host_packages"])
        self.assertTrue(lock["unresolved"], "unresolved facts must stay listed")
        for item in lock["unresolved"]:
            self.assertTrue(item["topic"].strip())
            self.assertTrue(item["status"].strip())

    def test_compatibility_document_separates_facts_from_open_items(self):
        self.assertTrue(
            COMPATIBILITY_DOC.is_file(),
            "missing NX30 Pro U-Boot compatibility document: %s" % COMPATIBILITY_DOC,
        )
        text = COMPATIBILITY_DOC.read_text(encoding="utf-8")
        for label, _, _ in EXPECTED_PARTITIONS:
            self.assertIn(label, text)
        self.assertIn("UNRESOLVED", text)
        self.assertIn("候选", text)
        self.assertNotIn("真机验证通过", text)
        self.assertIn("h3c_magic-nx30-pro", text)
        self.assertIn("114688k(ubi)", text)


    def test_install_and_recovery_document_designs_without_authorizing_a_flash(self):
        document = (
            ROOT / "devices" / "nx30pro" / "docs" / "nx30pro-uboot-install-and-recovery.md"
        )
        self.assertTrue(
            document.is_file(),
            "missing NX30 Pro U-Boot install and recovery document: %s" % document,
        )
        text = document.read_text(encoding="utf-8")
        for topic in ("备份", "回退", "验证", "UNRESOLVED", "192.168.1.1"):
            self.assertIn(topic, text)
        self.assertIn("授权", text)
        # Write commands stay out of the document; read only backup commands
        # are part of the required procedure.
        for forbidden in ("mtd write", "nandwrite", "flash_erase", "dd of="):
            self.assertNotIn(forbidden, text)


if __name__ == "__main__":
    unittest.main()
