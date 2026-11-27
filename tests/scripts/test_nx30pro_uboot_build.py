"""Tests for the NX30 Pro U-Boot build entry point.

The boot loader build must refuse to start when the source lock is not
complete: a missing commit, another board, a partition layout that does not
match the selected system, or an unconfirmed image type all stop the build
before any source is fetched. The produced images are classified by their
content, never by their file name.
"""

import importlib.util
import json
import os
import shutil
import struct
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BUILD_DIR = ROOT / "devices" / "nx30pro" / "build"
SCRIPT = BUILD_DIR / "build-uboot.sh"
HELPER = BUILD_DIR / "uboot_lock.py"
LOCK = ROOT / "devices" / "nx30pro" / "uboot" / "uboot-source-lock.json"

SOURCE_REPOSITORY = "https://github.com/Yuzhii0718/bl-mt798x-dhcpd"
SOURCE_COMMIT = "e4cf4dc72d451dc7a86c9508390ad5a2e50743c4"
REJECTED_REPOSITORY = "https://github.com/hanwckf/bl-mt798x"

# `check` reports a lock that is not build ready with the repository wide
# build-not-ready status, the same code tools/manifest.py uses.
BUILD_NOT_READY = 3

TOC_HEADER_NAME = 0xAA640001
BL31_UUID = bytes.fromhex("47d4086d4cfe98469b952950cbbd5a00")
BL33_UUID = bytes.fromhex("d6d0eea7fcead54b97829934f234b6e4")
SPIM_NAND_HEADER = b"SPINAND!"


def load_helper():
    spec = importlib.util.spec_from_file_location("nx30pro_uboot_lock", HELPER)
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


def build_fip_image(path, bl33_payload=b"U-Boot 2025.07 compiled"):
    """Write a structurally valid ATF FIP package carrying BL31 and BL33."""
    entries = [(BL31_UUID, b"\x00" * 32), (BL33_UUID, bl33_payload)]
    header = struct.pack("<IIQ", TOC_HEADER_NAME, 0x12345678, 0)
    offset = len(header) + 40 * (len(entries) + 1)
    toc = b""
    payloads = b""
    for uuid, payload in entries:
        toc += uuid + struct.pack("<QQQ", offset, len(payload), 0)
        offset += len(payload)
        payloads += payload
    toc += b"\x00" * 16 + struct.pack("<QQQ", offset, 0, 0)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header + toc + payloads)
    return path


