"""Read-only DDNS metadata boundaries: no provider API or private log imports."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tests.scripts.test_scripts import ROOT, bash_executable, lite_base_config, run_lite_configure

SCRIPT=ROOT/'scripts/tr3000-lite-ddns-status.sh'
FAKE=r'''
import json,os,pathlib,re,shlex,sys
root=pathlib.Path(os.environ['DDNS_FIXTURE']); command=sys.argv[1]; args=sys.argv[2:]
if command=='uci':
    directory=root/'etc/config'; args=[a for a in args if a!='-q']
    for flag in ('-c','-C','-t'):
        if flag in args:
            i=args.index(flag)
            if flag=='-c': directory=pathlib.Path(args[i+1])
            del args[i:i+2]
    if args[0]!='get': sys.exit(9)
    package,section,option=args[1].split('.'); current=None
    for line in (directory/package).read_text().splitlines():
        t=shlex.split(line,comments=True)
        if not t: continue
        if t[0]=='config': current=t[2] if len(t)>2 else None
        elif t[0]=='option' and current==section and t[1]==option:
            print(t[2]); sys.exit(0)
    sys.exit(1)
elif command=='ubus':
    if args!=['call','network.interface.wan','status']: sys.exit(2)
    print((root/'wan.json').read_text())
elif command=='jsonfilter':
    data=args[args.index('-s')+1] if '-s' in args else sys.stdin.read()
    value=json.loads(data); expr=args[args.index('-e')+1]
    tokens=re.findall(r'\.([A-Za-z0-9_-]+)|\["([^"]+)"\]|\[([0-9]+)\]',expr)
    try:
        for dot,quoted,index in tokens: value=value[int(index)] if index else value[dot or quoted]
    except (KeyError,IndexError,TypeError): sys.exit(1)
    print(str(value).lower() if isinstance(value,bool) else value)
elif command=='date': print(1700000000)
else: sys.exit(2)
'''


class DdnsStatusTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        for name in ('etc/config','var/run/ddns','var/run/tr3000-lite/uplink','bin','proc'):
            (self.root/name).mkdir(parents=True)
        self.token='TEST_ONLY_NOT_A_REAL_TOKEN_0123456789_abcdefgh'
        self.options={'enabled':'1','service_name':'cloudflare.com-v4','use_ipv6':'0','use_https':'1',
                      'username':'Bearer','password':self.token,'lookup_host':'bench.example.invalid',
                      'domain':'bench@example.invalid','ip_source':'network','ip_network':'wan'}
        self.save_config()
        self.set_wan('8.8.8.8')
        (self.root/'proc/uptime').write_text('1000.00 900.00\n')
        (self.root/'var/run/tr3000-lite/uplink/status.json').write_text(json.dumps({'schema_version':1,'active':'wan','interfaces':[]}))
        (self.root/'bin/fake.py').write_text(FAKE)
        for command in ('uci','ubus','jsonfilter','date'):
            path=self.root/'bin'/command
            path.write_text('#!/bin/sh\nexec "$DDNS_PYTHON" -S "$DDNS_FIXTURE/bin/fake.py" '+command+' "$@"\n'); path.chmod(0o755)
        for name,data in (
            ('tr3000-lite-uplink-status',{'schema_version':1,'active':'wan','interfaces':[]}),
            ('tr3000-lite-remote',{'schema_version':1,'enrolled':True,
                'gates':{'root_password':True,'ap_initialized':True,'identity':True,'keys':True},
                'roles':{'wg_direct':{'configured':True,'enabled':True},'wg_vps':{'configured':True,'enabled':True}},
                'private_key':'PRIVATE-SENTINEL'})):
            path=self.root/'bin'/name
            path.write_text("#!/bin/sh\nprintf '%s\\n' '"+json.dumps(data)+"'\n"); path.chmod(0o755)
    def save_config(self):
        p=self.root/'etc/config/ddns'
        p.write_text("config service 'tr3000_direct'\n"+''.join(" option "+key+" '"+value+"'\n" for key,value in self.options.items()))
        p.chmod(0o600)
    def set_wan(self,address):
        self.wan={'up':True,'proto':'dhcp','device':'eth0','l3_device':'eth0','metric':10,
                  'ipv4-address':[] if address is None else [{'address':address,'mask':24}],
                  'ipv6-address':[],'route':[]}
        (self.root/'wan.json').write_text(json.dumps(self.wan))
    def run_status(self,*args,code=0):
        self.assertTrue(SCRIPT.is_file(),'sanitized DDNS status controller is missing')
        text=SCRIPT.read_text().replace('PATH=/usr/sbin:/usr/bin:/sbin:/bin','PATH="'+str(self.root/'bin')+':/usr/bin:/bin"')
        text=text.replace('OWNER_UID=0','OWNER_UID='+str(os.getuid()))
        text=text.replace('/usr/sbin/lite-common.sh',str(ROOT/'scripts/lite-common.sh'))
        text=text.replace('/usr/lib/tr3000-lite/ddns-lib.sh',str(ROOT/'scripts/tr3000-lite-ddns-lib.sh'))
        for name in ('tr3000-lite-uplink-status','tr3000-lite-remote'):
            text=text.replace('/usr/sbin/'+name,str(self.root/'bin'/name))
        for prefix in ('/etc/config','/var/run','/proc/uptime'):
            text=text.replace(prefix,str(self.root)+prefix)
        path=self.root/'status.sh'; path.write_text(text)
        result=subprocess.run([bash_executable(),str(path),*args],capture_output=True,text=True,
                              env=dict(os.environ,DDNS_FIXTURE=str(self.root),DDNS_PYTHON=sys.executable))
        self.assertEqual(code,result.returncode,result.stdout+result.stderr)
        for private in (self.token,'PRIVATE-SENTINEL'): self.assertNotIn(private,result.stdout+result.stderr)
        if code==0: self.assertEqual('',result.stderr,'typed status must not leak parser diagnostics')
        if code!=0: return None
        return json.loads(result.stdout)

    def test_readonly_status_and_library_are_installed_only_by_lite(self):
        result,_,assets=run_lite_configure(lite_base_config())
        self.assertEqual(0,result.returncode,result.stderr)
        self.assertTrue('files/usr/sbin/tr3000-lite-ddns-status' in assets,'Lite status executable is missing')
        self.assertTrue('files/usr/lib/tr3000-lite/ddns-lib.sh' in assets,'Lite metadata library is missing')

    def test_address_scope_is_not_dns_success_or_inbound_reachability(self):
        for address,scope,candidate in (
            (None,'missing',False),('10.0.0.1','private',False),('172.16.5.1','private',False),
            ('192.168.1.2','private',False),('100.64.0.1','cgnat',False),('100.127.255.254','cgnat',False),
            ('127.0.0.1','loopback',False),('169.254.3.1','link_local',False),('192.0.2.1','reserved',False),
            ('198.18.0.1','reserved',False),('224.0.0.1','reserved',False),('not-an-ip','reserved',False),
            ('8.8.8.8','global',True),('9.9.9.9','global',True)):
            with self.subTest(address=address):
                self.set_wan(address); data=self.run_status('--json')
                self.assertEqual(scope,data['wan_scope']); self.assertEqual(candidate,data['direct_candidate'])
                self.assertEqual('A',data['record_type']); self.assertFalse(data.get('reachable',False))
    def test_only_public_typed_metadata_is_returned_and_uptime_is_converted(self):
        (self.root/'var/run/ddns/tr3000_direct.update').write_text('900\n')
        (self.root/'var/run/ddns/tr3000_direct.err').write_text(self.token+' PRIVATE-SENTINEL\n')
        before=(self.root/'etc/config/ddns').read_bytes()
        data=self.run_status('--json')
        self.assertTrue(data['configured']); self.assertTrue(data['enabled'])
        self.assertEqual('bench.example.invalid',data['hostname'])
        self.assertEqual(1699999900,data['last_update'])
        self.assertEqual(before,(self.root/'etc/config/ddns').read_bytes())
    def test_invalid_hostname_and_public_credential_file_are_not_configured(self):
        self.options['lookup_host']='PRIVATE-SENTINEL/invalid'; self.save_config()
        data=self.run_status('--json'); self.assertFalse(data['configured']); self.assertEqual('',data['hostname'])
        self.options['lookup_host']='bench.example.invalid'; self.save_config()
        (self.root/'etc/config/ddns').chmod(0o644)
        self.assertFalse(self.run_status('--json')['configured'])
    def test_bad_standard_update_metadata_cannot_crash_or_forge_a_timestamp(self):
        p=self.root/'var/run/ddns/tr3000_direct.update'
        for stamp in ('PRIVATE-SENTINEL','09','1:2','99999999999','1001','0'):
            with self.subTest(stamp=stamp):
                p.write_text(stamp+'\n')
                self.assertIsNone(self.run_status('--json')['last_update'])

    def test_unsafe_provider_options_are_not_accepted_as_configured(self):
        for option,value in (('cacert','IGNORE'),('ip_source','script'),('proxy','http://proxy.example.invalid'),
                             ('update_script','/tmp/untrusted'),('use_ipv6','1')):
            with self.subTest(option=option):
                self.options[option]=value; self.save_config()
                self.assertFalse(self.run_status('--json')['configured'])
                del self.options[option]
                self.options.update({'ip_source':'network','use_ipv6':'0'})

    def test_unknown_cli_never_mutates_private_config(self):
        before=(self.root/'etc/config/ddns').read_bytes()
        for args in ((),('enable',),('--json','--token',self.token),('status','--json')):
            with self.subTest(args=args): self.run_status(*args,code=2)
        self.assertEqual(before,(self.root/'etc/config/ddns').read_bytes())
