#!/bin/sh
# Lite-only reconciler; Full deliberately retains the original shared watcher.
PATH=/usr/sbin:/usr/bin:/sbin:/bin
export PATH
set -u
usage() { printf 'Usage: %s reconcile | daemon | status --json | --help\n' "$0"; }
case "$*" in
	--help) usage; exit 0 ;;
	reconcile|daemon|'status --json') ;;
	*) usage >&2; exit 2 ;;
esac
. /usr/sbin/lite-common.sh
. /usr/lib/tr3000-lite/uplink-lib.sh
STATE=/var/run/tr3000-lite/uplink
EVENT=/usr/lib/tr3000-lite/uplink-changed
USB_HOOK=/etc/hotplug.d/net/90-tr3000-lite-usbwan
log() { logger -t tr3000-lite-uplink "$1" 2>/dev/null || :; }
[ ! -L /var/run/tr3000-lite ] && [ ! -L "$STATE" ] || exit 1
mkdir -p "$STATE" && chmod 0700 /var/run/tr3000-lite "$STATE" || exit 1
if [ "$1" = status ]; then
	if [ -f "$STATE/status.json" ] && [ ! -L "$STATE/status.json" ]; then
		cat "$STATE/status.json"
	else
		printf '{"schema_version":1,"active":"","previous":"","last_event_error":false,"reconcile_error":false,"foreign_default":false,"interfaces":[]}\n'
	fi
	exit 0
fi

# Failure paths retain a known safe retry cadence, never rejected input.
INTERVAL=15
config_value() { uci -q get "$1" 2>/dev/null; }
validate_config() {
	cfg_failures=$(config_value lite-uplink-watch.globals.failures || printf 3)
	cfg_successes=$(config_value lite-uplink-watch.globals.successes || printf 2)
	cfg_interval=$(config_value lite-uplink-watch.globals.interval || printf 15)
	uplink_uint "$cfg_failures" 1 100 && uplink_uint "$cfg_successes" 1 100 &&
		uplink_uint "$cfg_interval" 15 300 || return 1
	for cfg_name in wan wwan usbwan; do
		case "$cfg_name" in wan) cfg_metric=10 ;; wwan) cfg_metric=20 ;; usbwan) cfg_metric=30 ;; esac
		[ "$(config_value "network.$cfg_name.metric")" = "$cfg_metric" ] || return 1
		cfg_probes=$(config_value "lite-uplink-watch.$cfg_name.probe_ip") || return 1
		[ -n "$cfg_probes" ] || return 1
		cfg_count=0
		# Disable pathname expansion only while splitting configuration input.
		set -f
		for cfg_probe in $cfg_probes; do
			lite_valid_ipv4 "$cfg_probe" || { set +f; return 1; }
			cfg_count=$((cfg_count+1))
		done
		set +f
		[ "$cfg_count" -le 8 ] || return 1
	done
	FAILURES=$cfg_failures
	SUCCESSES=$cfg_successes
	INTERVAL=$cfg_interval
}

