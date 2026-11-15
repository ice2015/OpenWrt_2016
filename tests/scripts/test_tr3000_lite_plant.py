"""Exercise the real shell transaction against isolated OpenWrt command doubles."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from tests.scripts.test_scripts import ROOT, bash_executable


FAKE = r'''
import json, os, pathlib, shlex, sys
cmd, *args = sys.argv[1:]
root = pathlib.Path(os.environ['PLANT_ROOT'])
with (root / 'events').open('a') as log:
    log.write(cmd + ' ' + ' '.join(args) + '\n')
with (root / 'arguments.jsonl').open('a') as log:
    log.write(json.dumps([cmd, *args])+'\n')
failure = os.environ.get('FAILURE', '')
def fail_once(name):
    marker = root / ('failed-'+name)
    if marker.exists(): return False
    marker.touch(); return True
if cmd == 'uci':
    directory = root / 'etc/config'
    savedir = root / 'tmp/.uci'
    if '-c' in args:
        n = args.index('-c'); directory = pathlib.Path(args[n+1]); del args[n:n+2]
    if '-C' in args:
        n = args.index('-C'); del args[n:n+2]
    if '-t' in args:
        n = args.index('-t'); savedir = pathlib.Path(args[n+1]); del args[n:n+2]
    args = [a for a in args if a != '-q']
    action, *args = args
    def read(package):
        data = {}; section = None
        for line in (directory / package).read_text().splitlines():
            t = shlex.split(line, comments=True)
            if t and t[0] == 'config': section = t[2] if len(t) > 2 else None
            elif section and len(t) > 2 and t[0] == 'option': data[section+'.'+t[1]] = t[2]
        return data
    if action == 'get':
        package, key = args[0].split('.', 1)
        value = read(package).get(key)
        if value is None: sys.exit(1)
        print(value)
    elif action == 'set':
        key, value = args[0].split('=',1); package, key = key.split('.',1)
        data = read(package); data[key] = value
        sections = {}
        for key, value in data.items():
            section, option = key.split('.',1); sections.setdefault(section, {})[option] = value
        (directory/package).write_text(''.join("config interface '%s'\n"%s+''.join(" option '%s' '%s'\n"%(k,v) for k,v in opts.items()) for s,opts in sections.items()))
    elif action == 'commit':
        # UCI commit consumes saved deltas, even with a relocated confdir.
        (savedir/args[0]).unlink(missing_ok=True)
    else: sys.exit(2)
elif cmd == 'ip':
    if 'route' in args: print('192.168.77.0/24 dev br-mgmt\n' + os.environ.get('EXTRA_ROUTE',''))
    elif 'addr' in args:
        if failure != 'missing_ip' or not fail_once('missing_ip'):
            text = (root/'etc/config/network').read_text()
            import ipaddress, re
            address = re.search(r"option '?ipaddr'? '([^']+)'", text).group(1)
            mask = re.search(r"option '?netmask'? '([^']+)'", text).group(1)
            prefix = ipaddress.IPv4Network('0.0.0.0/'+mask).prefixlen
            if failure == 'wrong_prefix' and fail_once('wrong_prefix'): prefix = 25
            print('2: eth1 inet '+address+'/'+str(prefix)+' scope global eth1')
elif cmd == 'arping': sys.exit(int(os.environ.get('ARP_EXIT','0')))
elif cmd == 'fw4':
    if args == ['check']:
        candidate = root/'var/run/uci/firewall'
        if candidate.exists():
            (root/'checked-network').write_text((root/'etc/config/network').read_text())
            (root/'checked-firewall').write_text(candidate.read_text())
        if failure == 'candidate': sys.exit(1)
    if args == ['reload'] and (failure == 'degraded' or (failure == 'firewall' and fail_once('firewall'))): sys.exit(1)
elif cmd == 'ubus':
    if args == ['call','network','reload'] and (failure == 'degraded' or (failure == 'network' and fail_once('network'))): sys.exit(1)
elif cmd == 'stat':
    # NTFS cannot represent Linux owner/mode; production still uses real stat.
    if args[:2] == ['-c','%a']: print(os.environ.get('BACKUP_MODE','600'))
    elif args[:2] == ['-c','%u']: print('0')
    else: sys.exit(2)
'''


class PlantControllerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root/'tmp').mkdir()
        config = self.root / 'etc/config'
        config.mkdir(parents=True)
        for name in ('network', 'firewall', 'tr3000-lite'):
            shutil.copyfile(ROOT / 'overlays/devices/tr3000-lite/files/etc/config' / name, config/name)
        (self.root/'etc/shadow').write_text('root:!:0:0:99999:7:::\n')
        self.before = {name: (config/name).read_bytes() for name in ('network','firewall')}
        bindir = self.root/'bin'; bindir.mkdir()
        (bindir/'fake.py').write_text(FAKE)
        commands = ('uci','ip','arping','fw4','ubus') + (('stat',) if os.name == 'nt' else ())
        for command in commands:
            script = bindir/command
            script.write_text('#!/bin/sh\nexec "$TEST_PYTHON" -S "$PLANT_ROOT/bin/fake.py" '+command+' "$@"\n', newline='\n')
            script.chmod(0o755)
        self.env = dict(os.environ, PLANT_ROOT=self.root.as_posix(), TEST_PYTHON=Path(sys.executable).as_posix())
        self.env['PATH'] = bindir.as_posix()+os.pathsep+os.environ['PATH']

    def run_controller(self, *args, code=0, **environment):
        result = subprocess.run([bash_executable(), '-c', 'PATH="$(cd "$PLANT_ROOT/bin" && pwd):$PATH"; export PATH; exec sh "$@"', 'sh', (ROOT/'scripts/tr3000-lite-plant.sh').as_posix(), *args], env=dict(self.env, **environment), text=True, capture_output=True)
        self.assertEqual(code, result.returncode, result.stdout+result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual({'schema_version','plant','checks','backup_id','rollback'}, set(data))
        self.assertEqual(1, data['schema_version'])
        return data

    def unchanged(self):
        for name, contents in self.before.items():
            self.assertEqual(contents, (self.root/'etc/config'/name).read_bytes())

    def apply(self, **kw):
        return self.run_controller('apply','--address','192.168.20.254/24','--allow-luci','false','--allow-mgmt','true',**kw)

    def test_status_and_valid_address(self):
        for data in (self.run_controller('status','--json'), self.run_controller('validate','--address','192.168.10.254/24')):
            self.assertEqual('192.168.10.254',data['plant']['address'])
            self.assertEqual(24,data['plant'].get('prefix'))
            self.assertEqual('255.255.255.0',data['plant'].get('netmask'))
        self.unchanged()

    def test_status_reports_applied_prefix(self):
        data = self.run_controller('apply','--address','192.168.20.62/26','--allow-luci','false','--allow-mgmt','true')
        self.assertEqual('192.168.20.62',data['plant']['address'])
        self.assertEqual(26,data['plant'].get('prefix'))
        self.assertEqual('255.255.255.192',data['plant'].get('netmask'))
        self.assertEqual(26,self.run_controller('status','--json')['plant']['prefix'])

    def test_postcheck_rejects_wrong_live_prefix(self):
        data = self.apply(code=3,FAILURE='wrong_prefix')
        self.assertEqual('post_apply_verification',data['checks']['result'])
        self.assertEqual('restored',data['rollback'])
        self.unchanged()

    def test_invalid_inputs_leave_both_configs_unchanged(self):
        for address in ('999.1.1.1/24','192.168.10.1/31','192.168.10.0/24','192.168.10.255/24','192.168.77.254/24','192.168.1.1/16'):
            with self.subTest(address=address):
                self.run_controller('validate','--address',address,code=2)
                self.unchanged()

    def test_unknown_repeated_and_unsafe_arguments(self):
        for args in (('status','--oops'),('validate','--address','192.168.10.254/24','--address','192.168.20.1/24'),('restore','--backup-id','../network'),('apply','--address','192.168.20.254/24','--allow-luci','yes','--allow-mgmt','true')):
            self.run_controller(*args,code=2)
            self.unchanged()

    def test_wan_reuse_routes_and_arp_fail_closed(self):
        for extra in ({'ARP_EXIT':'1'},{'ARP_EXIT':'2'},{'EXTRA_ROUTE':'192.168.10.0/24 dev wg0'}):
            self.run_controller('validate','--address','192.168.10.254/24',code=2,**extra)
            self.unchanged()
        network = self.root/'etc/config/network'
        network.write_text(network.read_text().replace("option device 'eth0'", "option device 'eth1'"))
        self.run_controller('validate','--address','192.168.10.254/24',code=2)

    def test_empty_repeated_options_are_rejected(self):
        self.run_controller('validate','--address','','--address','192.168.10.254/24',code=2)
        self.unchanged()

    def test_candidate_check_precedes_live_changes(self):
        self.apply(code=3,FAILURE='candidate')
        self.unchanged()
        self.assertNotIn('ubus call network reload', (self.root/'events').read_text())
        self.assertFalse((self.root/'var/run/uci/firewall').exists())

    def test_existing_firewall_override_or_delta_is_preserved_and_rejected(self):
        for relative in ('var/run/uci/firewall','tmp/.uci/firewall','var/run/uci/network','tmp/.uci/network'):
            path = self.root/relative; path.parent.mkdir(parents=True,exist_ok=True)
            path.write_text('existing administrator state')
            result = self.apply(code=3)
            self.assertEqual('pending_firewall_state',result['checks']['result'])
            self.assertEqual('existing administrator state',path.read_text())
            self.assertNotIn(' set ', (self.root/'events').read_text())
            self.unchanged()
            path.unlink()

    def test_success_updates_address_and_snat_and_restores_pair(self):
        result = self.apply()
        self.assertEqual(24,result['plant']['prefix'])
        self.assertEqual('255.255.255.0',result['plant']['netmask'])
        firewall = (self.root/'etc/config/firewall').read_text()
        self.assertIn('192.168.20.0/24', firewall)
        self.assertIn('192.168.20.254', firewall)
        self.assertEqual((self.root/'checked-firewall').read_text(),firewall)
        self.assertEqual(self.before['network'].decode(),(self.root/'checked-network').read_text())
        self.assertFalse((self.root/'var/run/uci/firewall').exists())
        for call in map(json.loads,(self.root/'arguments.jsonl').read_text().splitlines()):
            if call[0] == 'uci' and '-c' in call and 'tr3000-lite-candidate.' in call[call.index('-c')+1]:
                self.assertIn('-C',call)
                self.assertEqual('',call[call.index('-C')+1])
                self.assertIn('-t',call)
                self.assertTrue(call[call.index('-t')+1].endswith('/.uci'))
        self.run_controller('restore','--backup-id',result['backup_id'])
        self.unchanged()

    def test_reload_and_postcheck_failures_restore_both(self):
        for failure in ('network','firewall','missing_ip','degraded'):
            with self.subTest(failure=failure):
                data = self.apply(code=3,FAILURE=failure)
                self.assertEqual('degraded' if failure == 'degraded' else 'restored', data['rollback'])
                self.unchanged()

    def test_management_gate(self):
        self.run_controller('apply','--address','192.168.20.254/24','--allow-luci','true','--allow-mgmt','true',code=2)
        self.unchanged()
        (self.root/'etc/tr3000-lite/management-ap.initialized').touch()
        data = self.run_controller('apply','--address','192.168.20.254/24','--allow-luci','true','--allow-mgmt','true',code=2)
        self.assertEqual('root_password_required',data['checks']['result'])
        self.unchanged()

    def test_restore_rejects_nonprivate_backup(self):
        backups = self.root/'etc/tr3000-lite/backups'; backups.mkdir(parents=True)
        for package, contents in self.before.items():
            path = backups/('unsafe.'+package)
            path.write_bytes(contents)
            path.chmod(0o644)
        data = self.run_controller('restore','--backup-id','unsafe',code=2,BACKUP_MODE='644')
        self.assertEqual('backup_permissions',data['checks']['result'])
        self.unchanged()

    def test_restore_rejects_pending_state_before_reading_backup_gate(self):
        backups = self.root/'etc/tr3000-lite/backups'; backups.mkdir(parents=True)
        for package, contents in self.before.items():
            path = backups/('safe.'+package)
            path.write_bytes(contents)
            subprocess.run([bash_executable(),'-c','chmod 600 "$1"','sh',path.as_posix()],check=True)
        delta = self.root/'tmp/.uci/firewall'; delta.parent.mkdir(parents=True)
        delta.write_text("firewall.tr3000_lite_plant_luci.enabled='0'\n")
        data = self.run_controller('restore','--backup-id','safe',code=3)
        self.assertEqual('pending_firewall_state',data['checks']['result'])
        self.assertEqual("firewall.tr3000_lite_plant_luci.enabled='0'\n",delta.read_text())
        self.assertNotIn('ubus call network reload',(self.root/'events').read_text())
        self.unchanged()

    def runtime_symlink(self, target, path):
        # MSYS shortcut symlinks exercise sh's -L/readlink without Windows
        # administrator privileges. Linux uses actual filesystem symlinks.
        self.env['MSYS'] = 'winsymlinks:lnk'
        subprocess.run([bash_executable(),'-c','ln -s "$1" "$2"','sh',target,path.as_posix()],env=self.env,check=True)

    def test_standard_openwrt_var_alias_reaches_backup_validation(self):
        self.runtime_symlink('tmp',self.root/'var')
        data = self.run_controller('restore','--backup-id','missing',code=2)
        self.assertEqual('invalid_backup',data['checks']['result'])
        self.unchanged()

    def test_arbitrary_var_alias_is_rejected(self):
        (self.root/'other').mkdir()
        self.runtime_symlink('other',self.root/'var')
        data = self.apply(code=3)
        self.assertEqual('unsafe_path',data['checks']['result'])
        self.unchanged()

    def test_arbitrary_run_alias_is_rejected(self):
        (self.root/'var').mkdir()
        (self.root/'other').mkdir()
        self.runtime_symlink('../other',self.root/'var/run')
        data = self.apply(code=3)
        self.assertEqual('unsafe_path',data['checks']['result'])
        self.unchanged()

    def test_backup_directory_symlink_is_rejected(self):
        (self.root/'etc/tr3000-lite').mkdir()
        self.runtime_symlink('../../tmp',self.root/'etc/tr3000-lite/backups')
        data = self.apply(code=3)
        self.assertEqual('unsafe_path',data['checks']['result'])
        self.unchanged()

    def test_restore_cannot_bypass_management_gate(self):
        backups = self.root/'etc/tr3000-lite/backups'; backups.mkdir(parents=True)
        for package in ('network','firewall'):
            path = backups/('safe.'+package)
            contents = self.before[package].decode()
            if package == 'firewall':
                contents = contents.replace("option name 'Allow-Lite-plant-HTTPS'\n\toption enabled '0'", "option name 'Allow-Lite-plant-HTTPS'\n\toption enabled '1'")
            path.write_text(contents)
            subprocess.run([bash_executable(),'-c','chmod 600 "$1"','sh',path.as_posix()],check=True)
        data = self.run_controller('restore','--backup-id','safe',code=2)
        self.assertEqual('management_not_initialized',data['checks']['result'])
        self.unchanged()

    def test_only_five_private_backup_pairs_remain(self):
        for _ in range(6): self.apply()
        backups = self.root/'etc/tr3000-lite/backups'
        self.assertEqual(5,len(list(backups.glob('*.network'))))
        self.assertEqual(5,len(list(backups.glob('*.firewall'))))
        if os.name != 'nt':
            for path in backups.iterdir(): self.assertEqual(0o600,path.stat().st_mode & 0o777)


if __name__ == '__main__': unittest.main()
