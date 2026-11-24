#!/bin/sh
# Internal scheduler. Only the pinned stock section updater performs DNS/API I/O.
PATH=/usr/sbin:/usr/bin:/sbin:/bin
export PATH
set -uf
usage() { printf 'Usage: %s notify ACTIVE PREVIOUS | tick | worker\n' "$0"; }
[ "${1:-}" != --help ] || { usage; exit 0; }
command=${1:-}; [ "$#" -gt 0 ] || exit 2; shift
case "$command" in
	notify) [ "$#" = 2 ] || exit 2; for arg do case "$arg" in ''|wan|wwan|usbwan) ;; *) exit 2 ;; esac; done ;;
	tick|worker) [ "$#" = 0 ] || exit 2 ;;
	*) exit 2 ;;
esac
. /usr/sbin/lite-common.sh
. /usr/lib/tr3000-lite/ddns-lib.sh
OWNER_UID=0
CONFIG=/etc/config
RUNTIME=/var/run/tr3000-lite/ddns
STOCK_RUN=/var/run/ddns
SELF=/usr/lib/tr3000-lite/ddns-event
UPDATER=/usr/lib/ddns/dynamic_dns_updater.sh
CONFIG_LOCK=/var/lock/tr3000-lite-plant
LOCKED=0; CONFIG_LOCKED=0; CANDIDATE=; CHILD=; WORK_OWNED=0
[ "$(id -u)" = "$OWNER_UID" ] || exit 3
owned() { [ -f "$1" ] && [ ! -L "$1" ] && [ "$(stat -c %u "$1" 2>/dev/null)" = "$OWNER_UID" ]; }
jget() { jsonfilter -e "$1" 2>/dev/null; }
clock() { DD_NOW=$(cut -d ' ' -f1 /proc/uptime); DD_NOW=${DD_NOW%%.*}; ddns_uint "$DD_NOW"; }
config_sha() { sha256sum "$CONFIG/ddns" | cut -d ' ' -f1; }
request_id() { printf '%s\n%s\n%s\n' "$DD_CONFIG_SHA" "$DD_ACTIVE" "$DD_ADDRESS" | sha256sum | cut -d ' ' -f1; }
pending() {
	for p in /var/run/uci/ddns /tmp/.uci/ddns; do [ ! -e "$p" ] && [ ! -L "$p" ] || return 0; done
	return 1
}
snapshot() {
	DD_BLOCK=; DD_ACTIVE=; DD_ADDRESS=; DD_CONFIG_SHA=
	if [ -L "$CONFIG" ] || ! owned "$CONFIG/ddns" || [ "$(stat -c %a "$CONFIG/ddns")" != 600 ]; then DD_BLOCK=not_configured; return; fi
	DD_CONFIG_SHA=$(config_sha)
	data=$(/usr/sbin/tr3000-lite-ddns-status --json 2>/dev/null) || { DD_BLOCK=not_configured; return; }
	[ "$(printf '%s' "$data" | jget '@.configured')" = true ] || { DD_BLOCK=not_configured; return; }
	[ "$(printf '%s' "$data" | jget '@.enabled')" = true ] || { DD_BLOCK=disabled; return; }
	remote=$(/usr/sbin/tr3000-lite-remote status --json 2>/dev/null) || { DD_BLOCK=remote_not_ready; return; }
	for field in enrolled gates.root_password gates.ap_initialized gates.identity gates.keys; do
		[ "$(printf '%s' "$remote" | jget "@.$field")" = true ] || { DD_BLOCK=remote_not_ready; return; }
	done
	[ "$(printf '%s' "$remote" | jget '@.checks.result')" = ok ] || { DD_BLOCK=remote_not_ready; return; }
	pending && { DD_BLOCK=pending_config; return; }
	active_json=$(/usr/sbin/tr3000-lite-uplink-status --json 2>/dev/null) || { DD_BLOCK=no_public_egress; return; }
	DD_ACTIVE=$(printf '%s' "$active_json" | jget '@.active')
	case "$DD_ACTIVE" in wan|wwan|usbwan) ;; *) DD_ACTIVE=; DD_BLOCK=no_public_egress; return ;; esac
	address_json=$(ubus call "network.interface.$DD_ACTIVE" status 2>/dev/null) || { DD_BLOCK=no_public_egress; return; }
	[ "$(printf '%s' "$address_json" | jget '@.up')" = true ] || { DD_BLOCK=no_public_egress; return; }
	DD_ADDRESS=$(printf '%s' "$address_json" | jget '@["ipv4-address"][0].address')
	[ "$(ddns_wan_scope "$DD_ADDRESS")" = global ] || { DD_BLOCK=no_public_egress; return; }
}
worker_live() {
	owned "$RUNTIME/work/pid" || return 1
	read -r worker_pid < "$RUNTIME/work/pid" || return 1
	ddns_uint "$worker_pid" && [ "$worker_pid" -gt 1 ] || return 1
	[ "$(stat -c %u "/proc/$worker_pid" 2>/dev/null)" = "$OWNER_UID" ] && [ -r "/proc/$worker_pid/cmdline" ] || return 1
	tr '\000' '\n' < "/proc/$worker_pid/cmdline" | awk -v path="$SELF" '
		{a[NR]=$0} END {for(i=1;i<=2;i++) if(a[i]==path && a[i+1]=="worker" && i+1==NR) exit 0; exit 1}'
}
read_state() {
	DD_SAVED=; DD_ATTEMPTS=0; DD_DUE=0; DD_ERROR=pending_update
	if owned "$RUNTIME/state.json"; then
		DD_SAVED=$(jget '@.request_id' < "$RUNTIME/state.json" || :)
		DD_ATTEMPTS=$(jget '@.retry_count' < "$RUNTIME/state.json" || :)
		DD_DUE=$(jget '@.next_retry_uptime' < "$RUNTIME/state.json" || :)
		DD_ERROR=$(jget '@.last_error' < "$RUNTIME/state.json" || :)
	fi
	case "$DD_SAVED" in *[!0-9a-f]*) DD_SAVED= ;; esac
	[ "${#DD_SAVED}" = 64 ] || DD_SAVED=
	ddns_uint "$DD_ATTEMPTS" && [ "$DD_ATTEMPTS" -le 6 ] || DD_ATTEMPTS=0
	ddns_uint "$DD_DUE" || DD_DUE=0
}
write_state() {
	tmp=$(mktemp "$RUNTIME/.state.XXXXXX") || return 1
	printf '{"schema_version":1,"request_id":"%s","config_sha":"%s","active":"%s","address":"%s","retry_count":%s,"next_retry_uptime":%s,"last_error":"%s"}\n' \
		"$DD_ID" "$DD_CONFIG_SHA" "$DD_ACTIVE" "$DD_ADDRESS" "$DD_ATTEMPTS" "$DD_DUE" "$DD_ERROR" > "$tmp" &&
		mv -f "$tmp" "$RUNTIME/state.json"
}
cleanup() {
	[ "$LOCKED" = 0 ] || rmdir "$RUNTIME/lock" 2>/dev/null || :
	[ "$CONFIG_LOCKED" = 0 ] || rmdir "$CONFIG_LOCK" 2>/dev/null || :
	[ -z "$CANDIDATE" ] || rm -rf "$CANDIDATE"
	if [ "$WORK_OWNED" = 1 ]; then
		[ -z "$CHILD" ] || kill -TERM -- "-$CHILD" 2>/dev/null || :
		rm -rf "$RUNTIME/work"
	fi
}
trap cleanup EXIT
trap 'exit 3' HUP INT TERM
for p in /var/run/tr3000-lite "$RUNTIME" "$CONFIG" "$STOCK_RUN"; do [ ! -L "$p" ] || exit 3; done
umask 077
mkdir -p "$RUNTIME" || exit 3
[ "$(stat -c %u "$RUNTIME")" = "$OWNER_UID" ] && [ "$(stat -c %u /var/run/tr3000-lite)" = "$OWNER_UID" ] || exit 3
chmod 0700 /var/run/tr3000-lite "$RUNTIME" || exit 3
clock || exit 3
if [ "$command" = worker ]; then
	[ ! -L "$RUNTIME/work" ] && owned "$RUNTIME/work/request" || exit 0
	mkdir "$RUNTIME/work/owner" 2>/dev/null || exit 0
	WORK_OWNED=1
	printf '%s\n' "$$" > "$RUNTIME/work/pid"
