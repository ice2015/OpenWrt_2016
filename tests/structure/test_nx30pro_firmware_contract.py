"""Contract for the NX30 Pro firmware source lock and device layer.

The lock is the only thing that ties a firmware build to a verified upstream
revision and to the feed revisions it consumed. These tests keep the commit
and the feeds pinned, keep the partition contract equal to the one the boot
loader uses, keep the package table honest about what this base really has,
and keep the device layer from touching another target.
"""

import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEVICE = ROOT / "devices" / "nx30pro"
LOCK = DEVICE / "source-lock.json"
CONFIG = DEVICE / "config.config"
FEEDS = DEVICE / "feeds.conf"
MANIFEST = ROOT / "manifests" / "devices" / "nx30pro.json"
SOURCES = ROOT / "manifests" / "sources.json"
COMPATIBILITY_DOC = DEVICE / "docs" / "nx30pro-firmware-compatibility.md"
VALIDATION_DOC = DEVICE / "docs" / "nx30pro-firmware-install-and-validation.md"

COMMIT = re.compile(r"^[0-9a-f]{40}$")

EXPECTED_PACKAGES = (
    "luci-app-passwall",
    "sing-box",
    "cloudflared",
    "wireguard",
    "ddns-scripts",
    "tailscale",
    "zerotier",
    "docker",
    "argon",
    "bootstrap",
    "zh-cn",
)


class Nx30ProFirmwareSourceLockTests(unittest.TestCase):
    def load_lock(self):
        self.assertTrue(LOCK.is_file(), "missing NX30 Pro source lock: %s" % LOCK)
        return json.loads(LOCK.read_text(encoding="utf-8"))

    def test_lock_pins_the_source_and_every_feed(self):
        lock = self.load_lock()
        source = lock["source"]
        self.assertRegex(source["revision"], COMMIT)
        self.assertTrue(source["repository"].startswith("https://"))
        self.assertEqual("5.4", source["kernel"])
        feeds = {feed["id"]: feed for feed in lock["feeds"]}
        for feed_id in ("packages", "luci", "routing", "telephony"):
            self.assertIn(feed_id, feeds)
            self.assertRegex(feeds[feed_id]["revision"], COMMIT)
            self.assertTrue(feeds[feed_id]["repository"].startswith("https://"))

    def test_lock_records_the_target_profile_and_the_image_rules(self):
        lock = self.load_lock()
        target = lock["target"]
        self.assertEqual("mediatek", target["target"])
        self.assertEqual("mt7981", target["subtarget"])
        self.assertEqual("h3c_nx30pro_112M", target["profile"])
        self.assertEqual(
            "CONFIG_TARGET_mediatek_mt7981_DEVICE_h3c_nx30pro_112M=y",
            target["profile_symbol"],
        )
        image = lock["image"]
        self.assertEqual(110592, image["image_size_kib"])
        self.assertEqual("factory.bin", image["factory_image"])
        self.assertEqual("sysupgrade.bin", image["sysupgrade_image"])

    def test_lock_uses_the_same_partition_contract_as_the_boot_loader(self):
        lock = self.load_lock()
        uboot_lock = json.loads(
            (DEVICE / "uboot" / "uboot-source-lock.json").read_text(encoding="utf-8")
        )
        firmware = [
            (entry["label"], entry["offset"], entry["size"])
            for entry in lock["partition_contract"]["partitions"]
        ]
        boot_loader = [
            (entry["label"], entry["offset"], entry["size"])
            for entry in uboot_lock["partition_contract"]["partitions"]
        ]
        self.assertEqual(boot_loader, firmware)

    def test_package_table_covers_every_requirement_and_states_the_gaps(self):
        lock = self.load_lock()
        packages = lock["packages"]
        self.assertTrue(packages)
        joined = " ".join(
            "%s %s %s" % (entry.get("requirement", ""), entry.get("package", ""), entry.get("detail", ""))
            for entry in packages
        )
        for expected in EXPECTED_PACKAGES:
            self.assertIn(expected, joined, expected)
        for entry in packages:
            self.assertIn(entry["status"], ("available", "partial", "unavailable"))
            self.assertTrue(entry.get("requirement"))
            if entry["status"] != "available":
                self.assertTrue(entry.get("detail"), entry.get("package"))
        unavailable = [
            entry["package"]
            for entry in packages
            if entry["status"] == "unavailable"
        ]
        self.assertTrue(any("sing-box" in name for name in unavailable), unavailable)
        self.assertTrue(any("wireguard" in name for name in unavailable), unavailable)

    def test_excluded_packages_carry_a_reason(self):
        lock = self.load_lock()
        excluded = lock["excluded_packages"]
        self.assertTrue(excluded)
        names = set()
        for entry in excluded:
            self.assertTrue(entry.get("package"))
            self.assertTrue(entry.get("reason"), entry.get("package"))
            names.add(entry["package"])
        for name in ("sing-box", "luci-app-openclash", "ruby", "libruby"):
            self.assertIn(name, names)

    def test_unresolved_items_stay_listed(self):
        lock = self.load_lock()
        self.assertTrue(lock["unresolved"])
        for item in lock["unresolved"]:
            self.assertTrue(item.get("topic"))
            self.assertEqual("UNRESOLVED", item.get("status"))


