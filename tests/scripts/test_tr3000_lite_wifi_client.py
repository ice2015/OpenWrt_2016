"""Lite AP preservation and navigation boundaries; no custom Wi-Fi secret API."""
import json
import shutil
import subprocess
import unittest

from tests.scripts.test_scripts import ROOT, lite_base_config, run_lite_configure, uci_sections
from tests.scripts import test_tr3000_lite_wifi as wifi_tests


class WifiClientTests(unittest.TestCase):
    def test_client_interface_is_optional_dhcp_without_a_default_station(self):
        result, _, assets = run_lite_configure(lite_base_config())
        self.assertEqual(0, result.returncode, result.stderr)
        network = {section['.name']: section for section in uci_sections(assets['files/etc/config/network'])}
        self.assertEqual('dhcp', network['wwan']['proto'])
        self.assertEqual('20', network['wwan']['metric'])
        self.assertEqual('0', network['wwan']['auto'])
        self.assertNotIn('device', network['wwan'])
        wireless = uci_sections(assets.get('files/etc/config/wireless', ''))
        self.assertFalse(any(section.get('mode') == 'sta' for section in wireless))

    def test_management_identity_survives_station_add_disconnect_and_removal(self):
        for radios in (1, 2):
            with self.subTest(radios=radios):
                fixture = wifi_tests.ManagementAPTests(methodName='runTest')
                fixture.setUp()
                try:
                    fixture.state = {'wireless.radio0': 'wifi-device'}
                    if radios == 2:
                        fixture.state['wireless.radioOther'] = 'wifi-device'
                    fixture.save()
                    original = fixture.run_ap()
                    managed = {key: value for key, value in original.items()
                               if key.startswith('wireless.tr3000_lite_mgmt_')}
                    self.assertEqual(radios, len(fixture.aps(original)))
                    self.assertFalse(any(value == 'sta' for value in original.values()))
                    sta = 'wireless.approved_station'
                    fixture.state = dict(original)
                    fixture.state.update({sta: 'wifi-iface', sta+'.mode': 'sta',
                        sta+'.device': 'radio0' if radios == 1 else 'radioOther',
                        sta+'.network': 'wwan', sta+'.encryption': 'psk2',
                        sta+'.ssid': 'Approved bench hotspot', sta+'.key': 'private-test-fixture',
                        sta+'.disabled': '0'})
                    fixture.save()
                    connected = fixture.run_ap()
                    for key, value in managed.items():
                        self.assertEqual(value, connected[key], key)
                    self.assertEqual('wwan', connected[sta+'.network'])
                    # A disconnected station may remain saved but must not disable APs.
                    fixture.state = dict(connected)
                    fixture.state[sta+'.disabled'] = '1'
                    fixture.save()
                    disconnected = fixture.run_ap()
                    for key, value in managed.items():
                        self.assertEqual(value, disconnected[key], key)
                    fixture.state = {key: value for key, value in disconnected.items()
                                     if key != sta and not key.startswith(sta+'.')}
                    fixture.save()
                    removed = fixture.run_ap()
                    for key, value in managed.items():
                        self.assertEqual(value, removed[key], key)
                    for ap in fixture.aps(removed):
                        self.assertEqual('0', removed[ap+'.disabled'])
                        self.assertEqual('lan', removed[ap+'.network'])
                        self.assertEqual('psk2', removed[ap+'.encryption'])
                finally:
                    fixture.doCleanups()

    def test_client_navigation_uses_standard_luci_and_explains_safe_join(self):
        node = shutil.which('node')
        if node is None:
            self.skipTest('Node.js is required for the LuCI behavior test')
        view = ROOT/'packages/luci-app-tr3000-lite/htdocs/luci-static/resources/view/tr3000-lite/industrial-lan.js'
        harness = r'''
const assert = require('node:assert/strict');
const source = require('node:fs').readFileSync(process.argv[1], 'utf8');
const E = (tag, attrs, children) => ({ tag, attrs: attrs || {},
  children: children === undefined ? attrs : children, textContent: '',
  value: attrs?.value || '', addEventListener() {} });
const L = { url: (...parts) => '/custom-luci/' + parts.join('/') };
const page = new Function('view', 'fs', 'ui', 'E', '_', 'window', 'L', source)(
  {extend: x => x}, {exec() { throw Error('render must not execute commands'); }}, {}, E,
  x => x, {}, L);
const tree = page.render({schema_version:2, mode:'lan',
  lan:{cidr:'192.168.10.1/24', netmask:'255.255.255.0', dhcp_pool:'192.168.10.100-192.168.10.249'},
  plant:{address:'192.168.20.254', prefix:24, netmask:'255.255.255.0', cidr:'192.168.20.0/24',
  active:false, allow_luci:false, allow_mgmt:true, dhcp:'disabled'},
  ap_ready:true, legacy_config_detected:false, backup_id:''});
const walk = item => !item || typeof item !== 'object' ? [] :
  [item, ...[item.children].flat(Infinity).flatMap(walk)];
const text = item => typeof item === 'string' ? item : !item ? '' :
  [item.textContent, ...[item.children].flat(Infinity).map(text)].join(' ');
const links = walk(tree).filter(item => item.tag === 'a');
assert.ok(links.some(item => item.attrs.href === '/custom-luci/admin/network/wireless'),
  'Client configuration must navigate to the standard authenticated Wireless page');
assert.ok(links.some(item => item.attrs.href === '/custom-luci/admin/network/network'));
assert.match(text(tree), /AP-only/);
assert.match(text(tree), /AP\+Client/);
assert.match(text(tree), /disconnected Client/i);
assert.match(text(tree), /same radio.*channel.*interrupt/i);
assert.match(text(tree), /encrypted.*approved/i);
assert.match(text(tree), /Replace wireless configuration/);
assert.match(text(tree), /wwan.*automatic startup/i);
assert.equal(walk(tree).filter(item => item.tag === 'input' && item.attrs.type === 'password').length, 0);
'''
        result = subprocess.run([node, '-e', harness, str(view)], capture_output=True, text=True)
        self.assertEqual(0, result.returncode, result.stdout+result.stderr)


if __name__ == '__main__':
    unittest.main()