fi
# A busy call must not remove another caller's lock or block the health loop.
tries=0
until mkdir "$RUNTIME/lock" 2>/dev/null; do
	[ "$command" = worker ] && [ "$tries" -lt 10 ] || exit 0
	tries=$((tries+1)); sleep 0.05
done
LOCKED=1
snapshot
DD_ID=$(request_id)
read_state
if [ -n "$DD_BLOCK" ]; then
	DD_ERROR=$DD_BLOCK; DD_DUE=0
	write_state || exit 3
	exit 0
fi
if [ "$command" = notify ] && [ "$1" != "$DD_ACTIVE" ]; then exit 0; fi
if [ "$DD_SAVED" != "$DD_ID" ]; then
	DD_ATTEMPTS=0; DD_DUE=$((DD_NOW+30)); DD_ERROR=pending_update
	write_state || exit 3
fi
[ "$command" != notify ] || exit 0
if [ "$command" = tick ]; then
	[ "$DD_NOW" -ge "$DD_DUE" ] && [ "$DD_ATTEMPTS" -lt 6 ] || exit 0
	if [ -e "$RUNTIME/work" ] || [ -L "$RUNTIME/work" ]; then
		[ ! -L "$RUNTIME/work" ] && [ "$(stat -c %u "$RUNTIME/work")" = "$OWNER_UID" ] || exit 3
		worker_live && exit 0
		if owned "$RUNTIME/work/started"; then
			read -r started < "$RUNTIME/work/started" || started=0
			if ddns_uint "$started" && [ "$DD_NOW" -ge "$started" ] && [ "$((DD_NOW-started))" -lt 5 ]; then exit 0; fi
		fi
		rm -rf "$RUNTIME/work"
	fi
	mkdir "$RUNTIME/work" 2>/dev/null || exit 0
	printf '%s\n' "$DD_NOW" > "$RUNTIME/work/started"
	printf '%s\n' "$DD_ID" > "$RUNTIME/work/request"
	"$SELF" worker >/dev/null 2>&1 &
	exit 0
