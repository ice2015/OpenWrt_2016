#!/bin/sh
# Lite management AP self-healing. The radio driver recreates its open
# default access point on every boot; this controller keeps exactly one
# encrypted management AP per radio and publishes the readiness marker.
set -eu
PATH=/usr/sbin:/usr/bin:/sbin:/bin
LC_ALL=C
export PATH LC_ALL
umask 077
STATE=/etc/tr3000-lite
CONFIG=/etc/config
WIRELESS="$CONFIG/wireless"
MARKER="$STATE/management-ap.initialized"
AP_SCRIPT=/usr/sbin/tr3000-lite-wifi-ap
WIFI_RELOAD=/sbin/wifi

COMMAND=${1:-status}
[ "$#" -gt 0 ] && shift

fail() {
	printf 'tr3000-lite-wifi: %s\n' "$1" >&2
	exit "${2:-1}"
}

usage() {
	printf 'Usage: %s status --json | repair\n' "$0"
}

# Read one option of one wireless section from the exported configuration.
option_of() {
	printf '%s\n' "$EXPORTED" | sed -n "s/^wireless\.$1\.$2='\(.*\)'$/\1/p"
}

section_name() {
	value=${1#wireless.}
	printf '%s\n' "${value%%=*}"
}

# The state comes from the live wireless configuration only. A missing or
# unsafe configuration means the radio is not ready yet, never a failure.
read_state() {
	RADIO_COUNT=0; MANAGED_COUNT=0; OPEN_COUNT=0; OPEN_DISABLED_COUNT=0
	OPEN_DISABLED=1; SSID_PRESENT=0; KEY_PRESENT=0; READY=0
	MARKER="$STATE/management-ap.initialized"
	[ -f "$WIRELESS" ] && [ ! -L "$WIRELESS" ] || return 1
	[ ! -L "$STATE" ] || return 1
	EXPORTED=$(uci -q -c "$CONFIG" show wireless 2>/dev/null) || return 1
	radios=; ifaces=
	while IFS= read -r line; do
		case "$line" in
			wireless.*=wifi-device) radios="$radios $(section_name "$line")" ;;
			wireless.*=wifi-iface) ifaces="$ifaces $(section_name "$line")" ;;
		esac
	done <<EOF
$EXPORTED
EOF
	for radio in $radios; do RADIO_COUNT=$((RADIO_COUNT + 1)); done
	for section in $ifaces; do
		[ "$(option_of "$section" mode)" = ap ] || continue
		if [ "$(option_of "$section" tr3000_lite_managed)" = 1 ]; then
			MANAGED_COUNT=$((MANAGED_COUNT + 1))
			[ -n "$(option_of "$section" ssid)" ] && SSID_PRESENT=1
			[ -n "$(option_of "$section" key)" ] && KEY_PRESENT=1
			continue
		fi
		case "$(option_of "$section" encryption)" in
			''|none|open)
				# A disabled open access point is already handled; an enabled
				# one is a management hole.
				if [ "$(option_of "$section" disabled)" = 1 ]; then
					OPEN_DISABLED_COUNT=$((OPEN_DISABLED_COUNT + 1))
				else
					OPEN_COUNT=$((OPEN_COUNT + 1))
					OPEN_DISABLED=0
				fi
				;;
		esac
	done
	[ "$RADIO_COUNT" -gt 0 ] || return 0
	[ "$MANAGED_COUNT" = "$RADIO_COUNT" ] || return 0
	[ "$OPEN_COUNT" -eq 0 ] || return 0
	[ "$OPEN_DISABLED" = 1 ] || return 0
	[ "$SSID_PRESENT" = 1 ] || return 0
	[ "$KEY_PRESENT" = 1 ] || return 0
	READY=1
	return 0
}

emit_status() {
	printf '{"schema_version":1,"ready":%s,"radio_count":%s,"managed_aps":%s,' \
		"$([ "$READY" = 1 ] && printf true || printf false)" "$RADIO_COUNT" "$MANAGED_COUNT"
	printf '"open_aps":%s,"open_aps_disabled":%s,"ssid_present":%s,"key_present":%s}\n' \
		"$OPEN_COUNT" "$([ "$OPEN_DISABLED" = 1 ] && printf true || printf false)" \
		"$([ "$SSID_PRESENT" = 1 ] && printf true || printf false)" \
		"$([ "$KEY_PRESENT" = 1 ] && printf true || printf false)"
}

clear_marker() {
	[ -f "$MARKER" ] && [ ! -L "$MARKER" ] || return 0
	rm -f "$MARKER" || :
}

case "$COMMAND" in
	status)
		[ "$#" -eq 1 ] && [ "$1" = --json ] || { usage; exit 2; }
		if ! read_state; then
			printf '{"schema_version":1,"ready":false,"radio_count":0,"managed_aps":0,"open_aps":0,"open_aps_disabled":true,"ssid_present":false,"key_present":false}\n'
			exit 1
		fi
		emit_status
		[ "$READY" = 1 ] || exit 1
		;;
	repair)
		[ "$#" -eq 0 ] || { usage; exit 2; }
		read_state || fail wireless_not_ready
		if [ "$READY" = 1 ]; then
			# The identity is in place; only the readiness marker may lag.
			[ -f "$MARKER" ] && [ ! -L "$MARKER" ] || fail marker_missing
			emit_status
			exit 0
		fi
		clear_marker
		[ -x "$AP_SCRIPT" ] || fail ap_controller_missing 3
		"$AP_SCRIPT" || fail repair_failed
		if [ -x "$WIFI_RELOAD" ]; then
			"$WIFI_RELOAD" >/dev/null 2>&1 || :
		fi
		read_state || fail wireless_not_ready
		emit_status
		[ "$READY" = 1 ] || fail repair_incomplete
		;;
	*)
		usage
		exit 2
		;;
esac
