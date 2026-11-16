"""Exercise the real packaging script with offline feed/build stand-ins."""
import os
import ipaddress
import io
import tarfile
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from tests.scripts.test_scripts import ROOT, bash_executable, lite_base_config, uci_sections


class LiteBuildEvidenceTests(unittest.TestCase):
    def run_build(self, *, drop_package=False, drop_image_package=False,
                  missing_manifest=False, extra_image_package=None, invalid_image=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo, source, upstream, artifacts, fake_bin = [root / name for name in
                ("repo", "source", "upstream", "artifacts", "bin")]
            for path in (repo / "scripts", repo / "feeds/devices", source / "scripts",
                         upstream / "config", fake_bin):
                path.mkdir(parents=True)
            shutil.copyfile(ROOT / "scripts/build-lite.sh", repo / "scripts/build-lite.sh")
            shutil.copyfile(ROOT / "scripts/verify-image.sh", repo / "scripts/verify-image.sh")
            lock = ROOT / "feeds/devices/tr3000-lite.lock"
            (repo / "feeds/devices/tr3000-lite.lock").write_bytes(lock.read_text().encode("utf-8"))
            (source / ".config").write_text(lite_base_config(), encoding="utf-8")
            (upstream / "config/128muboot.config").write_text("fixture\n", encoding="utf-8")
            (upstream / "LICENSE").write_text("fixture license\n", encoding="utf-8")
            dts = source / "target/linux/mediatek/dts/mt7981b-cudy-tr3000-v1-ubootmod.dts"
            dts.parent.mkdir(parents=True)
            dts.write_text("reg = <0x5c0000 0x7000000>;\n", encoding="utf-8")
            image = source / "bin/targets/mediatek/filogic/test-cudy_tr3000-v1-ubootmod-sysupgrade.bin"
            image.parent.mkdir(parents=True)
            if invalid_image:
                image.write_bytes(b"not a sysupgrade archive\n")
            else:
                with tarfile.open(image, "w") as archive:
                    payload=b"BOARD=cudy_tr3000-v1-ubootmod\n"
                    entry=tarfile.TarInfo("sysupgrade-cudy_tr3000-v1-ubootmod/CONTROL")
                    entry.size=len(payload)
                    archive.addfile(entry, io.BytesIO(payload))
            image_packages=["luci-app-tr3000-lite", "wpad-openssl", "kmod-usb-net",
                            "kmod-usb-net-rndis", "kmod-usb-net-cdc-ether"]
            if drop_image_package:
                image_packages.remove("luci-app-tr3000-lite")
            if extra_image_package:
                image_packages.append(extra_image_package)
            if not missing_manifest:
                (image.parent / "test-cudy_tr3000-v1-ubootmod.manifest").write_text(
                    "".join(f"{name} - 1.0\n" for name in image_packages), encoding="utf-8")
            target_index=image.parent / "packages/Packages.manifest"
            target_index.parent.mkdir()
            target_index.write_text("Package: kmod-usb-net\nVersion: 1.0\n", encoding="utf-8")
            # Runtime private configuration must never be copied into evidence.
            wireless = source / "files/etc/config/wireless"
            wireless.parent.mkdir(parents=True)
            wireless.write_text("option key 'SENSITIVE-FIXTURE-DO-NOT-EXPORT'\n", encoding="utf-8")
            scripts = {
                repo / "scripts/configure-lite.sh": "exit 0\n",
                source / "scripts/feeds": "exit 0\n",
                fake_bin / "make": (
                    "sed '/^CONFIG_PACKAGE_luci-app-tr3000-lite=y$/d' .config > .next && mv .next .config\n"
                    if drop_package else "exit 0\n"),
                fake_bin / "git": """if [ "$1" = clone ]; then mkdir -p "$5/.git"; exit 0; fi
if [ "$3" = rev-parse ]; then
case "$2" in
""" + "".join(f"*/{name}) echo {revision} ;;\n" for name, _, revision in
                    (line.split() for line in lock.read_text().splitlines() if line.strip())) + """*) echo aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa ;;
esac
else echo offline-commit; fi
""",
            }
            for path, body in scripts.items():
                path.write_text("#!/bin/sh\n" + body, encoding="utf-8")
                path.chmod(0o755)
            env = dict(os.environ)
            # Convert the fixture prefix through Bash so Git Bash PATH is POSIX.
            prefix = subprocess.run([bash_executable(), "-c", 'cd "$1" && pwd', "fixture",
                                     fake_bin.as_posix()], capture_output=True, text=True, check=True).stdout.strip()
            env["FIXTURE_BIN"] = prefix
            result = subprocess.run([bash_executable(), "-c",
                'export PATH="$FIXTURE_BIN:$PATH"; exec sh "$@"', "fixture",
                (repo / "scripts/build-lite.sh").as_posix(), "--source-dir", source.as_posix(),
                "--upstream-dir", upstream.as_posix(), "--artifact-dir", artifacts.as_posix()],
                env=env, cwd=ROOT, capture_output=True, text=True)
            evidence = {p.relative_to(artifacts).as_posix(): p.read_text(encoding="utf-8")
                        for p in artifacts.rglob("*") if p.is_file()}
            return result, evidence

    def test_generated_runtime_contract_matches_lite_defaults_without_credentials(self):
        result, evidence = self.run_build()
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("CONFIG_PACKAGE_luci-app-tr3000-lite=y", evidence["selected-packages.txt"].splitlines())
        self.assertIn("lite-runtime-contract.txt", evidence)
        contract = dict(line.split("=", 1) for line in evidence["lite-runtime-contract.txt"].splitlines())
        self.assertEqual("1", contract["schema_version"])
        self.assertEqual("expected-defaults-not-live-state", contract["evidence_kind"])
        configs = ROOT / "overlays/devices/tr3000-lite/files/etc/config"
        network = {s[".name"]: s for s in uci_sections((configs / "network").read_text())}
        policy = uci_sections((configs / "tr3000-lite").read_text())[0]
        self.assertEqual(network["plant"]["device"], contract["plant_device"])
        self.assertEqual(str(ipaddress.IPv4Interface(network["plant"]["ipaddr"] + "/" + network["plant"]["netmask"])), contract["plant_cidr"])
        self.assertEqual(network["mgmt"]["device"], contract["mgmt_device"])
        self.assertEqual(str(ipaddress.IPv4Interface(network["mgmt"]["ipaddr"] + "/" + network["mgmt"]["netmask"])), contract["mgmt_cidr"])
        dhcp = {s[".name"]: s for s in uci_sections((configs / "dhcp").read_text())}
        mgmt_net = ipaddress.IPv4Interface(contract["mgmt_cidr"]).network
        start = int(dhcp["mgmt"]["start"])
        end = start + int(dhcp["mgmt"]["limit"]) - 1
        self.assertEqual(f"{mgmt_net[start]}-{mgmt_net[end]}", contract["mgmt_dhcp_pool"])
        self.assertEqual("1", dhcp["plant"]["ignore"])
        for service in ("dhcpv4", "dhcpv6", "ra", "ndp"):
            self.assertEqual("disabled", dhcp["plant"][service])
        firewall = {s[".name"]: s for s in uci_sections((configs / "firewall").read_text()) if s[".name"]}
        for proto in ("icmp", "tcp"):
            rule = firewall[f"tr3000_lite_mgmt_plant_{proto}"]
            snat = firewall[f"tr3000_lite_mgmt_plant_snat_{proto}"]
            self.assertEqual(contract["allow_mgmt"], rule["enabled"])
            self.assertEqual(str(ipaddress.IPv4Interface(contract["plant_cidr"]).network), rule["dest_ip"])
            self.assertEqual(network["plant"]["ipaddr"], snat["snat_ip"])
            self.assertEqual("SNAT", snat["target"])
        self.assertEqual(contract["allow_luci"], firewall["tr3000_lite_plant_luci"]["enabled"])
        self.assertEqual(contract["plant_https_port"], firewall["tr3000_lite_plant_luci"]["dest_port"])
        for flag in ("allow_luci", "allow_mgmt", "allow_wireguard"):
            self.assertEqual(policy[flag], contract[flag])
        self.assertEqual("luci-app-tr3000-lite", contract["luci_package"])
        self.assertEqual("icmp-echo,tcp", contract["mgmt_to_plant_protocols"])
        self.assertEqual("plant-address", contract["mgmt_to_plant_snat"])
        self.assertEqual("off", contract["plant_dhcpv4_dhcpv6_ra_ndp"])
        self.assertEqual("root-password-and-ap-initialized", contract["plant_https_gate"])
        self.assertNotIn("SENSITIVE-FIXTURE", "\n".join(evidence.values()))
        self.assertIn("firmware/SHA256SUMS", evidence)

    def test_image_manifest_and_verified_profile_are_archived_not_just_target_index(self):
        result, evidence=self.run_build()
        self.assertEqual(0,result.returncode,result.stderr)
        self.assertIn("luci-app-tr3000-lite", evidence.get("packages-manifest.txt", "").splitlines())
        self.assertIn("wpad-openssl", evidence["packages-manifest.txt"].splitlines())
        self.assertIn("luci-app-tr3000-lite - 1.0", evidence["image-packages.manifest"].splitlines())
        self.assertEqual("kmod-usb-net\n",evidence["target-package-index.txt"])
        self.assertEqual("reg = <0x5c0000 0x7000000>;\n",evidence["profile.dts"])
        contract=dict(line.split("=",1) for line in evidence["lite-runtime-contract.txt"].splitlines())
        self.assertEqual("wan,wwan,usbwan",contract["uplink_order"])
        self.assertEqual("10,20,30",contract["uplink_metrics"])
        self.assertEqual("rndis_host,cdc_ether",contract["usb_drivers"])
        settings={s[".name"]:s for s in uci_sections((ROOT / "overlays/devices/tr3000-lite/files/etc/config/lite-uplink-watch").read_text())}
        for option,key in (("interval","uplink_interval_seconds"),("failures","uplink_fail_rounds"),("successes","uplink_recover_rounds")):
            self.assertEqual(settings["globals"][option],contract[key])
        self.assertEqual("/usr/sbin/tr3000-lite-uplink-status",contract["uplink_status"])
        self.assertEqual("/etc/hotplug.d/net/90-tr3000-lite-usbwan",contract["usb_hotplug"])
        self.assertEqual("on-daemon-round",contract["usb_periodic_rescan"])
        self.assertNotIn("SENSITIVE-FIXTURE","\n".join(evidence.values()))

    def test_image_evidence_requires_actual_packages_and_valid_sysupgrade(self):
        for arguments,message in (
            ({"missing_manifest":True},"exactly one image package manifest"),
            ({"drop_image_package":True},"image manifest is missing required package"),
            ({"extra_image_package":"ruby"},"image manifest contains excluded package"),
            ({"extra_image_package":"kmod-usb-net-cdc-ncm"},"unexpected USB network package"),
            ({"invalid_image":True},"readable sysupgrade tar archive")):
            with self.subTest(arguments=arguments):
                result,evidence=self.run_build(**arguments)
                self.assertNotEqual(0,result.returncode)
                self.assertIn(message,result.stderr)
                self.assertNotIn("lite-runtime-contract.txt",evidence)

    def test_final_package_evidence_rejects_missing_lite_luci_package(self):
        result, evidence = self.run_build(drop_package=True)
        self.assertNotEqual(0, result.returncode)
        self.assertIn("final selected packages do not include luci-app-tr3000-lite", result.stderr)
        self.assertNotIn("lite-runtime-contract.txt", evidence)