fi
# worker: reserved by tick, never created through arbitrary caller arguments.
owned "$RUNTIME/work/request" || exit 0
read -r reserved < "$RUNTIME/work/request"
[ "$reserved" = "$DD_ID" ] || exit 0
DD_JOB_ID=$DD_ID
# Adapt only this section's fixed ip_network using the common config lock.
configured_network=$(uci -q -c "$CONFIG" -C '' get ddns.tr3000_direct.ip_network 2>/dev/null || :)
[ -n "$configured_network" ] || configured_network=wan
if [ "$configured_network" != "$DD_ACTIVE" ]; then
	mkdir -p /var/lock || exit 3
	mkdir "$CONFIG_LOCK" 2>/dev/null || exit 0
	CONFIG_LOCKED=1
	pending && exit 0
	[ "$DD_CONFIG_SHA" = "$(config_sha)" ] || exit 0
	CANDIDATE=$(mktemp -d "$RUNTIME/config.XXXXXX") || exit 3
	mkdir "$CANDIDATE/delta" && cp -p "$CONFIG/ddns" "$CANDIDATE/ddns" || exit 3
	uci -q -c "$CANDIDATE" -C '' -t "$CANDIDATE/delta" set "ddns.tr3000_direct.ip_network=$DD_ACTIVE" >/dev/null 2>&1 &&
		uci -q -c "$CANDIDATE" -C '' -t "$CANDIDATE/delta" commit ddns >/dev/null 2>&1 || exit 3
	[ "$DD_CONFIG_SHA" = "$(config_sha)" ] || exit 0
	new_config=$(mktemp "$CONFIG/.ddns.XXXXXX") || exit 3
	cp "$CANDIDATE/ddns" "$new_config" && chmod 0600 "$new_config" && mv -f "$new_config" "$CONFIG/ddns" || exit 3
	DD_CONFIG_SHA=$(config_sha); DD_ID=$(request_id); DD_JOB_ID=$DD_ID
	write_state || exit 3
	rmdir "$CONFIG_LOCK"; CONFIG_LOCKED=0
