"""Run the AP defaults with isolated UCI, entropy and hardware inputs."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tests.scripts.test_scripts import ROOT, bash_executable
from tests.scripts import test_tr3000_lite_plant as plant_tests

# The fixture's fake /dev/urandom. The controller derives the key and the
# fallback suffix from it with busybox head+sha256sum (od is not shipped).
FIXTURE_RANDOM = bytes(range(16)) * 4
FIXTURE_KEY = hashlib.sha256(FIXTURE_RANDOM[:16]).hexdigest()[:32]
FIXTURE_SUFFIX = hashlib.sha256(FIXTURE_RANDOM[:3]).hexdigest()[:6].upper()

SCRIPT = ROOT/'overlays/devices/tr3000-lite/files/etc/uci-defaults/91-tr3000-lite-management-ap'
FAKE = r'''
import hashlib, json, os, pathlib, sys
# Mirror Linux UCI bytes even when this command double runs on Windows.
sys.stdout.reconfigure(encoding='utf-8', newline='\n')
r=pathlib.Path(os.environ['WIFI_FIXTURE']); a=[x for x in sys.argv[1:] if x!='-q']
extended='-X' not in a
if not extended: a.remove('-X')
export_names='-n' in a
if export_names: a.remove('-n')
delimiter=' '
if '-d' in a:
    i=a.index('-d'); delimiter=a[i+1]; del a[i:i+2]
directory=pathlib.Path(a[a.index('-c')+1])
p=directory/'wireless'
delta=pathlib.Path(a[a.index('-t')+1])/'wireless' if '-t' in a else None
for flag in ('-c','-C','-t'):
    if flag in a:
        i=a.index(flag); del a[i:i+2]
d=json.loads(p.read_text()); action=a[0]
if delta is not None and delta.is_file(): d=json.loads(delta.read_text())
if delta is None: delta=p
names=[k for k,v in d.items() if v=='wifi-device']
anonymous=d.get('.anonymous',[])
def selector(k):
    for i,name in enumerate(names):
        if name in anonymous and (k==name or k.startswith(name+'.')):
            return 'wireless.@wifi-device['+str(i)+']'+k[len(name):]
    return k
def internal(k):
    for i,name in enumerate(names):
        alias='wireless.@wifi-device['+str(i)+']'
        if k==alias or k.startswith(alias+'.'): return name+k[len(alias):]
    return k
if action=='show':
    for k,v in d.items():
        if k=='.anonymous': continue
        k=selector(k) if extended else k
        print(k+'='+v if v in ('wifi-device','wifi-iface') else k+'='+(' '.join("'"+x+"'" for x in v) if isinstance(v,list) else "'"+v+"'"))
elif action=='export':
    def quote(value): return "'"+value.replace("'", "'\\''")+"'"
    print('package wireless')
    for section,kind in d.items():
        if kind not in ('wifi-device','wifi-iface'): continue
        print('\nconfig '+kind+(' '+quote(section.split('.',1)[1]) if export_names or section not in anonymous else ''))
        for option,value in d.items():
            if not option.startswith(section+'.'): continue
            name=option[len(section)+1:]
            if isinstance(value,list):
                for entry in value: print('\tlist '+name+' '+quote(entry))
            else: print('\toption '+name+' '+quote(value))
elif action=='get':
    a[1]=internal(a[1])
    if a[1] not in d: sys.exit(1)
    value=d[a[1]]; print(delimiter.join(value) if isinstance(value,list) else value)
elif action=='set':
    if os.environ.get('FAIL_STAGE')=='uci_set': sys.exit(1)
    k,v=a[1].split('=',1); d[internal(k)]=v; delta.write_text(json.dumps(d))
elif action=='rename':
    if os.environ.get('FAIL_STAGE')=='uci_rename': sys.exit(1)
    old,new=a[1].split('=',1); old=internal(old); new='wireless.'+new
    if old not in d or new in d: sys.exit(1)
    d={new+k[len(old):] if k==old or k.startswith(old+'.') else k:v for k,v in d.items()}
    d['.anonymous']=[name for name in anonymous if name!=old]
    delta.write_text(json.dumps(d))
elif action=='delete':
    d.pop(internal(a[1]),None); delta.write_text(json.dumps(d))
elif action=='add_list':
    k,v=a[1].split('=',1); k=internal(k)
    if k not in d: d[k]=[]
    elif not isinstance(d[k],list): d[k]=[d[k]]
    d[k].append(v); delta.write_text(json.dumps(d))
elif action=='commit':
    if os.environ.get('FAIL_COMMIT'): sys.exit(1)
    if os.environ.get('NOOP_COMMIT'): sys.exit(0)
    (r/'committed.json').write_text(json.dumps(d))
    if os.environ.get('BAD_COMMIT'):
        d.pop('wireless.tr3000_lite_mgmt_radio0.key',None)
    # Commit exports anonymous sections without names. Reload derives cfg...
    # from type/options, so changing disabled changes the internal name.
    reloaded=[]
    for old in anonymous:
        content=[(k[len(old):],v) for k,v in d.items() if k==old or k.startswith(old+'.')]
        new='wireless.cfg'+hashlib.sha1(json.dumps(content).encode()).hexdigest()[:6]
        d={new+k[len(old):] if k==old or k.startswith(old+'.') else k:v for k,v in d.items()}
        reloaded.append(new)
    if anonymous: d['.anonymous']=reloaded
    p.write_text(json.dumps(d))
    if delta != p: delta.unlink(missing_ok=True)
else: sys.exit(2)
'''


MTWIFI_STATE={
 'wireless.radio0':'wifi-device',
 'wireless.radio0.type':'mtwifi',
 'wireless.radio0.phy':'ra0',
 'wireless.radio0.country':'CN',
 'wireless.radio1':'wifi-device',
 'wireless.radio1.type':'mtwifi',
 'wireless.radio1.phy':'ra1',
 'wireless.default_radio0':'wifi-iface',
 'wireless.default_radio0.device':'radio0',
 'wireless.default_radio0.mode':'ap',
 'wireless.default_radio0.network':'lan',
 'wireless.default_radio0.ssid':'ImmortalWrt-2.4G',
 'wireless.default_radio0.encryption':'none',
 'wireless.default_radio1':'wifi-iface',
 'wireless.default_radio1.device':'radio1',
 'wireless.default_radio1.mode':'ap',
 'wireless.default_radio1.network':'lan',
 'wireless.default_radio1.ssid':'ImmortalWrt-5G',
 'wireless.default_radio1.encryption':'none',
}


class ManagementAPTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        for p in ('etc/config','etc/uci-defaults','sys/class/net/ra0','sys/class/net/eth0','bin','tmp'):
            (self.root/p).mkdir(parents=True)
        (self.root/'etc/config/wireless').touch()
        (self.root/'etc/shadow').write_text('root:!:0:0:99999:7:::\n')
        # The radio hardware names the management network; a wired port
        # address must never leak into the SSID.
        (self.root/'sys/class/net/ra0/address').write_text('02:ab:cd:12:34:ef\n')
        (self.root/'sys/class/net/eth0/address').write_text('aa:bb:cc:dd:ee:ff\n')
        (self.root/'random').write_bytes(FIXTURE_RANDOM)
        (self.root/'bin/fake.py').write_text(FAKE)
        uci=self.root/'bin/uci'
        uci.write_text('#!/bin/sh\nexec "$TEST_PYTHON" -S "$WIFI_FIXTURE/bin/fake.py" "$@"\n',newline='\n'); uci.chmod(0o755)
        # The firmware image ships a busybox without the "od" applet. A stub
        # that fails like a missing applet proves the controller never needs it.
        od=self.root/'bin/od'
        od.write_text('#!/bin/sh\ntouch "$WIFI_FIXTURE/od-used"\nexit 127\n',newline='\n'); od.chmod(0o755)
        self.state={'wireless.radio0':'wifi-device','wireless.radioOdd':'wifi-device'}
        self.save()

    def save(self): (self.root/'etc/config/wireless').write_text(json.dumps(self.state))
    def load(self): return json.loads((self.root/'etc/config/wireless').read_text())
    def marker(self): return self.root/'etc/tr3000-lite/management-ap.initialized'

    def run_ap(self, success=True, state=None, **extra):
        if state is not None:
            self.state=state; self.save()
        self.assertTrue(SCRIPT.is_file(), 'management AP defaults script is missing')
        text=SCRIPT.read_text().replace('PATH=/usr/sbin:/usr/bin:/sbin:/bin','PATH="$(cd "$WIFI_FIXTURE/bin" && pwd):/usr/bin:/bin"')
        text=text.replace('RUNTIME=/tmp','RUNTIME="'+self.root.as_posix()+'/tmp"')
        for old,new in (('/etc/',self.root.as_posix()+'/etc/'),('/sys/',self.root.as_posix()+'/sys/'),('/var/',self.root.as_posix()+'/var/'),('/tmp/.uci',self.root.as_posix()+'/tmp/.uci'),('/dev/urandom',(self.root/'random').as_posix())):
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
        self.assertNotIn(FIXTURE_KEY,r.stdout+r.stderr)
        return self.load()

    def aps(self,d): return [k for k,v in d.items() if v=='wifi-iface' and d.get(k+'.tr3000_lite_managed')=='1']

    def test_mtwifi_default_open_aps_are_disabled(self):
        d=self.run_ap(state=MTWIFI_STATE)
        self.assertEqual('1',d.get('wireless.default_radio0.disabled'))
        self.assertEqual('1',d.get('wireless.default_radio1.disabled'))

    def test_managed_ap_binds_the_access_segment_with_wpa2(self):
        d=self.run_ap(state=MTWIFI_STATE); aps=self.aps(d)
        self.assertEqual(2,len(aps))
        for ap in aps:
            self.assertEqual('lan',d[ap+'.network'])
            self.assertEqual('psk2',d[ap+'.encryption'])
            self.assertEqual('ap',d[ap+'.mode'])
            self.assertEqual('0',d[ap+'.disabled'])
            self.assertEqual(32,len(d[ap+'.key']))
            self.assertEqual('TR3000-Lite-1234EF',d[ap+'.ssid'])

    def test_ssid_suffix_uses_the_radio_mac_not_a_wired_port(self):
        d=self.run_ap(state=MTWIFI_STATE); aps=self.aps(d)
        self.assertEqual({'TR3000-Lite-1234EF'},{d[a+'.ssid'] for a in aps})

    def test_repeated_run_keeps_the_same_identity(self):
        first=self.run_ap(state=MTWIFI_STATE)
        second=self.run_ap(state=MTWIFI_STATE)
        for ap in self.aps(first):
            self.assertEqual(first[ap+'.ssid'],second[ap+'.ssid'])
            self.assertEqual(first[ap+'.key'],second[ap+'.key'])

    def ap_script_text(self):
        text=SCRIPT.read_text().replace('PATH=/usr/sbin:/usr/bin:/sbin:/bin','PATH="$(cd "$WIFI_FIXTURE/bin" && pwd):/usr/bin:/bin"')
        text=text.replace('RUNTIME=/tmp','RUNTIME="'+self.root.as_posix()+'/tmp"')
        for old,new in (('/etc/',self.root.as_posix()+'/etc/'),('/sys/',self.root.as_posix()+'/sys/'),('/var/',self.root.as_posix()+'/var/'),('/tmp/.uci',self.root.as_posix()+'/tmp/.uci'),('/dev/urandom',(self.root/'random').as_posix())):
            text=text.replace(old,new)
        return text

    def install_ap_script(self):
        target=self.root/'usr/sbin/tr3000-lite-wifi-ap'
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(self.ap_script_text(),newline='\n'); target.chmod(0o755)
        return target

    def install_fake_wifi(self):
        target=self.root/'bin/wifi'
        target.write_text('#!/bin/sh\ntouch "$WIFI_FIXTURE/reloaded"\n',newline='\n'); target.chmod(0o755)
        return target

    def run_service(self, *args, success=True, **extra):
        service=ROOT/'scripts/tr3000-lite-wifi.sh'
        self.assertTrue(service.is_file(),'wireless self-healing controller is missing')
        text=service.read_text().replace('PATH=/usr/sbin:/usr/bin:/sbin:/bin','PATH="$(cd "$WIFI_FIXTURE/bin" && pwd):/usr/bin:/bin"')
        for old,new in (('/etc/',self.root.as_posix()+'/etc/'),
                        ('/usr/sbin/tr3000-lite-wifi-ap',(self.root/'usr/sbin/tr3000-lite-wifi-ap').as_posix()),
                        ('/sbin/wifi',(self.root/'bin/wifi').as_posix())):
            text=text.replace(old,new)
        target=self.root/'bin/tr3000-lite-wifi'; target.write_text(text,newline='\n'); target.chmod(0o755)
        result=subprocess.run([bash_executable(),str(target),*args],capture_output=True,text=True,
                              env=dict(os.environ,WIFI_FIXTURE=self.root.as_posix(),TEST_PYTHON=Path(sys.executable).as_posix(),**extra))
        self.assertEqual(success,result.returncode==0,result.stdout+result.stderr)
        return result

    def test_repair_restores_a_missing_managed_ap(self):
        self.install_ap_script(); self.install_fake_wifi()
        self.state=dict(MTWIFI_STATE); self.save()
        self.run_service('repair')
        d=self.load()
        self.assertEqual(2,len(self.aps(d)))
        self.assertTrue(self.marker().is_file())
        self.assertTrue((self.root/'reloaded').exists())

    def test_repair_disables_a_resurrected_open_ap(self):
        self.install_ap_script(); self.install_fake_wifi()
        d=self.run_ap(state=MTWIFI_STATE)
        resurrected=dict(d); resurrected['wireless.default_radio0.disabled']='0'
        self.state=resurrected; self.save()
        self.marker().unlink(missing_ok=True)
        self.run_service('repair')
        self.assertEqual('1',self.load()['wireless.default_radio0.disabled'])
        self.assertTrue(self.marker().is_file())

    def test_repair_publishes_a_missing_readiness_marker(self):
        self.install_ap_script(); self.install_fake_wifi()
        self.run_ap(state=MTWIFI_STATE)
        self.marker().unlink(missing_ok=True)
        self.run_service('repair')
        self.assertTrue(self.marker().is_file())

    def test_marker_is_written_only_after_verification(self):
        self.install_ap_script(); self.install_fake_wifi()
        self.state={}; self.save()
        self.run_service('repair',success=False)
        self.assertFalse(self.marker().exists())

    def test_status_reports_the_management_ap_state(self):
        self.install_ap_script()
        self.run_ap(state=MTWIFI_STATE)
        data=json.loads(self.run_service('status','--json').stdout)
        self.assertTrue(data['ready'])
        self.assertEqual(2,data['radio_count'])
        self.assertEqual(2,data['managed_aps'])
        self.assertEqual(0,data['open_aps'])
        self.assertTrue(data['ssid_present'])
        self.assertTrue(data['key_present'])

    def test_detected_radios_have_encrypted_shared_identity(self):
        d=self.run_ap(); aps=self.aps(d); self.assertEqual(2,len(aps))
        for ap in aps:
            for option,value in {'mode':'ap','network':'lan','encryption':'psk2','disabled':'0','ssid':'TR3000-Lite-1234EF','key':FIXTURE_KEY}.items(): self.assertEqual(value,d[ap+'.'+option])
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

    def test_ap_creation_waits_for_the_radio_driver_configuration(self):
        # The radio driver publishes /etc/config/wireless a few seconds into
        # the boot. The controller must wait for it instead of failing the
        # first-boot identity before the radios are configured.
        (self.root/'etc/config/wireless').unlink(missing_ok=True)
        import threading
        def publish():
            import time
            time.sleep(4)
            (self.root/'etc/config/wireless').write_text(json.dumps(MTWIFI_STATE))
        publisher = threading.Thread(target=publish); publisher.start()
        d = self.run_ap(state=None)
        publisher.join()
        self.assertEqual(2, len(self.aps(d)))
        self.assertEqual('1', d.get('wireless.default_radio0.disabled'))

    def test_repair_service_retries_until_the_radio_configuration_exists(self):
        # The init service runs before the radio driver has published its
        # configuration, so it has to retry instead of giving up for the boot.
        self.install_ap_script(); self.install_fake_wifi()
        (self.root/'etc/config/wireless').unlink(missing_ok=True)
        init=ROOT/'overlays/devices/tr3000-lite/files/etc/init.d/tr3000-lite-wifi'
        self.assertTrue(init.is_file(),'the wireless init service is missing')
        text=init.read_text().replace('#!/bin/sh /etc/rc.common','#!/bin/sh')
        for old,new in (('/etc/',self.root.as_posix()+'/etc/'),
                        ('/usr/sbin/tr3000-lite-wifi',(self.root/'bin/tr3000-lite-wifi').as_posix()),
                        ('/sbin/wifi',(self.root/'bin/wifi').as_posix())):
            text=text.replace(old,new)
        # The controller and the fake wifi helper have to exist for the service.
        shutil_src=self.root/'bin/tr3000-lite-wifi'
        shutil_src.write_text((ROOT/'scripts/tr3000-lite-wifi.sh').read_text()
                              .replace('PATH=/usr/sbin:/usr/bin:/sbin:/bin','PATH="$(cd \"$WIFI_FIXTURE/bin\" && pwd):/usr/bin:/bin"')
                              .replace('/etc/',self.root.as_posix()+'/etc/')
                              .replace('/usr/sbin/tr3000-lite-wifi-ap',(self.root/'usr/sbin/tr3000-lite-wifi-ap').as_posix())
                              .replace('/sbin/wifi',(self.root/'bin/wifi').as_posix()),newline='\n')
        shutil_src.chmod(0o755)
        (self.root/'bin/logger').write_text('#!/bin/sh\nexit 0\n',newline='\n'); (self.root/'bin/logger').chmod(0o755)
        target=self.root/'bin/tr3000-lite-wifi-init'
        target.write_text(text,newline='\n'); target.chmod(0o755)
        import threading
        def publish():
            import time
            time.sleep(4)
            (self.root/'etc/config/wireless').write_text(json.dumps(MTWIFI_STATE))
        publisher=threading.Thread(target=publish); publisher.start()
        result=subprocess.run([bash_executable(),'-c','. "%s"; start' % target],
                              capture_output=True,text=True,timeout=180,
                              env=dict(os.environ,WIFI_FIXTURE=self.root.as_posix(),TEST_PYTHON=Path(sys.executable).as_posix()))
        publisher.join()
        self.assertEqual(0,result.returncode,result.stdout+result.stderr)
        d=self.load()
        self.assertEqual(2,len(self.aps(d)))
        self.assertTrue(self.marker().is_file())

    def test_marker_directory_cannot_complete_initialization(self):
        self.marker().mkdir(parents=True); self.run_ap(False)

    def test_empty_uci_runtime_delta_does_not_block_the_management_ap(self):
        # The radio driver creates an empty uci runtime delta on every boot.
        # It carries no pending change, so it must not keep the open default
        # access point enabled or block the managed AP.
        delta=self.root/'tmp/.uci/wireless'; delta.parent.mkdir(parents=True, exist_ok=True)
        delta.write_text('')
        d=self.run_ap(state=MTWIFI_STATE)
        self.assertEqual(2,len(self.aps(d)))
        self.assertEqual('1',d.get('wireless.default_radio0.disabled'))
        self.assertEqual('1',d.get('wireless.default_radio1.disabled'))
        self.assertTrue(self.marker().is_file())

    def test_pending_uci_runtime_delta_still_blocks_the_management_ap(self):
        # A delta that really carries a staged administrator change must keep
        # the controller from consuming it.
        delta=self.root/'tmp/.uci/wireless'; delta.parent.mkdir(parents=True, exist_ok=True)
        delta.write_text("package wireless\n")
        self.run_ap(False)
        self.assertFalse(self.marker().exists())

    def test_pending_uci_state_delta_still_blocks_the_management_ap(self):
        delta=self.root/'var/run/uci/wireless'; delta.parent.mkdir(parents=True, exist_ok=True)
        delta.write_text("package wireless\n")
        self.run_ap(False)
        self.assertFalse(self.marker().exists())

    def test_symlinked_uci_delta_is_rejected(self):
        delta=self.root/'tmp/.uci/wireless'; delta.parent.mkdir(parents=True, exist_ok=True)
        target=self.root/'tmp/.uci/real'
        target.write_text('')
        delta.symlink_to(target)
        self.run_ap(False)
        self.assertFalse(self.marker().exists())

    def test_stale_persistent_lock_cannot_block_boot_retry(self):
        (self.root/'etc/tr3000-lite/ap.lock').mkdir(parents=True)
        self.run_ap()
        self.assertFalse((self.root/'tmp/tr3000-lite-management-ap.lock').exists())

    def test_concurrent_runtime_lock_fails_busy_without_removing_owner_lock(self):
        lock=self.root/'tmp/tr3000-lite-management-ap.lock'; lock.mkdir()
        self.run_ap(False)
        self.assertTrue(lock.is_dir())

    def test_anonymous_detected_radio_is_supported(self):
        self.state={'wireless.cfg012345':'wifi-device','wireless.cfg012345.disabled':'1','.anonymous':['wireless.cfg012345']}; self.save()
        d=self.run_ap(); self.assertEqual(1,len(self.aps(d)))
        radio=d[self.aps(d)[0]+'.device']
        self.assertEqual('wifi-device',d['wireless.'+radio])
        self.assertEqual('0',d['wireless.'+radio+'.disabled'])
        self.assertEqual([],d['.anonymous'])
        self.assertNotIn('@wifi-device[',json.dumps(d))
        self.assertEqual(d,self.run_ap())

    def test_anonymous_rename_preserves_named_cfg_and_existing_iface_links(self):
        old='cfg012345'
        self.state={'wireless.'+old:'wifi-device','wireless.'+old+'.disabled':'1','.anonymous':['wireless.'+old],
                    'wireless.cfgNamed':'wifi-device','wireless.tr3000_lite_radio_0':'wifi-iface',
                    'wireless.sta':'wifi-iface','wireless.sta.device':old,'wireless.sta.mode':'sta',
                    'wireless.open':'wifi-iface','wireless.open.device':old,'wireless.open.mode':'ap','wireless.open.encryption':'none'}
        self.save(); d=self.run_ap()
        radio=d['wireless.sta.device']
        self.assertNotEqual(old,radio)
        self.assertNotEqual('tr3000_lite_radio_0',radio)
        self.assertEqual('wifi-device',d['wireless.'+radio])
        self.assertEqual('wifi-device',d['wireless.cfgNamed'])
        self.assertEqual('wifi-iface',d['wireless.tr3000_lite_radio_0'])
        self.assertEqual('sta',d['wireless.sta.mode'])
        self.assertEqual(radio,d['wireless.open.device'])
        self.assertEqual('1',d['wireless.open.disabled'])
        self.assertEqual({radio,'cfgNamed'},{d[ap+'.device'] for ap in self.aps(d)})
        self.assertEqual(d,self.run_ap())

    def test_anonymous_rename_failure_leaves_live_config_unchanged(self):
        self.state={'wireless.cfg012345':'wifi-device','wireless.cfg012345.disabled':'1','.anonymous':['wireless.cfg012345']}
        self.save(); before=self.load()
        self.assertEqual(before,self.run_ap(False,FAIL_STAGE='uci_rename'))

    def test_anonymous_rename_preserves_list_device_type_order_and_links(self):
        old='cfg012345'
        self.state={'wireless.'+old:'wifi-device','wireless.'+old+'.disabled':'1','.anonymous':['wireless.'+old],
                    'wireless.radio1':'wifi-device',
                    'wireless.sta':'wifi-iface','wireless.sta.device':['radio1',old,'radio1'],'wireless.sta.mode':'sta',
                    'wireless.secure':'wifi-iface','wireless.secure.device':[old,'radio1'],'wireless.secure.mode':'ap','wireless.secure.encryption':'sae',
                    'wireless.single':'wifi-iface','wireless.single.device':[old],'wireless.single.mode':'sta'}
        self.save(); d=self.run_ap()
        stable=next(d[ap+'.device'] for ap in self.aps(d) if d[ap+'.device']!='radio1')
        self.assertNotEqual(old,stable)
        self.assertEqual('wifi-device',d['wireless.'+stable])
        for interface,expected in (('sta',['radio1',stable,'radio1']),('secure',[stable,'radio1']),('single',[stable])):
            with self.subTest(interface=interface):
                self.assertEqual(expected,d['wireless.'+interface+'.device'])
        self.assertEqual('sta',d['wireless.sta.mode'])
        self.assertEqual('sae',d['wireless.secure.encryption'])
        self.assertEqual(d,self.run_ap())

    def test_list_open_ap_is_disabled_after_anonymous_reference_rename(self):
        old='cfg012345'
        self.state={'wireless.'+old:'wifi-device','wireless.'+old+'.disabled':'1','.anonymous':['wireless.'+old],
                    'wireless.radio1':'wifi-device',
                    'wireless.open':'wifi-iface','wireless.open.device':[old,'radio1'],'wireless.open.mode':'ap','wireless.open.encryption':'none',
                    'wireless.secure':'wifi-iface','wireless.secure.device':[old,'radio1'],'wireless.secure.mode':'ap','wireless.secure.encryption':'sae','wireless.secure.disabled':'0',
                    'wireless.sta':'wifi-iface','wireless.sta.device':['radio1',old],'wireless.sta.mode':'sta','wireless.sta.disabled':'0'}
        self.save(); d=self.run_ap()
        self.assertEqual('1',d.get('wireless.open.disabled'))
        self.assertEqual('0',d['wireless.secure.disabled'])
        self.assertEqual('0',d['wireless.sta.disabled'])
        self.assertEqual(d['wireless.secure.device'],d['wireless.open.device'])
        self.assertEqual(list(reversed(d['wireless.open.device'])),d['wireless.sta.device'])
        self.assertEqual(d,self.run_ap())

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
                    (self.root/'sys/class/net/ra0/address').write_text('00:00:00:00:00:00')
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
        # Without a usable radio address the suffix is random but persisted.
        (self.root/'sys/class/net/ra0/address').write_text('00:00:00:00:00:00')
        d=self.run_ap(); self.assertEqual({'TR3000-Lite-'+FIXTURE_SUFFIX},{d[a+'.ssid'] for a in self.aps(d)})
        self.assertEqual(d,self.run_ap())

    def test_management_ap_does_not_depend_on_the_od_applet(self):
        # The image has no "od"; the controller must derive its entropy from
        # the hash utilities instead of dumping the random bytes.
        d=self.run_ap(state=MTWIFI_STATE)
        self.assertEqual(2,len(self.aps(d)))
        self.assertFalse((self.root/'od-used').exists(),'the controller called od')
        for ap in self.aps(d):
            self.assertEqual(32,len(d[ap+'.key']))
            self.assertTrue(all(c in '0123456789abcdef' for c in d[ap+'.key']))

    def test_ap_creation_does_not_mutate_plant_policy(self):
        firewall=ROOT/'overlays/devices/tr3000-lite/files/etc/config/firewall'
        (self.root/'etc/config'/firewall.name).write_bytes(firewall.read_bytes())
        self.run_ap()
        self.assertEqual(firewall.read_bytes(),(self.root/'etc/config'/firewall.name).read_bytes())

    @unittest.skipIf(os.name=='nt','NTFS does not model Linux chmod; verify on Linux/firmware')
    def test_wireless_credentials_are_private(self):
        self.run_ap(); self.assertEqual(0o600,(self.root/'etc/config/wireless').stat().st_mode & 0o777)


class ManagementGateTests(unittest.TestCase):
    setUp = plant_tests.PlantControllerTests.setUp
    reset_live = plant_tests.PlantControllerTests.reset_live
    unchanged = plant_tests.PlantControllerTests.unchanged
    run_controller = plant_tests.PlantControllerTests.run_controller
    render_sections = plant_tests.PlantControllerTests.render_sections
    set_plant_section = plant_tests.PlantControllerTests.set_plant_section
    access_mode = plant_tests.PlantControllerTests.access_mode
    set_root_password = plant_tests.PlantControllerTests.set_root_password
    def test_plant_https_requires_only_a_root_password(self):
        # The plant Web gate is the root password plus the operator's explicit
        # choice; the management AP readiness guards the port handover instead.
        for password,marker,code in (('!',False,2),('$6$fixture',False,0),('!',True,2),('',True,2),('$6$fixture',True,0)):
            with self.subTest(password_set=bool(password),marker=marker):
                self.reset_live()
                (self.root/'etc/shadow').write_text('root:'+password+':0:0:99999:7:::\n')
                p=self.root/'etc/tr3000-lite/management-ap.initialized'; p.parent.mkdir(exist_ok=True)
                if marker: p.touch()
                else: p.unlink(missing_ok=True)
                self.run_controller('apply','--address','192.168.20.254/24','--allow-luci','true','--allow-mgmt','true',code=code)
                if code: self.unchanged()
