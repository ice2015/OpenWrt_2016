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

# The boot loader source is the Yuzhii DHCPD fork. The old hanwckf tree is
# rejected evidence, never a build input.
SOURCE_REPOSITORY = "https://github.com/Yuzhii0718/bl-mt798x-dhcpd"
SOURCE_COMMIT = "e4cf4dc72d451dc7a86c9508390ad5a2e50743c4"
REJECTED_REPOSITORY = "https://github.com/hanwckf/bl-mt798x"
UBOOT_TREE = "uboot-mtk-20250711"
ATF_TREE = "atf-20240117-bacca82a8"
SOC = "mt7981"
BOARD = "h3c_magic-nx30-pro"
VERSIONS = ("2025", "SP1", "SP2")

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
        self.assertEqual(SOURCE_REPOSITORY, source["repository"])
        self.assertEqual(SOURCE_COMMIT, source["commit"])
        self.assertRegex(source["commit"], COMMIT)
        self.assertEqual(UBOOT_TREE, source["uboot_tree"])
        self.assertEqual(ATF_TREE, source["atf_tree"])
        for tree in (source["atf_tree"], source["uboot_tree"]):
            self.assertIn(tree, source["vendored_trees"])
            self.assertEqual(source["commit"], source["vendored_trees"][tree]["revision"])

        board = lock["board"]
        self.assertEqual(SOC, board["soc"])
        self.assertEqual(BOARD, board["name"])
        self.assertEqual("configs/%s_%s_defconfig" % (SOC, BOARD), board["defconfig"])
        self.assertEqual(
            "configs/%s_%s_multi_layout_defconfig" % (SOC, BOARD),
            board["multi_layout_defconfig"],
        )
        self.assertEqual("arch/arm/dts/%s-%s.dts" % (SOC, BOARD), board["dts"])

        build_env = source["build_env"]
        self.assertEqual(SOC, build_env["SOC"])
        self.assertEqual(BOARD, build_env["BOARD"])
        self.assertEqual("SP1", build_env["VERSION"])
        self.assertEqual("default", build_env["VARIANT"])
        self.assertEqual("1", build_env["FIXED_MTDPARTS"])
        self.assertEqual("1", build_env["MULTI_LAYOUT"])

    def test_lock_rejects_the_old_boot_loader_repository_as_a_source(self):
        lock = self.load_lock()
        source = lock["source"]
        self.assertNotEqual(REJECTED_REPOSITORY, source["repository"])
        rejected = {item["repository"]: item for item in source["rejected_sources"]}
        self.assertIn(REJECTED_REPOSITORY, rejected)
        self.assertTrue(rejected[REJECTED_REPOSITORY]["reason"].strip())

    def test_lock_records_the_evidence_that_selected_the_sp1_version(self):
        lock = self.load_lock()
        selection = lock["source"]["version_selection"]
        self.assertEqual("SP1", selection["selected"])
        self.assertEqual(sorted(VERSIONS), sorted(selection["candidates"]))
        self.assertEqual(ATF_TREE, selection["atf_tree"])
        self.assertEqual(UBOOT_TREE, selection["uboot_tree"])
        # The selection is evidence based: the pinned fork documents SP1 as the
        # pairing for a 5.4 kernel system, which is what the firmware plan builds.
        self.assertIn("5.4", selection["evidence"])
        self.assertIn("README.md", selection["evidence_source"])
        for rejected in selection["rejected"]:
            self.assertIn(rejected["version"], VERSIONS)
            self.assertTrue(rejected["reason"].strip())

    def test_lock_names_the_artifacts_the_pinned_build_script_emits(self):
        lock = self.load_lock()
        artifacts = lock["artifacts"]
        for kind in ("fip", "bl2"):
            entry = artifacts[kind]
            self.assertEqual("output", entry["directory"])
            self.assertIn("md5-", entry["pattern"])
            self.assertIn("*", entry["pattern"])
        self.assertTrue(artifacts["fip"]["pattern"].endswith(".bin"))
        self.assertTrue(artifacts["bl2"]["pattern"].endswith(".img"))
        self.assertIn("SP1-Yuzhii-dhcpd-fixed-parts-multi-layout", artifacts["fip"]["pattern"])
        self.assertIn("bl2-mt7981_h3c_magic-nx30-pro_SP1", artifacts["bl2"]["pattern"])

    def test_lock_records_the_host_dependencies_of_the_pinned_build_script(self):
        lock = self.load_lock()
        host_packages = lock["host_packages"]
        # build.sh compiles the failsafe web assets with npm before it builds.
        for package in ("npm", "python3", "gcc-aarch64-linux-gnu", "build-essential"):
            self.assertIn(package, host_packages)

    def test_lock_partition_contract_matches_the_112m_layout(self):
        lock = self.load_lock()
        contract = lock["partition_contract"]
        actual = [
            (entry["label"], entry["offset"], entry["size"])
            for entry in contract["partitions"]
        ]
        self.assertEqual(EXPECTED_PARTITIONS, actual)
        self.assertEqual(0x7580000, contract["ubi_end_offset"])
        # The partition contract is read from the pinned boot loader source, not
        # from the rejected firmware source of the earlier candidate.
        self.assertEqual("Yuzhii0718/bl-mt798x-dhcpd", contract["source_repository"])
        self.assertEqual(SOURCE_COMMIT, contract["source_commit"])
        self.assertIn("mt7981-h3c_magic-nx30-pro.dts", contract["source_file"])

    def test_lock_whitelists_exactly_the_two_upstream_layouts(self):
        lock = self.load_lock()
        layouts = lock["layouts"]
        self.assertEqual("immortalwrt-112m", layouts["default_label"])
        self.assertEqual({"immortalwrt-112m", "default"}, set(layouts["entries"]))
        self.assertEqual("nmbm0=nmbm0", layouts["mtdids"])
        self.assertEqual("nmbm-logical", layouts["address_space"])
        self.assertIn("mt7981-h3c_magic-nx30-pro.dts", layouts["source"])
        for label, entry in layouts["entries"].items():
            self.assertEqual(label, entry["label"])
            self.assertTrue(entry["partitions"])
        self.assertEqual(
            "nmbm0:1024k(bl2),512k(u-boot-env),2048k(Factory),2048k(fip),112M(ubi)",
            layouts["entries"]["immortalwrt-112m"]["mtdparts"],
        )
        self.assertEqual(
            "nmbm0:1024k(bl2),512k(u-boot-env),2048k(Factory),2048k(fip),"
            "65536k(ubi),6144k(pdt_data),6144k(pdt_data_1),1024k(exp),38400k(plugin)",
            layouts["entries"]["default"]["mtdparts"],
        )

    def test_stock_layout_keeps_the_oem_partitions_behind_ubi(self):
        lock = self.load_lock()
        stock = lock["layouts"]["entries"]["default"]["partitions"]
        labels = [entry["label"] for entry in stock]
        for partition in ("pdt_data", "pdt_data_1", "exp", "plugin"):
            self.assertIn(partition, labels)
        self.assertEqual(0x4000000, dict((e["label"], e["size"]) for e in stock)["ubi"])

    def test_both_layouts_share_the_boot_loader_partition_offsets(self):
        lock = self.load_lock()
        entries = lock["layouts"]["entries"]
        shared = {}
        for label, entry in entries.items():
            shared[label] = [
                (partition["label"].lower(), partition["offset"], partition["size"])
                for partition in entry["partitions"][:4]
            ]
        self.assertEqual(shared["default"], shared["immortalwrt-112m"])
        self.assertEqual(
            [("bl2", 0, 0x100000), ("u-boot-env", 0x100000, 0x80000),
             ("factory", 0x180000, 0x200000), ("fip", 0x380000, 0x200000)],
            shared["immortalwrt-112m"],
        )

    def test_partition_contract_is_the_locked_112m_layout(self):
        lock = self.load_lock()
        contract = [
            (entry["label"].lower(), entry["offset"], entry["size"])
            for entry in lock["partition_contract"]["partitions"]
        ]
        layout = [
            (entry["label"].lower(), entry["offset"], entry["size"])
            for entry in lock["layouts"]["entries"]["immortalwrt-112m"]["partitions"]
        ]
        self.assertEqual(layout, contract)
        # The contract keeps the capitalised labels of the system side; the boot
        # loader tables spell bl2, Factory and fip as the mtdparts names them.
        self.assertEqual(
            [(label.lower(), offset, size) for label, offset, size in EXPECTED_PARTITIONS],
            contract,
        )

    def test_lock_records_the_stock_layout_mismatch(self):
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

        # Both required tables already exist in the pinned device tree, so no
        # partition table has to be patched into the source.
        patch = compatibility["minimal_device_patch"]
        self.assertEqual("none-required-for-the-partition-tables", patch["action"])
        self.assertIn("mt7981-h3c_magic-nx30-pro.dts", patch["target"])

    def test_lock_keeps_nmbm_geometry_and_web_failsafe_facts(self):
        lock = self.load_lock()
        nmbm = lock["nmbm"]
        self.assertTrue(nmbm["enabled"])
        self.assertEqual("CONFIG_ENABLE_NAND_NMBM=y", nmbm["u_boot_config"])
        self.assertEqual(1, nmbm["max_ratio"])
        self.assertEqual(256, nmbm["max_reserved_blocks"])
        # The bootloader side of the geometry is verified in the pinned tree;
        # the system side belongs to the firmware source, which is not locked
        # yet, so the comparison stays unresolved instead of being asserted.
        self.assertEqual("UNRESOLVED", nmbm["geometry_matches_across_bootloader_and_system"])
        self.assertIn(UBOOT_TREE, nmbm["evidence_source"])

        failsafe = lock["web_failsafe"]
        self.assertTrue(failsafe["enabled"])
        self.assertEqual("http://192.168.1.1/", failsafe["url"])
        self.assertEqual(80, failsafe["port"])
        self.assertEqual(["bl2", "fip"], sorted(failsafe["bootloader_uploads"]))
        self.assertEqual(["firmware", "initramfs"], sorted(failsafe["system_uploads"]))
        self.assertEqual("fip", failsafe["fip_target_partition"])
        self.assertEqual("bl2", failsafe["bl2_target_partition"])
        self.assertIn("CONFIG_MTK_WEB_FAILSAFE=y", failsafe["u_boot_config"])

    def test_lock_records_the_restricted_feature_set(self):
        lock = self.load_lock()
        features = lock["features"]
        self.assertEqual("locked", features["status"])
        enabled = {item["symbol"]: item for item in features["enabled"]}
        disabled = {item["symbol"]: item for item in features["disabled"]}

        # Recovery features the design requires.
        for symbol in (
            "CONFIG_MTK_DHCPD",
            "CONFIG_MTK_WEB_FAILSAFE",
            "CONFIG_MTK_WEB_FAILSAFE_AFTER_BOOT_FAILURE",
            "CONFIG_WEBUI_FAILSAFE_BACKUP",
            "CONFIG_MTK_UBI_SUPPORT",
            "CONFIG_MTK_UPGRADE_BL2_VERIFY",
            "CONFIG_CMD_TFTPPUT",
            "CONFIG_DEBUG_UART",
            "CONFIG_MEDIATEK_MULTI_MTD_LAYOUT",
            "CONFIG_MTK_FIXED_MTD_MTDPARTS",
            "CONFIG_MTK_DEFAULT_MTD_LAYOUT",
        ):
            self.assertIn(symbol, enabled, "%s must be enabled" % symbol)
            self.assertTrue(enabled[symbol]["purpose"].strip())
        self.assertEqual("immortalwrt-112m", enabled["CONFIG_MTK_DEFAULT_MTD_LAYOUT"]["value"])

        # Features the design forbids on this device.
        for symbol in (
            "CONFIG_WEBUI_FAILSAFE_FACTORY",
            "CONFIG_WEBUI_FAILSAFE_FLASH",
            "CONFIG_WEBUI_FAILSAFE_ENV",
            "CONFIG_WEBUI_FAILSAFE_CONSOLE",
            "CONFIG_WEBUI_FAILSAFE_UBI",
            "CONFIG_WEBUI_FAILSAFE_SIMG",
            "CONFIG_WEBUI_FAILSAFE_NAND_RAW",
            "CONFIG_MTK_TELNETD",
        ):
            self.assertIn(symbol, disabled, "%s must be disabled" % symbol)
            self.assertTrue(disabled[symbol]["reason"].strip())
        self.assertTrue(features["overclock"]["note"].strip())

    def test_lock_records_the_device_patch_and_its_applicability(self):
        lock = self.load_lock()
        patches = lock["source"]["patches"]
        self.assertEqual(1, len(patches))
        patch = patches[0]
        self.assertEqual(
            "devices/nx30pro/uboot/patches/0001-nx30pro-restrict-recovery-ui.patch",
            patch["path"],
        )
        self.assertEqual(SOURCE_COMMIT, patch["applies_to_commit"])
        self.assertTrue(patch["purpose"].strip())
        touched = patch["upstream_files"]
        self.assertTrue(touched)
        for path in touched:
            self.assertTrue(path.startswith("uboot-mtk-20250711/"), path)
        self.assertTrue((ROOT / patch["path"]).is_file(), "missing device patch %s" % patch["path"])

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
        self.assertIn("112M(ubi)", text)


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

    def test_backup_procedure_does_not_assume_the_master_device(self):
        text = (
            ROOT / "devices" / "nx30pro" / "docs" / "nx30pro-uboot-install-and-recovery.md"
        ).read_text(encoding="utf-8")
        self.assertIsNone(
            re.search(r"nanddump[^\n]*/dev/mtd", text),
            "the backup procedure must not name a flash device before it is identified",
        )
        self.assertNotIn("/dev/mtd0", text)
        self.assertIn("master", text)
        self.assertIn("长度", text)
        self.assertIn("坏块", text)

    def test_recovery_document_separates_upgrade_first_install_and_recovery(self):
        text = (
            ROOT / "devices" / "nx30pro" / "docs" / "nx30pro-uboot-install-and-recovery.md"
        ).read_text(encoding="utf-8")
        self.assertIn("首次安装", text)
        self.assertIn("不可启动", text)
        self.assertIn("独立恢复路径", text)
        self.assertIn("UNRESOLVED", text)
        # The candidate boot loader cannot recover itself, so it must not be
        # presented as the recovery path.
        self.assertIn("不能替代", text)

    def test_lock_records_the_mac_dependency_of_the_selected_system(self):
        lock = self.load_lock()
        dependencies = lock["system_dependencies"]
        self.assertTrue(dependencies)
        joined = " ".join(
            "%s %s %s" % (item.get("topic", ""), item.get("detail", ""), item.get("impact", ""))
            for item in dependencies
        )
        self.assertIn("pdt_data_1", joined)
        self.assertIn("Factory", joined)
        self.assertIn("ethaddr", joined)
        for item in dependencies:
            self.assertEqual("UNRESOLVED", item.get("status"))

        compatibility = (
            ROOT / "devices" / "nx30pro" / "docs" / "nx30pro-uboot-compatibility.md"
        ).read_text(encoding="utf-8")
        recovery = (
            ROOT / "devices" / "nx30pro" / "docs" / "nx30pro-uboot-install-and-recovery.md"
        ).read_text(encoding="utf-8")
        self.assertIn("pdt_data_1", compatibility)
        self.assertIn("pdt_data_1", recovery)

    def test_documents_use_nmbm_logical_addresses_and_do_not_claim_measured_capacity(self):
        lock = self.load_lock()
        contract = lock["partition_contract"]
        self.assertEqual("derived-not-measured", contract["trailing_logical_space_status"])
        self.assertIn("UNRESOLVED", contract["trailing_logical_space_note"])

        compatibility = (
            ROOT / "devices" / "nx30pro" / "docs" / "nx30pro-uboot-compatibility.md"
        ).read_text(encoding="utf-8")
        self.assertIn("NMBM 逻辑", compatibility)
        self.assertIn("122880", compatibility)
        self.assertNotIn("实测容量", compatibility)

    def test_documents_record_the_button_entry_and_keep_the_dram_type_unresolved(self):
        compatibility = (
            ROOT / "devices" / "nx30pro" / "docs" / "nx30pro-uboot-compatibility.md"
        ).read_text(encoding="utf-8")
        # The button entry is verified in the pinned defconfigs; the DRAM type of
        # this ATF pairing is not, so it must stay unresolved instead of being
        # carried over from the rejected candidate.
        self.assertIn("GL_BTN", compatibility)
        self.assertIn("UNRESOLVED", compatibility)
        self.assertNotIn("EMI: Using DDR3/DDR4", compatibility)

    def test_toolchain_digest_is_part_of_the_accepted_evidence(self):
        lock = self.load_lock()
        self.assertIn("compiler_sha256", lock["toolchain"]["capture"])
        helper = (
            ROOT / "devices" / "nx30pro" / "build" / "uboot_lock.py"
        ).read_text(encoding="utf-8")
        self.assertIn("compiler_sha256", helper)


