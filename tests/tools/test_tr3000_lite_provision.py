"""Unit tests for offline inventory validation and provisioning bundle rendering."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tests.scripts.test_scripts import ROOT

PROVISION_TOOL = ROOT / "tools/tr3000_lite_provision.py"


def valid_inventory():
    return {
        "schema_version": 1,
        "customer": "factory-a",
        "devices": [
            {
                "device_id": "tr3000-cell-01",
                "ddns_hostname": "cell01.example.org",
                "direct_address": "10.10.1.1/32",
                "direct_listen_port": 51820,
                "vps_address": "10.20.1.2/32",
                "vps_endpoint": "vps.example.com:51820",
                "vps_public_key": "x5yp9v7tZ09Z10q/4+KjL18v79Z810q4+KjL18v79Z8=",
                "plant_cidr": "192.168.10.0/24",
                "device_public_keys": {
                    "direct": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
                    "vps": "BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB=",
                },
                "remote_peers": [
                    {
                        "name": "engineer-laptop",
                        "public_key": "CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC=",
                        "allowed_ips": ["10.10.1.10/32"],
                    }
                ],
                "vps_remote_peers": [
                    {
                        "name": "engineer-laptop",
                        "public_key": "CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC=",
                        "allowed_ips": ["10.20.1.10/32"],
                    }
                ],
            },
            {
                "device_id": "tr3000-cell-02",
                "ddns_hostname": "cell02.example.org",
                "direct_address": "10.10.2.1/32",
                "direct_listen_port": 51821,
                "vps_address": "10.20.2.2/32",
                "vps_endpoint": "vps.example.com:51820",
                "vps_public_key": "x5yp9v7tZ09Z10q/4+KjL18v79Z810q4+KjL18v79Z8=",
                "plant_cidr": "192.168.20.0/24",
                "device_public_keys": {
                    "direct": "DDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDD=",
                    "vps": "EEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEE=",
                },
                "remote_peers": [
                    {
                        "name": "engineer-laptop-2",
                        "public_key": "FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF=",
                        "allowed_ips": ["10.10.2.10/32"],
                    }
                ],
                "vps_remote_peers": [
                    {
                        "name": "engineer-laptop-2",
                        "public_key": "FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF=",
                        "allowed_ips": ["10.20.2.10/32"],
                    }
                ],
            },
        ],
    }


class ProvisionToolTests(unittest.TestCase):
    def run_tool(self, *args, check=True):
        cmd = [sys.executable, str(PROVISION_TOOL), *args]
        return subprocess.run(cmd, capture_output=True, text=True, check=check)

    def test_valid_inventory_passes_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            inv_file = Path(tmp) / "inventory.json"
            inv_file.write_text(json.dumps(valid_inventory()))
            proc = self.run_tool("validate", "--inventory", str(inv_file))
            self.assertEqual(0, proc.returncode)
            # Ensure no secret in output
            self.assertNotIn("PRIVATE", proc.stdout)

    def test_duplicate_device_id_fails_validation(self):
        inv = valid_inventory()
        inv["devices"][1]["device_id"] = "tr3000-cell-01"
        with tempfile.TemporaryDirectory() as tmp:
            inv_file = Path(tmp) / "inventory.json"
            inv_file.write_text(json.dumps(inv))
            proc = self.run_tool("validate", "--inventory", str(inv_file), check=False)
            self.assertNotEqual(0, proc.returncode)
            self.assertIn("duplicate device_id", proc.stderr.lower())

    def test_duplicate_hostname_fails_validation(self):
        inv = valid_inventory()
        inv["devices"][1]["ddns_hostname"] = "cell01.example.org"
        with tempfile.TemporaryDirectory() as tmp:
            inv_file = Path(tmp) / "inventory.json"
            inv_file.write_text(json.dumps(inv))
            proc = self.run_tool("validate", "--inventory", str(inv_file), check=False)
            self.assertNotEqual(0, proc.returncode)
            self.assertIn("duplicate ddns_hostname", proc.stderr.lower())

    def test_wide_route_fails_validation(self):
        inv = valid_inventory()
        inv["devices"][0]["remote_peers"][0]["allowed_ips"] = ["10.10.1.0/24"]
        with tempfile.TemporaryDirectory() as tmp:
            inv_file = Path(tmp) / "inventory.json"
            inv_file.write_text(json.dumps(inv))
            proc = self.run_tool("validate", "--inventory", str(inv_file), check=False)
            self.assertNotEqual(0, proc.returncode)
            self.assertIn("/32", proc.stderr.lower())

    def test_render_creates_bundle_manifest_and_templates(self):
        with tempfile.TemporaryDirectory() as tmp:
            inv_file = Path(tmp) / "inventory.json"
            inv_file.write_text(json.dumps(valid_inventory()))
            out_dir = Path(tmp) / "output"
            proc = self.run_tool("render", "--inventory", str(inv_file), "--device-id", "tr3000-cell-01", "--output", str(out_dir))
            self.assertEqual(0, proc.returncode)

            # Check bundle directory and manifest
            bundle_dir = out_dir / "bundle"
            self.assertTrue(bundle_dir.is_dir())
            manifest_file = bundle_dir / "manifest.json"
            self.assertTrue(manifest_file.is_file())
            manifest = json.loads(manifest_file.read_text())
            self.assertEqual(1, manifest["schema_version"])
            self.assertEqual("tr3000-cell-01", manifest["device_id"])
            self.assertIn("files", manifest)

            # Check bundle mode permissions
            self.assertEqual(0o700, bundle_dir.stat().st_mode & 0o777)
            for f in bundle_dir.iterdir():
                self.assertEqual(0o600, f.stat().st_mode & 0o777)

            # Check VPS snippet
            vps_snippet = out_dir / "vps" / "peer.conf"
            self.assertTrue(vps_snippet.is_file())
            vps_text = vps_snippet.read_text()
            self.assertIn("[Peer]", vps_text)
            self.assertIn("BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB=", vps_text)
            self.assertIn("10.20.1.2/32", vps_text)

            # Check Windows client templates
            win_dir = out_dir / "windows"
            direct_conf = win_dir / "TR3000-tr3000-cell-01-Direct.conf"
            vps_conf = win_dir / "TR3000-tr3000-cell-01-VPS.conf"
            self.assertTrue(direct_conf.is_file())
            self.assertTrue(vps_conf.is_file())

            direct_text = direct_conf.read_text()
            self.assertIn("exclusive_group=tr3000-cell-01", direct_text)
            self.assertIn("10.10.1.1/32, 192.168.10.0/24", direct_text)
            self.assertNotIn("0.0.0.0/0", direct_text)
            self.assertIn("PrivateKey = <CLIENT_PRIVATE_KEY_FILL_LOCALLY>", direct_text)

            vps_text = vps_conf.read_text()
            self.assertIn("exclusive_group=tr3000-cell-01", vps_text)
            self.assertIn("10.20.1.2/32, 192.168.10.0/24", vps_text)
            self.assertNotIn("0.0.0.0/0", vps_text)


if __name__ == "__main__":
    unittest.main()
