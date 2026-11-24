"""Full multi-uplink failover and USB tethering (spec D2a semantic points)."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tests.scripts.test_scripts import ROOT, bash_executable
from tests.scripts.test_tr3000_full_drift import rename
from tests.scripts.test_tr3000_lite_uplink import FAKE as LITE_UPLINK_FAKE, lease, route
from tests.scripts.test_tr3000_lite_usbwan import FAKE as USB_FAKE

SCRIPT = ROOT/'scripts/tr3000-full-uplink-watch.sh'
LIB = ROOT/'scripts/tr3000-full-uplink-lib.sh'
STATUS = ROOT/'scripts/tr3000-full-uplink-status.sh'
CHANGED = ROOT/'scripts/tr3000-full-uplink-changed.sh'
USBWAN_LIB = ROOT/'scripts/tr3000-full-usbwan-lib.sh'
USB_HOOK = ROOT/'overlays/devices/tr3000-full/files/etc/hotplug.d/net/90-tr3000-full-usbwan'

# Same controlled boundaries as Lite, with the Full event name and the single
# standard wg interface instead of the two industrial WG roles.
FAKE = LITE_UPLINK_FAKE.replace("'tr3000-lite.uplink-changed'", "'tr3000-full.uplink-changed'")
FAKE = FAKE.replace("('wg_direct','wg_vps')", "('wg',)")


class FullUplinkTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for path in ('bin', 'etc/config', 'var/run/tr3000-full', 'usr/lib/tr3000-full'):
            (self.root/path).mkdir(parents=True)
        (self.root/'bin/fake.py').write_text(FAKE)
        for command in ('uci', 'ubus', 'jsonfilter', 'ping', 'ip', 'logger', 'sleep', 'ifdown', 'ifup'):
            path = self.root/'bin'/command
            path.write_text('#!/bin/sh\nexec "$UPLINK_PYTHON" -S "$UPLINK_FIXTURE/bin/fake.py" '+command+' "$@"\n')
            path.chmod(0o755)
        self.data = {'config': {}, 'leases': {}, 'routes': [], 'probes': {}, 'reads': {}}
        for name, dev, ip, gw, metric in (
            ('wan', 'eth0', '192.0.2.2', '192.0.2.1', 10),
            ('wwan', 'wlan1-sta0', '198.51.100.2', '198.51.100.1', 20),
            ('usbwan', 'modem7', '203.0.113.2', '203.0.113.1', 30)):
            self.data['config'][f'network.{name}.metric'] = str(metric)
            self.data['config'][f'tr3000-full-uplink-watch.{name}.probe_ip'] = '1.1.1.1 9.9.9.9'
            self.data['leases'][name] = lease(dev, ip, gw, metric)
            self.data['routes'].append(route(dev, ip, gw, metric))
            self.data['probes'][dev] = {'1.1.1.1': True, '9.9.9.9': True}
        self.save()
        hook = self.root/'usr/lib/tr3000-full/uplink-changed'
        hook.write_text('#!/bin/sh\nprintf "%s %s\\n" "$1" "$2" >> "$UPLINK_FIXTURE/events"\n[ ! -e "$UPLINK_FIXTURE/fail-hook" ]\n')
        hook.chmod(0o755)

    def save(self): (self.root/'fixture.json').write_text(json.dumps(self.data))
    def load(self): return json.loads((self.root/'fixture.json').read_text())
    def calls(self):
        path = self.root/'calls.jsonl'
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
    def events(self):
        path = self.root/'events'
        return path.read_text().splitlines() if path.exists() else []

    def run_watch(self, *args, success=True):
        self.assertTrue(SCRIPT.is_file(), 'Full reconciler is missing')
        self.assertTrue(LIB.is_file(), 'Full uplink library is missing')
        text = SCRIPT.read_text().replace('PATH=/usr/sbin:/usr/bin:/sbin:/bin',
                                          'PATH="'+str(self.root/'bin')+':/usr/bin:/bin"')
        text = text.replace('/usr/lib/tr3000-full/uplink-lib.sh', str(LIB))
        text = text.replace('/usr/sbin/lite-common.sh', str(ROOT/'scripts/lite-common.sh'))
        for prefix in ('/var/run', '/etc/config', '/usr/lib/tr3000-full/uplink-changed',
                       '/etc/hotplug.d/net', '/usr/sbin/tr3000-full-remote'):
            text = text.replace(prefix, str(self.root)+prefix)
        path = self.root/'watch.sh'; path.write_text(text)
        result = subprocess.run([bash_executable(), str(path), *(args or ('reconcile',))],
                                capture_output=True, text=True,
                                env=dict(os.environ, UPLINK_FIXTURE=str(self.root), UPLINK_PYTHON=sys.executable))
        if success is not None:
            self.assertEqual(success, result.returncode == 0, result.stdout+result.stderr)
        return result

    def status(self):
        return json.loads(self.run_watch('status', '--json').stdout)
    def by_name(self): return {entry['name']: entry for entry in self.status()['interfaces']}
    def probes(self, name, good):
        self.data = self.load(); dev = self.data['leases'][name]['l3_device']
        self.data['probes'][dev] = {'1.1.1.1': good, '9.9.9.9': good}; self.save()

    def run_changed(self, *args):
        self.assertTrue(CHANGED.is_file(), 'Full uplink event hook is missing')
        text = CHANGED.read_text().replace('PATH=/usr/sbin:/usr/bin:/sbin:/bin',
                                           'PATH="'+str(self.root/'bin')+':/usr/bin:/bin"')
        script = self.root/'event.sh'; script.write_text(text)
        return subprocess.run([bash_executable(), str(script), *args], capture_output=True, text=True,
                              env=dict(os.environ, UPLINK_FIXTURE=str(self.root), UPLINK_PYTHON=sys.executable))

    def test_protected_set_is_the_access_segment(self):
        text = LIB.read_text(encoding='utf-8')
        self.assertIn('for protected in lan', text)
        self.assertNotIn('plant', text)

    def test_status_maps_managed_ap_to_lan(self):
        text = STATUS.read_text(encoding='utf-8')
        self.assertIn("ap:*' lan '*) network=lan", text)
        self.assertNotIn('mgmt', text)

    def test_uplink_event_restarts_the_single_wg_interface(self):
        self.data['config'].update({'network.wg.proto': 'wireguard', 'network.wg.auto': '1'}); self.save()
        result = self.run_changed('wwan', 'wan')
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual([['ifdown', 'wg'], ['ifup', 'wg']], self.load().get('wg_actions', []))
        sent = [call for call in self.calls() if call[:3] == ['ubus', 'send', 'tr3000-full.uplink-changed']]
        self.assertEqual({'schema_version': 1, 'active': 'wwan', 'previous': 'wan'}, json.loads(sent[0][3]))
        # auto=0: configured but not enabled -> no restart.
        self.data = self.load(); self.data['config']['network.wg.auto'] = '0'; self.save()
        result = self.run_changed('usbwan', 'wwan')
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(2, len(self.load().get('wg_actions', [])))
        # No wg interface at all -> no restart.
        self.data = self.load()
        self.data['config'].pop('network.wg.proto'); self.data['config'].pop('network.wg.auto'); self.save()
        result = self.run_changed('wan', 'usbwan')
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(2, len(self.load().get('wg_actions', [])))

    def test_usbwan_lock_is_the_full_network_lock(self):
        text = USB_HOOK.read_text(encoding='utf-8')
        self.assertIn('/var/lock/tr3000-full-network', text)
        self.assertIn('for protected in wan lan wwan', text)

    def test_three_failures_demote_and_two_successes_recover(self):
        self.run_watch(); self.probes('wan', False)
        for round_number in (1, 2):
            self.run_watch(); self.assertEqual('wan', self.status()['active'])
            self.assertEqual(round_number, self.by_name()['wan']['failures'])
        self.run_watch(); state = self.by_name()['wan']
        self.assertEqual('unhealthy', state['health'])
        self.assertEqual(1010, state['effective_metric'])
        self.assertEqual('wwan', self.status()['active'])
        self.assertEqual([20, 30, 1010], sorted(r['metric'] for r in self.load()['routes']))
        self.assertEqual('wwan wan', self.events()[-1])
        self.probes('wan', True)
        self.run_watch(); self.assertEqual('wwan', self.status()['active'])
        self.assertEqual(1, self.by_name()['wan']['successes'])
        self.run_watch(); self.assertEqual('wan', self.status()['active'])
        self.assertEqual([10, 20, 30], sorted(r['metric'] for r in self.load()['routes']))
        self.assertEqual('wan wwan', self.events()[-1])
        self.run_watch(); self.assertEqual(3, len(self.events()))

    def test_usbwan_lib_is_a_pure_rename_of_lite(self):
        expected = rename((ROOT/'scripts/tr3000-lite-usbwan-lib.sh').read_text(encoding='utf-8'))
        self.assertEqual(expected, USBWAN_LIB.read_text(encoding='utf-8'))


class FullUsbwanTests(unittest.TestCase):
    """USB classification/hotplug with real sysfs symlinks and isolated UCI."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.sysfs = self.root/'sys'
        for path in ('sys/devices', 'sys/class/net', 'sys/bus/usb/drivers',
                     'etc/config', 'var/run/tr3000-full', 'var/lock', 'tmp', 'bin'):
            (self.root/path).mkdir(parents=True)
        self.state = {'network.wan.device': 'eth0', 'network.lan.device': 'br-lan',
                      'network.usbwan': 'interface', 'network.usbwan.proto': 'dhcp',
                      'network.usbwan.metric': '30', 'network.usbwan.auto': '0'}
        self.save()
        (self.root/'bin/fake.py').write_text(USB_FAKE)
        for command in ('uci', 'ifup', 'ifdown', 'ubus', 'sleep'):
            path = self.root/'bin'/command
            path.write_text('#!/bin/sh\nexec "$USB_PYTHON" -S "$USB_FIXTURE/bin/fake.py" '+command+' "$@"\n')
            path.chmod(0o755)

    def save(self): (self.root/'etc/config/network').write_text(json.dumps(self.state))
    def load(self): return json.loads((self.root/'etc/config/network').read_text())

    def add_device(self, name='modem7', driver='rndis_host', usb=True):
        device = self.sysfs/'devices/platform/usb1'/('1-'+name)/('1-'+name+':1.0')
        device.mkdir(parents=True)
        if usb:
            (device.parent/'idVendor').write_text('2c7c\n')
            (device.parent/'idProduct').write_text('0125\n')
        if driver is not None:
            driver_path = self.sysfs/'bus/usb/drivers'/driver
            driver_path.mkdir(exist_ok=True)
            (device/'driver').symlink_to(driver_path, target_is_directory=True)
        net = self.sysfs/'class/net'/name
        net.mkdir()
        (net/'device').symlink_to(device, target_is_directory=True)
        return device

    def hook(self, action='add', device='modem7', **extra):
        self.assertTrue(USB_HOOK.is_file(), 'Full USB hotplug hook is missing')
        source = USB_HOOK.read_text().replace('PATH=/usr/sbin:/usr/bin:/sbin:/bin',
                                              'PATH="'+str(self.root/'bin')+':/usr/bin:/bin"')
        source = source.replace('/usr/lib/tr3000-full/usbwan-lib.sh', str(USBWAN_LIB))
        for path in ('/sys', '/etc/config', '/var/run', '/var/lock', '/tmp/.uci'):
            source = source.replace(path, str(self.root)+path)
        script = self.root/'hook.sh'; script.write_text(source)
        env = dict(os.environ, USB_FIXTURE=str(self.root), USB_PYTHON=sys.executable,
                   ACTION=action, INTERFACE=device, DEVPATH='/untrusted/unused', **extra)
        return subprocess.run([bash_executable(), str(script)], capture_output=True, text=True, env=env)

    def calls(self):
        path = self.root/'calls.jsonl'
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def status(self):
        return json.loads((self.root/'var/run/tr3000-full/usbwan.json').read_text())

    def test_multiple_candidates_fail_closed_and_recover_after_removal(self):
        self.add_device()
        self.assertEqual(0, self.hook().returncode)
        self.add_device('ether9', 'cdc_ether')
        self.assertEqual(0, self.hook(device='ether9').returncode)
        self.assertNotIn('network.usbwan.device', self.load())
        self.assertEqual('ambiguous', self.status()['state'])
        self.assertIn(['ifdown', 'usbwan'], self.calls())
        import shutil
        shutil.rmtree(self.sysfs/'class/net/ether9')
        self.assertEqual(0, self.hook('remove', 'ether9').returncode)
        self.assertEqual('modem7', self.load()['network.usbwan.device'])

    def test_existing_manual_binding_and_protected_interfaces_are_not_stolen(self):
        self.add_device()
        for values in ({'network.usbwan.device': 'manual0'}, {'network.wan.device': 'modem7'},
                       {'network.lan.device': 'modem7'}, {'network.wwan.device': 'modem7'}):
            with self.subTest(values=values):
                self.state = {'network.usbwan': 'interface', 'network.usbwan.proto': 'dhcp',
                              'network.usbwan.metric': '30', 'network.usbwan.auto': '0', **values}
                self.save()
                self.assertNotEqual(0, self.hook().returncode)
                self.assertEqual(self.state, self.load())
                self.assertFalse(any(call[0] == 'ifup' for call in self.calls()))


if __name__ == '__main__':
    unittest.main()