LOCKED=0
cleanup() { [ "$LOCKED" = 0 ] || rmdir "$STATE/lock"; }
trap cleanup EXIT
trap 'exit 1' HUP INT TERM
atomic_text() {
	text_file=$1; shift
	[ ! -L "$text_file" ] || return 1
	text_tmp=$(mktemp "$STATE/.state.XXXXXX") || return 1
	printf '%s\n' "$*" > "$text_tmp" && mv -f "$text_tmp" "$text_file"
}
# Only exact recorded synthetic routes, or the exact current netifd fingerprint,
# may be removed. A route at the same metric with any other tuple is foreign.
route_cmd() (
	op=$1; shift
	uplink_fingerprint_valid "$@" || return 1
	r_dev=$1; r_gw=$2; r_src=$3; r_metric=$4
	set -- -4 route "$op" default via "$r_gw" dev "$r_dev" proto static metric "$r_metric"
	[ "$r_src" = - ] || set -- "$@" src "$r_src"
	ip "$@" >/dev/null 2>&1
)
delete_exact() {
	del_tuple=$1
	# All tuples were validated before being journaled; never eval state text.
	set -- $del_tuple
	uplink_fingerprint_valid "$@" || return 1
	del_routes=$(uplink_kernel_routes) || return 1
	if printf '%s\n' "$del_routes" | grep -Fxq "$del_tuple"; then
		route_cmd del "$@" || {
			del_routes=$(uplink_kernel_routes) || return 1
			! printf '%s\n' "$del_routes" | grep -Fxq "$del_tuple"
		}
	fi
}
read_journal() {
	[ ! -L "$STATE/$NET.owned" ] || return 1
	if [ -f "$STATE/$NET.owned" ]; then
		while IFS= read -r journal_line; do
			[ -z "$journal_line" ] && continue
			set -- $journal_line
			uplink_fingerprint_valid "$@" || return 1
			printf '%s\n' "$journal_line"
		done < "$STATE/$NET.owned"
	fi
}
cleanup_owned() {
	keep=$1
	owned_lines=$(read_journal) || return 1
	while IFS= read -r owned_line; do
		[ -z "$owned_line" ] || [ "$owned_line" = "$keep" ] || delete_exact "$owned_line" || return 1
	done <<EOF
$owned_lines
EOF
}

reconcile_interface() {
	NET=$1; BASE=$2
	attempt=0
	while [ "$attempt" -lt 3 ]; do
		attempt=$((attempt+1))
		SNAPSHOT=$(uplink_snapshot "$NET" "$BASE" || :)
		DEVICE=; ADDRESS=; GATEWAY=; SOURCE=-; AVAILABLE=false
		HEALTH=unavailable; DOWN_COUNT=0; UP_COUNT=0; EFFECTIVE=$BASE
		owned=$(read_journal) || return 1
		if [ -n "$SNAPSHOT" ]; then
			read -r DEVICE ADDRESS GATEWAY SOURCE <<EOF
$SNAPSHOT
EOF
			kernel=$(uplink_kernel_routes) || return 1
			printf '%s\n' "$kernel" | grep -Fxq INVALID && return 1
			baseline="$DEVICE $GATEWAY $SOURCE $BASE static"
			have_route=0
			if [ "$GATEWAY" != - ]; then
				printf '%s\n' "$kernel" | grep -Fxq "$baseline" && have_route=1
				while IFS= read -r owner_line; do
					case "$owner_line" in "$DEVICE $GATEWAY $SOURCE "*)
						printf '%s\n' "$kernel" | grep -Fxq "$owner_line" && have_route=1 ;;
					esac
				done <<EOF
$owned
EOF
			fi
			if [ "$have_route" = 1 ]; then
				AVAILABLE=true
				OLD_HEALTH=healthy; OLD_DOWN=0; OLD_UP=0
				[ ! -L "$STATE/$NET.health" ] || return 1
				if [ -f "$STATE/$NET.health" ]; then
					read -r OLD_HEALTH OLD_DOWN OLD_UP < "$STATE/$NET.health" || :
				fi
				GOOD=0
				PROBES=$(config_value "lite-uplink-watch.$NET.probe_ip") || return 1
				for probe in $PROBES; do
					ping -I "$DEVICE" -c 1 -W 2 "$probe" >/dev/null 2>&1 && GOOD=1
				done
				decision=$(uplink_health "$OLD_HEALTH" "$OLD_DOWN" "$OLD_UP" "$GOOD" "$FAILURES" "$SUCCESSES") || return 1
				read -r HEALTH DOWN_COUNT UP_COUNT <<EOF
$decision
EOF
				[ "$HEALTH" != unhealthy ] || EFFECTIVE=$((BASE+1000))
				desired="$DEVICE $GATEWAY $SOURCE $EFFECTIVE static"
				# Probing takes seconds. Reread DHCP data before every mutation.
				[ "$(uplink_snapshot "$NET" "$BASE" || :)" = "$SNAPSHOT" ] || continue
				kernel=$(uplink_kernel_routes) || return 1
				printf '%s\n' "$kernel" | grep -Fxq INVALID && return 1
				collisions=$(printf '%s\n' "$kernel" | awk -v metric="$EFFECTIVE" -v expected="$desired" '$4==metric && $0!=expected { print }')
				while IFS= read -r collision; do
					[ -z "$collision" ] || printf '%s\n' "$owned" | grep -Fxq "$collision" || return 1
				done <<EOF
