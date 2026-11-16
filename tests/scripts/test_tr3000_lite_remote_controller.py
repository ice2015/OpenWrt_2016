"""Execute remote authorization against isolated UCI/firewall/WireGuard boundaries."""
import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from tests.scripts.test_scripts import ROOT, bash_executable, uci_sections, lite_base_config, run_lite_configure

SCRIPT=ROOT/'scripts/tr3000-lite-remote.sh'
PREFIX='tr3000_lite_remote_'
FAKE=r'''
import base64,json,os,pathlib,shlex,signal,sys
root=pathlib.Path(os.environ['REMOTE_FIXTURE']); cmd=sys.argv[1]; args=sys.argv[2:]
with (root/'calls.jsonl').open('a') as f: f.write(json.dumps([cmd,*args])+'\n')
failure=os.environ.get('REMOTE_FAILURE','')
def parse(path):
    rows=[]; row=None
    for line in path.read_text().splitlines():
        t=shlex.split(line,comments=True)
        if not t: continue
        if t[0]=='config':
            row={'.type':t[1],'.name':t[2] if len(t)>2 else 'cfg%06d'%len(rows),'.anonymous':len(t)<3}; rows.append(row)
        elif t[0]=='option': row[t[1]]=t[2]
        elif t[0]=='list': row.setdefault(t[1],[]).append(t[2])
    return rows

def write(path,rows):
    text=''
    for row in rows:
        text+='config '+row['.type']+('' if row['.anonymous'] else ' '+shlex.quote(row['.name']))+'\n'
        for k,v in row.items():
            if k.startswith('.'): continue
            if isinstance(v,list):
                for value in v: text+='\tlist '+k+' '+shlex.quote(value)+'\n'
            else: text+='\toption '+k+' '+shlex.quote(v)+'\n'
        text+='\n'
    path.write_text(text)

if cmd=='uci':
    directory=root/'etc/config'; args=[a for a in args if a not in ('-q','-X')]
    for flag in ('-c','-C','-t'):
        if flag in args:
            i=args.index(flag)
            if flag=='-c': directory=pathlib.Path(args[i+1])
            del args[i:i+2]
    action=args[0]
    key=args[1] if len(args)>1 else ''
    if action=='changes':
        if failure=='pending': print('pending operator change')
        sys.exit(0)
    if action=='commit':
        if failure=='commit': sys.exit(1)
        sys.exit(0)
    value=None
    if action in ('set','add_list'): key,value=key.split('=',1)
    parts=key.split('.'); package=parts[0]; path=directory/package
    if not path.is_file(): sys.exit(1)
    rows=parse(path)
    if action=='show':
        for row in rows:
            name=package+'.'+row['.name']; print(name+'='+row['.type'])
            for k,v in row.items():
                if not k.startswith('.'): print(name+'.'+k+"='"+(' '.join(v) if isinstance(v,list) else v)+"'")
        sys.exit(0)
    section=next((row for row in rows if row['.name']==parts[1]),None)
    if action=='get':
        if section is None: sys.exit(1)
        result=section['.type'] if len(parts)==2 else section.get(parts[2])
        if result is None: sys.exit(1)
        print(' '.join(result) if isinstance(result,list) else result); sys.exit(0)
    if directory==root/'etc/config': sys.exit(9) # no live UCI staging permitted
    if action=='set':
        if failure=='set': sys.exit(1)
        if len(parts)==2:
            if section is None: section={'.type':value,'.name':parts[1],'.anonymous':False}; rows.append(section)
            else: section['.type']=value
        elif section is None: sys.exit(1)
        else: section[parts[2]]=value
    elif action=='add_list':
        if section is None: sys.exit(1)
        previous=section.get(parts[2],[])
        if not isinstance(previous,list): previous=[previous]
        section[parts[2]]=previous+[value]
    elif action=='delete':
        if section is None: sys.exit(1)
        if len(parts)==2: rows.remove(section)
        else: section.pop(parts[2],None)
    else: sys.exit(2)
    write(path,rows)
elif cmd=='fw4':
    if args==['check']:
        candidate=root/'var/run/uci/firewall'
        if candidate.is_file():
            (root/'checked-firewall').write_bytes(candidate.read_bytes())
            (root/'policy-at-check').write_bytes((root/'etc/config/tr3000-lite-remote').read_bytes())
            for row in parse(candidate):
                if row['.name'].startswith('tr3000_lite_remote_guard_'):
                    assert row['.type']=='include' and row['type']=='nftables'
                    assert row['position']=='chain-prepend' and row['chain'] in ('input','forward')
                    (root/('checked-guard-'+row['chain']+'.nft')).write_bytes(pathlib.Path(row['path']).read_bytes())
        if failure=='candidate': sys.exit(1)
    elif args==['reload']:
        if failure=='interrupt': os.kill(os.getppid(),signal.SIGTERM); sys.exit(1)
        if failure=='reload': sys.exit(1)
        (root/'active-firewall').write_bytes((root/'etc/config/firewall').read_bytes())
    else: sys.exit(2)
elif cmd=='wg':
    if args!=['pubkey']: sys.exit(2)
    try: data=base64.b64decode(sys.stdin.read().strip(),validate=True)
    except Exception: sys.exit(1)
    if len(data)!=32 or not any(data): sys.exit(1)
    print(base64.b64encode(bytes(reversed(data))).decode())
elif cmd=='ubus':
    if len(args)==3 and args[0]=='call' and args[2]=='status':
        role=args[1].split('.')[-1]
        print(json.dumps({'up':not (root/('down-'+role)).exists(),'l3_device':role}))
    else: sys.exit(2)
elif cmd=='ifdown':
    if args not in (['wg_direct'],['wg_vps']): sys.exit(9)
    if failure=='ifdown': sys.exit(1)
    (root/('down-'+args[0])).touch()
elif cmd=='jsonfilter':
    import re
    value=json.loads(sys.stdin.read()); expr=args[args.index('-e')+1][1:]
    try:
        for key,index in re.findall(r'\.([A-Za-z0-9_-]+)|\[([0-9]+)\]',expr): value=value[int(index)] if index else value[key]
    except (KeyError,IndexError,TypeError): sys.exit(1)
    print(str(value).lower() if isinstance(value,bool) else value)
elif cmd=='logger': pass
else: sys.exit(2)
'''


