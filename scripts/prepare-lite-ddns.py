#!/usr/bin/env python3
"""Generate a Lite-only stock-DDNS overlay; never edit the pinned feed checkout."""
import argparse
from pathlib import Path
import re
import shutil
import subprocess
import tempfile


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-dir',required=True,type=Path)
    parser.add_argument('--packages-dir',required=True,type=Path)
    args=parser.parse_args()
    source=args.source_dir.resolve(); package=args.packages_dir.resolve()/'net/ddns-scripts'
    if not (source/'Makefile').is_file(): parser.error('not an OpenWrt source directory')
    try:
        makefile=(package/'Makefile').read_text()
        if not re.search(r'^PKG_VERSION:=2\.8\.2$',makefile,re.M) or not re.search(r'^PKG_RELEASE:=68$',makefile,re.M):
            parser.error('unsupported DDNS package version; revalidate the pinned provider')
        original=(package/'files/usr/lib/ddns/dynamic_dns_functions.sh').read_bytes()
        patch=Path(__file__).resolve().parents[1]/'patches/devices/tr3000-lite/ddns/0001-reserve-managed-bulk-start.patch'
        # Patch an isolated copy first. A failed context must not install partial
        # output, broaden bulk filtering or alter any foreign DDNS section.
        with tempfile.TemporaryDirectory(prefix='lite-ddns-') as tmp:
            tree=Path(tmp); target=tree/'usr/lib/ddns/dynamic_dns_functions.sh'
            target.parent.mkdir(parents=True); target.write_bytes(original)
            subprocess.run(['patch','--batch','--fuzz=0','-p1','-d',str(tree),'-i',str(patch)],
                           check=True,capture_output=True)
            destination=source/'files/usr/lib/ddns/dynamic_dns_functions.sh'
            destination.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(target,destination); destination.chmod(0o644)
    except (OSError,subprocess.CalledProcessError):
        parser.error('cannot prepare pinned DDNS bulk reservation; no usable overlay installed')


if __name__=='__main__':
    main()
