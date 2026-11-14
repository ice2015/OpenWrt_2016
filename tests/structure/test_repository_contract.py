from pathlib import Path
import json
import re
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[2]


class RepositoryContractTests(unittest.TestCase):
    def test_tr3000_lite_overlay_is_device_scoped(self) -> None:
        overlay = ROOT / "overlays/devices/tr3000-lite/files/etc/config"
        for config in ("network", "dhcp", "firewall", "tr3000-lite"):
            self.assertTrue((overlay / config).is_file(), f"missing Lite overlay: {config}")
        self.assertFalse((ROOT / "files/etc/config/tr3000-lite").exists())
        for manifest in (ROOT / "manifests/devices").glob("*.json"):
            self.assertNotIn("tr3000-lite", manifest.read_text(encoding="utf-8"))

    def test_required_layer_files_exist(self) -> None:
        required = {
            ".editorconfig",
            ".gitignore",
            "AGENTS.md",
            "local/README.md",
            "configs/common/base.config",
            "configs/common/packages.config",
            "configs/distributions/openwrt.config",
            "configs/distributions/immortalwrt.config",
            "configs/devices/tr3000.config",
            "configs/devices/x86-64.config",
            "configs/devices/raspberry-pi.config",
            "feeds/common.conf",
            "feeds/openwrt.conf",
            "feeds/immortalwrt.conf",
            "overlays/README.md",
            "patches/README.md",
        }

        missing = sorted(path for path in required if not (ROOT / path).is_file())

        self.assertEqual([], missing)

    def test_generated_and_private_paths_are_ignored(self) -> None:
        ignored = [
            "work/example",
            "output/example",
            "cache/example",
            "local/private.config",
            ".env",
            "secret.key",
        ]
        results = {
            path: subprocess.run(
                ["git", "check-ignore", "--quiet", path],
                cwd=ROOT,
                check=False,
            ).returncode
            for path in ignored
        }

        self.assertEqual({path: 0 for path in ignored}, results)

    def test_local_readme_remains_trackable(self) -> None:
        result = subprocess.run(
            ["git", "check-ignore", "--quiet", "local/README.md"],
            cwd=ROOT,
            check=False,
        )

        self.assertEqual(1, result.returncode)

    def test_operating_documents_exist(self) -> None:
        documents = [
            "README.md",
            "docs/architecture.md",
            "docs/configuration-layers.md",
            "docs/adding-a-device.md",
            "docs/LITE-README.md",
            "docs/FULL-README.md",
            "docs/UBOOT-SAFETY.md",
            "docs/WIREGUARD-VPS-ROUTING.md",
            "docs/WIREGUARD-SNAT.md",
            "docs/TAILSCALE.md",
            "docs/SINGBOX-SPLIT-ROUTING.md",
            "docs/CLOUDFLARED-ACCESS.md",
            "docs/TEST-PLAN.md",
        ]

        self.assertEqual([], [path for path in documents if not (ROOT / path).is_file()])

    def test_readme_local_links_resolve(self) -> None:
        readme = ROOT / "README.md"
        links = re.findall(r"(?<!!)\[[^]]+\]\(([^)]+)\)", readme.read_text(encoding="utf-8"))
        local_links = [link.split("#", 1)[0] for link in links if "://" not in link]

        missing = sorted(link for link in local_links if link and not (ROOT / link).exists())

        self.assertEqual([], missing)

    def test_full_luci_package_is_admin_only_and_uses_fixed_controller(self) -> None:
        package = ROOT / "packages/luci-app-tr3000-full"
        menu_path = package / "root/usr/share/luci/menu.d/luci-app-tr3000-full.json"
        acl_path = package / "root/usr/share/rpcd/acl.d/luci-app-tr3000-full.json"
        view_path = package / "htdocs/luci-static/resources/view/tr3000-full/services.js"

        self.assertTrue((package / "Makefile").is_file())
        self.assertTrue(view_path.is_file())
        menu = json.loads(menu_path.read_text(encoding="utf-8"))
        acl = json.loads(acl_path.read_text(encoding="utf-8"))
        entry = menu["admin/services/tr3000-full"]
        self.assertNotIn("auth", entry)
        self.assertEqual(["luci-app-tr3000-full"], entry["depends"]["acl"])
        self.assertNotIn("file", acl["luci-app-tr3000-full"].get("read", {}))
        write_files = acl["luci-app-tr3000-full"]["write"]["file"]
        self.assertEqual(
            {"/usr/sbin/tr3000-full-service": ["exec"]},
            write_files,
        )
        view = view_path.read_text(encoding="utf-8")
        for service in ("wireguard", "tailscale", "sing-box", "cloudflared"):
            self.assertIn(f"'{service}'", view)
        self.assertNotIn("/bin/sh", view)

    def test_full_first_boot_policy_disables_remote_services(self) -> None:
        defaults = (
            ROOT / "files/etc/uci-defaults/95-tr3000-full-services"
        ).read_text(encoding="utf-8")

        for service in ("wireguard", "tailscale", "sing-box", "cloudflared"):
            self.assertIn(f"disable {service}", defaults)


if __name__ == "__main__":
    unittest.main()
