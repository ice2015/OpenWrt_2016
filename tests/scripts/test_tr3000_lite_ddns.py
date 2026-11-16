"""Read-only DDNS metadata boundaries: no provider API or private log imports."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
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
    if args[0]=='commit': sys.exit(0)
    if args[0]=='set':
        if directory==root/'etc/config': sys.exit(9)
        key,value=args[1].split('=',1)
        assert key=='ddns.tr3000_direct.ip_network' and value in ('wan','wwan','usbwan')
        path=directory/'ddns'; text=path.read_text()
        text=re.sub(r"(?m)^\\s*option ip_network .*",' option ip_network '+shlex.quote(value),text)
        path.write_text(text); sys.exit(0)
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
            ('tr3000-lite-remote',{'schema_version':1,'identity':'TR3000-BENCH-01','enrolled':True,
                'checks':{'result':'ok'},'degraded':False,
                'policy':{'allow_luci':True,'allow_plant':False},'effective':{'allow_luci':True,'allow_plant':False},
                'sources':{'direct':['10.77.0.10/32'],'vps':['10.88.0.20/32']},
                'plant':{'address':'192.168.10.254','cidr':'192.168.10.0/24'},
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
        path=self.root/'status.sh'; path.write_text(text); path.chmod(0o755)
        result=subprocess.run([bash_executable(),str(path),*args],capture_output=True,text=True,
                              env=dict(os.environ,DDNS_FIXTURE=str(self.root),DDNS_PYTHON=sys.executable))
        self.assertEqual(code,result.returncode,result.stdout+result.stderr)
        for private in (self.token,'PRIVATE-SENTINEL'): self.assertNotIn(private,result.stdout+result.stderr)
        if code==0: self.assertEqual('',result.stderr,'typed status must not leak parser diagnostics')
        if code!=0: return None
        return json.loads(result.stdout)

    def run_event(self,*args,code=0):
        source=ROOT/'scripts/tr3000-lite-ddns-event.sh'
        self.assertTrue(source.is_file(),'bounded managed DDNS event worker is missing')
        # Materialize the already-tested status path in this fixture first.
        self.run_status('--json')
        text=source.read_text().replace('PATH=/usr/sbin:/usr/bin:/sbin:/bin','PATH="'+str(self.root/'bin')+':/usr/bin:/bin"')
        text=text.replace('OWNER_UID=0','OWNER_UID='+str(os.getuid()))
        text=text.replace('/usr/sbin/lite-common.sh',str(ROOT/'scripts/lite-common.sh'))
        text=text.replace('/usr/lib/tr3000-lite/ddns-lib.sh',str(ROOT/'scripts/tr3000-lite-ddns-lib.sh'))
        text=text.replace('/usr/sbin/tr3000-lite-ddns-status',str(self.root/'status.sh'))
        text=text.replace('/usr/sbin/tr3000-lite-remote',str(self.root/'bin/tr3000-lite-remote'))
        text=text.replace('/usr/sbin/tr3000-lite-uplink-status',str(self.root/'bin/tr3000-lite-uplink-status'))
        text=text.replace('/usr/lib/ddns/dynamic_dns_updater.sh',str(self.root/'bin/updater'))
        text=text.replace('/usr/lib/tr3000-lite/ddns-event',str(self.root/'event.sh'))
        for prefix in ('/etc/config','/var/run','/var/lock','/tmp/.uci','/proc/uptime'):
            text=text.replace(prefix,str(self.root)+prefix)
        path=self.root/'event.sh'; path.write_text(text); path.chmod(0o755)
        result=subprocess.run([bash_executable(),str(path),*args],capture_output=True,text=True,
                              env=dict(os.environ,DDNS_FIXTURE=str(self.root),DDNS_PYTHON=sys.executable))
        self.assertEqual(code,result.returncode,result.stdout+result.stderr)
        self.assertNotIn(self.token,result.stdout+result.stderr)
        self.assertNotIn('PRIVATE-SENTINEL',result.stdout+result.stderr)
    def prepare_updater(self):
        p=self.root/'bin/updater'
        p.write_text('''#!/bin/sh
printf '%s\\n' "$*" >> "$DDNS_FIXTURE/updater.calls"
[ "$VERBOSE_MODE" = 2 ] || exit 9
[ ! -f "$DDNS_FIXTURE/var/run/ddns/tr3000_direct.pid" ] || exit 9
if [ -f "$DDNS_FIXTURE/update-blocks" ]; then
    while [ ! -f "$DDNS_FIXTURE/update-release" ]; do sleep 0.02; done
fi
if [ -f "$DDNS_FIXTURE/update-fails" ]; then
    printf 'PRIVATE-SENTINEL' >&2
    exit 1
fi
cut -d. -f1 "$DDNS_FIXTURE/proc/uptime" | cut -d' ' -f1 > "$DDNS_FIXTURE/var/run/ddns/tr3000_direct.update"
'''); p.chmod(0o755)
        p=self.root/'bin/timeout'
        p.write_text('''#!/bin/sh
[ "$1:$2:$3:$4:$5" = '-s:TERM:-k:5:360' ] || exit 9
shift 5
[ ! -f "$DDNS_FIXTURE/update-times-out" ] || exit 124
exec "$@"
'''); p.chmod(0o755)
    def wait_for(self,predicate):
        deadline=time.monotonic()+8
        while time.monotonic()<deadline:
            if predicate(): return
            time.sleep(0.02)
        self.fail('bounded DDNS worker did not publish completion')
    def test_stable_event_debounces_and_never_repeats_same_request(self):
        self.prepare_updater()
        self.run_event('notify','wan','')
        self.run_event('tick')
        self.assertFalse((self.root/'updater.calls').exists(),'debounce must not call provider early')
        (self.root/'proc/uptime').write_text('1031.00 900.00\n')
        self.run_event('tick')
        self.wait_for(lambda:(self.root/'var/run/ddns/tr3000_direct.update').is_file())
        self.run_event('notify','wan','')
        self.run_event('tick')
        self.assertEqual(['-v 2 -S tr3000_direct -- start'],(self.root/'updater.calls').read_text().splitlines())
        self.assertNotIn(self.token,(self.root/'updater.calls').read_text())

    def event_state(self):
        p=self.root/'var/run/tr3000-lite/ddns/state.json'
        try: return json.loads(p.read_text())
        except (FileNotFoundError,json.JSONDecodeError): return {}
    def start_event(self):
        self.prepare_updater(); self.run_event('notify','wan','')
        (self.root/'proc/uptime').write_text('1031.00 900.00\n'); self.run_event('tick')
    def test_update_failure_uses_visible_bounded_backoff_without_reset_on_duplicate(self):
        (self.root/'update-fails').touch(); self.start_event()
        self.wait_for(lambda:self.event_state().get('last_error')=='update_failed')
        first=self.event_state(); self.assertEqual(1,first['retry_count'])
        self.assertTrue(1091<=first['next_retry_uptime']<=1106)
        self.assertEqual('update_failed',self.run_status('--json')['last_error'])
        self.run_event('notify','wan',''); self.assertEqual(first,self.event_state())
        (self.root/'proc/uptime').write_text(str(first['next_retry_uptime']-1)+'.00 0\n')
        self.run_event('tick'); self.assertEqual(1,len((self.root/'updater.calls').read_text().splitlines()))
        (self.root/'proc/uptime').write_text(str(first['next_retry_uptime'])+'.00 0\n')
        self.run_event('tick'); self.wait_for(lambda:self.event_state().get('retry_count')==2)
        second=self.event_state(); self.assertTrue(120<=second['next_retry_uptime']-first['next_retry_uptime']<=135)
    def test_unenrolled_private_egress_and_pending_config_never_start_provider(self):
        self.prepare_updater()
        remote=self.root/'bin/tr3000-lite-remote'; original=remote.read_text()
        remote.write_text(original.replace('"enrolled": true','"enrolled": false'))
        self.run_event('notify','wan',''); (self.root/'proc/uptime').write_text('1031.00 0\n'); self.run_event('tick')
        self.assertFalse((self.root/'updater.calls').exists())
        remote.write_text(original); self.set_wan('100.64.0.1'); self.run_event('tick')
        self.assertFalse((self.root/'updater.calls').exists())
        self.set_wan('8.8.8.8')
        p=self.root/'tmp/.uci'; p.mkdir(parents=True); (p/'ddns').write_text('pending\n')
        self.run_event('tick'); self.assertFalse((self.root/'updater.calls').exists())
    def test_timeout_is_typed_and_stale_pid_cannot_target_an_unrelated_process(self):
        (self.root/'update-times-out').touch(); self.start_event()
        self.wait_for(lambda:self.event_state().get('last_error')=='update_timeout')
        self.assertEqual('update_timeout',self.run_status('--json')['last_error'])
        (self.root/'update-times-out').unlink()
        (self.root/'var/run/ddns/tr3000_direct.pid').write_text(str(os.getpid())+'\n')
        due=self.event_state()['next_retry_uptime']
        (self.root/'proc/uptime').write_text(str(due)+'.00 0\n'); self.run_event('tick')
        self.wait_for(lambda:self.event_state().get('last_error')=='')
        self.assertFalse((self.root/'var/run/ddns/tr3000_direct.pid').exists())
    def test_only_one_nonblocking_worker_and_foreign_lock_is_preserved(self):
        (self.root/'update-blocks').touch(); self.start_event()
        try:
            self.wait_for(lambda:(self.root/'updater.calls').is_file())
            self.run_event('tick'); self.run_event('tick')
            self.assertEqual(1,len((self.root/'updater.calls').read_text().splitlines()))
        finally: (self.root/'update-release').touch()
        self.wait_for(lambda:self.event_state().get('last_error')=='')
        lock=self.root/'var/run/tr3000-lite/ddns/lock'; lock.mkdir(); (lock/'other-owner').touch()
        self.run_event('tick'); self.assertTrue((lock/'other-owner').exists())
    def test_lost_worker_reservation_recovers_without_signaling_unrelated_pid(self):
        self.prepare_updater(); self.run_event('notify','wan','')
        work=self.root/'var/run/tr3000-lite/ddns/work'; work.mkdir()
        (work/'request').write_text(self.event_state()['request_id']+'\n')
        (work/'pid').write_text(str(os.getpid())+'\n'); (work/'started').write_text('900\n')
        (self.root/'proc/uptime').write_text('1031.00 0\n'); self.run_event('tick')
        self.wait_for(lambda:self.event_state().get('last_error')=='')
        self.assertEqual(1,len((self.root/'updater.calls').read_text().splitlines()))
    def test_six_failures_exhaust_budget_and_config_change_resets_it(self):
        (self.root/'update-fails').touch(); self.start_event()
        for count in range(1,7):
            self.wait_for(lambda:self.event_state().get('retry_count')==count)
            state=self.event_state()
            if count<6:
                (self.root/'proc/uptime').write_text(str(state['next_retry_uptime'])+'.00 0\n')
                self.run_event('tick')
        self.assertEqual('retry_exhausted',self.event_state()['last_error'])
        (self.root/'proc/uptime').write_text('30000.00 0\n'); self.run_event('tick')
        self.assertEqual(6,len((self.root/'updater.calls').read_text().splitlines()))
        self.options['password']=self.token+'NEW'; self.save_config()
        self.run_event('notify','wan','')
        self.assertEqual(0,self.event_state()['retry_count'])
        self.assertEqual('pending_update',self.event_state()['last_error'])

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
