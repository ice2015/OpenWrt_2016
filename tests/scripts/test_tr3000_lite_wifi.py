"""Run the AP defaults with isolated UCI, entropy and hardware inputs."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tests.scripts.test_scripts import ROOT, bash_executable
from tests.scripts import test_tr3000_lite_plant as plant_tests

SCRIPT = ROOT/'overlays/devices/tr3000-lite/files/etc/uci-defaults/91-tr3000-lite-management-ap'
FAKE = r'''
import json, os, pathlib, sys
# Mirror Linux UCI bytes even when this command double runs on Windows.
sys.stdout.reconfigure(encoding='utf-8', newline='\n')
r=pathlib.Path(os.environ['WIFI_FIXTURE']); a=[x for x in sys.argv[1:] if x!='-q']
extended='-X' not in a
if not extended: a.remove('-X')
directory=pathlib.Path(a[a.index('-c')+1])
delta=pathlib.Path(a[a.index('-t')+1])/'wireless'
for flag in ('-c','-C','-t'):
    if flag in a:
        i=a.index(flag); del a[i:i+2]
p=directory/'wireless'; d=json.loads(p.read_text()); action=a[0]
if delta.is_file(): d=json.loads(delta.read_text())
names=[k for k,v in d.items() if v=='wifi-device']
def selector(k):
    for i,name in enumerate(names):
        if name.startswith('wireless.cfg') and (k==name or k.startswith(name+'.')):
            return 'wireless.@wifi-device['+str(i)+']'+k[len(name):]
    return k
def internal(k):
    for i,name in enumerate(names):
        alias='wireless.@wifi-device['+str(i)+']'
        if k==alias or k.startswith(alias+'.'): return name+k[len(alias):]
    return k
if action=='show':
    for k,v in d.items():
        k=selector(k) if extended else k
        print(k+'='+v if v in ('wifi-device','wifi-iface') else k+"='"+v+"'")
elif action=='get':
    a[1]=internal(a[1])
    if a[1] not in d: sys.exit(1)
    print(d[a[1]])
elif action=='set':
    if os.environ.get('FAIL_STAGE')=='uci_set': sys.exit(1)
    k,v=a[1].split('=',1); d[internal(k)]=v; delta.write_text(json.dumps(d))
elif action=='commit':
    if os.environ.get('FAIL_COMMIT'): sys.exit(1)
    if os.environ.get('NOOP_COMMIT'): sys.exit(0)
    (r/'committed.json').write_text(json.dumps(d))
    if os.environ.get('BAD_COMMIT'):
        d.pop('wireless.tr3000_lite_mgmt_radio0.key',None)
    p.write_text(json.dumps(d)); delta.unlink(missing_ok=True)
else: sys.exit(2)
'''


class ManagementAPTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        for p in ('etc/config','etc/uci-defaults','sys/class/net/eth0','bin','tmp'):
            (self.root/p).mkdir(parents=True)
        (self.root/'etc/config/wireless').touch()
        (self.root/'etc/shadow').write_text('root:!:0:0:99999:7:::\n')
        (self.root/'sys/class/net/eth0/address').write_text('02:ab:cd:12:34:ef\n')
        (self.root/'random').write_bytes(bytes(range(16))*4)
        (self.root/'bin/fake.py').write_text(FAKE)
        uci=self.root/'bin/uci'
        uci.write_text('#!/bin/sh\nexec "$TEST_PYTHON" -S "$WIFI_FIXTURE/bin/fake.py" "$@"\n',newline='\n'); uci.chmod(0o755)
        self.state={'wireless.radio0':'wifi-device','wireless.radioOdd':'wifi-device'}
        self.save()

    def save(self): (self.root/'etc/config/wireless').write_text(json.dumps(self.state))
    def load(self): return json.loads((self.root/'etc/config/wireless').read_text())
    def marker(self): return self.root/'etc/tr3000-lite/management-ap.initialized'

    def run_ap(self, success=True, **extra):
        self.assertTrue(SCRIPT.is_file(), 'management AP defaults script is missing')
        text=SCRIPT.read_text().replace('PATH=/usr/sbin:/usr/bin:/sbin:/bin','PATH="$(cd "$WIFI_FIXTURE/bin" && pwd):/usr/bin:/bin"')
        text=text.replace('RUNTIME=/tmp','RUNTIME="'+self.root.as_posix()+'/tmp"')
        for old,new in (('/etc/',self.root.as_posix()+'/etc/'),('/sys/',self.root.as_posix()+'/sys/'),('/var/',self.root.as_posix()+'/var/'),('/dev/urandom',(self.root/'random').as_posix())):
            text=text.replace(old,new)
        installed=self.root/'etc/uci-defaults/91-tr3000-lite-management-ap'
        installed.write_text(text,newline='\n')
        lock=self.root/'tmp/tr3000-lite-management-ap.lock'; already_locked=lock.exists()
        # Match pinned boot: sourced defaults run as the left side of &&.
        # set -e inside the sourced file is deliberately ineffective here.
        runner=r'''
mv() {
    case "${FAIL_STAGE-}:$2" in
        live_install:*/etc/config/wireless|marker_move:*/management-ap.initialized|suffix_move:*/ap-suffix) return 1;;
    esac
    command mv "$@"
}
printf() {
    if [ "${FAIL_STAGE-}" = marker_write ] && [ "$1" = 'initialized\n' ]; then return 1; fi
    command printf "$@"
}
cp() { [ "${FAIL_STAGE-}" != copy ] || return 1; command cp "$@"; }
chmod() { [ "${FAIL_STAGE-}" != chmod ] || return 1; command chmod "$@"; }
mkdir() {
    if [ "${FAIL_STAGE-}" = delta_mkdir ]; then case "$1" in */delta) return 1;; esac; fi
    command mkdir "$@"
}
file=91-tr3000-lite-management-ap
( . "./$(basename "$file")" ) && rm -f "$file"
'''
        r=subprocess.run([bash_executable(),'-c',runner],cwd=installed.parent,capture_output=True,text=True,env=dict(os.environ,WIFI_FIXTURE=self.root.as_posix(),TEST_PYTHON=Path(sys.executable).as_posix(),**extra))
        self.assertEqual(success,r.returncode==0,r.stdout+r.stderr)
        self.assertEqual(success,self.marker().is_file())
        self.assertEqual(not success,installed.exists())
        self.assertEqual(already_locked,lock.exists(), 'runtime lock ownership/cleanup changed')
        self.assertNotIn('000102030405060708090a0b0c0d0e0f',r.stdout+r.stderr)
        return self.load()

    def aps(self,d): return [k for k,v in d.items() if v=='wifi-iface' and d.get(k+'.tr3000_lite_managed')=='1']

    def test_detected_radios_have_encrypted_shared_identity(self):
        d=self.run_ap(); aps=self.aps(d); self.assertEqual(2,len(aps))
        for ap in aps:
            for option,value in {'mode':'ap','network':'mgmt','encryption':'psk2','disabled':'0','ssid':'TR3000-Lite-1234EF','key':'000102030405060708090a0b0c0d0e0f'}.items(): self.assertEqual(value,d[ap+'.'+option])
        self.assertEqual({'radio0','radioOdd'},{d[a+'.device'] for a in aps})

    def test_repeat_and_new_radio_preserve_credentials(self):
        first=self.run_ap(); self.assertEqual(first,self.run_ap())
        self.state=first; self.state['wireless.extra']='wifi-device'; self.save()
        d=self.run_ap(); self.assertEqual(3,len(self.aps(d)))
        self.assertEqual({'TR3000-Lite-1234EF'},{d[a+'.ssid'] for a in self.aps(d)})

    def test_existing_nonempty_managed_identity_is_preserved(self):
        a='wireless.saved'; self.state.update({a:'wifi-iface',a+'.tr3000_lite_managed':'1',a+'.device':'radio0',a+'.ssid':'Bench management',a+'.key':'preserved-secure-passphrase'})
        self.save(); d=self.run_ap()
        self.assertEqual({'Bench management'},{d[a+'.ssid'] for a in self.aps(d)})
        self.assertEqual({'preserved-secure-passphrase'},{d[a+'.key'] for a in self.aps(d)})

    def test_existing_utf8_ssid_is_preserved_as_bytes(self):
        a='wireless.saved'; self.state.update({a:'wifi-iface',a+'.tr3000_lite_managed':'1',a+'.device':'radio0',a+'.ssid':'现场管理网络',a+'.key':'preserved-secure-passphrase'})
        self.save(); d=self.run_ap()
        self.assertEqual({'现场管理网络'},{d[a+'.ssid'] for a in self.aps(d)})

    def test_saved_ssid_byte_limit_and_controls_are_rejected(self):
        for ssid in ('管'*11,'bench\n','bench\t'):
            with self.subTest(ssid=repr(ssid)):
                a='wireless.saved'; self.state.update({a:'wifi-iface',a+'.tr3000_lite_managed':'1',a+'.device':'radio0',a+'.ssid':ssid,a+'.key':'preserved-secure-passphrase'})
                self.marker().unlink(missing_ok=True)
                self.save(); self.run_ap(False)

    def test_no_radios_remains_retryable(self):
        self.state={}; self.save(); self.run_ap(False)

    def test_upstream_open_ap_disabled_and_sta_preserved(self):
        self.state.update({'wireless.radio0.disabled':'1','wireless.default_radio0':'wifi-iface','wireless.default_radio0.device':'radio0','wireless.default_radio0.mode':'ap','wireless.default_radio0.encryption':'none','wireless.sta':'wifi-iface','wireless.sta.device':'radio0','wireless.sta.mode':'sta','wireless.sta.disabled':'0','wireless.secure':'wifi-iface','wireless.secure.device':'radio0','wireless.secure.mode':'ap','wireless.secure.encryption':'sae','wireless.secure.disabled':'0'})
        self.save(); d=self.run_ap()
        self.assertEqual('1',d.get('wireless.default_radio0.disabled'))
        self.assertEqual('0',d['wireless.radio0.disabled'])
        self.assertEqual('psk2',d['wireless.tr3000_lite_mgmt_radio0.encryption'])
        self.assertEqual('0',d['wireless.sta.disabled'])
        self.assertEqual('0',d['wireless.secure.disabled'])
        self.assertEqual('sae',d['wireless.secure.encryption'])

    def test_marker_directory_cannot_complete_initialization(self):
        self.marker().mkdir(parents=True); self.run_ap(False)

    def test_stale_persistent_lock_cannot_block_boot_retry(self):
        (self.root/'etc/tr3000-lite/ap.lock').mkdir(parents=True)
        self.run_ap()
        self.assertFalse((self.root/'tmp/tr3000-lite-management-ap.lock').exists())

    def test_concurrent_runtime_lock_fails_busy_without_removing_owner_lock(self):
        lock=self.root/'tmp/tr3000-lite-management-ap.lock'; lock.mkdir()
        self.run_ap(False)
        self.assertTrue(lock.is_dir())

    def test_anonymous_detected_radio_is_supported(self):
        self.state={'wireless.cfg012345':'wifi-device'}; self.save()
        d=self.run_ap(); self.assertEqual(1,len(self.aps(d)))
        self.assertEqual('cfg012345',d[self.aps(d)[0]+'.device'])
        self.assertNotIn('@wifi-device[',json.dumps(d))

    def test_sourced_boot_commit_failure_or_noop_retains_script_and_live_config(self):
        for failure in ('FAIL_COMMIT','NOOP_COMMIT'):
            with self.subTest(failure=failure):
                self.state={'wireless.radio0':'wifi-device'}; self.save()
                self.marker().unlink(missing_ok=True)
                original=(self.root/'etc/config/wireless').read_bytes()
                self.run_ap(False,**{failure:'1'})
                self.assertEqual(original,(self.root/'etc/config/wireless').read_bytes())

    def test_sourced_boot_required_mutation_failures_remain_retryable(self):
        for stage in ('delta_mkdir','copy','chmod','uci_set','live_install','marker_write','marker_move','suffix_move'):
            with self.subTest(stage=stage):
                self.state={'wireless.radio0':'wifi-device'}; self.save()
                self.marker().unlink(missing_ok=True)
                if stage=='suffix_move':
                    (self.root/'sys/class/net/eth0/address').write_text('00:00:00:00:00:00')
                before=self.load()
                d=self.run_ap(False,FAIL_STAGE=stage)
                if stage in ('marker_write','marker_move'):
                    self.assertEqual('psk2',d['wireless.tr3000_lite_mgmt_radio0.encryption'])
                    self.assertEqual(32,len(d['wireless.tr3000_lite_mgmt_radio0.key']))
                else: self.assertEqual(before,d)

    def test_existing_raw_wpa_psk_is_preserved(self):
        a='wireless.saved'; self.state.update({a:'wifi-iface',a+'.tr3000_lite_managed':'1',a+'.device':'radio0',a+'.ssid':'saved',a+'.key':'a'*64})
        self.save(); d=self.run_ap(); self.assertEqual({'a'*64},{d[a+'.key'] for a in self.aps(d)})

    def test_bad_credentials_remain_retryable(self):
        a='wireless.saved'; self.state.update({a:'wifi-iface',a+'.tr3000_lite_managed':'1',a+'.device':'radio0',a+'.ssid':'saved'})
        self.save(); self.run_ap(False)

    def test_commit_or_verification_failure_never_marks_initialized(self):
        for failure in ('FAIL_COMMIT','BAD_COMMIT'):
            with self.subTest(failure=failure):
                self.save(); self.run_ap(False,**{failure:'1'})

    def test_random_fallback_suffix_is_persisted(self):
        (self.root/'sys/class/net/eth0/address').write_text('00:00:00:00:00:00')
        d=self.run_ap(); self.assertEqual({'TR3000-Lite-000102'},{d[a+'.ssid'] for a in self.aps(d)})
        self.assertEqual(d,self.run_ap())

    def test_ap_creation_does_not_mutate_plant_policy(self):
        firewall=ROOT/'overlays/devices/tr3000-lite/files/etc/config/firewall'
        policy=ROOT/'overlays/devices/tr3000-lite/files/etc/config/tr3000-lite'
        for p in (firewall,policy): (self.root/'etc/config'/p.name).write_bytes(p.read_bytes())
        self.run_ap()
        for p in (firewall,policy): self.assertEqual(p.read_bytes(),(self.root/'etc/config'/p.name).read_bytes())

    @unittest.skipIf(os.name=='nt','NTFS does not model Linux chmod; verify on Linux/firmware')
    def test_wireless_credentials_are_private(self):
        self.run_ap(); self.assertEqual(0o600,(self.root/'etc/config/wireless').stat().st_mode & 0o777)


class ManagementGateTests(unittest.TestCase):
    setUp = plant_tests.PlantControllerTests.setUp
    reset_live = plant_tests.PlantControllerTests.reset_live
    unchanged = plant_tests.PlantControllerTests.unchanged
    run_controller = plant_tests.PlantControllerTests.run_controller
    def test_root_password_and_ap_marker_both_required(self):
        for password,marker,code in (('!',False,2),('$6$fixture',False,2),('!',True,2),('',True,2),('$6$fixture',True,0)):
            with self.subTest(password_set=bool(password),marker=marker):
                self.reset_live()
                (self.root/'etc/shadow').write_text('root:'+password+':0:0:99999:7:::\n')
                p=self.root/'etc/tr3000-lite/management-ap.initialized'; p.parent.mkdir(exist_ok=True)
                if marker: p.touch()
                else: p.unlink(missing_ok=True)
                self.run_controller('apply','--address','192.168.20.254/24','--allow-luci','true','--allow-mgmt','true',code=code)
                if code: self.unchanged()
