#!/bin/sh
# Public metadata only. Do not import stock updater logs, UCI dumps or stderr.
PATH=/usr/sbin:/usr/bin:/sbin:/bin
export PATH
set -uf
usage() { printf 'Usage: %s --json\n' "$0"; }
[ "${1:-}" != --help ] || { usage; exit 0; }
[ "$#" = 1 ] && [ "$1" = --json ] || { usage >&2; exit 2; }
. /usr/sbin/lite-common.sh
. /usr/lib/tr3000-lite/ddns-lib.sh
OWNER_UID=0
CONFIG=/etc/config
STOCK_RUN=/var/run/ddns
[ "$(id -u)" = "$OWNER_UID" ] || exit 3
owned_file() {
	[ -f "$1" ] && [ ! -L "$1" ] && [ "$(stat -c %u "$1" 2>/dev/null)" = "$OWNER_UID" ]
}
get() {
	[ ! -L "$CONFIG" ] && owned_file "$CONFIG/ddns" || return 1
	case "$(stat -c %a "$CONFIG/ddns")" in 600|640|644) ;; *) return 1 ;; esac
	uci -q -c "$CONFIG" -C '' get "ddns.tr3000_direct.$1" 2>/dev/null
}
json_get() { jsonfilter -e "$1" 2>/dev/null; }
configured=false; enabled=false; hostname=; last_update=null; last_error=not_configured
network_source=false
case "$(get ip_source || :)" in ''|network) network_source=true ;; esac
hostname=$(get lookup_host || :)
ddns_valid_hostname "$hostname" || hostname=
[ "$(get enabled || :)" != 1 ] || enabled=true
# Never fetch credentials from an insecure/symlinked config file. The token is
# used only in this predicate, never argv, JSON, raw diagnostics or exports.
if owned_file "$CONFIG/ddns" && [ "$(stat -c %a "$CONFIG/ddns")" = 600 ] &&
	[ -n "$hostname" ] && [ "$(get service_name || :)" = cloudflare.com-v4 ] &&
	[ "$(get use_ipv6 || :)" = 0 ] && [ "$(get use_https || :)" = 1 ] &&
	[ "$(get username || :)" = Bearer ] && ddns_cloudflare_domain "$(get domain || :)" "$hostname" &&
	[ "$network_source" = true ] && [ "$(get cacert || :)" != IGNORE ] &&
	[ -z "$(get update_url || :)$(get update_script || :)$(get ip_script || :)$(get proxy || :)" ]; then
	token=$(get password || :)
	case "$token" in ''|*[!A-Za-z0-9_-]*) ;; *) configured=true ;; esac
	unset token
fi
if [ "$configured" = true ]; then
	[ "$enabled" = true ] && last_error=not_updated || last_error=disabled
fi
# .update is standard ddns-scripts uptime, not wall-clock epoch; never read
# .dat/.err/.log (their free-form contents are not a public status contract).
if [ ! -L "$STOCK_RUN" ] && owned_file "$STOCK_RUN/tr3000_direct.update"; then
	stamp=$(cat "$STOCK_RUN/tr3000_direct.update" 2>/dev/null || :)
	uptime=$(cut -d ' ' -f 1 /proc/uptime 2>/dev/null || :); uptime=${uptime%%.*}
	now=$(date +%s)
	if ddns_uint "$stamp" && ddns_uint "$uptime" && ddns_uint "$now" &&
		[ "$stamp" -gt 0 ] && [ "$stamp" -le "$uptime" ] && [ "$now" -ge "$uptime" ]; then
		last_update=$((now - uptime + stamp))
		[ "$configured:$enabled" != true:true ] || last_error=
	fi
fi
active_json=$(/usr/sbin/tr3000-lite-uplink-status --json 2>/dev/null || :)
active=$(printf '%s' "$active_json" | json_get '@.active' || :)
address=
case "$active" in wan|wwan|usbwan)
	status=$(ubus call "network.interface.$active" status 2>/dev/null || :)
	if [ "$(printf '%s' "$status" | json_get '@.up' || :)" = true ]; then
		address=$(printf '%s' "$status" | json_get '@["ipv4-address"][0].address' || :)
	fi ;;
esac
scope=$(ddns_wan_scope "$address"); candidate=false
[ "$scope" != global ] || candidate=true
# Candidacy describes the active IPv4 network only, NOT configuration readiness,
# DNS propagation, inbound UDP, WireGuard authentication or external acceptance.
printf '{"schema_version":1,"configured":%s,"enabled":%s,"hostname":"%s","record_type":"A","last_update":%s,"last_error":"%s","wan_scope":"%s","direct_candidate":%s}\n' \
	"$configured" "$enabled" "$hostname" "$last_update" "$last_error" "$scope" "$candidate"
