#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
. "$SCRIPT_DIR/lite-common.sh"

NETWORKS='wan wwan usbwan'
PROBE_CONFIG=lite-uplink-watch
PROBE_FILE=/etc/config/lite-uplink-watch
STATE_FILE=/var/run/lite-uplink-active
STATE_DIR=/var/run/lite-uplink-watch

log() {
	logger -t lite-uplink-watch "$*" 2>/dev/null ||
		printf 'lite-uplink-watch: %s\n' "$*" >&2
}

fail() {
	log "Error: $*"
	return 1
}

require_runtime() {
	for COMMAND in ip ubus uci jsonfilter ping; do
		command -v "$COMMAND" >/dev/null 2>&1 || {
			fail "required command not found: $COMMAND"
			exit 1
		}
	done
	[ -r "$PROBE_FILE" ] || {
		fail "probe configuration not found: $PROBE_FILE"
		exit 1
	}
}

check_uplink() {
	NETWORK=$1
	BASE_METRIC=$(uci -q get "network.$NETWORK.metric" 2>/dev/null || :)
	[ -n "$BASE_METRIC" ] || {
		case "$NETWORK" in
			wan) BASE_METRIC=10 ;;
			wwan) BASE_METRIC=20 ;;
			usbwan) BASE_METRIC=30 ;;
		esac
	}
	case "$BASE_METRIC" in
		*[!0-9]*|'') fail "invalid route metric for $NETWORK"; return 1 ;;
	esac

	STATUS=$(ubus call "network.interface.$NETWORK" status 2>/dev/null) || {
		log "$NETWORK link down or not configured"
		return 0
	}
	UP=$(printf '%s' "$STATUS" | jsonfilter -e '@.up' 2>/dev/null || :)
	DEVICE=$(printf '%s' "$STATUS" | jsonfilter -e '@.l3_device' 2>/dev/null || :)
	case "$UP" in
		1|true) ;;
		*) log "$NETWORK link down"; return 0 ;;
	esac
	[ -n "$DEVICE" ] || {
		log "$NETWORK link up but no layer-3 device is available"
		return 0
	}

	ROUTE=$(ip -4 route show default dev "$DEVICE" | sed -n '1p')
	[ -n "$ROUTE" ] || {
		log "$NETWORK link up on $DEVICE but has no default route"
		return 0
	}
	GATEWAY=
	CURRENT_METRIC=$BASE_METRIC
	ROUTE_SOURCE=
	set -- $ROUTE
	while [ "$#" -gt 1 ]; do
		case "$1" in
			via) GATEWAY=$2; shift 2 ;;
			metric) CURRENT_METRIC=$2; shift 2 ;;
			src) ROUTE_SOURCE=$2; shift 2 ;;
			*) shift ;;
		esac
	done
	[ -n "$GATEWAY" ] || {
		log "$NETWORK has a default route without a gateway; leaving it unchanged"
		return 0
	}

	PROBES=$(uci -q get "$PROBE_CONFIG.$NETWORK.probe_ip" 2>/dev/null || :)
	[ -n "$PROBES" ] || PROBES='1.1.1.1
