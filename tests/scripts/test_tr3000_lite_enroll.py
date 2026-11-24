"""Unit tests for on-device staging and enrollment tool tr3000-lite-enroll.sh."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from tests.scripts.test_scripts import ROOT, bash_executable

SCRIPT = ROOT / "devices/tr3000/lite/runtime/tr3000-lite-enroll.sh"

FAKE_TOOLS = r'''
import base64, hashlib, json, os, pathlib, sys

root = pathlib.Path(os.environ['ENROLL_FIXTURE'])
cmd = sys.argv[1]; args = sys.argv[2:]

if cmd == 'wg':
    sub = args[0]
    if sub == 'genkey':
        # Generate 32 bytes and base64 encode
        key = base64.b64encode(os.urandom(32)).decode()
        print(key)
        sys.exit(0)
    elif sub == 'pubkey':
        priv = sys.stdin.read().strip()
        # Deterministic dummy pubkey from priv
        h = hashlib.sha256(priv.encode()).digest()
        pub = base64.b64encode(h[:32]).decode()
        print(pub)
        sys.exit(0)
    elif sub == 'show':
        # wg show wg_vps latest-handshakes
        if 'latest-handshakes' in args:
            print("x5yp9v7tZ09Z10q/4+KjL18v79Z810q4+KjL18v79Z8=\t1700000000")
            sys.exit(0)
        sys.exit(0)
    sys.exit(0)
elif cmd == 'tr3000-lite-remote':
    if args == ['status', '--json']:
        st = {
            "schema_version": 1,
            "enrolled": (root / "etc/tr3000-lite/enrolled").is_file(),
            "gates": {
                "root_password": True,
                "ap_initialized": True,
                "identity": True,
                "keys": True
            },
            "checks": {"result": "ok"},
            "degraded": False
        }
        if os.environ.get("MOCK_REMOTE_GATE_FAIL"):
            st["gates"]["root_password"] = False
            st["checks"]["result"] = "root_password_empty"
        print(json.dumps(st))
        sys.exit(0)
    sys.exit(0)
elif cmd == 'jsonfilter':
    import re
    data = open(args[args.index('-i')+1]).read() if '-i' in args else (args[args.index('-s')+1] if '-s' in args else sys.stdin.read())
    value = json.loads(data); expr = args[args.index('-e')+1]
    tokens = re.findall(r'\.([A-Za-z0-9_-]+)|\["([^"]+)"\]|\[\'([^\']+)\'\]|\[([0-9]+)\]', expr)
    try:
        for t in tokens:
            k = next(x for x in t if x)
            value = value[int(k)] if k.isdigit() else value[k]
        print(value if not isinstance(value, (dict, list)) else json.dumps(value))
        sys.exit(0)
    except Exception:
        sys.exit(1)
elif cmd == 'uci':
    # Stub uci
    sys.exit(0)
'''


class EnrollTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "etc/tr3000-lite").mkdir(parents=True, mode=0o700)
        (self.root / "etc/config").mkdir(parents=True, mode=0o755)
        (self.root / "bin").mkdir(parents=True)

        fake_py = self.root / "fake.py"
        fake_py.write_text(FAKE_TOOLS)
        for tool in ("wg", "tr3000-lite-remote", "uci", "jsonfilter"):
            p = self.root / "bin" / tool
            p.write_text(f"#!/bin/sh\nexec {sys.executable} {fake_py} {tool} \"$@\"\n")
            p.chmod(0o755)

        self.env = dict(os.environ)
        self.env["ENROLL_FIXTURE"] = str(self.root)
        self.env["ENROLL_ROOT"] = str(self.root)
        self.env["PATH"] = f"{self.root/'bin'}:{self.env.get('PATH', '')}"

    def tearDown(self):
        self.tmp.cleanup()

    def run_enroll(self, *args, code=0):
        cmd = [bash_executable(), str(SCRIPT), *args]
        proc = subprocess.run(cmd, env=self.env, capture_output=True, text=True)
        self.assertEqual(code, proc.returncode, f"stdout: {proc.stdout}\nstderr: {proc.stderr}")
        return proc

    def test_prepare_generates_keys_and_returns_public_facts(self):
        proc = self.run_enroll("prepare", "--device-id", "device-01", "--json")
        data = json.loads(proc.stdout)
        self.assertEqual(1, data["schema_version"])
        self.assertEqual("device-01", data["device_id"])
        self.assertFalse(data["enrolled"])
        self.assertIn("direct", data["public_keys"])
        self.assertIn("vps", data["public_keys"])

        # Check private keys on disk
        kdir = self.root / "etc/tr3000-lite/keys"
        self.assertTrue((kdir / "direct.key").is_file())
        self.assertTrue((kdir / "vps.key").is_file())
        self.assertEqual(0o600, (kdir / "direct.key").stat().st_mode & 0o777)
        self.assertEqual(0o600, (kdir / "vps.key").stat().st_mode & 0o777)

        # Idempotent: run again with same ID retains keys
        proc2 = self.run_enroll("prepare", "--device-id", "device-01", "--json")
        data2 = json.loads(proc2.stdout)
        self.assertEqual(data["public_keys"], data2["public_keys"])

    def test_prepare_rejects_invalid_device_id(self):
        self.run_enroll("prepare", "--device-id", "invalid id/with/slash", code=2)

    def test_prepare_refuses_when_already_enrolled(self):
        (self.root / "etc/tr3000-lite/enrolled").write_text("1\n")
        self.run_enroll("prepare", "--device-id", "device-01", code=1)

    def test_apply_verifies_manifest_and_applies(self):
        # Prepare first
        self.run_enroll("prepare", "--device-id", "device-01")
        # Create a mock bundle
        bundle_dir = self.root / "bundle"
        bundle_dir.mkdir(mode=0o700)
        conf_file = bundle_dir / "ddns"
        conf_file.write_text("config ddns\n")
        conf_file.chmod(0o600)

        import hashlib
        sha = hashlib.sha256(b"config ddns\n").hexdigest()
        manifest = {
            "schema_version": 1,
            "device_id": "device-01",
            "files": {
                "ddns": {"sha256": sha}
            }
        }
        manifest_file = bundle_dir / "manifest.json"
        manifest_file.write_text(json.dumps(manifest))
        manifest_file.chmod(0o600)

        proc = self.run_enroll("apply", "--bundle", str(bundle_dir), "--json")
        data = json.loads(proc.stdout)
        self.assertTrue(data.get("success"))

    def test_apply_rejects_corrupted_manifest_hash(self):
        self.run_enroll("prepare", "--device-id", "device-01")
        bundle_dir = self.root / "bundle"
        bundle_dir.mkdir(mode=0o700)
        conf_file = bundle_dir / "ddns"
        conf_file.write_text("tampered content\n")
        conf_file.chmod(0o600)

        manifest = {
            "schema_version": 1,
            "device_id": "device-01",
            "files": {
                "ddns": {"sha256": "badhash"}
            }
        }
        (bundle_dir / "manifest.json").write_text(json.dumps(manifest))
        self.run_enroll("apply", "--bundle", str(bundle_dir), code=1)

    def test_verify_checks_gates_and_marks_enrolled(self):
        self.run_enroll("prepare", "--device-id", "device-01")
        (self.root / "etc/tr3000-lite/management-ap.initialized").touch()
        proc = self.run_enroll("verify", "--json")
        data = json.loads(proc.stdout)
        self.assertTrue(data.get("verified"))
        self.assertTrue(data.get("enrolled"))
        self.assertTrue((self.root / "etc/tr3000-lite/enrolled").is_file())


if __name__ == "__main__":
    unittest.main()
