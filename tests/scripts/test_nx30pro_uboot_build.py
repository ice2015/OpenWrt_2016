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
    def setUp(self):
        self.helper = load_helper()
        self.lock = json.loads(LOCK.read_text(encoding="utf-8"))
        self.table = self.lock["compatibility"]["minimal_device_patch"]["value"]

    def config(self, table=None, extra=""):
        table = self.table if table is None else table
        return (
            "CONFIG_TARGET_MT7981=y\n"
            'CONFIG_DEFAULT_DEVICE_TREE="mt7981-h3c_magic-nx30-pro"\n'
            "CONFIG_MTK_FIXED_MTD_MTDPARTS=y\n"
            'CONFIG_MTDPARTS_DEFAULT="%s"\n%s' % (table, extra)
        )

    def test_effective_configuration_must_carry_the_112m_partition_table(self):
        self.assertEqual([], self.helper.validate_effective_config(self.config(), self.lock))

    def test_stock_partition_table_in_the_effective_configuration_is_rejected(self):
        stock = (
            "nmbm0:1024k(bl2),512k(u-boot-env),2048k(Factory),2048k(fip),"
            "65536k(ubi),6144k(pdt_data),6144k(pdt_data_1),1024k(exp),38400k(plugin)"
        )
        with self.assertRaises(Exception):
            self.helper.validate_effective_config(self.config(stock), self.lock)

    def test_effective_configuration_without_fixed_mtd_parts_is_rejected(self):
        text = self.config().replace("CONFIG_MTK_FIXED_MTD_MTDPARTS=y\n", "")
        with self.assertRaises(Exception):
            self.helper.validate_effective_config(text, self.lock)

    def test_effective_configuration_of_another_board_is_rejected(self):
        text = self.config().replace(
            'CONFIG_DEFAULT_DEVICE_TREE="mt7981-h3c_magic-nx30-pro"',
            'CONFIG_DEFAULT_DEVICE_TREE="mt7981_wr30u"',
        )
        with self.assertRaises(Exception):
            self.helper.validate_effective_config(text, self.lock)


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


if __name__ == "__main__":
    unittest.main()