$collisions
EOF
				if printf '%s\n' "$kernel" | grep -Fxq "$desired"; then
					if [ "$EFFECTIVE" != "$BASE" ]; then
						printf '%s\n' "$owned" | grep -Fxq "$desired" || return 1
					fi
				else
					# Journal both old and candidate tuples before changing a route;
					# interrupted rounds can later clean only their own exact tuples.
					journal=$(printf '%s\n%s\n' "$owned" "$desired" | awk 'NF && !seen[$0]++')
					atomic_text "$STATE/$NET.owned" "$journal" || return 1
					set -- $desired
					route_cmd replace "$@" || return 1
				fi
				if [ "$(uplink_snapshot "$NET" "$BASE" || :)" != "$SNAPSHOT" ]; then
					# A DHCP renewal won the race; discard only this stale candidate.
					delete_exact "$desired" || return 1
					continue
				fi
				if [ "$EFFECTIVE" != "$BASE" ]; then delete_exact "$baseline" || return 1; fi
				cleanup_owned "$desired" || return 1
				if [ "$EFFECTIVE" = "$BASE" ]; then
					atomic_text "$STATE/$NET.owned" '' || return 1
				else atomic_text "$STATE/$NET.owned" "$desired" || return 1; fi
			fi
		fi
		if [ "$AVAILABLE" = false ]; then
			cleanup_owned '' && atomic_text "$STATE/$NET.owned" '' || return 1
		fi
		atomic_text "$STATE/$NET.health" "$HEALTH $DOWN_COUNT $UP_COUNT" &&
			atomic_text "$STATE/$NET.row" "$NET ${DEVICE:--} ${ADDRESS:--} ${GATEWAY:--} $BASE $EFFECTIVE $HEALTH $DOWN_COUNT $UP_COUNT $AVAILABLE" || return 1
		return 0
	done
	return 1
}

write_status() {
	status_tmp=$(mktemp "$STATE/.status.XXXXXX") || return 1
	{
		printf '{"schema_version":1,"active":"%s","previous":"%s","last_event_error":%s,"reconcile_error":%s,"foreign_default":%s,"interfaces":[' "$ACTIVE" "$PREVIOUS" "$EVENT_ERROR" "$RECONCILE_ERROR" "$FOREIGN_DEFAULT"
		separator=
		for row_net in wan wwan usbwan; do
			[ -f "$STATE/$row_net.row" ] && [ ! -L "$STATE/$row_net.row" ] || continue
			read -r rn rd ra rg rb re rh rf rs rav < "$STATE/$row_net.row" || return 1
			# These files are private controller output; revalidate before JSON.
			[ "$rn" = "$row_net" ] && uplink_uint "$rb" 1 30 && uplink_uint "$re" 1 1030 &&
				uplink_uint "$rf" 0 100 && uplink_uint "$rs" 0 100 || return 1
			case "$rh:$rav" in healthy:true|unhealthy:true|unavailable:false) ;; *) return 1 ;; esac
			if [ "$rd" = - ]; then rd=; else uplink_device_valid "$rd" || return 1; fi
			if [ "$ra" = - ]; then ra=; else lite_valid_ipv4 "$ra" || return 1; fi
			if [ "$rg" = - ]; then rg=; else lite_valid_ipv4 "$rg" || return 1; fi
			printf '%s{"name":"%s","device":"%s","address":"%s","gateway":"%s","base_metric":%s,"effective_metric":%s,"health":"%s","failures":%s,"successes":%s,"available":%s}' "$separator" "$rn" "$rd" "$ra" "$rg" "$rb" "$re" "$rh" "$rf" "$rs" "$rav"
			separator=,
		done
		printf ']}\n'
	} > "$status_tmp" && mv -f "$status_tmp" "$STATE/status.json"
}

