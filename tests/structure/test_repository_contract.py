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
        self.assertEqual({"admin/network/tr3000-lite", "admin/network/tr3000-lite/industrial-lan", "admin/network/tr3000-lite/uplinks", "admin/network/tr3000-lite/remote-access"}, set(menu))
        parent = menu["admin/network/tr3000-lite"]
        self.assertEqual("TR3000 Lite", parent["title"])
        self.assertEqual({"type": "firstchild"}, parent["action"])
        self.assertNotIn("auth", parent)
        self.assertEqual(["luci-app-tr3000-lite"], parent["depends"]["acl"])
        entry = menu["admin/network/tr3000-lite/industrial-lan"]
        self.assertNotIn("auth", entry)
        self.assertEqual(["luci-app-tr3000-lite"], entry["depends"]["acl"])
        self.assertEqual({"type": "view", "path": "tr3000-lite/industrial-lan"}, entry["action"])
        remote_entry = menu["admin/network/tr3000-lite/remote-access"]
        self.assertNotIn("auth", remote_entry)
        self.assertEqual(["luci-app-tr3000-lite"], remote_entry["depends"]["acl"])
        self.assertEqual({"type": "view", "path": "tr3000-lite/remote-access"}, remote_entry["action"])
        grant = acl["luci-app-tr3000-lite"]
        self.assertEqual({}, grant["read"])
        self.assertEqual({
            "file": {
                "/usr/sbin/tr3000-lite-plant": ["exec"],
                "/usr/sbin/tr3000-lite-uplink-status": ["exec"],
                "/usr/sbin/tr3000-lite-remote": ["exec"],
                "/usr/sbin/tr3000-lite-ddns-status": ["exec"]
            },
            "ubus": {"file": ["exec"]}
        }, grant["write"])
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
const page = new Function('view', 'fs', 'ui', 'E', '_', 'window', 'L', source)(
  { extend: x => x }, fs, ui, E, x => x,
  { confirm: message => { confirmation = message; return confirmed; } },
  { url: (...parts) => '/cgi-bin/luci/' + parts.join('/') });
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
  assert.match(text(tree), /Backup ID: safe-backup/, 'successful apply must expose its safe recovery ID');
  const secret = 'SECRET /etc/private /bin/sh stack trace';
  for (const reply of [{code:2, stdout:JSON.stringify(state), stderr:secret},
    {code:0, stdout:secret, stderr:secret}, ok({schema_version:99}),
    ok({...state, checks:{result:secret}})]) {
    replies.push(reply); await validate.attrs.click();
    assert.equal(apply.disabled, true); assert.ok(notices.length);
    assert.ok(!text(notices).includes(secret));
  }
  for (const [rollback, message] of [['restored', /previous settings were restored/i],
    ['degraded', /recovery is incomplete/i], ['none', /no rollback was reported/i]]) {
    replies.push(ok(state)); await validate.attrs.click();
    const backup = '20261115123000-42-' + rollback;
    replies.push({code:3, stdout:JSON.stringify({...state, checks:{result:'network_reload'},
      rollback, backup_id:backup}), stderr:secret});
    const before = notices.length; await apply.attrs.click();
    assert.equal(apply.disabled, true); assert.ok(notices.length > before);
    assert.match(text(notices.at(-1)), message, 'recovery outcomes must be distinguishable');
    assert.match(text(tree), message, 'inline feedback must preserve the recovery outcome');
    assert.ok(text(tree).includes('Backup ID: ' + backup));
    assert.ok(!text(notices.at(-1)).includes(secret));
  }
  replies.push({code:2, stdout:JSON.stringify({...state, checks:{result:'management_overlap'}}), stderr:secret});
  await validate.attrs.click();
  assert.match(text(notices.at(-1)), /overlaps.*management/i, 'allowlisted rejection should explain validation failure');
  for (const data of [{...state, backup_id:secret}, {...state, backup_id:'../backup'},
    {...state, backup_id:'x'.repeat(81)}, {...state, rollback:secret},
    {...state, checks:{result:secret}}]) {
    replies.push(ok(data)); await validate.attrs.click();
    assert.equal(apply.disabled, true);
    assert.ok(!text(notices.at(-1)).includes(secret));
    assert.ok(!text(tree).includes(secret));
  }
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

    def test_lite_uplink_view_is_read_only(self) -> None:
        package = ROOT / 'packages/luci-app-tr3000-lite'
        view = package / 'htdocs/luci-static/resources/view/tr3000-lite/uplinks.js'
        self.assertTrue(view.is_file(), 'missing read-only uplink view')
        menu = json.loads((package / 'root/usr/share/luci/menu.d/luci-app-tr3000-lite.json').read_text())
        entry = menu['admin/network/tr3000-lite/uplinks']
        self.assertEqual({'type':'view', 'path':'tr3000-lite/uplinks'}, entry['action'])
        self.assertEqual(['luci-app-tr3000-lite'], entry['depends']['acl'])
        self.assertNotIn('auth', entry)
        node = shutil.which('node')
        if node is None:
            self.skipTest('Node.js is required for LuCI view behavior checks')
        harness = r'''
const assert = require('node:assert/strict');
const source = require('node:fs').readFileSync(process.argv[1], 'utf8');
const replies = [], calls = [];
const fs = {exec: (path,args) => {
  assert.equal(path, '/usr/sbin/tr3000-lite-uplink-status');
  assert.deepEqual(args, ['--json']); calls.push(args);
  return Promise.resolve(replies.shift());
}};
const E = (tag,attrs,children) => ({tag,attrs:attrs||{},children:children===undefined?attrs:children,textContent:''});
const page = new Function('view','fs','ui','E','_','L','window',source)(
  {extend:x=>x}, fs, {}, E, x=>x, {url:(...parts)=>'/custom/'+parts.join('/')}, {location:{reload(){}}});
const text = item => typeof item==='string' ? item : !item ? '' :
  [item.textContent,...[item.children].flat(Infinity).map(text)].join(' ');
const walk = item => !item || typeof item!=='object' ? [] :
  [item,...[item.children].flat(Infinity).flatMap(walk)];
const status={schema_version:1,active:'wan',previous:'wwan',status_error:false,reconcile_error:false,
  foreign_default:false,last_event_error:false,interfaces:[
    {name:'wan',device:'eth0',address:'192.0.2.2',gateway:'192.0.2.1',base_metric:10,effective_metric:10,health:'healthy',failures:0,successes:0,available:true,link:true},
    {name:'wwan',device:'wlanOdd',address:'198.51.100.2',gateway:'198.51.100.1',base_metric:20,effective_metric:1020,health:'unhealthy',failures:0,successes:1,available:true,link:true},
    {name:'usbwan',device:'modem7',address:'203.0.113.2',gateway:'203.0.113.1',base_metric:30,effective_metric:30,health:'healthy',failures:0,successes:0,available:true,link:true}],
  usb:{state:'bound',device:'modem7',driver:'rndis_host',vid:'2c7c',pid:'0125',path:'/devices/platform/usb1/1-1'},
  wireless:{mode:'ap_client',error:false,interfaces:[
    {section:'management',radio:'radioOdd',ifname:'phy7-ap0',phy:'phy7',mode:'ap',network:'mgmt',enabled:true,up:true,channel:6,frequency:2437,shared_phy:true},
    {section:'client',radio:'radioOther',ifname:'wlanOdd',phy:'phy7',mode:'sta',network:'wwan',enabled:true,up:false,channel:6,frequency:2437,shared_phy:true}]}};
const ok = data => ({code:0,stdout:JSON.stringify(data),stderr:''});
(async()=>{
  replies.push(ok(status)); const tree=page.render(await page.load());
  assert.equal(calls.length,1);
  const rendered=text(tree);
  for (const value of ['eth0','192.0.2.2','192.0.2.1','10','20','1020','30','healthy','unhealthy',
    'rndis_host','2c7c','0125','radioOdd','radioOther','phy7','2437']) assert.ok(rendered.includes(value),value);
  assert.match(rendered,/active/i); assert.match(rendered,/shared.*radio|same.*PHY/i);
  assert.match(rendered,/channel.*interrupt/i);
  assert.ok(walk(tree).some(item=>item.tag==='a' && item.attrs.href==='/custom/admin/network/wireless'));
  assert.ok(walk(tree).some(item=>item.tag==='a' && item.attrs.href==='/custom/admin/network/network'));
  assert.equal(walk(tree).filter(item=>['input','textarea','select','form'].includes(item.tag)).length,0);
  const warning=structuredClone(status); Object.assign(warning,{foreign_default:true,reconcile_error:true,status_error:true,last_event_error:true});
  assert.match(text(page.render(warning)),/foreign.*default/i);
  assert.match(text(page.render(warning)),/reconcil|verified snapshot/i);
  const secret='SECRET /etc/shadow <script>key</script>';
  for (const reply of [{code:2,stdout:secret,stderr:secret},ok({...status,schema_version:99}),
    ok({...status,usb:{...status.usb,driver:secret}}),
    ok({...status,interfaces:[{...status.interfaces[0],address:secret}]}),
    ok({...status,wireless:{...status.wireless,interfaces:[{...status.wireless.interfaces[0],channel:secret}]}})]) {
    replies.push(reply); await assert.rejects(page.load(),e=>!e.message.includes(secret));
  }
  replies.push(ok({...status,private_key:secret}));
  assert.ok(!text(page.render(await page.load())).includes(secret));
})().catch(error=>{console.error(error);process.exitCode=1;});
'''
        result = subprocess.run([node, '-e', harness, str(view)], capture_output=True, text=True)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_lite_remote_access_view_contract(self) -> None:
        package = ROOT / "packages/luci-app-tr3000-lite"
        view = package / "htdocs/luci-static/resources/view/tr3000-lite/remote-access.js"
        self.assertTrue(view.is_file(), "missing remote-access view")
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node.js is needed to execute the LuCI view contract")
        harness = r'''
const assert = require('node:assert/strict');
const source = require('node:fs').readFileSync(process.argv[1], 'utf8');
const replies = [], calls = [];
const fs = {exec: (path, args) => {
  calls.push([path, args]);
  if (!replies.length) throw new Error('unexpected call');
  return Promise.resolve(replies.shift());
}};
const view = {extend: spec => spec};
const ui = {showModal: () => {}, hideModal: () => {}, addNotification: () => {}};
const E = (tag, attrs, children) => {
  if (Array.isArray(attrs)) { children = attrs; attrs = {}; }
  return {tag, attrs: attrs || {}, children: children || []};
};
const _ = s => s;
const fn = new Function('view', 'fs', 'ui', 'E', '_', source + '\nreturn this;');
const page = fn(view, fs, ui, E, _);

const text = node => {
  if (typeof node === 'string') return node;
  if (!node) return '';
  if (Array.isArray(node)) return node.map(text).join(' ');
  return (text(node.children) + ' ' + Object.values(node.attrs || {}).join(' ')).trim();
};

const remoteData = {
  schema_version: 1,
  identity: "cell-01",
  enrolled: true,
  gates: { root_password: true, ap_initialized: true, identity: true, keys: true },
  roles: {
    wg_direct: { configured: true, enabled: true, address: "10.10.1.1/32" },
    wg_vps: { configured: true, enabled: true, address: "10.20.1.2/32" }
  },
  policy: { allow_luci: false, allow_plant: false },
  effective: { allow_luci: true, allow_plant: true },
  sources: { direct: ["10.10.1.10/32"], vps: ["10.20.1.10/32"] },
  plant: { address: "192.168.10.254", cidr: "192.168.10.0/24" },
  checks: { result: "ok" },
  degraded: false
};
const ddnsData = {
  schema_version: 1,
  configured: true,
  enabled: true,
  hostname: "cell01.example.org",
  record_type: "A",
  last_update: 1700000000,
  last_error: "",
  wan_scope: "global",
  direct_candidate: true,
  retry_count: 0,
  next_retry_uptime: 0
};

const ok = data => ({code: 0, stdout: JSON.stringify(data), stderr: ''});

(async () => {
  replies.push(ok(remoteData));
  replies.push(ok(ddnsData));
  const data = await page.load();
  assert.equal(calls.length, 2);
  const rendered = text(page.render(data));
  assert.ok(rendered.includes('10.10.1.1/32, 192.168.10.0/24'));
  assert.ok(rendered.includes('10.20.1.2/32, 192.168.10.0/24'));
  assert.ok(!rendered.includes('0.0.0.0/0'));
  assert.ok(rendered.includes('Do NOT activate both profiles simultaneously'));
  console.log('Remote access LuCI view contract passed');
})().catch(err => { console.error(err); process.exitCode = 1; });
'''
        result = subprocess.run([node, '-e', harness, str(view)], capture_output=True, text=True)
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
            "docs/TR3000-LITE-PROVISIONING.md",
            "docs/TR3000-LITE-REMOTE-ACCESS.md",
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
