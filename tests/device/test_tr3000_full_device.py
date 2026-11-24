"""Device acceptance checks for the TR3000 Full firmware on a real router.

These tests talk to a flashed lab router over SSH and assert the shipped
behaviour of the Full variant (network contract, closed-by-default remote
services, Argon theme, Cloudflare DDNS template and the managed WPA2 access
point). They are opt-in: set TR3000_FULL_DEVICE to the router address, e.g.

    TR3000_FULL_DEVICE=192.168.10.1 python -m unittest tests.device.test_tr3000_full_device -v

The SSH identity must be able to log in as root without a password prompt
(key based). Without the environment variable every test is skipped, so the
regular CI run stays untouched.
"""
import json
import os
import re
import subprocess
import unittest

DEVICE = os.environ.get("TR3000_FULL_DEVICE", "").strip()
SSH_OPTIONS = [
    "-o", "StrictHostKeyChecking=no",
    "-o", "BatchMode=yes",
    "-o", "ConnectTimeout=8",
]
KEY = os.environ.get("TR3000_FULL_SSH_KEY", os.path.expanduser("~/.ssh/id_ed25519"))


def ssh(command: str) -> str:
    """Run a read-only command on the router and return its output."""
    if KEY and os.path.exists(KEY):
        options = SSH_OPTIONS + ["-i", KEY]
    else:
        options = SSH_OPTIONS
    result = subprocess.run(
        ["ssh", *options, f"root@{DEVICE}", command],
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        raise AssertionError(f"ssh failed ({result.returncode}): {result.stderr.strip()}")
    return result.stdout


def uci_show(package: str) -> str:
    return ssh(f"uci -q show {package} 2>/dev/null || true")


@unittest.skipUnless(DEVICE, "TR3000_FULL_DEVICE is not set")
class FullDeviceAcceptanceTests(unittest.TestCase):
    """The Full firmware contract on a flashed router."""

    def test_access_segment_is_reachable_and_industrial_free(self) -> None:
        network = ssh("cat /etc/config/network")
        self.assertIn("config interface 'lan'", network)
        self.assertIn("option ipaddr '192.168.10.1'", network)
        self.assertIn("config device 'br_lan'", network)
        self.assertIn("list ports 'eth1'", network)
        self.assertNotIn("plant", network)
        self.assertNotIn("mgmt", network)
        dhcp = ssh("cat /etc/config/dhcp")
        self.assertIn("config dhcp 'lan'", dhcp)
        self.assertIn("option start '100'", dhcp)
        self.assertIn("option limit '150'", dhcp)

    def test_tunnel_firewall_is_closed_by_default(self) -> None:
        firewall = ssh("cat /etc/config/firewall")
        self.assertIn("option name 'wg'", firewall)
        self.assertRegex(firewall, r"option src 'wg'\s*\n\s*option dest 'lan'")
        self.assertNotRegex(firewall, r"option src 'wg'\s*\n\s*option dest 'wan'")
        for rule in ("tr3000_full_wg_mgmt", "tr3000_full_wg_icmp", "tr3000_full_wg_listener"):
            body = re.search(rf"(?s)config rule '{rule}'(.*?)(?=\nconfig |\Z)", firewall)
            self.assertIsNotNone(body, rule)
            self.assertIn("option enabled '0'", body.group(1), rule)
        # The WireGuard management rules are not industrial plant/mgmt zones.
        self.assertNotIn("option name 'mgmt'", firewall)
        self.assertNotIn("option name 'plant'", firewall)

    def test_remote_services_are_installed_but_stopped(self) -> None:
        status = json.loads(ssh("/usr/sbin/tr3000-full-service status --json"))
        for service in ("wireguard", "tailscale", "homeproxy", "cloudflared"):
            self.assertIn(service, status)
        self.assertFalse(status["homeproxy"]["running"])
        self.assertFalse(status["cloudflared"]["running"])
        self.assertFalse(status["legacy_config_detected"])
        for service in ("homeproxy", "sing-box", "cloudflared"):
            running = ssh(f"ubus call service list '{service}' 2>/dev/null || true")
            self.assertNotIn('"running":true', running, f"{service} must not run")

    def test_homeproxy_leaves_no_residue_when_it_does_not_run(self) -> None:
        # HomeProxy owns the sing-box binary; the standalone service stays off.
        self.assertFalse(ssh("test -e /etc/rc.d/S99homeproxy && echo present || echo absent").startswith("present"))
        self.assertEqual("", ssh("ls /var/run/homeproxy 2>/dev/null || true").strip())
        self.assertNotIn("sing-box", ssh("ps w | grep sing-box | grep -v grep || true"))

    def test_argon_is_the_default_theme_and_bootstrap_is_kept(self) -> None:
        self.assertEqual("/luci-static/argon", ssh("uci -q get luci.main.mediaurlbase").strip())
        self.assertIn("bootstrap", ssh("ls /www/luci-static/ | tr '\\n' ' '"))

    def test_cloudflare_ddns_template_is_present_and_disabled(self) -> None:
        ddns = ssh("cat /etc/config/ddns")
        self.assertIn("cloudflare.com-v4", ddns)
        body = re.search(r"(?s)config service 'cloudflare_v4'(.*?)(?=\nconfig |\Z)", ddns)
        self.assertIsNotNone(body)
        self.assertIn("option enabled '0'", body.group(1))
        self.assertNotIn("option domain", body.group(1))
        self.assertNotIn("option password", body.group(1))

    def test_managed_access_point_replaces_the_open_default(self) -> None:
        # The mt_wifi driver recreates open default access points on every
        # boot; exactly one encrypted management AP per radio must survive.
        self.assertNotEqual("", ssh("cat /etc/config/wireless 2>/dev/null || true").strip(),
                            "the device must ship a wireless configuration")
        wireless = ssh("cat /etc/config/wireless")
        self.assertIn("TR3000-Full-", wireless)
        self.assertIn("option encryption 'psk2'", wireless)
        self.assertIn("option network 'lan'", wireless)
        managed = re.findall(r"(?s)config wifi-iface '([^']+)'(.*?)(?=\nconfig |\Z)", wireless)
        aps = [body for _, body in managed if "tr3000_full_managed '1'" in body]
        self.assertEqual(2, len(aps), "one managed access point per radio")
        for body in aps:
            self.assertIn("option disabled '0'", body)
            self.assertIn("option mode 'ap'", body)
        # Every open default access point must be disabled.
        for name, body in managed:
            if "tr3000_full_managed '1'" in body:
                continue
            self.assertRegex(body, r"option disabled '1'|option encryption '(psk2|sae|psk)'")

    def test_wireless_credentials_stay_private(self) -> None:
        mode = ssh("ls -l /etc/config/wireless | cut -c1-10").strip()
        self.assertEqual("-rw-------", mode)

    def test_management_ap_controller_reports_ready(self) -> None:
        report = json.loads(ssh("/usr/sbin/tr3000-full-wifi status --json"))
        self.assertTrue(report["ready"])
        self.assertEqual(2, report["radio_count"])
        self.assertEqual(2, report["managed_aps"])
        self.assertEqual(0, report["open_aps"])
        self.assertTrue(report["ssid_present"])
        self.assertTrue(report["key_present"])

    def test_uplink_status_keeps_the_documented_shape(self) -> None:
        status = json.loads(ssh("/usr/sbin/tr3000-full-uplink-status --json"))
        self.assertEqual(1, status["schema_version"])
        names = [row["name"] for row in status["interfaces"]]
        self.assertEqual(["wan", "wwan", "usbwan"], names)
        self.assertEqual([10, 20, 30], [row["base_metric"] for row in status["interfaces"]])
        self.assertIn("wireless", status)
        self.assertIn("usb", status)

    def test_radio_driver_never_times_out_on_the_access_segment(self) -> None:
        count = ssh("logread | grep -c 'wait_for network.interface.lan' || true").strip()
        self.assertEqual("0", count)

    def test_full_luci_package_is_installed(self) -> None:
        for path in ("/www/luci-static/resources/view/tr3000-full/services.js",
                     "/www/luci-static/resources/view/tr3000-full/uplinks.js",
                     "/usr/share/luci/menu.d/luci-app-tr3000-full.json"):
            self.assertEqual("present", ssh(f"test -f {path} && echo present || echo absent").strip(), path)
        services = ssh("cat /www/luci-static/resources/view/tr3000-full/services.js")
        # A boolean disabled attribute renders disabled="false" in HTML and
        # would leave the Enable action of an installed service inert.
        self.assertNotIn("'disabled': !state.installed", services)
        self.assertIn("attributes.disabled = 'disabled'", services)