reconcile() {
	mkdir "$STATE/lock" 2>/dev/null || return 1
	LOCKED=1
	if ! validate_config; then
		# Publish the failure under the same lock, retaining verified rows and
		# counters. An old successful snapshot must not hide rejected config.
		PREVIOUS=$(cat "$STATE/active" 2>/dev/null || :)
		case "$PREVIOUS" in ''|wan|wwan|usbwan) ;; *) PREVIOUS= ;; esac
		ACTIVE=$PREVIOUS
		EVENT_ERROR=$(cat "$STATE/event-error" 2>/dev/null || :)
		case "$EVENT_ERROR" in true|false) ;; *) EVENT_ERROR=false ;; esac
		old_status=$(cat "$STATE/status.json" 2>/dev/null || :)
		FOREIGN_DEFAULT=$(uplink_field "$old_status" '@.foreign_default' || :)
		case "$FOREIGN_DEFAULT" in true|false) ;; *) FOREIGN_DEFAULT=false ;; esac
		RECONCILE_ERROR=true
		write_status || return 1
		rmdir "$STATE/lock" || return 1
		LOCKED=0
		log 'invalid uplink configuration'
		return 1
	fi
	RECONCILE_ERROR=false
	for pair in wan:10 wwan:20 usbwan:30; do
		reconcile_interface "${pair%:*}" "${pair#*:}" || RECONCILE_ERROR=true
	done
	PREVIOUS=$(cat "$STATE/active" 2>/dev/null || :)
	case "$PREVIOUS" in ''|wan|wwan|usbwan) ;; *) PREVIOUS= ;; esac
	ACTIVE=; EVENT_ERROR=false; FOREIGN_DEFAULT=false
	if [ "$RECONCILE_ERROR" = false ]; then
		for row_net in wan wwan usbwan; do
			read -r rn rd ra rg rb re rh rf rs rav < "$STATE/$row_net.row" || return 1
			if [ "$rh" = healthy ] && [ "$rav" = true ]; then ACTIVE=$row_net; break; fi
		done
		if [ -n "$ACTIVE" ]; then
			# Do not advertise a managed egress while a better/equal foreign
			# main-table default actually wins. Never modify that foreign route.
			current_routes=$(uplink_kernel_routes) || { RECONCILE_ERROR=true; ACTIVE=$PREVIOUS; }
			if [ "$RECONCILE_ERROR" = false ]; then
				foreign=$(printf '%s\n' "$current_routes" | awk -v metric="$re" -v dev="$rd" -v gateway="$rg" '$4<=metric && ($1!=dev || $2!=gateway) {print "foreign"}')
				if [ -n "$foreign" ]; then ACTIVE=; FOREIGN_DEFAULT=true; fi
			fi
		fi
		if [ "$ACTIVE" != "$PREVIOUS" ]; then
			atomic_text "$STATE/active" "$ACTIVE" || return 1
			if [ -x "$EVENT" ] && [ ! -L "$EVENT" ]; then
				"$EVENT" "$ACTIVE" "$PREVIOUS" >/dev/null 2>&1 || { EVENT_ERROR=true; log 'uplink event notification failed'; }
			fi
		else
			[ ! -f "$STATE/event-error" ] || EVENT_ERROR=$(cat "$STATE/event-error")
			case "$EVENT_ERROR" in true|false) ;; *) EVENT_ERROR=false ;; esac
		fi
	else ACTIVE=$PREVIOUS; fi
	atomic_text "$STATE/event-error" "$EVENT_ERROR" && write_status || return 1
	rmdir "$STATE/lock" || return 1
	LOCKED=0
	[ "$RECONCILE_ERROR" = false ]
}

if [ "$1" = daemon ]; then
	while :; do
		# Hotplug can time out behind a long plant transaction. Re-enumerate
		# idempotently on the normal daemon cadence, never from iface callbacks.
		if [ -x "$USB_HOOK" ] && [ ! -L "$USB_HOOK" ]; then
			ACTION=reconcile INTERFACE=tr3000-rescan "$USB_HOOK" >/dev/null 2>&1 ||
				log 'USB reconciliation deferred until next interval'
		fi
		reconcile || { log 'uplink reconciliation failed; retrying on next interval'; cleanup; LOCKED=0; }
		sleep "${INTERVAL:-15}"
	done
else reconcile; fi