9.9.9.9'
	SUCCESS=0
	for PROBE in $PROBES; do
		lite_valid_ipv4 "$PROBE" ||
			{ fail "invalid probe address for $NETWORK"; return 1; }
		if ping -I "$DEVICE" -c 1 -W 2 "$PROBE" >/dev/null 2>&1; then
			SUCCESS=$((SUCCESS + 1))
		fi
	done

	HEALTH_FILE="$STATE_DIR/$NETWORK"
	OLD_STATE=$(sed -n '1p' "$HEALTH_FILE" 2>/dev/null || :)
	OLD_COUNT=$(sed -n '2p' "$HEALTH_FILE" 2>/dev/null || :)
	case "$OLD_COUNT" in
		''|*[!0-9]*) OLD_COUNT=0 ;;
	esac
	if [ "$SUCCESS" -gt 0 ]; then
		if [ "$OLD_STATE" = unhealthy ] && [ "$OLD_COUNT" -lt 2 ]; then
			HEALTH=unhealthy
			COUNT=$((OLD_COUNT + 1))
		else
			HEALTH=healthy
			COUNT=0
		fi
	else
		if [ "$OLD_STATE" = unhealthy ]; then
			HEALTH=unhealthy
			COUNT=0
		else
			COUNT=$((OLD_COUNT + 1))
			if [ "$COUNT" -ge 3 ]; then
				HEALTH=unhealthy
				COUNT=0
			else
				HEALTH=healthy
			fi
		fi
	fi
	mkdir -p "$STATE_DIR"
	printf '%s\n%s\n' "$HEALTH" "$COUNT" > "$HEALTH_FILE"
	if [ "$HEALTH" = healthy ]; then
		TARGET_METRIC=$BASE_METRIC
		if [ "$SUCCESS" -gt 0 ]; then
			log "$NETWORK link and Internet probe are healthy on $DEVICE"
		else
			log "$NETWORK Internet probe failed; waiting for health threshold on $DEVICE"
		fi
	else
		TARGET_METRIC=$((BASE_METRIC + 1000))
		if [ "$SUCCESS" -gt 0 ]; then
			log "$NETWORK Internet recovered; waiting for recovery threshold on $DEVICE"
		else
			log "$NETWORK link is up on $DEVICE but all Internet probes failed"
		fi
	fi
	if [ "$CURRENT_METRIC" -ne "$TARGET_METRIC" ]; then
		ip -4 route del default via "$GATEWAY" dev "$DEVICE" metric "$CURRENT_METRIC" ||
			{ fail "could not remove stale default route for $NETWORK"; return 1; }
		if [ -n "$ROUTE_SOURCE" ]; then
			ip -4 route add default via "$GATEWAY" dev "$DEVICE" \
				src "$ROUTE_SOURCE" metric "$TARGET_METRIC" ||
				{ ip -4 route add default via "$GATEWAY" dev "$DEVICE" \
					src "$ROUTE_SOURCE" metric "$CURRENT_METRIC"; fail "could not set route metric for $NETWORK"; return 1; }
		else
			ip -4 route add default via "$GATEWAY" dev "$DEVICE" metric "$TARGET_METRIC" ||
				{ ip -4 route add default via "$GATEWAY" dev "$DEVICE" \
					metric "$CURRENT_METRIC"; fail "could not set route metric for $NETWORK"; return 1; }
		fi
		log "$NETWORK route metric changed from $CURRENT_METRIC to $TARGET_METRIC"
	fi
}

check_all() {
	mkdir -p "$STATE_DIR"
	for NETWORK in $NETWORKS; do
		check_uplink "$NETWORK"
	done
	ACTIVE_DEVICE=$(ip -4 route get 1.1.1.1 2>/dev/null |
		sed -n 's/.* dev \([^ ]*\).*/\1/p' | head -n 1)
	PREVIOUS_DEVICE=$(cat "$STATE_FILE" 2>/dev/null || :)
	if [ -n "$ACTIVE_DEVICE" ] && [ -f "$STATE_FILE" ] &&
		[ "$ACTIVE_DEVICE" != "$PREVIOUS_DEVICE" ]; then
		if [ "$(uci -q get network.wg.proto 2>/dev/null || :)" = wireguard ]; then
			if ifstatus wg >/dev/null 2>&1; then
				log "default egress changed from $PREVIOUS_DEVICE to $ACTIVE_DEVICE; restarting WireGuard"
				ifdown wg
				ifup wg
			fi
		fi
		log "active default egress changed from $PREVIOUS_DEVICE to $ACTIVE_DEVICE"
	fi
	printf '%s\n' "$ACTIVE_DEVICE" > "$STATE_FILE"
}

case "${1:-check}" in
	check)
		require_runtime
		check_all
		;;
	daemon)
		require_runtime
		while :; do
			check_all
			sleep 15
		done
		;;
	--help|help)
		printf 'Usage: %s [check|daemon|--help]\n' "$0"
		;;
	*)
		printf 'Error: unknown command: %s\n' "$1" >&2
		exit 2
		;;
esac