def build_bl2_image(path):
    """Write a structurally valid MediaTek SPI-NAND BL2 preloader header."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        SPIM_NAND_HEADER + b"\x01\x00\x00\x00\x10\x00\x00\x00" + b"\x00" * 64
    )
    return path


# The orchestration tests drive the stub build with the host compiler;
# GitHub Actions installs the real cross compiler.
HOST_COMPILER = shutil.which("gcc")


class Nx30ProUbootBuildGateTests(unittest.TestCase):
    def test_locked_source_lock_is_build_ready(self):
        result = run_check(LOCK)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("h3c_magic-nx30-pro", result.stdout)
        self.assertIn(SOURCE_COMMIT, result.stdout)
        self.assertIn(SOURCE_REPOSITORY, result.stdout)

    def test_missing_commit_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock = write_lock(tmp, **{"source.commit": None})
            result = run_check(lock)
        self.assertEqual(BUILD_NOT_READY, result.returncode)
        self.assertIn("commit", result.stderr)

    def test_branch_name_instead_of_commit_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock = write_lock(tmp, **{"source.commit": "master"})
            result = run_check(lock)
        self.assertEqual(BUILD_NOT_READY, result.returncode)
        self.assertIn("commit", result.stderr)

    def test_the_old_boot_loader_repository_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock = write_lock(
                tmp,
                **{
                    "source.repository": REJECTED_REPOSITORY,
                    "source.commit": "36916669d0874306638196c5327a20c2ef215bed",
                },
            )
            result = run_check(lock)
        self.assertEqual(BUILD_NOT_READY, result.returncode)
        self.assertIn(SOURCE_REPOSITORY, result.stderr)

    def test_an_unresolved_version_blocks_build_readiness(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock = write_lock(tmp, **{"source.version": "UNRESOLVED"})
            result = run_check(lock)
        self.assertEqual(BUILD_NOT_READY, result.returncode)
        self.assertIn("version", result.stderr.lower())

    def test_a_version_that_does_not_match_the_locked_trees_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock = write_lock(tmp, **{"source.version": "2025"})
            result = run_check(lock)
        self.assertEqual(BUILD_NOT_READY, result.returncode)
        self.assertIn("version", result.stderr.lower())

    def test_wrong_board_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock = write_lock(tmp, **{"source.build_env.BOARD": "wr30u"})
            result = run_check(lock)
        self.assertEqual(BUILD_NOT_READY, result.returncode)
        self.assertIn("board", result.stderr.lower())

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

    def test_unconfirmed_image_type_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock = write_lock(tmp, **{"artifacts.fip": None})
            result = run_check(lock)
        self.assertNotEqual(0, result.returncode)
        self.assertIn("image", result.stderr.lower())

    def test_lock_naming_a_tree_that_the_build_does_not_use_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock = write_lock(
                tmp,
                **{
                    "source.uboot_tree": "uboot-mtk-20220606",
                    "source.vendored_trees": {
                        "uboot-mtk-20220606": {
                            "revision": SOURCE_COMMIT,
                            "kind": "vendored-in-upstream-repository",
                        }
                    },
                },
            )
            result = run_check(lock)
        self.assertEqual(BUILD_NOT_READY, result.returncode)
        self.assertIn("tree", result.stderr.lower())


class Nx30ProUbootArtifactNameTests(unittest.TestCase):
    """The pinned build script embeds an md5 in every artifact name.

    A lock that stored one fixed file name would describe a build that can
    never be reproduced, so the helper matches the recorded pattern instead.
    """

    def setUp(self):
        self.helper = load_helper()
        self.lock = json.loads(LOCK.read_text(encoding="utf-8"))

    def test_the_recorded_fip_and_bl2_names_are_accepted(self):
        fip = "fip-mt7981_h3c_magic-nx30-pro_SP1-Yuzhii-dhcpd-fixed-parts-multi-layout_md5-%s.bin" % (
            "a" * 32
        )
        bl2 = "bl2-mt7981_h3c_magic-nx30-pro_SP1_md5-%s.img" % ("b" * 32)
        self.assertEqual(fip, self.helper.match_artifact_name(self.lock, "fip", fip))
        self.assertEqual(bl2, self.helper.match_artifact_name(self.lock, "bl2", bl2))

    def test_a_name_of_another_version_or_variant_is_rejected(self):
        wrong_version = "fip-mt7981_h3c_magic-nx30-pro_2025-Yuzhii-dhcpd-fixed-parts-multi-layout_md5-%s.bin" % (
            "a" * 32
        )
        with self.assertRaises(Exception):
            self.helper.match_artifact_name(self.lock, "fip", wrong_version)

    def test_a_system_image_cannot_be_labelled_a_boot_loader_image(self):
        sysupgrade = "immortalwrt-21.02.7-mediatek-mt7981-h3c_nx30pro_112M-sysupgrade.bin"
        with self.assertRaises(Exception):
            self.helper.match_artifact_name(self.lock, "fip", sysupgrade)
        with self.assertRaises(Exception):
            self.helper.match_artifact_name(self.lock, "bl2", sysupgrade)

    def test_a_fixed_name_without_the_build_digest_is_rejected(self):
        with self.assertRaises(Exception):
            self.helper.match_artifact_name(
                self.lock, "bl2", "bl2-mt7981_h3c_magic-nx30-pro_SP1.img"
            )

    def test_script_refuses_to_flash_anything(self):
        text = SCRIPT.read_text(encoding="utf-8")
        for forbidden in ("flashwrite", "nandwrite", "mtd write", "dd if=", "/dev/mtd"):
            self.assertNotIn(forbidden, text)
        self.assertIn("no flash", text.lower())


class Nx30ProUbootLayoutSourceTests(unittest.TestCase):
    """The layout whitelist has to exist in the pinned upstream device tree.

    The verifier must not synthesise a layout the source does not carry, and it
    must not accept a source that offers a third, arbitrary layout.
    """

    LAYOUT_112M = (
        "nmbm0:1024k(bl2),512k(u-boot-env),2048k(Factory),2048k(fip),112M(ubi)"
    )
    LAYOUT_STOCK = (
        "nmbm0:1024k(bl2),512k(u-boot-env),2048k(Factory),2048k(fip),"
        "65536k(ubi),6144k(pdt_data),6144k(pdt_data_1),1024k(exp),38400k(plugin)"
    )

    def setUp(self):
        self.helper = load_helper()
        self.lock = json.loads(LOCK.read_text(encoding="utf-8"))

    def dts(self, layouts=None):
        if layouts is None:
            layouts = [
                ("layout@0", "default", self.LAYOUT_STOCK),
                ("layout@1", "immortalwrt-112m", self.LAYOUT_112M),
            ]
        body = ""
        for node, label, parts in layouts:
            body += (
                "\t\t%s {\n"
                '\t\t\tlabel = "%s";\n'
                '\t\t\tmtdids = "nmbm0=nmbm0";\n'
                '\t\t\tmtdparts = "%s";\n'
                "\t\t};\n\n" % (node, label, parts)
            )
        return (
            "// SPDX-License-Identifier: GPL-2.0-or-later OR MIT\n"
            "/dts-v1/;\n"
            "/ {\n"
            '\tmodel = "mt7981-h3c_magic-nx30-pro";\n'
            "\tmtd-layout {\n"
            "%s"
            "\t};\n"
            "};\n" % body
        )

    def verify(self, text, lock=None):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "board.dts"
            path.write_text(text, encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable, str(HELPER), "verify-layout-source",
                    "--lock", str(LOCK if lock is None else lock),
                    "--dts", str(path),
                ],
                capture_output=True,
                text=True,
            )
        return result

    def test_the_pinned_device_tree_carries_exactly_the_locked_whitelist(self):
        result = self.verify(self.dts())
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("immortalwrt-112m", result.stdout)
        self.assertIn("default", result.stdout)

    def test_a_source_without_the_112m_layout_is_rejected(self):
        result = self.verify(self.dts([("layout@0", "default", self.LAYOUT_STOCK)]))
        self.assertEqual(BUILD_NOT_READY, result.returncode)
        self.assertIn("immortalwrt-112m", result.stderr)

    def test_a_source_without_the_stock_layout_is_rejected(self):
        result = self.verify(self.dts([("layout@0", "immortalwrt-112m", self.LAYOUT_112M)]))
        self.assertEqual(BUILD_NOT_READY, result.returncode)
        self.assertIn("default", result.stderr)

    def test_a_source_with_a_third_layout_is_rejected(self):
        result = self.verify(
            self.dts(
                [
                    ("layout@0", "default", self.LAYOUT_STOCK),
                    ("layout@1", "immortalwrt-112m", self.LAYOUT_112M),
                    ("layout@2", "openwrt", "nmbm0:1024k(bl2),120M(firmware)"),
                ]
            )
        )
        self.assertEqual(BUILD_NOT_READY, result.returncode)
        self.assertIn("openwrt", result.stderr)

    def test_a_changed_factory_offset_is_rejected(self):
        changed = self.LAYOUT_112M.replace("2048k(Factory)", "4096k(Factory)")
        result = self.verify(
            self.dts(
                [
                    ("layout@0", "default", self.LAYOUT_STOCK),
                    ("layout@1", "immortalwrt-112m", changed),
                ]
            )
        )
        self.assertEqual(BUILD_NOT_READY, result.returncode)
        self.assertIn("Factory", result.stderr)

    def test_a_stock_layout_that_lost_an_oem_partition_is_rejected(self):
        changed = self.LAYOUT_STOCK.replace(",6144k(pdt_data_1)", "")
        result = self.verify(
            self.dts(
                [
                    ("layout@0", "default", changed),
                    ("layout@1", "immortalwrt-112m", self.LAYOUT_112M),
                ]
            )
        )
        self.assertEqual(BUILD_NOT_READY, result.returncode)
        self.assertIn("pdt_data_1", result.stderr)

    def test_physical_nand_addressing_is_not_accepted_as_nmbm_logical(self):
        physical = self.LAYOUT_112M.replace("nmbm0:", "spi-nand0:")
        text = self.dts(
            [
                ("layout@0", "default", self.LAYOUT_STOCK),
                ("layout@1", "immortalwrt-112m", physical),
            ]
        ).replace('mtdids = "nmbm0=nmbm0"', 'mtdids = "spi-nand0=spi-nand0"')
        result = self.verify(text)
        self.assertEqual(BUILD_NOT_READY, result.returncode)
        self.assertIn("nmbm", result.stderr.lower())

    def test_a_device_tree_without_a_layout_node_is_rejected(self):
        result = self.verify("/dts-v1/;\n/ {\n\tmodel = \"mt7981-h3c_magic-nx30-pro\";\n};\n")
        self.assertEqual(BUILD_NOT_READY, result.returncode)
        self.assertIn("mtd-layout", result.stderr)

    def test_a_lock_with_a_third_whitelisted_layout_is_not_build_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock = write_lock(
                tmp,
                **{
                    "layouts.entries.openwrt": {
                        "label": "openwrt",
                        "mtdids": "nmbm0=nmbm0",
                        "mtdparts": "nmbm0:1024k(bl2),120M(firmware)",
                        "address_space": "nmbm-logical",
                        "partitions": [],
                    }
                },
            )
            result = run_check(lock)
        self.assertEqual(BUILD_NOT_READY, result.returncode)
        self.assertIn("layout", result.stderr.lower())

    def test_a_lock_that_makes_the_stock_layout_the_default_is_not_build_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock = write_lock(tmp, **{"layouts.default_label": "default"})
            result = run_check(lock)
        self.assertEqual(BUILD_NOT_READY, result.returncode)
        self.assertIn("immortalwrt-112m", result.stderr)

    def test_a_lock_whose_112m_table_is_the_stock_table_is_not_build_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock = write_lock(
                tmp,
                **{"layouts.entries.immortalwrt-112m.mtdparts": self.LAYOUT_STOCK},
            )
            result = run_check(lock)
        self.assertEqual(BUILD_NOT_READY, result.returncode)
        self.assertIn("112M(ubi)", result.stderr)


    def test_a_lock_whose_declared_partitions_disagree_with_its_table_is_not_build_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock = write_lock(
                tmp,
                **{"layouts.entries.immortalwrt-112m.partitions": [
                    {"label": "bl2", "offset": 0, "size": 2097152},
                ]},
            )
            result = run_check(lock)
        self.assertEqual(BUILD_NOT_READY, result.returncode)
        self.assertIn("partition", result.stderr.lower())


class Nx30ProUbootArtifactTests(unittest.TestCase):
    def setUp(self):
        self.helper = load_helper()

    def build_fip(self, directory, bl33_payload=b"U-Boot 2023.07 compiled"):
        entries = [
            (BL31_UUID, b"\x00" * 32),
            (BL33_UUID, bl33_payload),
        ]
        header = struct.pack("<IIQ", TOC_HEADER_NAME, 0x12345678, 0)
        offset = len(header) + 40 * (len(entries) + 1)
        toc = b""
        payloads = b""
        for uuid, payload in entries:
            toc += uuid + struct.pack("<QQQ", offset, len(payload), 0)
            offset += len(payload)
            payloads += payload
        toc += b"\x00" * 16 + struct.pack("<QQQ", offset, 0, 0)
        path = Path(directory) / "fip.bin"
        path.write_bytes(header + toc + payloads)
        return path

    def test_fip_is_identified_by_its_table_of_contents(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.build_fip(tmp)
            info = self.helper.inspect_fip(path)
        self.assertEqual("atf-fip", info["kind"])
        self.assertEqual(2, len(info["components"]))
        self.assertEqual("BL31", info["components"][0]["name"])
        self.assertEqual("BL33", info["components"][1]["name"])
        self.assertIn("U-Boot", info["components"][1]["marker"])

    def test_fip_without_u_boot_is_not_a_boot_loader_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.build_fip(tmp, bl33_payload=b"\x00" * 32)
            with self.assertRaises(Exception):
                self.helper.inspect_fip(path)

    def test_bl2_is_identified_by_the_spi_nand_boot_header(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bl2.bin"
            path.write_bytes(SPIM_NAND_HEADER + b"\x01\x00\x00\x00\x10\x00\x00\x00" + b"\x00" * 64)
            info = self.helper.inspect_bl2(path)
            self.assertEqual("atf-bl2", info["kind"])
            self.assertEqual("SPINAND!", info["header"])
            other = Path(tmp) / "other.bin"
            other.write_bytes(b"SNFI_NAND!" + b"\x00" * 64)
            with self.assertRaises(Exception):
                self.helper.inspect_bl2(other)

    def test_truncated_bl2_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bl2.bin"
            path.write_bytes(SPIM_NAND_HEADER)
            with self.assertRaises(Exception):
                self.helper.inspect_bl2(path)

    def test_fip_component_that_reaches_past_the_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.build_fip(tmp)
            data = bytearray(path.read_bytes())
            # The second entry starts at 16 + 40 and its payload offset lives
            # 16 bytes into the entry.
            struct.pack_into("<Q", data, 16 + 40 + 16, len(data) + 4096)
            path.write_bytes(bytes(data))
            with self.assertRaises(Exception):
                self.helper.inspect_fip(path)

    def test_fip_component_without_payload_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.build_fip(tmp)
            data = bytearray(path.read_bytes())
            struct.pack_into("<Q", data, 16 + 40 + 24, 0)
            path.write_bytes(bytes(data))
            with self.assertRaises(Exception):
                self.helper.inspect_fip(path)

    def test_image_must_fit_its_partition(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.build_fip(tmp)
            with self.assertRaises(Exception):
                self.helper.inspect_fip(path, max_size=16)

    def test_build_report_carries_the_required_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            fip = self.build_fip(tmp)
            bl2 = Path(tmp) / "bl2.bin"
            bl2.write_bytes(SPIM_NAND_HEADER + b"\x01\x00\x00\x00\x10\x00\x00\x00" + b"\x00" * 64)
            report = self.helper.build_report(
                lock=json.loads(LOCK.read_text(encoding="utf-8")),
                artifacts=[
                    {"kind": "fip", "path": str(fip), "partition": "fip", "partition_size": 2097152},
                    {"kind": "bl2", "path": str(bl2), "partition": "bl2", "partition_size": 1048576},
                ],
                toolchain={
                    "version": "aarch64-linux-gnu-gcc (Ubuntu 13.3.0) 13.3.0",
                    "compiler_sha256": "0" * 64,
                    "package_version": "13.3.0-6ubuntu2~24.04",
                },
                build_env={"SOC": "mt7981", "BOARD": "h3c_magic-nx30-pro"},
            )
        for key in ("source_commit", "toolchain", "build_parameters", "partition_table", "artifacts"):
            self.assertIn(key, report)
        self.assertEqual(SOURCE_COMMIT, report["source_commit"])
        self.assertEqual(64, len(report["toolchain"]["compiler_sha256"]))
        self.assertEqual(5, len(report["partition_table"]))
        for artifact in report["artifacts"]:
            self.assertEqual(64, len(artifact["sha256"]))
            self.assertIn("components", artifact)


class Nx30ProUbootEffectiveConfigurationTests(unittest.TestCase):
    """Only the configuration the build really produced proves the feature set.

    Environment variables and defconfig wishes are not evidence: olddefconfig
    drops symbols that no Kconfig knows, and a feature that is merely requested
    can still be absent from the image.
    """

    CONFIG = """CONFIG_TARGET_MT7981=y
