#!/bin/sh
# Sanitized stable transition notification and single-wg restart.
PATH=/usr/sbin:/usr/bin:/sbin:/bin
export PATH
if [ "${1:-}" = --help ]; then
	printf 'Usage: %s ACTIVE PREVIOUS\n' "$0"
	exit 0
fi
[ "$#" -eq 2 ] || exit 2
for network in "$1" "$2"; do
	case "$network" in ''|wan|wwan|usbwan) ;; *) exit 2 ;; esac
done
result=0
ubus send tr3000-full.uplink-changed \
	"{\"schema_version\":1,\"active\":\"$1\",\"previous\":\"$2\"}" >/dev/null 2>&1 || result=1
# Full has one standard wg interface; restart it only when configured+enabled
# so a changed egress does not leave the tunnel on a dead path.
if [ "$(uci -q get network.wg.proto 2>/dev/null)" = wireguard ] &&
	[ "$(uci -q get network.wg.auto 2>/dev/null)" = 1 ]; then
	ifdown wg >/dev/null 2>&1 && ifup wg >/dev/null 2>&1 || result=1
fi
exit "$result"
