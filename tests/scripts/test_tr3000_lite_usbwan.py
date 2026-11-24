"""Execute USB classification/hotplug with real sysfs symlinks and isolated UCI."""
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

from tests.scripts.test_scripts import ROOT, bash_executable, lite_base_config, run_lite_configure

LIB = ROOT/'devices/tr3000/lite/runtime/tr3000-lite-usbwan-lib.sh'
HOOK = ROOT/'devices/tr3000/lite/files/etc/hotplug.d/net/90-tr3000-lite-usbwan'
FAKE = r'''
import json, os, pathlib, sys, time
root=pathlib.Path(os.environ['USB_FIXTURE']); command=sys.argv[1]; args=sys.argv[2:]
with (root/'calls.jsonl').open('a') as f: f.write(json.dumps([command,*args])+'\n')
if command=='uci':
    directory=root/'etc/config'; args=[a for a in args if a!='-q']
    for flag in ('-c','-C','-t'):
        if flag in args:
            i=args.index(flag)
            if flag=='-c': directory=pathlib.Path(args[i+1])
            del args[i:i+2]
    path=directory/'network'; data=json.loads(path.read_text()); action=args[0]
    if action=='get':
        if args[1] not in data: sys.exit(1)
        print(data[args[1]])
    elif action=='changes':
        if os.environ.get('USB_HOLD'):
            (root/'hold-ready').touch()
            deadline=time.monotonic()+5
            while (root/'hold').exists() and time.monotonic()<deadline: time.sleep(.01)
        if os.environ.get('USB_PENDING'): print('pending administrator changes')
    elif action=='set':
        if os.environ.get('USB_FAIL')=='set': sys.exit(1)
        key,value=args[1].split('=',1); data[key]=value; path.write_text(json.dumps(data))
    elif action=='delete':
        data.pop(args[1],None); path.write_text(json.dumps(data))
    elif action=='commit':
        if os.environ.get('USB_FAIL')=='commit': sys.exit(1)
    else: sys.exit(2)
elif command in ('ifup','ifdown'):
    if os.environ.get('USB_FAIL')==command: sys.exit(1)
elif command=='ubus':
    if args!=['call','network','reload']: sys.exit(2)
    if os.environ.get('USB_FAIL')=='reload': sys.exit(1)
elif command=='sleep': time.sleep(.05)
else: sys.exit(2)
'''


class UsbwanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.sysfs = self.root/'sys'
        for path in ('sys/devices', 'sys/class/net', 'sys/bus/usb/drivers',
                     'etc/config', 'var/run/tr3000-lite', 'var/lock', 'tmp', 'bin'):
            (self.root/path).mkdir(parents=True)
        self.state = {'network.wan.device':'eth0', 'network.plant.device':'eth1',
                      'network.mgmt.device':'br-mgmt', 'network.usbwan':'interface',
                      'network.usbwan.proto':'dhcp', 'network.usbwan.metric':'30',
                      'network.usbwan.auto':'0'}
        self.save()
        (self.root/'bin/fake.py').write_text(FAKE)
        for command in ('uci', 'ifup', 'ifdown', 'ubus', 'sleep'):
            path = self.root/'bin'/command
            path.write_text('#!/bin/sh\nexec "$USB_PYTHON" -S "$USB_FIXTURE/bin/fake.py" '+command+' "$@"\n')
            path.chmod(0o755)

    def save(self):
        (self.root/'etc/config/network').write_text(json.dumps(self.state))

    def load(self):
        return json.loads((self.root/'etc/config/network').read_text())

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

    def classify(self, name):
        self.assertTrue(LIB.is_file(), 'USB classifier library is missing')
        return subprocess.run([bash_executable(), '-c', '. "$1"; tr3000_lite_usbwan_classify "$2" "$3"',
                               'classify', str(LIB), name, str(self.sysfs)], capture_output=True, text=True)

    def hook(self, action='add', device='modem7', background=False, **extra):
        self.assertTrue(HOOK.is_file(), 'Lite USB hotplug hook is missing')
        source = HOOK.read_text().replace('PATH=/usr/sbin:/usr/bin:/sbin:/bin',
                                          'PATH="'+str(self.root/'bin')+':/usr/bin:/bin"')
        source = source.replace('/usr/lib/tr3000-lite/usbwan-lib.sh', str(LIB))
        for path in ('/sys', '/etc/config', '/var/run', '/var/lock', '/tmp/.uci'):
            source = source.replace(path, str(self.root)+path)
        script = self.root/'hook.sh'
        script.write_text(source)
        env=dict(os.environ, USB_FIXTURE=str(self.root), USB_PYTHON=sys.executable,
                 ACTION=action, INTERFACE=device, DEVPATH='/untrusted/unused', **extra)
        if background:
            return subprocess.Popen([bash_executable(), str(script)], stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, text=True, env=env)
        return subprocess.run([bash_executable(), str(script)], capture_output=True, text=True, env=env)

    def calls(self):
        path=self.root/'calls.jsonl'
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def status(self):
        return json.loads((self.root/'var/run/tr3000-lite/usbwan.json').read_text())

    def test_classifier_requires_supported_usb_driver_and_parent(self):
        for name, driver, usb, approved in (
            ('rndis9','rndis_host',True,True), ('ether3','cdc_ether',True,True),
            ('ncm','cdc_ncm',True,False), ('qmi','qmi_wwan',True,False),
            ('mbim','cdc_mbim',True,False), ('pci','rndis_host',False,False),
            ('virtual',None,False,False), ('nodriver',None,True,False)):
            with self.subTest(driver=driver, usb=usb):
                self.add_device(name, driver, usb)
                result=self.classify(name)
                self.assertEqual(approved, result.returncode==0, result.stderr)
                if approved:
                    fields=result.stdout.strip().split('\t')
                    self.assertEqual([driver, '2c7c', '0125'], fields[:3])
                    self.assertTrue(fields[3].startswith('/devices/'))
                else:
                    self.assertEqual('', result.stdout)

    def test_classifier_rejects_malformed_usb_identifiers(self):
        device=self.add_device()
        for bad in ('', 'abc', 'ab:c', 'zzzz', '12345', '12\n34'):
            with self.subTest(value=bad):
                (device.parent/'idVendor').write_text(bad+'\n')
                result=self.classify('modem7')
                self.assertNotEqual(0, result.returncode)
                self.assertEqual('', result.stdout)
        (device.parent/'idVendor').write_text('2C7C\n')
        result=self.classify('modem7')
        self.assertEqual(0, result.returncode)
        self.assertEqual('2c7c', result.stdout.split('\t')[1])

    def test_classifier_rejects_unsafe_names_and_external_paths(self):
        self.add_device()
        for name in ('../modem7', '.', '..', '-x', 'bad name', 'x'*16, 'absent'):
            with self.subTest(name=name):
                self.assertNotEqual(0, self.classify(name).returncode)
        external=self.root/'outside'; external.mkdir()
        (self.sysfs/'class/net/modem7/device').unlink()
        (self.sysfs/'class/net/modem7/device').symlink_to(external)
        self.assertNotEqual(0, self.classify('modem7').returncode)

    def test_attach_remove_and_repeat_are_idempotent(self):
        self.add_device()
        result=self.hook()
        self.assertEqual(0, result.returncode, result.stderr)
        state=self.load()
        self.assertEqual('modem7', state['network.usbwan.device'])
        self.assertEqual('1', state['network.usbwan.auto'])
        self.assertEqual('eth0', state['network.wan.device'])
        self.assertEqual('bound', self.status()['state'])
        self.assertEqual('rndis_host', self.status()['driver'])
        self.assertEqual('2c7c', self.status()['vid'])
        self.assertEqual([['ifup','usbwan']], [call for call in self.calls() if call[0]=='ifup'])
        before=list(self.calls())
        self.assertEqual(0, self.hook().returncode)
        self.assertEqual(before, self.calls()[:len(before)])
        self.assertEqual(1, sum(call[0]=='ifup' for call in self.calls()))
        self.assertEqual(0, self.hook('remove', 'unrelated').returncode)
        self.assertEqual(state, self.load())
        shutil.rmtree(self.sysfs/'class/net/modem7')
        self.assertEqual(0, self.hook('remove').returncode)
        self.assertNotIn('network.usbwan.device', self.load())
        self.assertEqual('0', self.load()['network.usbwan.auto'])
        self.assertEqual('unavailable', self.status()['state'])
        self.assertIn(['ifdown','usbwan'], self.calls())
        self.assertEqual(0, self.hook('remove').returncode)
        self.assertEqual(1, sum(call[0]=='ifdown' for call in self.calls()))

    def test_unsupported_and_unrelated_devices_are_not_claimed(self):
        self.add_device('ncm', 'cdc_ncm')
        self.assertEqual(0, self.hook(device='ncm').returncode)
        self.assertEqual(self.state, self.load())
        self.assertFalse(any(call[0]=='ifup' for call in self.calls()))

    def test_multiple_candidates_fail_closed_and_recover_after_removal(self):
        self.add_device()
        self.assertEqual(0, self.hook().returncode)
        self.add_device('ether9', 'cdc_ether')
        self.assertEqual(0, self.hook(device='ether9').returncode)
        self.assertNotIn('network.usbwan.device', self.load())
        self.assertEqual('ambiguous', self.status()['state'])
        self.assertIn(['ifdown','usbwan'], self.calls())
        shutil.rmtree(self.sysfs/'class/net/ether9')
        self.assertEqual(0, self.hook('remove','ether9').returncode)
        self.assertEqual('modem7', self.load()['network.usbwan.device'])

    def test_existing_manual_binding_and_protected_interfaces_are_not_stolen(self):
        self.add_device()
        for values in ({'network.usbwan.device':'manual0'}, {'network.wan.device':'modem7'},
                       {'network.plant.device':'modem7'}, {'network.mgmt.device':'modem7'},
                       {'network.wwan.device':'modem7'}):
            with self.subTest(values=values):
                self.state={'network.usbwan':'interface','network.usbwan.proto':'dhcp',
                            'network.usbwan.metric':'30','network.usbwan.auto':'0',**values}
                self.save()
                self.assertNotEqual(0, self.hook().returncode)
                self.assertEqual(self.state, self.load())
                self.assertFalse(any(call[0]=='ifup' for call in self.calls()))

    def test_pending_changes_failure_and_unsafe_runtime_leave_live_config_unchanged(self):
        self.add_device()
        for failure in ('set','commit','reload','ifup'):
            with self.subTest(failure=failure):
                self.save()
                self.assertNotEqual(0, self.hook(USB_FAIL=failure).returncode)
                self.assertEqual(self.state, self.load())
        self.assertNotEqual(0, self.hook(USB_PENDING='1').returncode)
        self.assertEqual(self.state, self.load())
        self.assertFalse((self.root/'var/run/tr3000-lite/usbwan.lock').exists())
        lock=self.root/'var/run/tr3000-lite/usbwan.lock'; lock.mkdir()
        self.assertNotEqual(0, self.hook().returncode)
        self.assertTrue(lock.exists(), 'never remove another hotplug owner lock')
        self.assertEqual(self.state, self.load())

    def test_unsupported_netdev_after_supported_one_does_not_erase_selection_metadata(self):
        self.add_device('modem7', 'rndis_host')
        self.add_device('zzunsupported', 'cdc_ncm')
        result=self.hook()
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual('modem7', self.load()['network.usbwan.device'])
        self.assertEqual('rndis_host', self.status()['driver'])

    def test_plant_transaction_lock_prevents_network_file_races(self):
        self.add_device()
        lock=self.root/'var/lock/tr3000-lite-plant'
        lock.mkdir()
        result=self.hook()
        self.assertNotEqual(0, result.returncode)
        self.assertTrue(lock.exists(), 'never remove the plant transaction owner lock')
        self.assertEqual(self.state, self.load())
        self.assertFalse(any(call[0]=='ifup' for call in self.calls()))

    def test_delayed_remove_does_not_detach_replugged_device(self):
        self.add_device()
        self.assertEqual(0, self.hook().returncode)
        # sysfs already shows a live NIC again when an older remove arrives.
        self.assertEqual(0, self.hook('remove').returncode)
        self.assertEqual('modem7', self.load()['network.usbwan.device'])
        self.assertFalse(any(call[0]=='ifdown' for call in self.calls()))

    def test_unplug_during_attach_serializes_and_reconciles_without_stale_ifup(self):
        self.add_device()
        hold=self.root/'hold'; hold.touch()
        first=self.hook(background=True, USB_HOLD='1')
        second=None
        try:
            deadline=time.monotonic()+4
            while not (self.root/'hold-ready').exists() and time.monotonic()<deadline:
                time.sleep(.01)
            self.assertTrue((self.root/'hold-ready').exists(), 'attach never reached UCI barrier')
            shutil.rmtree(self.sysfs/'class/net/modem7')
            second=self.hook('remove', background=True)
            deadline=time.monotonic()+2
            while not any(call[0]=='sleep' for call in self.calls()) and time.monotonic()<deadline:
                time.sleep(.01)
            self.assertTrue(any(call[0]=='sleep' for call in self.calls()), 'second event did not wait for lock')
            hold.unlink()
            out, err=first.communicate(timeout=5)
            self.assertNotEqual(0, first.returncode, out+err)
            out, err=second.communicate(timeout=5)
            self.assertEqual(0, second.returncode, out+err)
            self.assertEqual(self.state, self.load())
            self.assertEqual('unavailable', self.status()['state'])
            self.assertFalse(any(call[0]=='ifup' for call in self.calls()))
            self.assertFalse((self.root/'var/run/tr3000-lite/usbwan.lock').exists())
        finally:
            hold.unlink(missing_ok=True)
            for process in (first, second):
                if process is not None:
                    if process.poll() is None: process.kill()
                    process.communicate()

    def test_periodic_rescan_recovers_event_missed_during_plant_transaction(self):
        self.add_device()
        lock=self.root/'var/lock/tr3000-lite-plant'; lock.mkdir()
        self.assertNotEqual(0,self.hook().returncode)
        self.assertEqual(self.state,self.load())
        lock.rmdir()
        result=self.hook('reconcile','tr3000-rescan')
        self.assertEqual(0,result.returncode,result.stderr)
        self.assertEqual('modem7',self.load().get('network.usbwan.device'))
        self.assertEqual('bound',self.status()['state'])

    def test_lite_configuration_installs_library_and_executable_hook(self):
        result, _, assets=run_lite_configure(lite_base_config())
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn('files/usr/lib/tr3000-lite/usbwan-lib.sh', assets)
        self.assertIn('files/etc/hotplug.d/net/90-tr3000-lite-usbwan', assets)


if __name__=='__main__':
    unittest.main()
