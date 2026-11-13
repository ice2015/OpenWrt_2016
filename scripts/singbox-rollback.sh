#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

usage() {
	printf 'Usage: %s\n' "$0"
	printf 'Stops and disables sing-box, then removes only tr3000_full_singbox_* firewall sections.\n'
}

if [ "${1:-}" = --help ]; then
	usage
	exit 0
fi
[ "$#" -eq 0 ] || { usage >&2; exit 2; }

CONTROLLER=/usr/sbin/tr3000-full-service
[ -x "$CONTROLLER" ] || CONTROLLER="$SCRIPT_DIR/service-toggle.sh"
"$CONTROLLER" disable sing-box

command -v uci >/dev/null 2>&1 || exit 0
[ -r /etc/config/firewall ] || exit 0
SECTIONS=$(uci show firewall 2>/dev/null |
	sed -n 's/^firewall\.\(tr3000_full_singbox_[A-Za-z0-9_]*\)=.*/\1/p')
[ -n "$SECTIONS" ] || {
	printf '%s\n' 'sing-box disabled; no TR3000 Full sing-box firewall sections were present.'
	exit 0
}

BACKUP="/tmp/firewall.before-singbox-rollback.$$"
umask 077
cp -p /etc/config/firewall "$BACKUP"
ROLLBACK=1
restore_firewall() {
	if [ "$ROLLBACK" -eq 1 ]; then
		cp -p "$BACKUP" /etc/config/firewall
		/etc/init.d/firewall reload >/dev/null 2>&1 || :
	fi
	rm -f "$BACKUP"
}
trap restore_firewall EXIT HUP INT TERM
for SECTION in $SECTIONS; do
	uci -q delete "firewall.$SECTION"
done
uci commit firewall
fw4 check
/etc/init.d/firewall reload
ROLLBACK=0
printf '%s\n' 'sing-box disabled and TR3000 Full sing-box firewall sections removed.'
