"""The fixed status RPC must expose only validated, public diagnostics."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tests.scripts.test_scripts import ROOT, bash_executable, lite_base_config, run_lite_configure

SCRIPT=ROOT/'scripts/tr3000-lite-uplink-status.sh'
SECRET='PRIVATE-key-token-and-hotspot-password'
FAKE=r'''
import json, os, pathlib, re, sys
root=pathlib.Path(os.environ['STATUS_FIXTURE']); d=json.loads((root/'fixture.json').read_text())
command=sys.argv[1]; args=sys.argv[2:]
with (root/'calls.jsonl').open('a') as f: f.write(json.dumps([command,*args])+'\n')
if command=='uci':
    args=[a for a in args if a not in ('-q','-X')]
    if args[0]=='show' and args[1]=='wireless':
        for k,v in d['uci'].items():
            print(k+'='+v if v in ('wifi-device','wifi-iface') else k+"='"+v+"'")
    elif args[0]=='get':
        if args[1] not in d['uci']: sys.exit(1)
        print(d['uci'][args[1]])
    else: sys.exit(2)
elif command=='ubus':
    if args[:3]==['call','network.wireless','status']: print(json.dumps(d['wireless']))
    elif args[:3]==['call','network.interface.wwan','status']: print(json.dumps(d['wwan']))
    elif args[:3]==['call','iwinfo','info']:
        name=json.loads(args[3])['device']
        if name not in d['iwinfo']: sys.exit(1)
        print(json.dumps(d['iwinfo'][name]))
    else: sys.exit(2)
elif command=='jsonfilter':
    value=json.loads(sys.stdin.read()); expr=args[args.index('-e')+1][1:]
    tokens=re.findall(r"\.([A-Za-z0-9_-]+)|\['([^']+)'\]|\[([0-9]+)\]",expr)
    try:
        for key,quoted,index in tokens: value=value[int(index)] if index else value[key or quoted]
    except (KeyError,IndexError,TypeError): sys.exit(1)
    if value is None: sys.exit(1)
    print(str(value).lower() if isinstance(value,bool) else json.dumps(value) if isinstance(value,(dict,list)) else value)
else: sys.exit(2)
'''


class UplinkStatusTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        for path in ('bin','var/run/tr3000-lite/uplink'):
            (self.root/path).mkdir(parents=True)
        (self.root/'bin/fake.py').write_text(FAKE)
        for name in ('uci','ubus','jsonfilter'):
            p=self.root/'bin'/name
            p.write_text('#!/bin/sh\nexec "$STATUS_PYTHON" -S "$STATUS_FIXTURE/bin/fake.py" '+name+' "$@"\n'); p.chmod(0o755)
        self.uplink={'schema_version':1,'active':'wan','previous':'wwan',
                     'last_event_error':False,'reconcile_error':False,'foreign_default':False,'interfaces':[]}
        for name,device,ip,gw,base in (
            ('wan','eth0','192.0.2.2','192.0.2.1',10),
            ('wwan','wlanOdd','198.51.100.2','198.51.100.1',20),
            ('usbwan','modem7','203.0.113.2','203.0.113.1',30)):
            self.uplink['interfaces'].append({'name':name,'device':device,'address':ip,'gateway':gw,
                'base_metric':base,'effective_metric':base,'health':'healthy','failures':0,'successes':0,'available':True})
        self.usb={'schema_version':1,'state':'bound','interface':'usbwan','device':'modem7',
                  'driver':'rndis_host','vid':'2c7c','pid':'0125','path':'/devices/platform/usb1/1-1/1-1:1.0'}
        self.data={'uci':{
            'wireless.radioOdd':'wifi-device','wireless.radioOther':'wifi-device',
            'wireless.management':'wifi-iface','wireless.management.device':'radioOdd',
            'wireless.management.mode':'ap','wireless.management.network':'mgmt',
            'wireless.management.disabled':'0','wireless.management.key':SECRET,
            'wireless.client':'wifi-iface','wireless.client.device':'radioOther',
            'wireless.client.mode':'sta','wireless.client.network':'wwan',
            'wireless.client.disabled':'0','wireless.client.key':SECRET},
            'wireless':{
                'radioOdd':{'up':True,'config':{'key':SECRET,'channel':'auto'},
                    'interfaces':[{'section':'management','ifname':'phy7-ap0','config':{'key':SECRET}}]},
                'radioOther':{'up':True,'config':{'key':SECRET},
                    'interfaces':[{'section':'client','ifname':'wlanOdd','config':{'key':SECRET}}]}},
            'iwinfo':{'phy7-ap0':{'phy':'phy7','channel':6,'frequency':2437,'key':SECRET},
                      'wlanOdd':{'phy':'phy9','channel':44,'frequency':5220,'key':SECRET}},
            'wwan':{'up':True,'l3_device':'wlanOdd','key':SECRET}}
        self.save()

    def save(self):
        (self.root/'fixture.json').write_text(json.dumps(self.data))
        (self.root/'var/run/tr3000-lite/uplink/status.json').write_text(json.dumps(self.uplink))
        (self.root/'var/run/tr3000-lite/usbwan.json').write_text(json.dumps(self.usb))

    def run_status(self, *args, success=True):
        self.assertTrue(SCRIPT.is_file(),'fixed read-only uplink status controller is missing')
        source=SCRIPT.read_text().replace('PATH=/usr/sbin:/usr/bin:/sbin:/bin',
                                         'PATH="'+str(self.root/'bin')+':/usr/bin:/bin"')
        source=source.replace('/usr/sbin/lite-common.sh',str(ROOT/'scripts/lite-common.sh'))
        source=source.replace('/usr/lib/tr3000-lite/uplink-lib.sh',str(ROOT/'scripts/tr3000-lite-uplink-lib.sh'))
        source=source.replace('/usr/lib/tr3000-lite/plant-lib.sh',str(ROOT/'scripts/tr3000-lite-plant-lib.sh'))
        source=source.replace('/var/run',str(self.root/'var/run'))
        script=self.root/'status.sh'; script.write_text(source)
        result=subprocess.run([bash_executable(),str(script),*(args or ('--json',))],capture_output=True,text=True,
            env=dict(os.environ,STATUS_FIXTURE=str(self.root),STATUS_PYTHON=sys.executable))
        self.assertEqual(success,result.returncode==0,result.stdout+result.stderr)
        self.assertNotIn(SECRET,result.stdout+result.stderr)
        return result

    def status(self): return json.loads(self.run_status().stdout)

    def test_public_network_usb_and_actual_radio_data_without_secrets(self):
        before=copy.deepcopy(self.data)
        status=self.status()
        self.assertEqual(1,status['schema_version'])
        self.assertEqual('wan',status['active'])
        self.assertFalse(status['status_error'])
        self.assertEqual([10,20,30],[entry['base_metric'] for entry in status['interfaces']])
        self.assertTrue(status['interfaces'][1]['link'])
        self.assertIsNone(status['interfaces'][0]['link'], 'missing live netifd data is not inferred from a stored route')
        self.assertEqual('rndis_host',status['usb']['driver'])
        self.assertEqual('2c7c',status['usb']['vid'])
        self.assertEqual('0125',status['usb']['pid'])
        rows={entry['mode']:entry for entry in status['wireless']['interfaces']}
        self.assertEqual('radioOdd',rows['ap']['radio'])
        self.assertEqual('phy7',rows['ap']['phy'])
        self.assertEqual(6,rows['ap']['channel'])
        self.assertEqual(44,rows['sta']['channel'])
        self.assertTrue(rows['ap']['up']); self.assertTrue(rows['sta']['up'])
        self.assertFalse(rows['ap']['shared_phy'])
        self.assertEqual('ap_client',status['wireless']['mode'])
        self.assertEqual(before,json.loads((self.root/'fixture.json').read_text()))
        calls=[json.loads(line) for line in (self.root/'calls.jsonl').read_text().splitlines()]
        self.assertFalse(any(call[0]=='uci' and any(op in call for op in ('set','commit','delete','add_list')) for call in calls))
        self.assertFalse(any('reload' in call or 'ifup' in call or 'ifdown' in call for call in calls))

    def test_list_radio_configuration_does_not_share_disabled_state_between_radios(self):
        self.data['uci']['wireless.management.device']='radioOdd radioOther'
        self.data['uci']['wireless.radioOdd.disabled']='1'; self.save()
        rows=[row for row in self.status()['wireless']['interfaces'] if row['mode']=='ap']
        self.assertEqual(2,len(rows))
        self.assertFalse(next(row for row in rows if row['radio']=='radioOdd')['enabled'])
        self.assertTrue(next(row for row in rows if row['radio']=='radioOther')['enabled'])

    def test_same_runtime_phy_warns_even_when_uci_radio_names_differ(self):
        self.data['iwinfo']['wlanOdd'].update(phy='phy7',channel=6,frequency=2437); self.save()
        status=self.status()
        self.assertTrue(all(row['shared_phy'] for row in status['wireless']['interfaces']))
        self.assertEqual({6},{row['channel'] for row in status['wireless']['interfaces']})

    def test_disconnected_or_disabled_sta_preserves_ap_status_and_unknown_channel(self):
        self.data['wwan']['up']=False
        self.data['iwinfo'].pop('wlanOdd'); self.save()
        status=self.status(); rows={row['mode']:row for row in status['wireless']['interfaces']}
        self.assertEqual('client_disconnected',status['wireless']['mode'])
        self.assertTrue(rows['ap']['up']); self.assertFalse(rows['sta']['up'])
        self.assertIsNone(rows['sta']['channel'])
        self.data['uci']['wireless.client.disabled']='1'; self.save()
        self.assertEqual('ap_only',self.status()['wireless']['mode'])

    def test_corrupt_public_state_fails_closed_and_unknown_fields_never_leak(self):
        for field in ('device','address','gateway','health'):
            with self.subTest(field=field):
                original=copy.deepcopy(self.uplink)
                self.uplink['interfaces'][0][field]=SECRET; self.save()
                status=self.status()
                self.assertTrue(status['status_error'])
                self.assertEqual('',status['active'])
                self.uplink=original
        self.uplink['private_key']=SECRET
        self.usb['token']=SECRET
        self.data['iwinfo']['phy7-ap0']['channel']=SECRET
        self.save(); status=self.status()
        self.assertIsNone(next(row for row in status['wireless']['interfaces'] if row['mode']=='ap')['channel'])
        self.assertNotIn('private_key',status)
        self.assertNotIn('token',status['usb'])
        self.usb['driver']=SECRET; self.save()
        self.assertEqual('error',self.status()['usb']['state'])

    def test_foreign_and_reconcile_warnings_missing_state_and_symlink_refusal(self):
        self.uplink.update(foreign_default=True,active=''); self.save()
        self.assertTrue(self.status()['foreign_default'])
        self.uplink['reconcile_error']=True; self.save()
        self.assertTrue(self.status()['reconcile_error'])
        p=self.root/'var/run/tr3000-lite/uplink/status.json'; p.unlink()
        status=self.status(); self.assertTrue(status['status_error']); self.assertEqual('',status['active'])
        outside=self.root/'private.json'; outside.write_text(json.dumps({'key':SECRET}))
        p.symlink_to(outside)
        self.assertTrue(self.status()['status_error'])

    def test_cli_and_lite_installation(self):
        self.assertIn('Usage:',self.run_status('--help').stdout)
        for args in (('--json','extra'),('status','--json'),('--address',SECRET)):
            self.run_status(*args,success=False)
        result,_,assets=run_lite_configure(lite_base_config())
        self.assertEqual(0,result.returncode,result.stderr)
        self.assertEqual(SCRIPT.read_text(),assets['files/usr/sbin/tr3000-lite-uplink-status'])


if __name__=='__main__': unittest.main()