CONFIG_DEFAULT_DEVICE_TREE="mt7981-h3c_magic-nx30-pro"
CONFIG_MEDIATEK_MULTI_MTD_LAYOUT=y
CONFIG_MTK_FIXED_MTD_MTDPARTS=y
CONFIG_MTK_DEFAULT_MTD_LAYOUT="immortalwrt-112m"
CONFIG_ENABLE_NAND_NMBM=y
CONFIG_MTK_WEB_FAILSAFE=y
CONFIG_MTK_WEB_FAILSAFE_AFTER_BOOT_FAILURE=y
CONFIG_WEBUI_FAILSAFE=y
CONFIG_WEBUI_FAILSAFE_UI_BOOTSTRAP=y
CONFIG_WEBUI_FAILSAFE_ADVANCED=y
CONFIG_WEBUI_FAILSAFE_BACKUP=y
CONFIG_MTK_DHCPD=y
CONFIG_MTK_DNSD=y
CONFIG_MTK_UBI_SUPPORT=y
CONFIG_MTK_UPGRADE_BL2_VERIFY=y
CONFIG_CMD_TFTPPUT=y
CONFIG_CMD_PING=y
CONFIG_DEBUG_UART=y
CONFIG_MTK_SERIAL=y
# CONFIG_WEBUI_FAILSAFE_FACTORY is not set
# CONFIG_WEBUI_FAILSAFE_FLASH is not set
# CONFIG_WEBUI_FAILSAFE_ENV is not set
# CONFIG_WEBUI_FAILSAFE_CONSOLE is not set
# CONFIG_WEBUI_FAILSAFE_UBI is not set
# CONFIG_WEBUI_FAILSAFE_SIMG is not set
# CONFIG_WEBUI_FAILSAFE_NAND_RAW is not set
# CONFIG_MTK_TELNETD is not set
"""

    DANGEROUS = (
        "CONFIG_WEBUI_FAILSAFE_FACTORY",
        "CONFIG_WEBUI_FAILSAFE_FLASH",
        "CONFIG_WEBUI_FAILSAFE_ENV",
        "CONFIG_WEBUI_FAILSAFE_CONSOLE",
        "CONFIG_WEBUI_FAILSAFE_UBI",
        "CONFIG_WEBUI_FAILSAFE_SIMG",
        "CONFIG_WEBUI_FAILSAFE_NAND_RAW",
        "CONFIG_MTK_TELNETD",
    )

    def setUp(self):
        self.helper = load_helper()
        self.lock = json.loads(LOCK.read_text(encoding="utf-8"))

    def enable(self, text, symbol):
        return text.replace("# %s is not set" % symbol, "%s=y" % symbol)

    def drop(self, text, symbol):
        return text.replace("%s=y\n" % symbol, "")

    def test_the_locked_feature_set_passes_the_effective_configuration_check(self):
        result = self.helper.verify_effective_config(self.CONFIG, self.lock)
        self.assertEqual("immortalwrt-112m", result["default_layout"])
        self.assertEqual(sorted(self.DANGEROUS), sorted(result["disabled"]))

    def test_every_dangerous_web_feature_is_rejected_on_its_own(self):
        for symbol in self.DANGEROUS:
            with self.subTest(symbol=symbol):
                with self.assertRaises(Exception) as caught:
                    self.helper.verify_effective_config(self.enable(self.CONFIG, symbol), self.lock)
                self.assertIn(symbol, str(caught.exception))

    def test_a_configuration_without_the_patched_bootstrap_theme_is_rejected(self):
        # The device patch adds the data loss warning to the bootstrap assets;
        # another theme would ship a layout selector without any warning.
        with self.assertRaises(Exception) as caught:
            self.helper.verify_effective_config(
                self.drop(self.CONFIG, "CONFIG_WEBUI_FAILSAFE_UI_BOOTSTRAP"), self.lock
            )
        self.assertIn("CONFIG_WEBUI_FAILSAFE_UI_BOOTSTRAP", str(caught.exception))

    def test_a_configuration_without_the_advanced_gate_is_rejected(self):
        # The read-only backup page lives behind WEBUI_FAILSAFE_ADVANCED.
        with self.assertRaises(Exception) as caught:
            self.helper.verify_effective_config(
                self.drop(self.CONFIG, "CONFIG_WEBUI_FAILSAFE_ADVANCED"), self.lock
            )
        self.assertIn("CONFIG_WEBUI_FAILSAFE_ADVANCED", str(caught.exception))

    def test_a_configuration_that_lost_the_read_only_backup_is_rejected(self):
        text = self.enable(self.CONFIG, "CONFIG_WEBUI_FAILSAFE_FLASH")
        text = text.replace("CONFIG_WEBUI_FAILSAFE_BACKUP=y\n", "")
        with self.assertRaises(Exception) as caught:
            self.helper.verify_effective_config(text, self.lock)
        self.assertIn("CONFIG_WEBUI_FAILSAFE_BACKUP", str(caught.exception))

    def test_a_configuration_without_dhcpd_or_the_web_failsafe_is_rejected(self):
        for symbol in ("CONFIG_MTK_DHCPD", "CONFIG_MTK_WEB_FAILSAFE"):
            with self.subTest(symbol=symbol):
                with self.assertRaises(Exception):
                    self.helper.verify_effective_config(self.drop(self.CONFIG, symbol), self.lock)

    def test_a_configuration_without_tftp_or_uart_recovery_is_rejected(self):
        for symbol in ("CONFIG_CMD_TFTPPUT", "CONFIG_DEBUG_UART", "CONFIG_MTK_SERIAL"):
            with self.subTest(symbol=symbol):
                with self.assertRaises(Exception):
                    self.helper.verify_effective_config(self.drop(self.CONFIG, symbol), self.lock)

    def test_a_configuration_without_the_bl2_upgrade_check_is_rejected(self):
        with self.assertRaises(Exception):
            self.helper.verify_effective_config(
                self.drop(self.CONFIG, "CONFIG_MTK_UPGRADE_BL2_VERIFY"), self.lock
            )

    def test_a_fallback_to_the_single_layout_configuration_is_rejected(self):
        # build.sh silently downgrades to the single layout defconfig when the
        # multi layout one is missing, and that defconfig carries the stock table.
        text = self.CONFIG.replace("CONFIG_MEDIATEK_MULTI_MTD_LAYOUT=y\n", "")
        text = text.replace(
            'CONFIG_MTK_DEFAULT_MTD_LAYOUT="immortalwrt-112m"\n',
            'CONFIG_MTDPARTS_DEFAULT="nmbm0:1024k(bl2),512k(u-boot-env),2048k(Factory),'
            '2048k(fip),65536k(ubi),6144k(pdt_data),6144k(pdt_data_1),1024k(exp),'
            '38400k(plugin)"\n',
        )
        with self.assertRaises(Exception) as caught:
            self.helper.verify_effective_config(text, self.lock)
        message = str(caught.exception)
        self.assertIn("CONFIG_MEDIATEK_MULTI_MTD_LAYOUT", message)

    def test_a_stock_partition_table_in_the_effective_configuration_is_rejected(self):
        text = self.CONFIG + (
            'CONFIG_MTDPARTS_DEFAULT="nmbm0:1024k(bl2),512k(u-boot-env),2048k(Factory),'
            '2048k(fip),65536k(ubi),6144k(pdt_data),6144k(pdt_data_1),1024k(exp),'
            '38400k(plugin)"\n'
        )
        with self.assertRaises(Exception) as caught:
            self.helper.verify_effective_config(text, self.lock)
        self.assertIn("65536k(ubi)", str(caught.exception))

    def test_an_effective_configuration_that_defaults_to_the_stock_layout_is_rejected(self):
        for replacement in ('CONFIG_MTK_DEFAULT_MTD_LAYOUT="default"', ""):
            text = self.CONFIG.replace(
                'CONFIG_MTK_DEFAULT_MTD_LAYOUT="immortalwrt-112m"\n',
                replacement + ("\n" if replacement else ""),
            )
            with self.subTest(replacement=replacement or "missing"):
                with self.assertRaises(Exception) as caught:
                    self.helper.verify_effective_config(text, self.lock)
                self.assertIn("immortalwrt-112m", str(caught.exception))

    def test_an_overclock_profile_in_the_effective_configuration_is_rejected(self):
        text = self.CONFIG + "CONFIG_MTK_CPU_OVERCLOCK=y\nCONFIG_DRAM_OVERCLOCK_2600=y\n"
        with self.assertRaises(Exception) as caught:
            self.helper.verify_effective_config(text, self.lock)
        self.assertIn("overclock", str(caught.exception).lower())

    def test_the_effective_configuration_of_another_board_is_rejected(self):
        text = self.CONFIG.replace(
            'CONFIG_DEFAULT_DEVICE_TREE="mt7981-h3c_magic-nx30-pro"',
            'CONFIG_DEFAULT_DEVICE_TREE="mt7981_xiaomi_wr30u"',
        )
        with self.assertRaises(Exception):
            self.helper.verify_effective_config(text, self.lock)

    def test_the_command_line_reports_the_effective_configuration(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".config"
            path.write_text(self.CONFIG, encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(HELPER), "verify-config", "--lock", str(LOCK),
                 "--config", str(path)],
                capture_output=True, text=True,
            )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("immortalwrt-112m", result.stdout)


class Nx30ProUbootPatchContractTests(unittest.TestCase):
    """The device patch is the only place the recovery UI may be restricted.

    It must not grow into a second partition editor, an environment editor or a
    third layout, and it has to keep the 112M layout as the default.
    """

    def setUp(self):
        self.helper = load_helper()
        self.lock = json.loads(LOCK.read_text(encoding="utf-8"))
        self.patch_path = ROOT / self.lock["source"]["patches"][0]["path"]
        self.patch = self.patch_path.read_text(encoding="utf-8")

    def verify(self, text, lock=None):
        return self.helper.verify_patch(text, self.lock if lock is None else lock)

    def test_the_device_patch_satisfies_the_patch_contract(self):
        result = self.verify(self.patch)
        self.assertIn("uboot-mtk-20250711/board/mediatek/common/mtd_layout.c", result["files"])
        self.assertIn(
            "uboot-mtk-20250711/configs/mt7981_h3c_magic-nx30-pro_multi_layout_defconfig",
            result["files"],
        )

    def test_the_patch_records_the_commit_it_applies_to(self):
        result = self.verify(self.patch)
        self.assertEqual(SOURCE_COMMIT, result["applies_to_commit"])
        self.assertEqual(
            sorted(self.lock["source"]["patches"][0]["upstream_files"]),
            sorted(result["files"]),
        )

    def test_a_patch_that_adds_a_third_layout_label_is_rejected(self):
        text = self.patch.replace(
            'CONFIG_MTK_DEFAULT_MTD_LAYOUT="immortalwrt-112m"',
            'CONFIG_MTK_DEFAULT_MTD_LAYOUT="immortalwrt-112m"\n+CONFIG_MTD_LAYOUT_EXTRA="openwrt"',
            1,
        )
        with self.assertRaises(Exception) as caught:
            self.verify(text)
        self.assertIn("openwrt", str(caught.exception))

    def test_a_patch_that_re_enables_a_dangerous_feature_is_rejected(self):
        text = self.patch.replace(
            "+# CONFIG_WEBUI_FAILSAFE_ENV is not set",
            "+CONFIG_WEBUI_FAILSAFE_ENV=y",
        )
        with self.assertRaises(Exception) as caught:
            self.verify(text)
        self.assertIn("CONFIG_WEBUI_FAILSAFE_ENV", str(caught.exception))

    def test_a_patch_that_exposes_free_form_mtdparts_is_rejected(self):
        text = self.patch + '\n+\tsetenv mtd_layout_custom "$input"\n'
        with self.assertRaises(Exception) as caught:
            self.verify(text)
        self.assertIn("mtdparts", str(caught.exception).lower())

    def test_a_patch_that_can_write_arbitrary_environment_keys_is_rejected(self):
        text = self.patch + '\n+\tenv_set(name, value);\n'
        with self.assertRaises(Exception) as caught:
            self.verify(text)
        self.assertIn("environment", str(caught.exception).lower())

    def test_a_patch_that_does_not_make_the_112m_layout_the_default_is_rejected(self):
        text = self.patch.replace(
            'CONFIG_MTK_DEFAULT_MTD_LAYOUT="immortalwrt-112m"',
            'CONFIG_MTK_DEFAULT_MTD_LAYOUT="default"',
        )
        with self.assertRaises(Exception) as caught:
            self.verify(text)
        self.assertIn("immortalwrt-112m", str(caught.exception))

    def test_a_patch_that_removes_the_custom_mtdparts_guard_is_rejected(self):
        # A deletion changes the selector too: dropping the guard around
        # mtd_layout_custom would hand back free-form mtdparts editing.
        text = self.patch + '\n-\tif (custom_parts && custom_parts[0] && !custom_seen)\n'
        with self.assertRaises(Exception) as caught:
            self.verify(text)
        self.assertIn("mtdparts", str(caught.exception).lower())

    def test_a_patch_that_removes_an_environment_write_is_rejected(self):
        text = self.patch + '\n-\t\tenv_set(name, value);\n'
        with self.assertRaises(Exception) as caught:
            self.verify(text)
        self.assertIn("environment", str(caught.exception).lower())

    def test_a_patch_that_removes_a_feature_guard_is_rejected(self):
        for guard in ("CONFIG_WEBUI_FAILSAFE_CONSOLE", "CONFIG_MTK_TELNETD"):
            text = self.patch + "\n-#ifdef %s\n" % guard
            with self.subTest(guard=guard):
                with self.assertRaises(Exception) as caught:
                    self.verify(text)
                self.assertIn(guard, str(caught.exception))

    def test_a_patch_that_does_not_warn_before_leaving_the_stock_layout_is_rejected(self):
        without_warning = "\n".join(
            line for line in self.patch.splitlines()
            if "confirm" not in line and "pdt_data" not in line
        )
        with self.assertRaises(Exception) as caught:
            self.verify(without_warning)
        self.assertIn("warn", str(caught.exception).lower())

    def test_a_patch_that_touches_another_device_or_tree_is_rejected(self):
        text = self.patch.replace(
            "uboot-mtk-20250711/board/mediatek/common/mtd_layout.c",
            "uboot-mtk-20230718-09eda825/board/mediatek/common/mtd_layout.c",
        )
        with self.assertRaises(Exception):
            self.verify(text)

    def test_the_command_line_reports_the_patch_contract(self):
        result = subprocess.run(
            [sys.executable, str(HELPER), "verify-patch", "--lock", str(LOCK),
             "--patch", str(self.patch_path)],
            capture_output=True, text=True,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("immortalwrt-112m", result.stdout)

    def test_a_patch_that_does_not_apply_to_the_source_tree_is_rejected(self):
        # Without the real checkout the contract can only be read; with one, the
        # patch has to apply, so an empty directory must be refused.
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(["git", "init", "-q", tmp], check=True)
            with self.assertRaises(Exception):
                self.helper.verify_patch(self.patch, self.lock, source_dir=tmp)


class Nx30ProUbootPreflightTests(unittest.TestCase):
    def setUp(self):
        self.helper = load_helper()
        self.lock = json.loads(LOCK.read_text(encoding="utf-8"))

    def make_repo(self, directory):
        subprocess.run(["git", "init", "-q", str(directory)], check=True)
        subprocess.run(["git", "-C", str(directory), "config", "user.email", "t@example.invalid"], check=True)
        subprocess.run(["git", "-C", str(directory), "config", "user.name", "Test"], check=True)
        (Path(directory) / "file.txt").write_text("content\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(directory), "add", "file.txt"], check=True)
        subprocess.run(["git", "-C", str(directory), "commit", "-q", "-m", "init"], check=True)
        return directory

    def test_preflight_rejects_a_checkout_with_local_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.make_repo(Path(tmp) / "source")
            (Path(repo) / "file.txt").write_text("changed\n", encoding="utf-8")
            with self.assertRaises(Exception):
                self.helper.check_worktree_clean(repo)

    def test_preflight_accepts_the_device_patch_as_the_only_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.make_repo(Path(tmp) / "source")
            target = Path(repo) / "configs" / "board_defconfig"
            target.parent.mkdir(parents=True)
            target.write_text("CONFIG_X=y\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "configs/board_defconfig"], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "config"], check=True)
            target.write_text("CONFIG_X=y\nCONFIG_Y=y\n", encoding="utf-8")
            self.helper.check_worktree_clean(repo, allow_paths=("configs/board_defconfig",))

    def test_preflight_rejects_an_existing_build_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.make_repo(Path(tmp) / "source")
            output = Path(repo) / "output"
            output.mkdir()
            (output / "stale.bin").write_bytes(b"old")
            with self.assertRaises(Exception):
                self.helper.check_output_dir_empty(repo)

    def test_preflight_requires_the_cross_compiler(self):
        with self.assertRaises(Exception):
            self.helper.require_toolchain(lookup=lambda name: None)

    def test_toolchain_identity_records_a_compiler_digest(self):
        identity = self.helper.toolchain_identity(lookup=lambda name: "/usr/bin/true")
        self.assertIn("version", identity)
        self.assertIn("compiler_sha256", identity)
        self.assertEqual(64, len(identity["compiler_sha256"]))


FAKE_BUILD_SH = '''#!/bin/bash
AUTHOR="Yuzhii"
ATF24="atf-20240117-bacca82a8"
ATF25="atf-20250711"
ATF26="atf-20260123"
UBOOT25="uboot-mtk-20250711"
VERSION="${VERSION:-2025}"
VARIANT="${VARIANT:-default}"
case "${VERSION}" in
\t2025)
\t\tUBOOT_DIR="${UBOOT25}"
\t\tATF_DIR="${ATF25}"
\t\t;;
\tSP1|sp1)
\t\tVERSION="SP1"
\t\tUBOOT_DIR="${UBOOT25}"
\t\tATF_DIR="${ATF24}"
\t\t;;
\tSP2|sp2)
\t\tVERSION="SP2"
\t\tUBOOT_DIR="${UBOOT25}"
\t\tATF_DIR="${ATF26}"
\t\t;;
esac
{
\techo "SOC=$SOC"
\techo "BOARD=$BOARD"
\techo "VERSION=$VERSION"
\techo "VARIANT=$VARIANT"
\techo "FIXED_MTDPARTS=$FIXED_MTDPARTS"
\techo "MULTI_LAYOUT=$MULTI_LAYOUT"
\techo "SILENT=$SILENT"
} > build-env.txt
mkdir -p "$UBOOT_DIR" output
cp "$FIXTURE_CONFIG" "$UBOOT_DIR/.config"
cp "$FIXTURE_FIP" "output/$FIXTURE_FIP_NAME"
cp "$FIXTURE_BL2" "output/$FIXTURE_BL2_NAME"
'''

EFFECTIVE_CONFIG = """CONFIG_TARGET_MT7981=y
CONFIG_DEFAULT_DEVICE_TREE="mt7981-h3c_magic-nx30-pro"
CONFIG_MEDIATEK_MULTI_MTD_LAYOUT=y
CONFIG_MTK_FIXED_MTD_MTDPARTS=y
CONFIG_MTK_DEFAULT_MTD_LAYOUT="immortalwrt-112m"
CONFIG_ENABLE_NAND_NMBM=y
CONFIG_MTK_WEB_FAILSAFE=y
CONFIG_MTK_WEB_FAILSAFE_AFTER_BOOT_FAILURE=y
CONFIG_WEBUI_FAILSAFE=y
CONFIG_WEBUI_FAILSAFE_UI_BOOTSTRAP=y
CONFIG_WEBUI_FAILSAFE_ADVANCED=y
CONFIG_WEBUI_FAILSAFE_BACKUP=y
CONFIG_MTK_DHCPD=y
CONFIG_MTK_UBI_SUPPORT=y
CONFIG_MTK_UPGRADE_BL2_VERIFY=y
CONFIG_CMD_TFTPPUT=y
CONFIG_DEBUG_UART=y
CONFIG_MTK_SERIAL=y
# CONFIG_WEBUI_FAILSAFE_FACTORY is not set
# CONFIG_WEBUI_FAILSAFE_FLASH is not set
# CONFIG_WEBUI_FAILSAFE_ENV is not set
# CONFIG_WEBUI_FAILSAFE_CONSOLE is not set
# CONFIG_WEBUI_FAILSAFE_UBI is not set
# CONFIG_WEBUI_FAILSAFE_SIMG is not set
# CONFIG_WEBUI_FAILSAFE_NAND_RAW is not set
# CONFIG_MTK_TELNETD is not set
"""

DANGEROUS_CONFIG = EFFECTIVE_CONFIG.replace(
    "# CONFIG_WEBUI_FAILSAFE_CONSOLE is not set",
    "CONFIG_WEBUI_FAILSAFE_CONSOLE=y",
)

BOARD_DTS = """/dts-v1/;
/ {
\tmodel = "mt7981-h3c_magic-nx30-pro";
\tmtd-layout {
\t\tlayout@0 {
\t\t\tlabel = "default";
\t\t\tmtdids = "nmbm0=nmbm0";
\t\t\tmtdparts = "nmbm0:1024k(bl2),512k(u-boot-env),2048k(Factory),2048k(fip),65536k(ubi),6144k(pdt_data),6144k(pdt_data_1),1024k(exp),38400k(plugin)";
\t\t};
\t\tlayout@1 {
\t\t\tlabel = "immortalwrt-112m";
\t\t\tmtdids = "nmbm0=nmbm0";
\t\t\tmtdparts = "nmbm0:1024k(bl2),512k(u-boot-env),2048k(Factory),2048k(fip),112M(ubi)";
\t\t};
\t};
};
"""

MULTI_LAYOUT_DEFCONFIG = """CONFIG_TARGET_MT7981=y
CONFIG_DEFAULT_DEVICE_TREE="mt7981-h3c_magic-nx30-pro"
CONFIG_MEDIATEK_MULTI_MTD_LAYOUT=y
"""


class Nx30ProUbootOrchestrationTests(unittest.TestCase):
    """End to end gates of build-uboot.sh against a stub of the pinned source.

    The stub carries the structure the real build.sh has, so the orchestration
    is exercised without compiling anything. The steps that need the cross
    compiler are skipped when it is absent; GitHub Actions installs it.
    """

    FIP_NAME = "fip-mt7981_h3c_magic-nx30-pro_SP1-Yuzhii-dhcpd-fixed-parts-multi-layout_md5-%s.bin" % (
        "a" * 32
    )
    BL2_NAME = "bl2-mt7981_h3c_magic-nx30-pro_SP1_md5-%s.img" % ("b" * 32)

    def make_source(self, directory, drop_multi_layout=False):
        source = Path(directory) / "source"
        tree = source / "uboot-mtk-20250711"
        atf = source / "atf-20240117-bacca82a8"
        (tree / "configs").mkdir(parents=True)
        (tree / "arch/arm/dts").mkdir(parents=True)
        (atf / "configs").mkdir(parents=True)
        (source / "build.sh").write_text(FAKE_BUILD_SH, encoding="utf-8")
        (source / "build.sh").chmod(0o755)
        (tree / "configs/mt7981_h3c_magic-nx30-pro_defconfig").write_text(
            MULTI_LAYOUT_DEFCONFIG, encoding="utf-8"
        )
        if not drop_multi_layout:
            (tree / "configs/mt7981_h3c_magic-nx30-pro_multi_layout_defconfig").write_text(
                MULTI_LAYOUT_DEFCONFIG, encoding="utf-8"
            )
        (atf / "configs/mt7981_h3c_magic-nx30-pro_defconfig").write_text(
            "_PLAT_MT7981=y\n", encoding="utf-8"
        )
        (tree / "arch/arm/dts/mt7981-h3c_magic-nx30-pro.dts").write_text(
            BOARD_DTS, encoding="utf-8"
        )
        subprocess.run(["git", "init", "-q", str(source)], check=True)
        subprocess.run(["git", "-C", str(source), "config", "user.email", "t@example.invalid"], check=True)
        subprocess.run(["git", "-C", str(source), "config", "user.name", "Test"], check=True)
        subprocess.run(["git", "-C", str(source), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(source), "commit", "-q", "-m", "pinned"], check=True)
        commit = subprocess.run(
            ["git", "-C", str(source), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        return source, commit

    def make_patch(self, source):
        """Create a device patch that satisfies the recovery contract."""
        target = source / "uboot-mtk-20250711/configs/mt7981_h3c_magic-nx30-pro_multi_layout_defconfig"
        target.write_text(
            MULTI_LAYOUT_DEFCONFIG
            + 'CONFIG_MTK_DEFAULT_MTD_LAYOUT="immortalwrt-112m"\n'
            + "# CONFIG_WEBUI_FAILSAFE_FACTORY is not set\n"
            + "# CONFIG_WEBUI_FAILSAFE_FLASH is not set\n"
            + "# CONFIG_WEBUI_FAILSAFE_CONSOLE is not set\n"
            + "# CONFIG_WEBUI_FAILSAFE_ENV is not set\n"
            + "# CONFIG_WEBUI_FAILSAFE_SIMG is not set\n"
            + "# CONFIG_WEBUI_FAILSAFE_UBI is not set\n"
            + "# CONFIG_MTK_TELNETD is not set\n"
            + "// if (!window.confirm(\"pdt_data, pdt_data_1, exp and plugin are reclaimed\")) return;\n",
            encoding="utf-8",
        )
        patch = subprocess.run(
            ["git", "-C", str(source), "diff"],
            capture_output=True, text=True, check=True,
        ).stdout
        subprocess.run(["git", "-C", str(source), "checkout", "--", "."], check=True)
        return patch

    def prepare(self, tmp, config=None, patch_record=True, drop_multi_layout=False):
        source, commit = self.make_source(tmp, drop_multi_layout=drop_multi_layout)
        patch_text = "" if drop_multi_layout else self.make_patch(source)
        patch_dir = Path(tmp) / "patches"
        patch_dir.mkdir()
        patch_file = patch_dir / "0001-nx30pro-restrict-recovery-ui.patch"
        patch_file.write_text(patch_text, encoding="utf-8")
        changes = {"source.commit": commit}
        if patch_record:
            changes["source.patches"] = [
                {
                    "path": "patches/0001-nx30pro-restrict-recovery-ui.patch",
                    "applies_to_commit": commit,
                    "order": 1,
                    "purpose": "restrict the recovery interface of this device",
                    "upstream_files": [
                        "uboot-mtk-20250711/configs/mt7981_h3c_magic-nx30-pro_multi_layout_defconfig"
                    ],
                }
            ]
        lock = write_lock(tmp, **changes)
        fixtures = Path(tmp) / "fixtures"
        fixtures.mkdir()
        build_fip_image(fixtures / "fip.bin")
        build_bl2_image(fixtures / "bl2.img")
        (fixtures / "config").write_text(
            EFFECTIVE_CONFIG if config is None else config, encoding="utf-8"
        )
        env = dict(os.environ)
        env.update(
            {
                "FIXTURE_CONFIG": str(fixtures / "config"),
                "FIXTURE_FIP": str(fixtures / "fip.bin"),
                "FIXTURE_BL2": str(fixtures / "bl2.img"),
                "FIXTURE_FIP_NAME": self.FIP_NAME,
                "FIXTURE_BL2_NAME": self.BL2_NAME,
                # The stub build does not cross compile, so the toolchain gate
                # resolves the host compiler instead of the locked prefix.
                "TOOLCHAIN": "",
            }
        )
        return source, lock, env

    def run_build(self, lock, source, artifact_dir, env, repo_root=None):
        command = [
            "sh", str(SCRIPT),
            "--lock", str(lock),
            "--source-dir", str(source),
            "--artifact-dir", str(artifact_dir),
        ]
        if repo_root:
            command += ["--repo-root", str(repo_root)]
        return subprocess.run(command, capture_output=True, text=True, env=env)

    def test_check_only_publishes_nothing_and_never_runs_the_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, lock, env = self.prepare(tmp)
            artifact = Path(tmp) / "artifact"
            result = subprocess.run(
                ["sh", str(SCRIPT), "--lock", str(lock), "--check-only",
                 "--artifact-dir", str(artifact)],
                capture_output=True, text=True, env=env,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertFalse((source / "build-env.txt").exists())
            self.assertFalse((artifact / "images").exists())

    def test_a_source_at_the_wrong_revision_is_refused_before_the_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, _lock, env = self.prepare(tmp)
            artifact = Path(tmp) / "artifact"
            result = self.run_build(LOCK, source, artifact, env)
            self.assertNotEqual(0, result.returncode)
            self.assertIn("pins", result.stderr)
            self.assertFalse((source / "build-env.txt").exists())
            self.assertFalse((artifact / "images").exists())

    def test_a_dirty_source_is_refused_before_the_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, lock, env = self.prepare(tmp)
            (source / "build.sh").write_text(FAKE_BUILD_SH + "echo tampered\n", encoding="utf-8")
            artifact = Path(tmp) / "artifact"
            result = self.run_build(lock, source, artifact, env, repo_root=Path(tmp))
            self.assertNotEqual(0, result.returncode)
            self.assertIn("local changes", result.stderr)
            self.assertFalse((source / "build-env.txt").exists())

    def test_a_source_without_the_multi_layout_defconfig_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, lock, env = self.prepare(tmp, drop_multi_layout=True)
            artifact = Path(tmp) / "artifact"
            result = self.run_build(lock, source, artifact, env, repo_root=Path(tmp))
            self.assertNotEqual(0, result.returncode)
            self.assertIn("multi layout", result.stderr.lower())
            self.assertFalse((source / "build-env.txt").exists())

    def test_a_device_patch_that_does_not_apply_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, lock, env = self.prepare(tmp)
            # The recorded patch expects a file the checkout does not carry.
            (source / "uboot-mtk-20250711/configs/mt7981_h3c_magic-nx30-pro_multi_layout_defconfig").write_text(
                "CONFIG_TARGET_MT7981=y\n", encoding="utf-8"
            )
            artifact = Path(tmp) / "artifact"
            result = self.run_build(lock, source, artifact, env, repo_root=Path(tmp))
            self.assertNotEqual(0, result.returncode)
            self.assertFalse((source / "build-env.txt").exists())

    @unittest.skipUnless(HOST_COMPILER, "a host compiler is not installed")
    def test_a_successful_build_publishes_the_candidate_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, lock, env = self.prepare(tmp)
            artifact = Path(tmp) / "artifact"
            result = self.run_build(lock, source, artifact, env, repo_root=Path(tmp))
            self.assertEqual(0, result.returncode, result.stderr)

            recorded = dict(
                line.split("=", 1)
                for line in (source / "build-env.txt").read_text(encoding="utf-8").splitlines()
            )
            self.assertEqual("mt7981", recorded["SOC"])
            self.assertEqual("h3c_magic-nx30-pro", recorded["BOARD"])
            self.assertEqual("SP1", recorded["VERSION"])
            self.assertEqual("default", recorded["VARIANT"])
            self.assertEqual("1", recorded["FIXED_MTDPARTS"])
            self.assertEqual("1", recorded["MULTI_LAYOUT"])
            self.assertEqual("Y", recorded["SILENT"])

            images = sorted(path.name for path in (artifact / "images").iterdir())
            self.assertEqual(sorted([self.FIP_NAME, self.BL2_NAME, "SHA256SUMS"]), images)
            for name in ("build-report.json", "uboot-source-lock.json", "FLASH-TARGETS.txt"):
                self.assertTrue((artifact / name).is_file(), name)
            for name in (
                "preflight.json", "layout-source.json", "device-patch-verify.json",
                "device-patch.json", "build.log", "effective-config.json",
                "artifacts.json", "toolchain.json",
            ):
                self.assertTrue((artifact / "logs" / name).is_file(), name)

            report = json.loads((artifact / "build-report.json").read_text(encoding="utf-8"))
            self.assertEqual(
                json.loads(lock.read_text(encoding="utf-8"))["source"]["commit"],
                report["source_commit"],
            )
            self.assertEqual(64, len(report["toolchain"]["compiler_sha256"]))
            self.assertEqual(5, len(report["partition_table"]))
            self.assertEqual(2, len(report["artifacts"]))
            for entry in report["artifacts"]:
                self.assertEqual(64, len(entry["sha256"]))
            flash_targets = (artifact / "FLASH-TARGETS.txt").read_text(encoding="utf-8")
            self.assertIn("NMBM", flash_targets)
            self.assertNotIn("mtd write", flash_targets)

    @unittest.skipUnless(HOST_COMPILER, "a host compiler is not installed")
    def test_a_dangerous_effective_configuration_stops_the_build_before_publishing(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, lock, env = self.prepare(tmp, config=DANGEROUS_CONFIG)
            artifact = Path(tmp) / "artifact"
            result = self.run_build(lock, source, artifact, env, repo_root=Path(tmp))
            self.assertNotEqual(0, result.returncode)
            self.assertIn("CONFIG_WEBUI_FAILSAFE_CONSOLE", result.stderr)
            self.assertTrue((source / "build-env.txt").exists())
            self.assertFalse((artifact / "images").exists())

    @unittest.skipUnless(HOST_COMPILER, "a host compiler is not installed")
    def test_an_overclock_setting_in_the_built_configuration_stops_the_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, lock, env = self.prepare(
                tmp, config=EFFECTIVE_CONFIG + "CONFIG_MTK_DDR_OVERCLOCK=y\n"
            )
            artifact = Path(tmp) / "artifact"
            result = self.run_build(lock, source, artifact, env, repo_root=Path(tmp))
            self.assertNotEqual(0, result.returncode)
            self.assertIn("overclock", result.stderr.lower())
            self.assertFalse((artifact / "images").exists())


class Nx30ProUbootArtifactGateTests(unittest.TestCase):
    """The output directory is resolved before anything is published.

    A missing, empty, oversized, duplicated or misnamed image stops the build;
    a system image can never be published as a boot loader image.
    """

    def setUp(self):
        self.helper = load_helper()
        self.lock = json.loads(LOCK.read_text(encoding="utf-8"))
        self.fip_name = "fip-mt7981_h3c_magic-nx30-pro_SP1-Yuzhii-dhcpd-fixed-parts-multi-layout_md5-%s.bin" % (
            "a" * 32
        )
        self.bl2_name = "bl2-mt7981_h3c_magic-nx30-pro_SP1_md5-%s.img" % ("b" * 32)

    def fill(self, directory, fip=True, bl2=True):
        output = Path(directory)
        output.mkdir(parents=True, exist_ok=True)
        if fip:
            build_fip_image(output / self.fip_name)
        if bl2:
            build_bl2_image(output / self.bl2_name)
        return output

    def resolve(self, output):
        return self.helper.resolve_artifacts(self.lock, output)

    def test_both_locked_images_are_resolved_by_their_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = self.fill(tmp)
            found = {item["kind"]: item for item in self.resolve(output)}
        self.assertEqual({"fip", "bl2"}, set(found))
        self.assertEqual(self.fip_name, found["fip"]["name"])
        self.assertEqual("fip", found["fip"]["partition"])
        self.assertEqual(2097152, found["fip"]["partition_size"])
        self.assertEqual("bl2", found["bl2"]["partition"])
        self.assertEqual(1048576, found["bl2"]["partition_size"])
        self.assertEqual(64, len(found["bl2"]["sha256"]))

    def test_a_missing_image_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = self.fill(tmp, bl2=False)
            with self.assertRaises(Exception) as caught:
                self.resolve(output)
        self.assertIn("bl2", str(caught.exception).lower())

    def test_an_empty_image_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = self.fill(tmp)
            (output / self.fip_name).write_bytes(b"")
            with self.assertRaises(Exception) as caught:
                self.resolve(output)
        self.assertIn("empty", str(caught.exception).lower())

    def test_a_second_matching_image_is_rejected_as_ambiguous(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = self.fill(tmp)
            other = "fip-mt7981_h3c_magic-nx30-pro_SP1-Yuzhii-dhcpd-fixed-parts-multi-layout_md5-%s.bin" % (
                "c" * 32
            )
            build_fip_image(output / other)
            with self.assertRaises(Exception) as caught:
                self.resolve(output)
        self.assertIn("ambiguous", str(caught.exception).lower())

    def test_an_oversized_image_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = self.fill(tmp)
            build_fip_image(output / self.fip_name, bl33_payload=b"U" * (1048576 * 3))
            with self.assertRaises(Exception) as caught:
                self.resolve(output)
        self.assertIn("fit", str(caught.exception).lower())

    def test_a_system_image_is_not_accepted_as_a_boot_loader_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            (output / "immortalwrt-mediatek-mt7981-h3c_nx30pro_112M-sysupgrade.bin").write_bytes(
                b"\x00" * 4096
            )
            with self.assertRaises(Exception):
                self.resolve(output)

    def test_a_structurally_invalid_fip_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = self.fill(tmp)
            (output / self.fip_name).write_bytes(b"not a fip package at all" * 8)
            with self.assertRaises(Exception):
                self.resolve(output)


if __name__ == "__main__":
    unittest.main()