class Nx30ProFirmwareDeviceLayerTests(unittest.TestCase):
    def test_device_config_selects_only_this_target_and_profile(self):
        text = CONFIG.read_text(encoding="utf-8")
        targets = [
            line
            for line in text.splitlines()
            if line.startswith("CONFIG_TARGET_")
        ]
        self.assertTrue(targets)
        for line in targets:
            self.assertTrue(line.startswith("CONFIG_TARGET_mediatek"), line)
        self.assertIn(
            "CONFIG_TARGET_mediatek_mt7981_DEVICE_h3c_nx30pro_112M=y",
            text,
        )

    def test_device_config_requires_the_packages_of_the_requirement_table(self):
        text = CONFIG.read_text(encoding="utf-8")
        for symbol in (
            "CONFIG_PACKAGE_luci-app-passwall=y",
            "CONFIG_PACKAGE_luci-app-passwall_INCLUDE_Xray=y",
            "CONFIG_PACKAGE_xray-core=y",
            "CONFIG_PACKAGE_cloudflared=y",
            "CONFIG_PACKAGE_ddns-scripts=y",
            "CONFIG_PACKAGE_luci-app-ddns=y",
            "CONFIG_PACKAGE_tailscale=y",
            "CONFIG_PACKAGE_zerotier=y",
            "CONFIG_PACKAGE_luci-app-zerotier=y",
            "CONFIG_PACKAGE_dockerd=y",
            "CONFIG_PACKAGE_luci-app-docker=y",
            "CONFIG_PACKAGE_fuse-overlayfs=y",
            "CONFIG_PACKAGE_luci-theme-argon=y",
            "CONFIG_PACKAGE_luci-theme-bootstrap=y",
            "CONFIG_PACKAGE_luci-i18n-base-zh-cn=y",
        ):
            self.assertIn(symbol, text, symbol)

    def test_device_config_excludes_the_documented_packages(self):
        text = CONFIG.read_text(encoding="utf-8")
        for symbol in (
            "# CONFIG_PACKAGE_sing-box is not set",
            "# CONFIG_PACKAGE_luci-app-openclash is not set",
            "# CONFIG_PACKAGE_luci-app-wireguard is not set",
            "# CONFIG_PACKAGE_ruby is not set",
            "# CONFIG_PACKAGE_libruby is not set",
        ):
            self.assertIn(symbol, text, symbol)

    def test_feed_layer_matches_the_locked_feed_revisions(self):
        lock = json.loads(LOCK.read_text(encoding="utf-8"))
        text = FEEDS.read_text(encoding="utf-8")
        for feed in lock["feeds"]:
            self.assertIn(feed["revision"], text, feed["id"])
            self.assertIn(feed["repository"], text, feed["id"])

    def test_device_patch_carries_the_mac_provisioning(self):
        patches = sorted((DEVICE / "patches").glob("*.patch"))
        self.assertTrue(patches)
        text = patches[0].read_text(encoding="utf-8")
        self.assertIn("pdt_data_1", text)
        self.assertIn("/etc/nx30pro/wan-mac", text)
        self.assertIn("02_network", text)

    def test_overlay_keeps_every_service_switched_off(self):
        defaults = DEVICE / "files" / "etc" / "uci-defaults" / "90-nx30pro-defaults"
        self.assertTrue(defaults.is_file(), "missing NX30 Pro first boot defaults")
        text = defaults.read_text(encoding="utf-8")
        for service in ("passwall", "ddns", "tailscale", "zerotier", "docker"):
            self.assertRegex(text, r"uci -q set %s\.enabled='0'" % service, service)
        self.assertIn("/etc/nx30pro", text)

    def test_manifest_registers_the_device_with_its_own_source(self):
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual("nx30pro", manifest["id"])
        self.assertEqual(["immortalwrt-mt798x"], manifest["supported_distributions"])
        self.assertEqual("mediatek", manifest["target"])
        self.assertEqual("mt7981", manifest["subtarget"])
        self.assertEqual("h3c_nx30pro_112M", manifest["profile"])
        self.assertEqual(["devices/nx30pro/config.config"], manifest["config_layers"])
        self.assertEqual(["devices/nx30pro/feeds.conf"], manifest["feed_layers"])

        sources = json.loads(SOURCES.read_text(encoding="utf-8"))
        source = {entry["id"]: entry for entry in sources["sources"]}
        self.assertIn("immortalwrt-mt798x", source)
        lock = json.loads(LOCK.read_text(encoding="utf-8"))
        self.assertEqual(lock["source"]["revision"], source["immortalwrt-mt798x"]["revision"])
        self.assertEqual(lock["source"]["repository"], source["immortalwrt-mt798x"]["repository"])


class Nx30ProFirmwareDocumentTests(unittest.TestCase):
    def test_compatibility_document_states_the_facts_and_the_gaps(self):
        self.assertTrue(
            COMPATIBILITY_DOC.is_file(),
            "missing NX30 Pro firmware compatibility document: %s" % COMPATIBILITY_DOC,
        )
        text = COMPATIBILITY_DOC.read_text(encoding="utf-8")
        for topic in ("UNRESOLVED", "候选", "h3c_nx30pro_112M", "pdt_data_1", "sing-box"):
            self.assertIn(topic, text)
        self.assertNotIn("真机验证通过", text)

    def test_validation_document_plans_the_device_test_without_authorizing_a_flash(self):
        self.assertTrue(
            VALIDATION_DOC.is_file(),
            "missing NX30 Pro firmware validation document: %s" % VALIDATION_DOC,
        )
        text = VALIDATION_DOC.read_text(encoding="utf-8")
        for topic in ("备份", "回退", "验证", "UNRESOLVED", "授权", "wan-mac"):
            self.assertIn(topic, text)
        for forbidden in ("mtd write", "nandwrite", "flash_erase", "dd of="):
            self.assertNotIn(forbidden, text)


if __name__ == "__main__":
    unittest.main()
