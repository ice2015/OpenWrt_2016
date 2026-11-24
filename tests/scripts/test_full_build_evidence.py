"""The Full build must gate on the home-router contract before compiling."""
import ipaddress
import re
import unittest

from tests.scripts.test_scripts import ROOT, uci_sections

BUILD = ROOT / "devices/tr3000/build/build-full.sh"
OVERLAY = ROOT / "devices/tr3000/full/files/etc/config"


def contract_fields() -> dict:
    text = BUILD.read_text(encoding="utf-8")
    match = re.search(
        r"cat > \"\$ARTIFACT_DIR/full-runtime-contract\.txt\" <<'EOF'\n(.*?)\nEOF",
        text, re.S)
    if not match:
        return {}
    fields = {}
    for line in match.group(1).splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            fields[key] = value
    return fields


class FullBuildEvidenceTests(unittest.TestCase):
    def test_build_full_asserts_the_overlay_before_compiling(self) -> None:
        text = BUILD.read_text(encoding="utf-8")
        for token in ("config interface 'lan'", "option ipaddr '192.168.10.1'",
                      "config device 'br_lan'", "list ports 'eth1'", "config dhcp 'lan'"):
            self.assertIn(token, text)
        self.assertIn("must not ship a wireless configuration", text)
        # The overlay gate must run before any source download or compile.
        self.assertLess(text.index("config interface 'lan'"), text.index("make download"))

    def test_full_runtime_contract_matches_the_overlay(self) -> None:
        fields = contract_fields()
        self.assertEqual("1", fields.get("schema_version"))
        self.assertEqual("expected-defaults-not-live-state", fields.get("evidence_kind"))
        network = {s[".name"]: s for s in uci_sections((OVERLAY / "network").read_text(encoding="utf-8"))}
        lan = network["lan"]
        prefix = ipaddress.IPv4Network(f"0.0.0.0/{lan['netmask']}").prefixlen
        self.assertEqual(f"{lan['ipaddr']}/{prefix}", fields.get("lan_cidr"))
        self.assertNotIn("plant", network)
        self.assertNotIn("mgmt", network)
        self.assertEqual("absent", fields.get("plant_segment"))
        dhcp = {s[".name"]: s for s in uci_sections((OVERLAY / "dhcp").read_text(encoding="utf-8"))}
        base = int(ipaddress.IPv4Address(lan["ipaddr"])) & int(ipaddress.IPv4Address(lan["netmask"]))
        start = base + int(dhcp["lan"]["start"])
        end = start + int(dhcp["lan"]["limit"]) - 1
        self.assertEqual(f"{ipaddress.IPv4Address(start)}-{ipaddress.IPv4Address(end)}",
                         fields.get("lan_dhcp_pool"))
        metrics = ",".join(network[name]["metric"] for name in ("wan", "wwan", "usbwan"))
        self.assertEqual(metrics, fields.get("uplink_metrics"))
        self.assertEqual("wan,wwan,usbwan", fields.get("uplink_order"))
        self.assertEqual("mt_wifi", fields.get("wireless_stack"))
        self.assertEqual("lan", fields.get("management_ap_network"))
        self.assertEqual("psk2", fields.get("management_ap_encryption"))
        self.assertEqual("disabled", fields.get("management_ap_default_open_ap"))
        self.assertEqual("sing-box", fields.get("proxy_engine"))
        self.assertEqual("homeproxy", fields.get("proxy_ui"))
        self.assertEqual("disabled", fields.get("proxy_default"))
        self.assertEqual("disabled", fields.get("tunnel_default"))
        self.assertEqual("0", fields.get("wg_listener_default"))
        self.assertEqual("present", fields.get("wg_to_lan_forwarding"))
        self.assertEqual("cloudflare.com-v4", fields.get("ddns_provider_default"))
        self.assertEqual("disabled", fields.get("ddns_default"))
        self.assertEqual("argon", fields.get("luci_theme_default"))
        self.assertEqual("bootstrap", fields.get("luci_theme_fallback"))
        self.assertEqual("off", fields.get("wan_management"))
        # The DDNS template really is Cloudflare-first and disabled.
        ddns = {s[".name"]: s for s in uci_sections((OVERLAY / "ddns").read_text(encoding="utf-8"))}
        self.assertEqual(fields["ddns_provider_default"], ddns["cloudflare_v4"]["service_name"])
        self.assertEqual("0", ddns["cloudflare_v4"]["enabled"])

    def test_image_size_gate_is_unchanged(self) -> None:
        text = (ROOT / "devices/tr3000/build/verify-image.sh").read_text(encoding="utf-8")
        self.assertIn("MAX_BYTES=104857600", text)
        self.assertIn("verify-image.sh", BUILD.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