fi
# Native stock code trusts an old PID without checking argv. Remove only stale
# pointers; never signal an unrelated process, even when its numeric PID exists.
pidfile="$STOCK_RUN/tr3000_direct.pid"
if [ -e "$pidfile" ] || [ -L "$pidfile" ]; then
	owned "$pidfile" || exit 3
	read -r oldpid < "$pidfile" || oldpid=
	match=false
	if ddns_uint "$oldpid" && [ "$oldpid" -gt 1 ] && [ -r "/proc/$oldpid/cmdline" ]; then
		if tr '\000' '\n' < "/proc/$oldpid/cmdline" | awk -v updater="$UPDATER" '
			{a[NR]=$0} END {for(i=1;i<=NR;i++) if(a[i]==updater && a[i+1]=="-v" && a[i+2]=="2" && a[i+3]=="-S" && a[i+4]=="tr3000_direct" && a[i+5]=="--" && a[i+6]=="start") exit 0; exit 1}'; then match=true; fi
	fi
	[ "$match" = true ] || rm -f "$pidfile" || exit 3
fi
rmdir "$RUNTIME/lock"; LOCKED=0
# The legacy Cloudflare extension checks VERBOSE_MODE, not just -v. Keep both
# set for one-shot semantics; timeout bounds even a stuck network subprocess.
VERBOSE_MODE=2 setsid timeout -s TERM -k 5 360 "$UPDATER" -v 2 -S tr3000_direct -- start >/dev/null 2>&1 &
CHILD=$!
result=0; wait "$CHILD" || result=$?
CHILD=
# Never publish a successful old request over a newer pending uplink/config.
mkdir "$RUNTIME/lock" 2>/dev/null || exit 0
LOCKED=1
clock || exit 3
snapshot
read_state
DD_ID=$(request_id)
[ "$DD_ID" = "$DD_JOB_ID" ] && [ "$DD_SAVED" = "$DD_JOB_ID" ] || exit 0
if [ -n "$DD_BLOCK" ]; then DD_ERROR=$DD_BLOCK; DD_DUE=0
elif [ "$result" = 0 ]; then DD_ATTEMPTS=0; DD_DUE=$((DD_NOW+600)); DD_ERROR=
else
	DD_ATTEMPTS=$((DD_ATTEMPTS+1)); delay=$((60 << (DD_ATTEMPTS-1)))
	[ "$delay" -le 3600 ] || delay=3600
	# od is not part of the Lite image; busybox provides head and sha256sum.
	jitter=$(head -c 4 /dev/urandom 2>/dev/null | sha256sum | cut -c1-2)
	jitter=$((0x${jitter:-0}))
	ddns_uint "$jitter" || jitter=0
	DD_DUE=$((DD_NOW+delay+jitter%16)); DD_ERROR=update_failed
	[ "$result" != 124 ] && [ "$result" != 137 ] || DD_ERROR=update_timeout
	[ "$DD_ATTEMPTS" -lt 6 ] || DD_ERROR=retry_exhausted
fi
write_state || exit 3
