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
        self.assertIn("36916669d0874306638196c5327a20c2ef215bed", result.stdout)

    def test_missing_commit_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock = write_lock(tmp, **{"source.commit": None})
            result = run_check(lock)
        self.assertNotEqual(0, result.returncode)
        self.assertIn("commit", result.stderr)

    def test_branch_name_instead_of_commit_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock = write_lock(tmp, **{"source.commit": "master"})
            result = run_check(lock)
        self.assertNotEqual(0, result.returncode)
        self.assertIn("commit", result.stderr)

    def test_wrong_board_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock = write_lock(tmp, **{"source.build_env.BOARD": "wr30u"})
            result = run_check(lock)
        self.assertNotEqual(0, result.returncode)
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
                toolchain_version="aarch64-linux-gnu-gcc (Ubuntu 13.3.0) 13.3.0",
                build_env={"SOC": "mt7981", "BOARD": "h3c_magic-nx30-pro"},
            )
        for key in ("source_commit", "toolchain_version", "build_parameters", "partition_table", "artifacts"):
            self.assertIn(key, report)
        self.assertEqual(
            "36916669d0874306638196c5327a20c2ef215bed",
            report["source_commit"],
        )
        self.assertEqual(5, len(report["partition_table"]))
        for artifact in report["artifacts"]:
            self.assertEqual(64, len(artifact["sha256"]))
            self.assertIn("components", artifact)


if __name__ == "__main__":
    unittest.main()