class Nx30ProUbootDocumentationTests(unittest.TestCase):
    """The operator documents must not outrun the evidence.

    A candidate build is not a device validation, a design is not an executed
    step, and no document may hand out a destructive flash command.
    """

    DOCS = {
        "compatibility": "devices/nx30pro/docs/nx30pro-uboot-compatibility.md",
        "recovery": "devices/nx30pro/docs/nx30pro-uboot-install-and-recovery.md",
        "build": "devices/nx30pro/docs/UBOOT-BUILD.md",
        "report": "devices/nx30pro/docs/UBOOT-TEST-REPORT.md",
        "readme": "devices/nx30pro/README.md",
    }

    FORBIDDEN_COMMANDS = (
        "mtd write",
        "nandwrite",
        "flash_erase",
        "mtd_debug",
        "dd of=",
        "/dev/mtd0",
        "ubiformat",
    )

    def text(self, key):
        path = ROOT / self.DOCS[key]
        self.assertTrue(path.is_file(), "missing NX30 Pro U-Boot document: %s" % path)
        return path.read_text(encoding="utf-8")

    def test_every_document_names_the_pinned_source(self):
        for key in self.DOCS:
            text = self.text(key)
            self.assertIn("Yuzhii0718/bl-mt798x-dhcpd", text, key)
            self.assertIn(SOURCE_COMMIT, text, key)

    def test_documents_state_the_two_layouts_and_which_one_is_the_default(self):
        for key in ("compatibility", "recovery", "build", "report", "readme"):
            text = self.text(key)
            self.assertIn("immortalwrt-112m", text, key)
            self.assertIn("default", text, key)
            self.assertIn("默认", text, key)
        for key in ("compatibility", "build"):
            self.assertIn(
                "nmbm0:1024k(bl2),512k(u-boot-env),2048k(Factory),2048k(fip),112M(ubi)",
                self.text(key),
                key,
            )
            self.assertIn("65536k(ubi)", self.text(key), key)

    def test_documents_list_the_restricted_recovery_feature_set(self):
        for key in ("compatibility", "build", "readme"):
            text = self.text(key)
            for enabled in ("DHCP", "Web failsafe", "只读备份", "TFTP", "UART", "BL2", "FIP"):
                self.assertIn(enabled, text, "%s: %s" % (key, enabled))
            for disabled in (
                "CONFIG_WEBUI_FAILSAFE_FACTORY",
                "CONFIG_WEBUI_FAILSAFE_FLASH",
                "CONFIG_WEBUI_FAILSAFE_ENV",
                "CONFIG_WEBUI_FAILSAFE_CONSOLE",
                "CONFIG_WEBUI_FAILSAFE_UBI",
                "CONFIG_MTK_TELNETD",
                "超频",
            ):
                self.assertIn(disabled, text, "%s: %s" % (key, disabled))

    def test_documents_put_the_backup_before_the_layout_switch(self):
        for key in ("compatibility", "recovery", "build", "report"):
            text = self.text(key)
            self.assertIn("备份", text, key)
            self.assertIn("NMBM 逻辑", text, key)
            for partition in ("pdt_data_1", "exp", "plugin"):
                self.assertIn(partition, text, key)

    def test_documents_separate_artifact_roles(self):
        for key in ("compatibility", "build", "report"):
            text = self.text(key)
            self.assertIn("BL2", text, key)
            self.assertIn("FIP", text, key)
            self.assertIn("不是系统镜像", text, key)
            self.assertIn("md5", text.lower(), key)

    def test_no_document_claims_a_completed_device_validation(self):
        for key in self.DOCS:
            text = self.text(key)
            for claim in ("真机验证通过", "已真机验证", "验证成功", "可以安全刷写"):
                self.assertNotIn(claim, text, "%s claims %s" % (key, claim))
            for command in self.FORBIDDEN_COMMANDS:
                self.assertNotIn(command, text, "%s contains %s" % (key, command))

    def test_the_test_report_records_only_what_actually_happened(self):
        text = self.text("report")
        self.assertIn("静态", text)
        self.assertIn("未触发", text)
        self.assertIn("未编译", text)
        self.assertIn("UNRESOLVED", text)
        self.assertIn("授权", text)
        # No run id, hash or device result may be invented before it exists.
        self.assertNotRegex(text, r"run[ _]?id[^\n]*[0-9]{8,}")
        self.assertNotRegex(text, r"\b[0-9a-f]{64}\b")

    def test_the_build_document_gives_the_reproducible_inputs_and_the_gate(self):
        text = self.text("build")
        self.assertIn("devices/nx30pro/build/build-uboot.sh", text)
        self.assertIn("--check-only", text)
        self.assertIn(".github/workflows/build-nx30pro-uboot.yml", text)
        self.assertIn("workflow_dispatch", text)
        self.assertIn("SP1", text)
        self.assertIn("MULTI_LAYOUT", text)
        self.assertIn("FIXED_MTDPARTS", text)
        self.assertIn("npm", text)
        self.assertIn("授权", text)


if __name__ == "__main__":
    unittest.main()
