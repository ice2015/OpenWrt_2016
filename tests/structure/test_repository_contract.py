from pathlib import Path
import json
import re
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[2]


class RepositoryContractTests(unittest.TestCase):
    def test_lite_luci_package_is_admin_only_and_uses_fixed_controller(self) -> None:
        package = ROOT / "packages/luci-app-tr3000-lite"
        self.assertTrue((package / "Makefile").is_file(), "missing Lite LuCI package")
        menu = json.loads((package / "root/usr/share/luci/menu.d/luci-app-tr3000-lite.json").read_text(encoding="utf-8"))
        acl = json.loads((package / "root/usr/share/rpcd/acl.d/luci-app-tr3000-lite.json").read_text(encoding="utf-8"))
        self.assertEqual({"admin/network/tr3000-lite", "admin/network/tr3000-lite/industrial-lan"}, set(menu))
        parent = menu["admin/network/tr3000-lite"]
        self.assertEqual("TR3000 Lite", parent["title"])
        self.assertEqual({"type": "firstchild"}, parent["action"])
        self.assertNotIn("auth", parent)
        self.assertEqual(["luci-app-tr3000-lite"], parent["depends"]["acl"])
        entry = menu["admin/network/tr3000-lite/industrial-lan"]
        self.assertNotIn("auth", entry)
        self.assertEqual(["luci-app-tr3000-lite"], entry["depends"]["acl"])
        self.assertEqual({"type": "view", "path": "tr3000-lite/industrial-lan"}, entry["action"])
        grant = acl["luci-app-tr3000-lite"]
        self.assertEqual({}, grant["read"])
        self.assertEqual({"file": {"/usr/sbin/tr3000-lite-plant": ["exec"]}, "ubus": {"file": ["exec"]}}, grant["write"])
        makefile = (package / "Makefile").read_text(encoding="utf-8")
        self.assertRegex(makefile, r"DEPENDS:=\+luci-base \+rpcd-mod-file\s*\n")
        view = (package / "htdocs/luci-static/resources/view/tr3000-lite/industrial-lan.js").read_text(encoding="utf-8")
        self.assertNotIn("/bin/sh", view)
        self.assertNotRegex(view, r"(?:require uci|fs\.(?:read|write)|['\"]uci['\"])")

    def test_lite_luci_view_validates_current_input_and_handles_controller_errors(self) -> None:
        view = ROOT / "packages/luci-app-tr3000-lite/htdocs/luci-static/resources/view/tr3000-lite/industrial-lan.js"
        self.assertTrue(view.is_file(), "missing Industrial LAN view")
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node.js is needed to execute the LuCI view contract")
        harness = r"""
const assert = require('node:assert/strict');
const source = require('node:fs').readFileSync(process.argv[1], 'utf8');
const calls = [], replies = [], notices = [];
let confirmed = true, confirmation = '';
const fs = { exec: (path, args) => {
  assert.equal(path, '/usr/sbin/tr3000-lite-plant');
  calls.push(args);
  const reply = replies.shift();
  assert.ok(reply, 'unexpected controller call');
  return typeof reply === 'function' ? reply() : Promise.resolve(reply);
}};
const E = (tag, attrs, children) => ({ tag, attrs: attrs || {}, children: children === undefined ? attrs : children,
  value: attrs?.value || '', checked: !!attrs?.checked, disabled: !!attrs?.disabled,
  textContent: '', setAttribute(k, v) { this[k] = v; },
  addEventListener(name, fn) { this.attrs[name] = fn; } });
const ui = { addNotification: (title, body) => notices.push(body),
  createHandlerFn: (ctx, fn, ...args) => (...rest) => fn.apply(ctx, [...args, ...rest]) };
const page = new Function('view', 'fs', 'ui', 'E', '_', 'window', source)(
  { extend: x => x }, fs, ui, E, x => x,
  { confirm: message => { confirmation = message; return confirmed; } });
const state = {schema_version:1, plant:{device:'eth1', address:'192.168.10.254', prefix:24,
  netmask:'255.255.255.0', allow_luci:false, allow_mgmt:true, dhcp:'disabled'},
  checks:{result:'ok'}, backup_id:'', rollback:'none'};
const ok = data => ({code:0, stdout:JSON.stringify(data), stderr:''});
const walk = item => !item || typeof item !== 'object' ? [] :
  [item, ...[item.children].flat(Infinity).flatMap(walk)];
const byId = (tree, id) => walk(tree).find(x => x.attrs?.id === id);
const text = item => typeof item === 'string' ? item : !item ? '' :
  [item.textContent, ...[item.children].flat(Infinity).map(text)].join(' ');
(async () => {
  replies.push(ok(state));
  const tree = page.render(await page.load());
  assert.deepEqual(calls.shift(), ['status', '--json']);
  assert.match(text(tree), /255\.255\.255\.0/);
  assert.match(text(tree), /DHCP.*disabled/i);
  assert.match(text(tree), /HTTPS.*443/);
  const address = byId(tree, 'plant-address');
  const luci = byId(tree, 'plant-https');
  const mgmt = byId(tree, 'plant-mgmt');
  const validate = byId(tree, 'plant-validate');
  const apply = byId(tree, 'plant-apply');
  assert.equal(address.value, '192.168.10.254/24');
  assert.equal(luci.checked, false); assert.equal(mgmt.checked, true);
  assert.equal(apply.disabled, true);
  await apply.attrs.click(); assert.equal(calls.length, 0);
  replies.push(ok(state)); await validate.attrs.click();
  assert.deepEqual(calls.shift(), ['validate', '--address', '192.168.10.254/24']);
  assert.equal(apply.disabled, false);
  address.value = '192.168.20.254/26'; address.attrs.input();
  assert.equal(apply.disabled, true);
  let resolve;
  replies.push(() => new Promise(r => { resolve = r; }));
  const pending = validate.attrs.click();
  address.value = '192.168.30.254/24'; address.attrs.input();
  resolve(ok(state)); await pending;
  assert.equal(apply.disabled, true, 'stale validation must not enable apply');
  calls.length = 0;
  replies.push(ok(state)); await validate.attrs.click(); calls.length = 0;
  confirmed = false; await apply.attrs.click(); assert.equal(calls.length, 0);
  assert.match(confirmation, /disconnect/i);
  confirmed = true; luci.checked = true; mgmt.checked = false;
  const changed = structuredClone(state);
  Object.assign(changed.plant, {address:'192.168.30.254', allow_luci:true, allow_mgmt:false});
  changed.backup_id = 'safe-backup'; replies.push(ok(changed));
  await apply.attrs.click();
  assert.deepEqual(calls.shift(), ['apply', '--address', '192.168.30.254/24', '--allow-luci', 'true', '--allow-mgmt', 'false']);
  assert.equal(apply.disabled, true, 'must revalidate before another apply');
  const secret = 'SECRET /etc/private /bin/sh stack trace';
  for (const reply of [{code:2, stdout:JSON.stringify(state), stderr:secret},
    {code:0, stdout:secret, stderr:secret}, ok({schema_version:99}),
    ok({...state, checks:{result:secret}})]) {
    replies.push(reply); await validate.attrs.click();
    assert.equal(apply.disabled, true); assert.ok(notices.length);
    assert.ok(!text(notices).includes(secret));
  }
  replies.push(ok(state)); await validate.attrs.click();
  replies.push({code:3, stdout:JSON.stringify({...state, rollback:'degraded'}), stderr:secret});
  const before = notices.length; await apply.attrs.click();
  assert.equal(apply.disabled, true); assert.ok(notices.length > before);
  assert.ok(!text(notices.at(-1)).match(/success|applied/i));
  replies.push({code:3, stdout:secret, stderr:secret});
  await assert.rejects(page.load(), e => !e.message.includes(secret));
  for (const plant of [{...state.plant, address:secret}, {...state.plant, netmask:secret}]) {
    replies.push(ok({...state, plant}));
    await assert.rejects(page.load(), e => !e.message.includes(secret));
  }
  console.log('LuCI view behavior contract passed');
})().catch(e => { console.error(e); process.exitCode = 1; });
"""
        result = subprocess.run([node, "-e", harness, str(view)], text=True, capture_output=True, check=False)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

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
