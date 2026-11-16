#!/bin/sh
# Sanitized stable transition notification and gated WG role restart.
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
ubus send tr3000-lite.uplink-changed \
	"{\"schema_version\":1,\"active\":\"$1\",\"previous\":\"$2\"}" >/dev/null 2>&1 || result=1
REMOTE=/usr/sbin/tr3000-lite-remote
if [ -x "$REMOTE" ] && [ ! -L "$REMOTE" ]; then
	"$REMOTE" sync >/dev/null 2>&1 || exit 1
	snapshot=$("$REMOTE" status --json 2>/dev/null) || exit 1
	[ "$(printf '%s' "$snapshot" | jsonfilter -e '@.schema_version' 2>/dev/null)" = 1 ] || exit 1
	for role in wg_direct wg_vps; do
		configured=$(printf '%s' "$snapshot" | jsonfilter -e "@.roles.$role.configured" 2>/dev/null)
		enabled=$(printf '%s' "$snapshot" | jsonfilter -e "@.roles.$role.enabled" 2>/dev/null)
		[ "$configured:$enabled" = true:true ] || continue
		[ "$(uci -q get "network.$role.proto" 2>/dev/null)" = wireguard ] &&
			[ "$(uci -q get "network.$role.auto" 2>/dev/null)" = 1 ] || continue
		ifdown "$role" >/dev/null 2>&1 && ifup "$role" >/dev/null 2>&1 || result=1
	done
fi
exit "$result"
