"""Execute the Lite-only reservation of one stock DDNS bulk-start section."""
import pathlib
import subprocess
import tempfile
import unittest
from tests.scripts.test_scripts import ROOT, bash_executable

# Relevant unmodified function from packages171d5f... ddns-scripts2.8.2-68.
STOCK='''start_daemon_for_all_ddns_sections()
{
	local __EVENTIF="$1"
	local __SECTIONS=""
	local __SECTIONID=""
	local __IFACE=""

	load_all_service_sections __SECTIONS
	for __SECTIONID in $__SECTIONS; do
		config_get __IFACE "$__SECTIONID" interface "wan"
		[ -z "$__EVENTIF" -o "$__IFACE" = "$__EVENTIF" ] || continue
		if [ $VERBOSE -eq 0 ]; then	# start in background
			/usr/lib/ddns/dynamic_dns_updater.sh -v 0 -S "$__SECTIONID" -- start &
		else
			/usr/lib/ddns/dynamic_dns_updater.sh -v "$VERBOSE" -S "$__SECTIONID" -- start
		fi
	done
}
'''

class DdnsPrepareTests(unittest.TestCase):
    def test_bulk_start_skips_managed_section_but_keeps_foreign_and_original_source(self):
        script=ROOT/'scripts/prepare-lite-ddns.py'
        self.assertTrue(script.is_file(),'Lite stock DDNS reservation tool is missing')
        with tempfile.TemporaryDirectory() as tmp:
            root=pathlib.Path(tmp); source=root/'source'; source.mkdir(); (source/'Makefile').write_text('all:\n')
            package=root/'packages/net/ddns-scripts'; package.mkdir(parents=True)
            (package/'Makefile').write_text('PKG_VERSION:=2.8.2\nPKG_RELEASE:=68\n')
            native=package/'files/usr/lib/ddns/dynamic_dns_functions.sh'; native.parent.mkdir(parents=True); native.write_text(STOCK)
            command=['python3',str(script),'--source-dir',str(source),'--packages-dir',str(root/'packages')]
            result=subprocess.run(command,capture_output=True,text=True)
            self.assertEqual(0,result.returncode,result.stderr)
            output=source/'files/usr/lib/ddns/dynamic_dns_functions.sh'; first=output.read_bytes()
            self.assertEqual(STOCK,native.read_text(),'do not modify the pinned feed checkout')
            result=subprocess.run(command,capture_output=True,text=True); self.assertEqual(0,result.returncode,result.stderr)
            self.assertEqual(first,output.read_bytes())
            updater=root/'updater'; calls=root/'calls'
            updater.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "'+str(calls)+'"\n'); updater.chmod(0o755)
            body=output.read_text().replace('/usr/lib/ddns/dynamic_dns_updater.sh',str(updater))
            runner=root/'run.sh'
            runner.write_text('VERBOSE=0\nload_all_service_sections() { eval "$1=\\\"tr3000_direct foreign\\\""; }\nconfig_get() { eval "$1=wan"; }\n'+body+'\nstart_daemon_for_all_ddns_sections ""\nwait\n')
            result=subprocess.run([bash_executable(),str(runner)],capture_output=True,text=True)
            self.assertEqual(0,result.returncode,result.stderr)
            self.assertEqual(['-v 0 -S foreign -- start'],calls.read_text().splitlines())
            (package/'Makefile').write_text('PKG_VERSION:=9.0\nPKG_RELEASE:=1\n'); output.unlink()
            result=subprocess.run(command,capture_output=True,text=True)
            self.assertNotEqual(0,result.returncode); self.assertFalse(output.exists(),'unknown source must fail before output')
