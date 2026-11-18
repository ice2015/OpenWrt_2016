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
    if 'route' in args: print('192.168.10.0/24 dev br-lan\n' + os.environ.get('EXTRA_ROUTE',''))
    elif 'addr' in args:
        if failure != 'missing_ip' or not fail_once('missing_ip'):
            text = (root/'etc/config/network').read_text()
            import ipaddress, shlex
            address = mask = None; section = None
            for line in text.splitlines():
                tokens = shlex.split(line, comments=True)
                if not tokens: continue
                if tokens[0] == 'config': section = tokens[2] if len(tokens) > 2 else None
                elif section == 'plant' and tokens[0] == 'option':
                    if tokens[1] == 'ipaddr': address = tokens[2]
                    elif tokens[1] == 'netmask': mask = tokens[2]
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
        # The shipped default leaves the industrial segment unbound; the
        # controller only manages an address once the port is handed over.
        network = config/'network'
        network.write_text(network.read_text().replace(
            "config interface 'plant'\n\toption proto 'none'\n",
            "config interface 'plant'\n\toption device 'eth1'\n\toption proto 'static'\n"
            "\toption ipaddr '192.168.20.254'\n\toption netmask '255.255.255.0'\n",
        ))
        (self.root/'etc/shadow').write_text('root:!:0:0:99999:7:::\n')
        self.before = {name: (config/name).read_bytes() for name in ('network','firewall')}
        bindir = self.root/'bin'; bindir.mkdir()
        (bindir/'fake.py').write_text(FAKE)
        commands = ('uci','ip','arping','fw4','ubus') + (('stat',) if os.name == 'nt' else ())
        for command in commands:
            script = bindir/command
            script.write_text('#!/bin/sh\nexec "$TEST_PYTHON" -S "$PLANT_ROOT/bin/fake.py" '+command+' "$@"\n', newline='\n')
            script.chmod(0o755)
        self.env = dict(os.environ, PLANT_ROOT=self.root.as_posix(), TEST_PYTHON=Path(sys.executable).as_posix(), PLANT_TEST_MODE='1')
        self.env['PATH'] = bindir.as_posix()+os.pathsep+os.environ['PATH']

    def run_controller(self, *args, code=0, **environment):
        result = subprocess.run([bash_executable(), '-c', 'PATH="$(cd "$PLANT_ROOT/bin" && pwd):$PATH"; PLANT_TEST_PATH=$PATH; export PATH PLANT_TEST_PATH; exec sh "$@"', 'sh', (ROOT/'scripts/tr3000-lite-plant.sh').as_posix(), *args], env=dict(self.env, **environment), text=True, capture_output=True)
        self.assertEqual(code, result.returncode, result.stdout+result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual({'schema_version','plant','checks','backup_id','rollback'}, set(data))
        self.assertEqual(1, data['schema_version'])
        return data

    def unchanged(self):
        for name, contents in self.before.items():
            self.assertEqual(contents, (self.root/'etc/config'/name).read_bytes())

    def reset_live(self):
        for name, contents in self.before.items():
            (self.root/'etc/config'/name).write_bytes(contents)

    def apply(self, **kw):
        return self.run_controller('apply','--address','192.168.20.254/24','--allow-luci','false','--allow-mgmt','true',**kw)

    def startup_probe(self, identity, **environment):
        # Run actual startup and location selection under a chosen shell $0.
        # The harness supplies the source library because Windows cannot mount
        # this fixture at the real /usr/sbin and /usr/lib installation paths.
        source = (ROOT/'scripts/tr3000-lite-plant.sh').read_text()
        bootstrap = source.split('SCRIPT_DIR=',1)[0]
        locations = source[source.index('ROOT='):source.index('CHECKS=')]
        program = 'PATH="$(cd "$PLANT_ROOT/bin" && pwd):$PATH"; export PATH\n' + bootstrap + '''
dirname "$0" >/dev/null
. "$1"
''' + locations + '''
printf '%s\n' "$PATH" "$ROOT" "$CONFIG" "$BACKUPS" "$LOCK"
'''
        result = subprocess.run([bash_executable(),'-c',program,identity,(ROOT/'scripts/tr3000-lite-plant-lib.sh').as_posix()],env=dict(self.env,**environment),text=True,capture_output=True)
        self.assertEqual(0,result.returncode,result.stdout+result.stderr)
        return result.stdout.splitlines()

    def hostile_discovery_command(self):
        path = self.root/'bin/dirname'
        path.write_text('#!/bin/sh\nprintf invoked > "$PLANT_ROOT/hijacked"\nprintf /attacker\n',newline='\n')
        path.chmod(0o755)

    def test_installed_identity_resets_path_before_command_discovery(self):
        self.hostile_discovery_command()
        data = self.startup_probe('/usr/sbin/tr3000-lite-plant',PLANT_TEST_PATH='/attacker:/usr/bin:/bin')
        self.assertFalse((self.root/'hijacked').exists())
        self.assertEqual('/usr/sbin:/usr/bin:/sbin:/bin',data[0])

    def test_installed_identity_ignores_fixture_and_location_environment(self):
        data = self.startup_probe('/usr/sbin/tr3000-lite-plant',PLANT_TEST_PATH='/attacker',PLANT_TEST_ROOT='/attacker',ROOT='/attacker',CONFIG='/attacker',BACKUPS='/attacker',LOCK='/attacker',SCRIPT_DIR='/attacker')
        self.assertEqual(['','/etc/config','/etc/tr3000-lite/backups','/var/lock/tr3000-lite-plant'],data[1:])

    def test_source_identity_requires_explicit_test_mode(self):
        identity = (ROOT/'scripts/tr3000-lite-plant.sh').as_posix()
        for mode in ('','0'):
            with self.subTest(mode=mode):
                data = self.startup_probe(identity,PLANT_TEST_MODE=mode,PLANT_TEST_PATH='/attacker')
                self.assertEqual('/usr/sbin:/usr/bin:/sbin:/bin',data[0])
                self.assertEqual('',data[1])
        data = self.startup_probe(identity,PLANT_TEST_MODE='1',PLANT_TEST_PATH='/fixture:/usr/bin:/bin')
        self.assertEqual('/fixture:/usr/bin:/bin',data[0])
        self.assertEqual(self.root.as_posix(),data[1])

    def test_test_mode_predicate_is_bound_to_source_identity(self):
        for identity, mode, expected in (('/usr/sbin/tr3000-lite-plant','1','disabled'),('/tmp/tr3000-lite-plant','1','disabled'),('/repo/scripts/tr3000-lite-plant.sh','0','disabled'),('/repo/scripts/tr3000-lite-plant.sh','1','enabled')):
            with self.subTest(identity=identity,mode=mode):
                result = subprocess.run([bash_executable(),'-c','. "$1"; if plant_test_mode_allowed "$0" "$2"; then printf enabled; else printf disabled; fi',identity,(ROOT/'scripts/tr3000-lite-plant-lib.sh').as_posix(),mode],text=True,capture_output=True)
                self.assertEqual(0,result.returncode,result.stderr)
                self.assertEqual(expected,result.stdout)

    def write_backup(self, identifier, *, network=None, firewall=None):
        backups = self.root/'etc/tr3000-lite/backups'
        backups.mkdir(parents=True,exist_ok=True)
        for package, contents in (('network',network),('firewall',firewall)):
            path = backups/(identifier+'.'+package)
            path.write_bytes(self.before[package] if contents is None else contents)
            path.chmod(0o600)
        return backups

    def seed_five_backups(self):
        for number in range(5):
            backups = self.write_backup('old'+str(number))
            for package in ('network','firewall'):
                os.utime(backups/('old'+str(number)+'.'+package),(100+number,100+number))
        return backups

    def assert_five_backup_pairs(self):
        backups = self.root/'etc/tr3000-lite/backups'
        network = {p.stem for p in backups.glob('*.network')}
        firewall = {p.stem for p in backups.glob('*.firewall')}
        self.assertEqual(5,len(network))
        self.assertEqual(network,firewall)

    def test_status_and_valid_address(self):
        for data in (self.run_controller('status','--json'), self.run_controller('validate','--address','192.168.20.254/24')):
            self.assertEqual('192.168.20.254',data['plant']['address'])
            self.assertEqual(24,data['plant'].get('prefix'))
            self.assertEqual('255.255.255.0',data['plant'].get('netmask'))
        self.unchanged()

    def test_the_access_segment_is_not_a_valid_plant_address(self):
        # 192.168.10.0/24 now belongs to the operator-facing access segment.
        data = self.run_controller('validate','--address','192.168.10.254/24',code=2)
        self.assertEqual('management_overlap',data['checks']['result'])
        self.unchanged()

    def test_apply_updates_the_shipped_management_plant_rules(self):
        self.apply()
        firewall = (self.root/'etc/config/firewall').read_text()
        self.assertNotIn('tr3000_lite_mgmt_plant', firewall)
        self.assertIn('tr3000_lite_lan_plant_tcp', firewall)
        self.assertIn('tr3000_lite_lan_plant_snat_tcp', firewall)

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
        for address in ('999.1.1.1/24','192.168.20.1/31','192.168.20.0/24','192.168.20.255/24','192.168.10.254/24','192.168.1.1/16'):
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

    def test_restore_gates_all_values_except_explicit_disabled_booleans(self):
        for value in (None,'true','yes','on','1','invalid',''):
            with self.subTest(enabled=value):
                self.reset_live()
                old = b"option name 'Allow-Lite-plant-HTTPS'\n\toption enabled '0'"
                new = b"option name 'Allow-Lite-plant-HTTPS'"
                if value is not None: new += ("\n\toption enabled '"+value+"'").encode()
                self.write_backup('policy',firewall=self.before['firewall'].replace(old,new))
                data = self.run_controller('restore','--backup-id','policy',code=2)
                self.assertEqual('management_not_initialized',data['checks']['result'])
                self.unchanged()

    def test_restore_accepts_explicit_disabled_boolean_values(self):
        for value in ('false','no','off','0'):
            with self.subTest(enabled=value):
                firewall = self.before['firewall'].replace(b"option name 'Allow-Lite-plant-HTTPS'\n\toption enabled '0'",("option name 'Allow-Lite-plant-HTTPS'\n\toption enabled '"+value+"'").encode())
                self.write_backup('disabled',firewall=firewall)
                self.run_controller('restore','--backup-id','disabled')
                self.assertEqual(firewall,(self.root/'etc/config/firewall').read_bytes())

    def test_restore_checks_candidate_before_replacing_live_pair(self):
        self.write_backup('obsolete',network=self.before['network'].replace(b'192.168.10.254',b'192.168.30.254'),firewall=self.before['firewall']+b'\n# invalid candidate\n')
        data = self.run_controller('restore','--backup-id','obsolete',code=3,FAILURE='candidate')
        self.assertEqual('candidate_firewall',data['checks']['result'])
        self.unchanged()
        self.assertEqual(self.before['network'].decode(),(self.root/'checked-network').read_text())
        self.assertNotIn('ubus call network reload',(self.root/'events').read_text())
        self.assertFalse((self.root/'var/run/uci/firewall').exists())

    def test_failed_restore_recovers_exact_pre_restore_pair(self):
        self.write_backup('older',network=self.before['network'].replace(b'192.168.10.254',b'192.168.30.254'),firewall=self.before['firewall']+b'\n# older policy\n')
        for failure in ('network','firewall','missing_ip','wrong_prefix','degraded'):
            with self.subTest(failure=failure):
                self.reset_live()
                data = self.run_controller('restore','--backup-id','older',code=3,FAILURE=failure)
                self.assertEqual('degraded' if failure == 'degraded' else 'restored',data['rollback'])
                self.unchanged()
                self.assertNotEqual('older',data['backup_id'])
                for package in ('network','firewall'):
                    self.assertEqual(self.before[package],(self.root/'etc/tr3000-lite/backups'/(data['backup_id']+'.'+package)).read_bytes())

    def test_failed_apply_enforces_backup_retention(self):
        for failure in ('candidate','network'):
            with self.subTest(failure=failure):
                self.seed_five_backups()
                self.apply(code=3,FAILURE=failure)
                self.assert_five_backup_pairs()
                self.unchanged()

    def test_failed_restore_enforces_backup_retention(self):
        self.seed_five_backups()
        data = self.run_controller('restore','--backup-id','old0',code=3,FAILURE='network')
        self.assertEqual('restored',data['rollback'])
        self.assert_five_backup_pairs()
        self.unchanged()

    def test_only_five_private_backup_pairs_remain(self):
        for _ in range(6): self.apply()
        backups = self.root/'etc/tr3000-lite/backups'
        self.assertEqual(5,len(list(backups.glob('*.network'))))
        self.assertEqual(5,len(list(backups.glob('*.firewall'))))
        if os.name != 'nt':
            for path in backups.iterdir(): self.assertEqual(0o600,path.stat().st_mode & 0o777)


if __name__ == '__main__': unittest.main()
