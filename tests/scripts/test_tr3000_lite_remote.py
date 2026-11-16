"""Remote access validation first; controller integration follows in this module."""
import base64
import subprocess
import unittest

from tests.scripts.test_scripts import ROOT, bash_executable

LIB=ROOT/'scripts/tr3000-lite-remote-lib.sh'
COMMON=ROOT/'scripts/lite-common.sh'


class RemoteValidationTests(unittest.TestCase):
    def run_library(self, body, *arguments, stdin=''):
        self.assertTrue(LIB.is_file(),'remote access validation library is missing')
        return subprocess.run([bash_executable(),'-c','. "$1"; . "$2"; shift 2; '+body,
                               'remote-test',str(COMMON),str(LIB),*arguments],
                              input=stdin,capture_output=True,text=True)

    def test_only_exact_unicast_ipv4_sources_are_accepted(self):
        for source,valid in (
            ('10.77.0.10/32',True),('192.168.20.7/32',True),
            ('10.77.0.10/24',False),('0.0.0.0/0',False),('0.0.0.0/32',False),
            ('127.0.0.1/32',False),('224.0.0.1/32',False),('255.255.255.255/32',False),
            ('10.77.0.999/32',False),('010.77.0.10/32',False),('10.77.0.10/032',False),
            ('::1/128',False),('10.77.0.10',False),('10.77.0.10/32/32',False),
            ('10.77.0.10/32 10.77.0.11/32',False),('../private',False),('',False)):
            with self.subTest(source=source):
                result=self.run_library('remote_valid_source "$1"',source)
                self.assertEqual(valid,result.returncode==0,result.stderr)
                self.assertEqual('',result.stdout)

    def test_source_set_is_unique_and_emits_nothing_until_entire_set_is_valid(self):
        result=self.run_library('remote_source_set',stdin='10.77.0.12/32\n10.77.0.10/32\n')
        self.assertEqual(0,result.returncode,result.stderr)
        self.assertEqual('10.77.0.10/32\n10.77.0.12/32\n',result.stdout)
        empty=self.run_library('remote_source_set')
        self.assertEqual(0,empty.returncode); self.assertEqual('',empty.stdout)
        for bad in ('10.77.0.10/32','10.77.0.12/24','0.0.0.0/0','::1/128','',
                    '10.77.0.20/32;reboot','10.77.0.20/32 10.77.0.21/32'):
            with self.subTest(bad=bad):
                result=self.run_library('remote_source_set',stdin='10.77.0.10/32\n'+bad+'\n')
                self.assertNotEqual(0,result.returncode)
                self.assertEqual('',result.stdout,'partial valid prefix must not escape validation')
                self.assertEqual('',result.stderr)

    def test_key_format_is_validated_without_echoing_key_material(self):
        # Synthetic serialization fixtures, not deployed credentials.
        valid=base64.b64encode(bytes(range(1,33))).decode()
        for key,accepted in ((valid,True),(valid[:-1],False),(valid+'=',False),
                             (valid[:-2]+'==',False),('!'+valid[1:],False),
                             (valid+'\n',False),('',False)):
            with self.subTest(length=len(key),accepted=accepted):
                result=self.run_library('remote_key_format "$1"',key)
                self.assertEqual(accepted,result.returncode==0)
                self.assertEqual('',result.stdout+result.stderr)
        missing=self.run_library('set -u; remote_key_format')
        self.assertNotEqual(0,missing.returncode)
        self.assertEqual('',missing.stdout+missing.stderr)

    def test_device_identifier_is_not_an_arbitrary_path(self):
        for identifier,accepted in (('TR3000-001',True),('bench_02',True),('a'*64,True),
                                    ('a'*65,False),('../device',False),('/etc/shadow',False),
                                    ('-device',False),('_device',False),('a b',False),('',False)):
            with self.subTest(identifier=identifier):
                result=self.run_library('remote_valid_id "$1"',identifier)
                self.assertEqual(accepted,result.returncode==0)
                self.assertEqual('',result.stdout+result.stderr)

    def test_parser_accepts_only_fixed_commands_and_exact_boolean_options(self):
        for args,expected in (
            (('status','--json'),'status||'), (('sync',),'sync||'),
            (('set-policy','--allow-luci','true','--allow-plant','false'),'set-policy|true|false'),
            (('set-policy','--allow-plant','true','--allow-luci','false'),'set-policy|false|true')):
            with self.subTest(args=args):
                result=self.run_library('remote_parse "$@" || exit 2; printf "%s|%s|%s" "$REMOTE_COMMAND" "$ALLOW_LUCI" "$ALLOW_PLANT"',*args)
                self.assertEqual(0,result.returncode,result.stderr)
                self.assertEqual(expected,result.stdout)
        for args in ((),('status',),('status','--json','--json'),('sync','--json'),
                     ('set-policy','--allow-luci','true'),
                     ('set-policy','--allow-luci','TRUE','--allow-plant','false'),
                     ('set-policy','--allow-luci','','--allow-luci','true','--allow-plant','false'),
                     ('set-policy','--allow-luci','false','--allow-plant','true','--allow-plant','false'),
                     ('set-policy','--allow-luci','true','--allow-plant','false','--root','/private'),
                     ('restore','--backup','../../private')):
            with self.subTest(args=args):
                result=self.run_library('remote_parse "$@" || exit 2',*args)
                self.assertEqual(2,result.returncode)
                self.assertEqual('',result.stdout+result.stderr)


if __name__=='__main__': unittest.main()
