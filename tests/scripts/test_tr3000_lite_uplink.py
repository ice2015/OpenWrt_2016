"""Execute the Lite-only reconciler with controlled DHCP/kernel/probe boundaries."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tests.scripts.test_scripts import ROOT, bash_executable, lite_base_config, full_base_config, run_lite_configure, run_full_configure

SCRIPT = ROOT/'scripts/tr3000-lite-uplink-watch.sh'
LIB = ROOT/'scripts/tr3000-lite-uplink-lib.sh'
FAKE = r'''
import json, os, pathlib, re, sys
root=pathlib.Path(os.environ['UPLINK_FIXTURE']); command=sys.argv[1]; args=sys.argv[2:]
p=root/'fixture.json'; d=json.loads(p.read_text())
with (root/'calls.jsonl').open('a') as f: f.write(json.dumps([command,*args])+'\n')
def save(): p.write_text(json.dumps(d))
if command=='uci':
    args=[a for a in args if a!='-q']
    if args[0]!='get' or args[1] not in d['config']: sys.exit(1)
    print(d['config'][args[1]])
elif command=='ubus':
    if len(args)==3 and args[:2]==['send','tr3000-lite.uplink-changed']:
        payload=json.loads(args[2])
        if set(payload)!={'schema_version','active','previous'} or payload['schema_version']!=1: sys.exit(2)
        sys.exit(0)
    if len(args)!=3 or args[0]!='call' or args[2]!='status': sys.exit(2)
    name=args[1].split('.')[-1]
    d['reads'][name]=d['reads'].get(name,0)+1
    renew=d.get('renew')
    if renew and renew['name']==name and d['reads'][name]==renew['at']:
        d['leases'][name]=renew['lease']
        d['routes']=[r for r in d['routes'] if r['dev']!=renew['old_device']]+[renew['route']]
    save()
    if name not in d['leases']: sys.exit(1)
    print(json.dumps(d['leases'][name]))
elif command=='jsonfilter':
    expr=args[args.index('-e')+1]
    value=json.loads(sys.stdin.read())
    # Exact paths used by the real script, including quoted IPv4-array key.
    expr=expr[1:]
    tokens=re.findall(r"\.([A-Za-z0-9_-]+)|\['([^']+)'\]|\[([0-9]+)\]",expr)
    try:
        for key,quoted,index in tokens: value=value[int(index)] if index else value[key or quoted]
    except (KeyError,IndexError,TypeError): sys.exit(1)
    if value is None: sys.exit(1)
    if isinstance(value,bool): print(str(value).lower())
    elif isinstance(value,(dict,list)): print(json.dumps(value))
    else: print(value)
elif command=='ping':
    dev=args[args.index('-I')+1]; target=args[-1]
    sys.exit(0 if d['probes'].get(dev,{}).get(target,False) else 1)
elif command=='ip':
    if args[:4]==['-4','route','show','table']:
        if d.get('fail_show'): sys.exit(1)
        if args[4:]!=['main','default']: sys.exit(2)
        for r in d['routes']:
            print('default via '+r['via']+' dev '+r['dev']+' proto '+r.get('proto','static')+
                  (' src '+r['src'] if r.get('src') else '')+' metric '+str(r['metric']))
    elif args[:3] in (['-4','route','replace'],['-4','route','del']):
        op=args[2]; a=args[4:]; route={}
        for flag,key in [('via','via'),('dev','dev'),('src','src'),('metric','metric'),('proto','proto')]:
            if flag in a: route[key]=a[a.index(flag)+1]
        route['metric']=int(route['metric']); route.setdefault('src',''); route.setdefault('proto','static')
        if d.get('fail_route'): sys.exit(1)
        if op=='replace':
            # Linux default-route key includes priority, NOT just gateway/device.
            d['routes']=[r for r in d['routes'] if r['metric']!=route['metric']]+[route]
        else:
            found=[r for r in d['routes'] if all(r.get(k,'')==v for k,v in route.items())]
            if not found: sys.exit(2)
            d['routes']=[r for r in d['routes'] if r not in found]
        save()
    else: sys.exit(2)
elif command=='logger': pass
else: sys.exit(2)
'''


def lease(device, address, gateway, metric, source=True):
    return {'up':True, 'proto':'dhcp', 'l3_device':device, 'metric':metric,
            'ipv4-address':[{'address':address,'mask':24}],
            'route':[{'target':'0.0.0.0','mask':0,'nexthop':gateway,
                      'source':address+'/32' if source else '0.0.0.0/0'}]}


def route(device, address, gateway, metric, source=True):
    return {'dev':device,'src':address if source else '', 'via':gateway,'metric':metric,'proto':'static'}


class UplinkTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        for path in ('bin','etc/config','var/run/tr3000-lite','usr/lib/tr3000-lite'):
            (self.root/path).mkdir(parents=True)
        (self.root/'bin/fake.py').write_text(FAKE)
        for command in ('uci','ubus','jsonfilter','ping','ip','logger'):
            path=self.root/'bin'/command
            path.write_text('#!/bin/sh\nexec "$UPLINK_PYTHON" -S "$UPLINK_FIXTURE/bin/fake.py" '+command+' "$@"\n')
            path.chmod(0o755)
        self.data={'config':{},'leases':{},'routes':[],'probes':{},'reads':{}}
        for name,dev,ip,gw,metric in (
            ('wan','eth0','192.0.2.2','192.0.2.1',10),
            ('wwan','wlan1-sta0','198.51.100.2','198.51.100.1',20),
            ('usbwan','modem7','203.0.113.2','203.0.113.1',30)):
            self.data['config'][f'network.{name}.metric']=str(metric)
            self.data['config'][f'lite-uplink-watch.{name}.probe_ip']='1.1.1.1 9.9.9.9'
            self.data['leases'][name]=lease(dev,ip,gw,metric)
            self.data['routes'].append(route(dev,ip,gw,metric))
            self.data['probes'][dev]={'1.1.1.1':True,'9.9.9.9':True}
        self.save()
        hook=self.root/'usr/lib/tr3000-lite/uplink-changed'
        hook.write_text('#!/bin/sh\nprintf "%s %s\\n" "$1" "$2" >> "$UPLINK_FIXTURE/events"\n[ ! -e "$UPLINK_FIXTURE/fail-hook" ]\n')
        hook.chmod(0o755)

    def save(self): (self.root/'fixture.json').write_text(json.dumps(self.data))
    def load(self): return json.loads((self.root/'fixture.json').read_text())
    def calls(self):
        path=self.root/'calls.jsonl'
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
    def events(self):
        path=self.root/'events'
        return path.read_text().splitlines() if path.exists() else []

    def run_watch(self, *args, success=True):
        self.assertTrue(SCRIPT.is_file(), 'Lite-only reconciler is missing')
        self.assertTrue(LIB.is_file(), 'uplink library is missing')
        text=SCRIPT.read_text().replace('PATH=/usr/sbin:/usr/bin:/sbin:/bin',
                                      'PATH="'+str(self.root/'bin')+':/usr/bin:/bin"')
        text=text.replace('/usr/lib/tr3000-lite/uplink-lib.sh',str(LIB))
        text=text.replace('/usr/sbin/lite-common.sh',str(ROOT/'scripts/lite-common.sh'))
        for prefix in ('/var/run','/etc/config','/usr/lib/tr3000-lite/uplink-changed'):
            text=text.replace(prefix,str(self.root)+prefix)
        path=self.root/'watch.sh'; path.write_text(text)
        result=subprocess.run([bash_executable(),str(path),*(args or ('reconcile',))],capture_output=True,text=True,
                              env=dict(os.environ,UPLINK_FIXTURE=str(self.root),UPLINK_PYTHON=sys.executable))
        if success is not None: self.assertEqual(success,result.returncode==0,result.stdout+result.stderr)
        return result

    def status(self):
        result=self.run_watch('status','--json')
        return json.loads(result.stdout)
    def by_name(self): return {entry['name']:entry for entry in self.status()['interfaces']}
    def probes(self, name, good):
        self.data=self.load(); dev=self.data['leases'][name]['l3_device']
        self.data['probes'][dev]={'1.1.1.1':good,'9.9.9.9':good}; self.save()

    def test_initial_priority_and_idempotent_reconcile(self):
        self.run_watch()
        self.assertEqual('wan',self.status()['active'])
        self.assertEqual([10,20,30],[self.by_name()[name]['base_metric'] for name in ('wan','wwan','usbwan')])
        self.assertEqual(self.data['routes'],self.load()['routes'])
        self.run_watch(); self.run_watch()
        self.assertEqual(1,len(self.events()),'initial stable uplink is announced only once')
        self.assertFalse(any(call[:3] in (['ip','-4','route']) and call[3] in ('replace','del') for call in self.calls()))

    def test_three_failures_demote_and_two_successes_recover(self):
        self.run_watch(); self.probes('wan',False)
        for round_number in (1,2):
            self.run_watch(); self.assertEqual('wan',self.status()['active'])
            self.assertEqual(round_number,self.by_name()['wan']['failures'])
        self.run_watch(); state=self.by_name()['wan']
        self.assertEqual('unhealthy',state['health'])
        self.assertEqual(1010,state['effective_metric'])
        self.assertEqual('wwan',self.status()['active'])
        self.assertEqual([20,30,1010],sorted(r['metric'] for r in self.load()['routes']))
        self.assertEqual('wwan wan',self.events()[-1])
        self.probes('wan',True)
        self.run_watch(); self.assertEqual('wwan',self.status()['active'])
        self.assertEqual(1,self.by_name()['wan']['successes'])
        self.run_watch(); self.assertEqual('wan',self.status()['active'])
        self.assertEqual([10,20,30],sorted(r['metric'] for r in self.load()['routes']))
        self.assertEqual('wan wwan',self.events()[-1])
        self.run_watch(); self.assertEqual(3,len(self.events()))

    def test_usb_fallback_and_no_default_are_unavailable(self):
        self.data['leases']['wan']['up']=False
        self.data['leases']['wwan']['route']=[]
        self.data['routes']=[self.data['routes'][2]]; self.save()
        self.run_watch()
        self.assertEqual('usbwan',self.status()['active'])
        self.assertEqual('unavailable',self.by_name()['wwan']['health'])
        self.data=self.load(); self.data['leases']['usbwan']['route'][0]['nexthop']='0.0.0.0'; self.save()
        self.run_watch(); self.assertEqual('',self.status()['active'])

    def test_invalid_configuration_fails_before_any_routes_or_state_change(self):
        for name,value in (('lite-uplink-watch.wan.probe_ip','1.1.1.1 bad.host'),
                           ('lite-uplink-watch.wan.probe_ip','1.1.1.1;reboot'),
                           ('network.wan.metric','20'),
                           ('lite-uplink-watch.globals.interval','1'),
                           ('lite-uplink-watch.globals.failures','0')):
            with self.subTest(name=name,value=value):
                old=copy.deepcopy(self.data)
                self.data['config'][name]=value; self.save()
                before=self.load()['routes']; self.run_watch(success=False)
                self.assertEqual(before,self.load()['routes'])
                self.assertFalse((self.root/'var/run/tr3000-lite/uplink/status.json').exists())
                self.data=old; self.save()

    def test_alternate_probe_and_configured_hysteresis(self):
        self.data['config']['lite-uplink-watch.wan.probe_ip']='192.0.2.1'
        self.data['probes']['eth0']={'192.0.2.1':True}
        self.data['config']['lite-uplink-watch.globals.failures']='2'
        self.data['config']['lite-uplink-watch.globals.successes']='3'; self.save()
        self.run_watch(); self.assertEqual('healthy',self.by_name()['wan']['health'])
        self.data=self.load(); self.data['probes']['eth0']={'192.0.2.1':False}; self.save()
        self.run_watch(); self.run_watch(); self.assertEqual('wwan',self.status()['active'])
        self.data=self.load(); self.data['probes']['eth0']={'192.0.2.1':True}; self.save()
        self.run_watch(); self.run_watch(); self.assertEqual('wwan',self.status()['active'])
        self.run_watch(); self.assertEqual('wan',self.status()['active'])

    def test_foreign_routes_untouched_and_metric_collision_refused(self):
        foreign=route('vpn0','10.9.0.2','10.9.0.1',5); foreign['proto']='boot'
        self.data['routes'].append(foreign); self.save()
        self.run_watch()
        self.assertEqual('',self.status()['active'], 'an unmanaged better route must not be advertised as WAN egress')
        self.assertTrue(self.status()['foreign_default'])
        self.probes('wan',False)
        for _ in range(3): self.run_watch()
        self.assertIn(foreign,self.load()['routes'])
        self.data=self.load(); collision=route('foreign0','10.8.0.2','10.8.0.1',1020)
        self.data['routes'].append(collision)
        self.data['probes']['wlan1-sta0']={'1.1.1.1':False,'9.9.9.9':False}; self.save()
        self.run_watch(); self.run_watch(); self.run_watch(success=False)
        self.assertIn(collision,self.load()['routes'])
        self.assertTrue(self.status()['reconcile_error'])

    def test_dhcp_reinstalls_base_route_without_creating_duplicates(self):
        self.run_watch(); self.probes('wan',False)
        for _ in range(3): self.run_watch()
        self.data=self.load()
        self.data['routes'].append(route('eth0','192.0.2.2','192.0.2.1',10)); self.save()
        self.run_watch(); self.run_watch()
        owned=[r for r in self.load()['routes'] if r['dev']=='eth0']
        self.assertEqual([1010],[r['metric'] for r in owned])

    def test_lease_change_is_reread_before_route_mutation(self):
        self.run_watch(); self.probes('wan',False)
        self.run_watch(); self.run_watch()
        self.data=self.load()
        self.data['renew']={'name':'wan','at':self.data['reads']['wan']+2,'old_device':'eth0',
            'lease':lease('eth0','192.0.2.42','192.0.2.254',10),
            'route':route('eth0','192.0.2.42','192.0.2.254',10)}
        self.save(); self.run_watch()
        for r in self.load()['routes']:
            if r['dev']=='eth0':
                self.assertEqual('192.0.2.42',r['src'])
                self.assertEqual('192.0.2.254',r['via'])
        self.assertEqual('192.0.2.42',self.by_name()['wan']['address'])

    def test_routes_without_explicit_source_and_gateway_change_cleanup(self):
        self.data['leases']['wan']=lease('eth0','192.0.2.2','192.0.2.1',10,False)
        self.data['routes'][0]=route('eth0','192.0.2.2','192.0.2.1',10,False); self.save()
        self.run_watch(); self.probes('wan',False)
        for _ in range(3): self.run_watch()
        self.assertEqual('',next(r for r in self.load()['routes'] if r['dev']=='eth0')['src'])
        self.data=self.load()
        self.data['leases']['wan']=lease('eth0','192.0.2.9','192.0.2.254',10)
        self.data['routes'].append(route('eth0','192.0.2.9','192.0.2.254',10)); self.save()
        self.run_watch()
        self.assertFalse(any(r['via']=='192.0.2.1' for r in self.load()['routes']))

    def test_lock_and_event_failure_do_not_corrupt_state(self):
        state=self.root/'var/run/tr3000-lite/uplink'; state.mkdir()
        lock=state/'lock'; lock.mkdir()
        self.run_watch(success=False)
        self.assertTrue(lock.exists())
        self.assertEqual(self.data['routes'],self.load()['routes'])
        lock.rmdir(); (self.root/'fail-hook').touch()
        self.run_watch(); self.assertTrue(self.status()['last_event_error'])
        self.assertEqual('wan',self.status()['active'])
        self.run_watch(); self.assertEqual(1,len(self.events()),'failed notification is not an infinite retry loop')
        self.assertFalse(lock.exists())

    def test_failed_route_inspection_is_not_reported_as_all_interfaces_down(self):
        self.run_watch()
        self.data=self.load(); self.data['fail_show']=True; self.save()
        before=self.load()['routes']; events=list(self.events())
        self.run_watch(success=False)
        self.assertEqual(before,self.load()['routes'])
        self.assertEqual('wan',self.status()['active'])
        self.assertTrue(self.status()['reconcile_error'])
        self.assertEqual(events,self.events())

    def test_failed_route_replace_retains_last_verified_state_and_retries(self):
        self.run_watch(); self.probes('wan',False)
        self.run_watch(); self.run_watch()
        self.data=self.load(); self.data['fail_route']=True; self.save()
        before=self.load()['routes']; events=list(self.events())
        self.run_watch(success=False)
        self.assertEqual(before,self.load()['routes'])
        self.assertEqual('wan',self.status()['active'])
        self.assertTrue(self.status()['reconcile_error'])
        self.assertEqual(events,self.events())
        self.data=self.load(); self.data.pop('fail_route'); self.save()
        self.run_watch()
        self.assertEqual('wwan',self.status()['active'])
        self.assertFalse(self.status()['reconcile_error'])

    def test_event_hook_emits_only_validated_public_transition(self):
        hook=ROOT/'scripts/tr3000-lite-uplink-changed.sh'
        self.assertTrue(hook.is_file(), 'missing public uplink event hook')
        text=hook.read_text().replace('PATH=/usr/sbin:/usr/bin:/sbin:/bin',
                                     'PATH="'+str(self.root/'bin')+':/usr/bin:/bin"')
        script=self.root/'public-hook.sh'; script.write_text(text)
        env=dict(os.environ,UPLINK_FIXTURE=str(self.root),UPLINK_PYTHON=sys.executable)
        result=subprocess.run([bash_executable(),str(script),'wwan','wan'],env=env,capture_output=True,text=True)
        self.assertEqual(0,result.returncode,result.stderr)
        sent=[call for call in self.calls() if call[:3]==['ubus','send','tr3000-lite.uplink-changed']]
        self.assertEqual(1,len(sent))
        self.assertEqual({'schema_version':1,'active':'wwan','previous':'wan'},json.loads(sent[0][3]))
        for args in (('wan;reboot','wwan'),('wan','/etc/shadow'),('wan',),('wan','wwan','extra')):
            result=subprocess.run([bash_executable(),str(script),*args],env=env,capture_output=True,text=True)
            self.assertNotEqual(0,result.returncode)
        self.assertEqual(1,len([call for call in self.calls() if call[:2]==['ubus','send']]))

    def test_fixed_cli_and_installed_lite_only_assets(self):
        result=self.run_watch('--help'); self.assertIn('Usage:',result.stdout)
        for args in (('status',),('status','--json','extra'),('reconcile','bad'),('unknown',)):
            self.run_watch(*args,success=False)
        result,_,assets=run_lite_configure(lite_base_config())
        self.assertEqual(0,result.returncode,result.stderr)
        self.assertEqual(SCRIPT.read_text(),assets['files/usr/sbin/lite-uplink-watch'])
        self.assertEqual(LIB.read_text(),assets['files/usr/lib/tr3000-lite/uplink-lib.sh'])
        result,_,assets=run_full_configure(full_base_config())
        self.assertEqual(0,result.returncode,result.stderr)
        self.assertEqual((ROOT/'scripts/lite-uplink-watch.sh').read_text(),assets['files/usr/sbin/lite-uplink-watch'])
        self.assertNotIn('files/usr/lib/tr3000-lite/uplink-lib.sh',assets)


if __name__=='__main__': unittest.main()