def key(seed): return base64.b64encode(bytes((seed+i)%256 for i in range(32))).decode()


class RemoteControllerTests(unittest.TestCase):
    def setUp(self):
        old_umask=os.umask(0o022); self.addCleanup(os.umask,old_umask)
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        for p in ('etc/config','etc/tr3000-lite/keys','var/run/uci','var/lock','tmp/.uci','bin'):
            (self.root/p).mkdir(parents=True)
        for name in ('network','firewall'):
            shutil.copyfile(ROOT/'overlays/devices/tr3000-lite/files/etc/config'/name,self.root/'etc/config'/name)
        self.private=[key(1),key(71)]
        network=self.root/'etc/config/network'
        with network.open('a') as f:
            for role,address,private in (('wg_direct','10.77.0.2/32',self.private[0]),('wg_vps','10.88.0.2/32',self.private[1])):
                f.write(f"\nconfig interface '{role}'\n option proto 'wireguard'\n option auto '1'\n list addresses '{address}'\n option private_key '{private}'\n")
            f.write(f"\nconfig wireguard_wg_direct 'engineer'\n option public_key '{key(131)}'\n option route_allowed_ips '1'\n list allowed_ips '10.77.0.10/32'\n")
            f.write(f"\nconfig wireguard_wg_vps 'server'\n option public_key '{key(191)}'\n option endpoint_host 'vps.example.invalid'\n option endpoint_port '51820'\n option route_allowed_ips '1'\n option persistent_keepalive '25'\n list allowed_ips '10.88.0.1/32'\n list allowed_ips '10.88.0.20/32'\n")
        network.chmod(0o600)
        # Explicit private laboratory inputs, never the generic firmware defaults.
        self.set_option('network','wg_direct','listen_port','51820')
        policy=self.root/'etc/config/tr3000-lite-remote'
        policy.write_text("config policy 'access'\n option allow_luci '1'\n option allow_plant '1'\n option direct_enabled '1'\n option vps_enabled '1'\n list vps_remote_source '10.88.0.20/32'\n")
        for role,value in zip(('direct','vps'),self.private):
            path=self.root/f'etc/tr3000-lite/keys/{role}.key'; path.write_text(value+'\n'); path.chmod(0o600)
        (self.root/'etc/tr3000-lite').chmod(0o700); (self.root/'etc/tr3000-lite/keys').chmod(0o700)
        for name,value in (('device-id','TR3000-BENCH-01\n'),('enrolled','enrolled\n'),('management-ap.initialized','initialized\n')):
            p=self.root/'etc/tr3000-lite'/name; p.write_text(value); p.chmod(0o600)
        p=self.root/'etc/shadow'; p.write_text('root:$fixture-hash:0:0:99999:7:::\n'); p.chmod(0o600)
        (self.root/'bin/fake.py').write_text(FAKE)
        for command in ('uci','fw4','wg','ubus','ifdown','jsonfilter','logger'):
            p=self.root/'bin'/command
            p.write_text('#!/bin/sh\nexec "$REMOTE_PYTHON" -S "$REMOTE_FIXTURE/bin/fake.py" '+command+' "$@"\n'); p.chmod(0o755)
        self.network_before=network.read_bytes()
        self.foreign=[row for row in self.sections('firewall') if not (row.get('.name') or '').startswith(PREFIX)]

    def sections(self,package): return uci_sections((self.root/'etc/config'/package).read_text())
    def set_option(self,package,section,option,value):
        path=self.root/'etc/config'/package
        rows=uci_sections(path.read_text())
        row=next(row for row in rows if row['.name']==section); row[option]=value
        self.write_sections(package,rows)
    def write_sections(self,package,rows):
        path=self.root/'etc/config'/package
        text=''
        for row in rows:
            text+='config '+row['.type']+('' if row['.name'] is None else " '"+row['.name']+"'")+'\n'
            for k,v in row.items():
                if k.startswith('.'): continue
                if isinstance(v,list):
                    for item in v: text+=" list "+k+" '"+item+"'\n"
                else: text+=" option "+k+" '"+v+"'\n"
        path.write_text(text)
    def calls(self):
        path=self.root/'calls.jsonl'
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
    def owned(self): return [row for row in self.sections('firewall') if (row.get('.name') or '').startswith(PREFIX)]
    def permissions(self): return [row for row in self.owned() if row['.type']=='nat' or row.get('target')=='ACCEPT']

    def run_controller(self,*args,code=0,**extra):
        self.assertTrue(SCRIPT.is_file(),'remote authorization controller is missing')
        text=SCRIPT.read_text().replace('PATH=/usr/sbin:/usr/bin:/sbin:/bin',
                                     'PATH="'+str(self.root/'bin')+':/usr/bin:/bin"')
        text=text.replace('OWNER_UID=0','OWNER_UID='+str(os.getuid()))
        for name,filename in (('remote-lib.sh','tr3000-lite-remote-lib.sh'),('plant-lib.sh','tr3000-lite-plant-lib.sh')):
            text=text.replace('/usr/lib/tr3000-lite/'+name,str(ROOT/'scripts'/filename))
        text=text.replace('/usr/sbin/lite-common.sh',str(ROOT/'scripts/lite-common.sh'))
        for prefix in ('/etc/config','/etc/tr3000-lite','/etc/shadow','/var/run','/var/lock','/tmp/.uci'):
            text=text.replace(prefix,str(self.root)+prefix)
        script=self.root/'remote.sh'; script.write_text(text)
        result=subprocess.run([bash_executable(),str(script),*args],capture_output=True,text=True,
            env=dict(os.environ,REMOTE_FIXTURE=str(self.root),REMOTE_PYTHON=sys.executable,**extra))
        self.assertEqual(code,result.returncode,result.stdout+result.stderr)
        for private in self.private: self.assertNotIn(private,result.stdout+result.stderr)
        self.assertNotIn('PRIVATE-ERROR',result.stdout+result.stderr)
        if args==('--help',):
            self.assertIn('Usage:',result.stdout); return None
        self.assertTrue(result.stdout.strip(),'controller must return a sanitized transaction result')
        data=json.loads(result.stdout); self.assertEqual(1,data['schema_version'])
        return data

    @unittest.skipUnless(os.environ.get('TR3000_LITE_NATIVE_NFT')=='1','native nft packet gate runs explicitly in Linux Actions')
    def test_native_nft_established_flow_revocation(self):
        def snapshot(name):
            for chain in ('input','forward'):
                shutil.copyfile(self.root/f'etc/tr3000-lite/remote-{chain}.nft',self.root/f'native-{name}-{chain}.nft')
        self.run_controller('sync'); snapshot('on')
        self.run_controller('set-policy','--allow-luci','false','--allow-plant','true'); snapshot('plant')
        self.set_option('network','plant','ipaddr','192.168.20.200')
        self.set_option('network','plant','netmask','255.255.255.192')
        self.run_controller('set-policy','--allow-luci','true','--allow-plant','true'); snapshot('changed')
        self.run_controller('set-policy','--allow-luci','false','--allow-plant','false'); snapshot('off')
        result=subprocess.run(['/usr/bin/sudo','-n','/usr/bin/timeout','90','/usr/bin/unshare','--net',
                               '/usr/bin/python3',str(ROOT/'tests/scripts/native_remote_nft.py'),str(self.root)],
                              capture_output=True,text=True,timeout=110)
        self.assertEqual(0,result.returncode,result.stdout+result.stderr)
        self.assertIn('PASS',result.stdout)

    def test_generated_early_guards_revoke_existing_flows_and_track_current_plant(self):
        self.run_controller('sync')
        includes=[r for r in self.owned() if r['.type']=='include']
        self.assertEqual(2,len(includes),'ordinary late rules cannot revoke established traffic')
        private=self.root/'etc/tr3000-lite'
        input_rules=(private/'remote-input.nft').read_text()
        forward_rules=(private/'remote-forward.nft').read_text()
        self.assertIn('iifname "wg_direct" tcp dport 443 ip saddr != { 10.77.0.10/32 } drop',input_rules)
        self.assertIn('iifname "wg_vps" tcp dport 443 ip daddr != 10.88.0.2/32 drop',input_rules)
        self.assertIn('iifname "wg_direct" ip daddr != 192.168.10.0/24 drop',forward_rules)
        self.assertIn('oifname "wg_direct" ip saddr != 192.168.10.0/24 drop',forward_rules)
        self.assertIn('oifname "wg_direct" ct direction != reply drop',forward_rules)
        for chain in ('input','forward'):
            path=private/('remote-'+chain+'.nft')
            self.assertEqual(path.read_bytes(),(self.root/('checked-guard-'+chain+'.nft')).read_bytes())
            self.assertEqual(0o600,path.stat().st_mode&0o777)
            self.assertEqual('chain-prepend',next(r for r in includes if r['chain']==chain)['position'])
        self.run_controller('set-policy','--allow-luci','false','--allow-plant','false')
        self.assertEqual('iifname "wg_direct" tcp dport 443 drop\niifname "wg_vps" tcp dport 443 drop\n',(private/'remote-input.nft').read_text())
        self.assertEqual('iifname "wg_direct" drop\noifname "wg_direct" drop\niifname "wg_vps" drop\noifname "wg_vps" drop\n',(private/'remote-forward.nft').read_text())
        self.set_option('network','plant','ipaddr','192.168.20.200')
        self.set_option('network','plant','netmask','255.255.255.192')
        self.run_controller('set-policy','--allow-luci','false','--allow-plant','true')
        forward_rules=(private/'remote-forward.nft').read_text()
        self.assertIn('ip daddr != 192.168.20.192/26 drop',forward_rules)
        self.assertNotIn('192.168.10.',forward_rules)

    def test_offload_is_unsupported_without_mutating_foreign_defaults(self):
        for option in ('flow_offloading','flow_offloading_hw'):
            with self.subTest(option=option):
                self.set_option('firewall',None,option,'1')
                original=next(r for r in self.sections('firewall') if r['.type']=='defaults')
                data=self.run_controller('sync',code=3)
                self.assertTrue(data['degraded'])
                self.assertEqual('unsupported_offload',data['checks']['result'])
                self.assertFalse(data['roles']['wg_vps']['enabled'])
                self.assertTrue((self.root/'down-wg_direct').is_file())
                self.assertEqual(original,next(r for r in self.sections('firewall') if r['.type']=='defaults'))
                self.set_option('firewall',None,option,'0')

    def test_boot_barrier_closes_persisted_grants_without_touching_credentials(self):
        script=ROOT/'scripts/tr3000-lite-remote-boot-close.sh'
        self.assertTrue(script.is_file(),'boot barrier is missing')
        self.run_controller('sync')
        before=(self.root/'etc/tr3000-lite/keys/direct.key').read_bytes()
        text=script.read_text().replace('OWNER_UID=0','OWNER_UID='+str(os.getuid()))
        text=text.replace('/etc/tr3000-lite',str(self.root/'etc/tr3000-lite'))
        text=text.replace('/usr/sbin/lite-common.sh',str(ROOT/'scripts/lite-common.sh'))
        text=text.replace('/usr/lib/tr3000-lite/remote-lib.sh',str(ROOT/'scripts/tr3000-lite-remote-lib.sh'))
        target=self.root/'boot-close.sh'; target.write_text(text)
        result=subprocess.run([bash_executable(),str(target)],capture_output=True,text=True)
        self.assertEqual(0,result.returncode,result.stderr)
        self.assertEqual('iifname "wg_direct" tcp dport 443 drop\niifname "wg_vps" tcp dport 443 drop\n',(self.root/'etc/tr3000-lite/remote-input.nft').read_text())
        self.assertEqual(before,(self.root/'etc/tr3000-lite/keys/direct.key').read_bytes())
        self.assertIsNone(self.run_controller('status','--json')['effective']['allow_luci'])
        self.run_controller('sync')
        result,_,assets=run_lite_configure(lite_base_config())
        self.assertEqual(0,result.returncode,result.stderr)
        self.assertTrue('files/etc/rc.d/S18tr3000-lite-remote' in assets,'barrier must run before firewall startup even on first boot')

    def test_valid_source_rules_are_exact_and_preserve_foreign_configuration(self):
        data=self.run_controller('sync')
        self.assertTrue(data['effective']['allow_luci']); self.assertTrue(data['effective']['allow_plant'])
        self.assertEqual(['10.77.0.10/32'],data['sources']['direct'])
        self.assertEqual(['10.88.0.20/32'],data['sources']['vps'])
        self.assertEqual('192.168.10.0/24',data['plant']['cidr'])
        owned=self.owned()
        inputs=[r for r in owned if r['.type']=='rule' and r.get('dest_port')=='443']
        self.assertEqual(2,len(inputs))
        for r in inputs:
            self.assertEqual('tcp',r['proto']); self.assertNotIn('dest',r)
            self.assertIn(r['src_ip'],('10.77.0.10/32','10.88.0.20/32'))
            self.assertIn(r['dest_ip'],('10.77.0.2/32','10.88.0.2/32'))
        forwards=[r for r in owned if r['.type']=='rule' and r.get('dest')=='plant']
        self.assertEqual(4,len(forwards))
        for r in forwards:
            self.assertEqual('192.168.10.0/24',r['dest_ip'])
            self.assertIn(r['proto'],('icmp','tcp'))
            if r['proto']=='icmp': self.assertEqual('echo-request',r['icmp_type'])
        nats=[r for r in owned if r['.type']=='nat']; self.assertEqual(4,len(nats))
        for r in nats:
            self.assertEqual('plant',r['src']); self.assertNotIn('dest',r)
            self.assertEqual('192.168.10.254',r['snat_ip']); self.assertEqual('SNAT',r['target'])
            self.assertIn(r['src_ip'],('10.77.0.10/32','10.88.0.20/32'))
        self.assertEqual(self.foreign,[r for r in self.sections('firewall') if not (r.get('.name') or '').startswith(PREFIX)])
        self.assertEqual(self.network_before,(self.root/'etc/config/network').read_bytes())
        self.assertTrue((self.root/'checked-firewall').is_file())
        self.assertFalse((self.root/'var/run/uci/firewall').exists())
        reloads=sum(call==['fw4','reload'] for call in self.calls())
        self.run_controller('sync')
        self.assertEqual(reloads,sum(call==['fw4','reload'] for call in self.calls()),'unchanged sync must not reload recursively')

    def test_policy_controls_are_independent_and_off_revokes_every_owned_permission(self):
        self.run_controller('set-policy','--allow-luci','true','--allow-plant','false')
        self.assertTrue(any(r.get('dest_port')=='443' for r in self.owned()))
        self.assertFalse(any(r['.type']=='nat' or r.get('dest')=='plant' for r in self.owned()))
        data=self.run_controller('set-policy','--allow-luci','false','--allow-plant','false')
        self.assertFalse(data['effective']['allow_luci']); self.assertFalse(data['effective']['allow_plant'])
        self.assertEqual([],self.permissions())
        self.assertFalse(data['roles']['wg_direct']['enabled'])

    def test_disabled_policy_can_enable_direct_listener_after_full_validation(self):
        self.set_option('tr3000-lite-remote','access','allow_luci','0')
        self.set_option('tr3000-lite-remote','access','allow_plant','0')
        self.run_controller('sync')
        self.assertEqual([],self.permissions())
        before=(self.root/'etc/config/tr3000-lite-remote').read_bytes()
        data=self.run_controller('set-policy','--allow-luci','true','--allow-plant','false')
        self.assertTrue(data['roles']['wg_direct']['enabled'])
        self.assertTrue(data['effective']['allow_luci'])
        self.assertTrue(any(row.get('proto')=='udp' and row.get('dest_port')=='51820' for row in self.owned()))
        self.assertEqual(before,(self.root/'policy-at-check').read_bytes(),'validation must precede live policy commit')

    def test_disabled_roles_have_no_permissions_even_with_valid_registered_sources(self):
        self.set_option('tr3000-lite-remote','access','vps_enabled','0')
        self.set_option('network','wg_vps','auto','0')
        self.run_controller('sync')
        self.assertFalse(any('wg_vps_' in (row.get('.name') or '') for row in self.permissions()))
        self.set_option('tr3000-lite-remote','access','direct_enabled','0')
        self.set_option('network','wg_direct','auto','0')
        data=self.run_controller('sync')
        self.assertEqual([],self.permissions())
        self.assertFalse(data['effective']['allow_luci'])
        self.assertFalse(data['effective']['allow_plant'])

    def test_no_peers_or_unroutable_vps_sources_never_authorize_a_zone(self):
        self.write_sections('network',[row for row in self.sections('network') if row['.name']!='engineer'])
        self.set_option('tr3000-lite-remote','access','vps_remote_source',[])
        data=self.run_controller('sync')
        self.assertEqual([],data['sources']['direct']); self.assertEqual([],data['sources']['vps'])
        self.assertEqual([],self.permissions())
        for sources in (['10.88.0.20/24'],['10.88.0.21/32'],['10.88.0.20/32','10.88.0.20/32']):
            with self.subTest(sources=sources):
                self.set_option('tr3000-lite-remote','access','vps_remote_source',sources)
                self.run_controller('sync',code=2)
                self.assertEqual([],self.permissions())

    def test_key_symlink_world_writable_policy_and_unsafe_identity_fail_closed(self):
        self.run_controller('sync')
        p=self.root/'etc/tr3000-lite/keys/direct.key'; original=p.read_text()
        p.unlink(); outside=self.root/'outside-key'; outside.write_text(original); p.symlink_to(outside)
        self.run_controller('sync'); self.assertEqual([],self.permissions())
        p.unlink(); p.write_text(original); p.chmod(0o600)
        self.run_controller('sync')
        policy=self.root/'etc/config/tr3000-lite-remote'; policy.chmod(0o666)
        self.run_controller('sync',code=3)
        self.assertTrue((self.root/'down-wg_direct').exists())
        policy.chmod(0o644)
        (self.root/'etc/tr3000-lite/device-id').write_text('../PRIVATE-ERROR\n')
        data=self.run_controller('sync'); self.assertEqual('',data['identity'])
        self.assertEqual([],self.permissions())

    def test_generic_remote_defaults_and_fixed_assets_are_lite_scoped(self):
        result,_,assets=run_lite_configure(lite_base_config())
        self.assertEqual(0,result.returncode,result.stderr)
        for path in ('files/usr/sbin/tr3000-lite-remote','files/usr/lib/tr3000-lite/remote-lib.sh',
                     'files/etc/hotplug.d/iface/96-tr3000-lite-remote-sync'):
            self.assertTrue(path in assets,'missing fixed remote asset: '+path)
        policy=uci_sections(assets['files/etc/config/tr3000-lite-remote'])[0]
        self.assertEqual({'allow_luci','allow_plant','direct_enabled','vps_enabled'},set(policy)-{'.type','.name'})
        self.assertEqual({'0'},{policy[key] for key in policy if not key.startswith('.')})

    def test_any_invalid_or_duplicate_source_revokes_the_entire_candidate(self):
        for source in ('10.77.0.10/24','0.0.0.0/0','::1/128','', '10.88.0.20/32'):
            with self.subTest(source=source):
                self.set_option('network','engineer','allowed_ips',['10.77.0.10/32'])
                self.run_controller('sync')
                self.set_option('network','engineer','allowed_ips',[source])
                data=self.run_controller('sync',code=2)
                self.assertEqual('invalid_sources',data['checks']['result'])
                self.assertFalse(data['effective']['allow_luci'])
                self.assertEqual([],self.permissions())
        self.set_option('network','engineer','allowed_ips',['10.77.0.10/32','10.77.0.11/32'])
        data=self.run_controller('sync')
        self.assertEqual(2,len(data['sources']['direct']))

    def test_initialization_gates_close_listener_and_remote_permissions(self):
        gates=(('enrolled',None),('device-id',None),('management-ap.initialized',None),('keys/direct.key',None))
        for name,_ in gates:
            with self.subTest(gate=name):
                self.run_controller('sync')
                p=self.root/'etc/tr3000-lite'/name; saved=p.read_bytes(); mode=p.stat().st_mode
                p.unlink()
                data=self.run_controller('sync')
                self.assertFalse(data['effective']['allow_luci'])
                self.assertFalse(data['roles']['wg_direct']['enabled'])
                self.assertEqual([],self.permissions())
                p.write_bytes(saved); p.chmod(mode)
        p=self.root/'etc/shadow'; p.write_text('root::0:0:99999:7:::\n')
        data=self.run_controller('sync')
        self.assertFalse(data['gates']['root_password'])
        self.assertEqual([],self.permissions())

    def test_plant_change_rebuilds_all_targets_and_snat_and_missing_key_fails_closed(self):
        self.run_controller('sync')
        self.set_option('network','plant','ipaddr','192.168.20.254')
        self.set_option('network','plant','netmask','255.255.255.192')
        data=self.run_controller('sync')
        self.assertEqual('192.168.20.192/26',data['plant']['cidr'])
        for r in self.owned():
            if r.get('dest')=='plant' or r['.type']=='nat': self.assertEqual('192.168.20.192/26',r['dest_ip'])
            if r['.type']=='nat': self.assertEqual('192.168.20.254',r['snat_ip'])
        self.set_option('network','wg_vps','private_key','')
        data=self.run_controller('sync'); self.assertFalse(data['effective']['allow_plant'])
        self.assertEqual([],self.permissions())

    def test_pending_state_and_candidate_reload_failures_never_claim_success(self):
        self.run_controller('sync')
        pending=self.root/'tmp/.uci/network'; pending.write_text('PRIVATE-ERROR pending admin data\n')
        data=self.run_controller('sync',code=3)
        self.assertFalse(data['effective']['allow_luci'])
        self.assertTrue(pending.exists()); pending.unlink()
        for failure in ('candidate','reload'):
            with self.subTest(failure=failure):
                data=self.run_controller('sync',code=3,REMOTE_FAILURE=failure)
                self.assertTrue(data['degraded'])
                self.assertFalse(data['effective']['allow_luci'])
                self.assertTrue((self.root/'down-wg_direct').exists())
                self.assertTrue((self.root/'down-wg_vps').exists())
                self.assertFalse((self.root/'var/run/uci/firewall').exists())
                self.assertFalse((self.root/'var/lock/tr3000-lite-plant').exists())

    def test_interrupted_transaction_closes_owned_candidate_and_stops_only_wg_roles(self):
        data=self.run_controller('sync',code=3,REMOTE_FAILURE='interrupt')
        self.assertTrue(data['degraded'])
        self.assertEqual('interrupted',data['checks']['result'])
        self.assertEqual([],self.permissions())
        self.assertTrue((self.root/'down-wg_direct').exists())
        self.assertTrue((self.root/'down-wg_vps').exists())
        self.assertFalse((self.root/'var/run/uci/firewall').exists())
        self.assertFalse((self.root/'var/lock/tr3000-lite-plant').exists())

    def test_runtime_symlink_never_removes_external_cache_and_status_marks_unapplied(self):
        data=self.run_controller('status','--json')
        self.assertEqual('not_synchronized',data['checks']['result'])
        outside=self.root/'outside'; outside.mkdir()
        p=outside/'applied'; p.write_text('PRIVATE-ERROR external data\n')
        runtime=self.root/'var/run/tr3000-lite'; runtime.mkdir(parents=True,exist_ok=True)
        (runtime/'remote').symlink_to(outside,target_is_directory=True)
        self.run_controller('status','--json')
        self.run_controller('sync',code=3)
        self.assertTrue(p.is_file(),'unsafe runtime link must not delete an unrelated file')
        self.assertEqual('PRIVATE-ERROR external data\n',p.read_text())

    def test_status_is_read_only_and_bad_cli_is_rejected_without_mutation(self):
        before={p.name:p.read_bytes() for p in (self.root/'etc/config').iterdir()}
        self.run_controller('status','--json')
        self.assertEqual(before,{p.name:p.read_bytes() for p in (self.root/'etc/config').iterdir()})
        self.run_controller('--help')
        self.run_controller('set-policy','--allow-luci','true','--allow-luci','false','--allow-plant','true',code=2)
        self.assertEqual(before,{p.name:p.read_bytes() for p in (self.root/'etc/config').iterdir()})
        lock=self.root/'var/lock/tr3000-lite-plant'; lock.mkdir()
        self.run_controller('sync',code=3)
        self.assertTrue(lock.exists(),'never remove another transaction owner lock')


if __name__=='__main__': unittest.main()
