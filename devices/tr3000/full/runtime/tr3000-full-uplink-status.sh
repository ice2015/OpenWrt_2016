#!/bin/sh
# Fixed read-only RPC. Never return raw UCI, ubus, wireless keys or stderr.
PATH=/usr/sbin:/usr/bin:/sbin:/bin
export PATH
set -f
usage() { printf 'Usage: %s --json | --help\n' "$0"; }
case "$*" in --help) usage; exit 0 ;; --json) ;; *) usage >&2; exit 2 ;; esac
. /usr/sbin/lite-common.sh
. /usr/lib/tr3000-full/uplink-lib.sh
RUNTIME=/var/run/tr3000-full
safe_file() { [ -f "$1" ] && [ ! -L "$1" ]; }
identifier() {
	case "$1" in ''|*[!A-Za-z0-9_]*) return 1 ;; esac
	[ "${#1}" -le 64 ]
}
boolean() { case "$1" in true|false) return 0 ;; *) return 1 ;; esac; }
network_name() { case "$1" in ''|wan|wwan|usbwan) return 0 ;; *) return 1 ;; esac; }
get() { uci -q get "$1" 2>/dev/null; }
field() { uplink_field "$1" "$2"; }

parse_uplink() {
	[ ! -L "$RUNTIME" ] && [ ! -L "$RUNTIME/uplink" ] &&
		safe_file "$RUNTIME/uplink/status.json" || return 1
	json=$(cat "$RUNTIME/uplink/status.json") || return 1
	[ "$(field "$json" '@.schema_version')" = 1 ] || return 1
	ACTIVE=$(field "$json" '@.active') && PREVIOUS=$(field "$json" '@.previous') &&
		EVENT_ERROR=$(field "$json" '@.last_event_error') &&
		RECONCILE_ERROR=$(field "$json" '@.reconcile_error') &&
		FOREIGN=$(field "$json" '@.foreign_default') || return 1
	network_name "$ACTIVE" && network_name "$PREVIOUS" && boolean "$EVENT_ERROR" &&
		boolean "$RECONCILE_ERROR" && boolean "$FOREIGN" || return 1
	ROWS=; index=0; active_valid=0
	[ -n "$ACTIVE" ] || active_valid=1
	for pair in wan:10 wwan:20 usbwan:30; do
		net=${pair%:*}; base=${pair#*:}; prefix="@.interfaces[$index]"
		[ "$(field "$json" "$prefix.name")" = "$net" ] || return 1
		dev=$(field "$json" "$prefix.device") && addr=$(field "$json" "$prefix.address") &&
			gw=$(field "$json" "$prefix.gateway") && actual_base=$(field "$json" "$prefix.base_metric") &&
			effective=$(field "$json" "$prefix.effective_metric") && health=$(field "$json" "$prefix.health") &&
			failures=$(field "$json" "$prefix.failures") && successes=$(field "$json" "$prefix.successes") &&
			available=$(field "$json" "$prefix.available") || return 1
		[ -z "$dev" ] || uplink_device_valid "$dev" || return 1
		[ -z "$addr" ] || lite_valid_ipv4 "$addr" || return 1
		[ -z "$gw" ] || lite_valid_ipv4 "$gw" || return 1
		[ "$actual_base" = "$base" ] && uplink_uint "$effective" "$base" "$((base+1000))" &&
			uplink_uint "$failures" 0 100 && uplink_uint "$successes" 0 100 && boolean "$available" || return 1
		[ "$effective" = "$base" ] || [ "$effective" = "$((base+1000))" ] || return 1
		case "$health:$available" in healthy:true|unhealthy:true|unavailable:false) ;; *) return 1 ;; esac
		if [ "$net" = "$ACTIVE" ] && [ "$health" = healthy ] && [ "$available" = true ]; then active_valid=1; fi
		link_json=$(ubus call "network.interface.$net" status 2>/dev/null || printf '{}')
		link=$(field "$link_json" '@.up' || :)
		boolean "$link" || link=null
		ROWS="$ROWS$net ${dev:--} ${addr:--} ${gw:--} $base $effective $health $failures $successes $available $link
"
		index=$((index+1))
	done
	[ "$active_valid" = 1 ] || return 1
	[ "$FOREIGN" != true ] || ACTIVE=
}

STATUS_ERROR=false
if ! parse_uplink; then
	STATUS_ERROR=true; ACTIVE=; PREVIOUS=; EVENT_ERROR=false; RECONCILE_ERROR=true; FOREIGN=false
	ROWS='wan - - - 10 10 unknown 0 0 false null
wwan - - - 20 20 unknown 0 0 false null
usbwan - - - 30 30 unknown 0 0 false null
'
fi

USB_STATE=unavailable; USB_DEVICE=; USB_DRIVER=; USB_VID=; USB_PID=; USB_PATH=
parse_usb() {
	[ ! -L "$RUNTIME" ] && safe_file "$RUNTIME/usbwan.json" || return 1
	usb=$(cat "$RUNTIME/usbwan.json") || return 1
	[ "$(field "$usb" '@.schema_version')" = 1 ] || return 1
	USB_STATE=$(field "$usb" '@.state') && USB_DEVICE=$(field "$usb" '@.device') &&
		USB_DRIVER=$(field "$usb" '@.driver') && USB_VID=$(field "$usb" '@.vid') &&
		USB_PID=$(field "$usb" '@.pid') && USB_PATH=$(field "$usb" '@.path') || return 1
	case "$USB_STATE" in bound|unavailable|ambiguous|blocked|error) ;; *) return 1 ;; esac
	[ -z "$USB_DEVICE" ] || uplink_device_valid "$USB_DEVICE" || return 1
	case "$USB_DRIVER" in ''|rndis_host|cdc_ether) ;; *) return 1 ;; esac
	case "$USB_VID$USB_PID" in *[!0-9a-f]*) return 1 ;; esac
	[ -z "$USB_VID" ] || [ "${#USB_VID}" -eq 4 ] || return 1
	[ -z "$USB_PID" ] || [ "${#USB_PID}" -eq 4 ] || return 1
	case "$USB_PATH" in ''|/devices/*) ;; *) return 1 ;; esac
	case "$USB_PATH" in *[!A-Za-z0-9_./:-]*) return 1 ;; esac
	if [ "$USB_STATE" = bound ]; then
		[ -n "$USB_DEVICE" ] && [ -n "$USB_DRIVER" ] && [ -n "$USB_VID" ] &&
			[ -n "$USB_PID" ] && [ -n "$USB_PATH" ] || return 1
	fi
}
if [ -e "$RUNTIME/usbwan.json" ] || [ -L "$RUNTIME/usbwan.json" ]; then
	if ! parse_usb; then USB_STATE=error; USB_DEVICE=; USB_DRIVER=; USB_VID=; USB_PID=; USB_PATH=; fi
fi

# Read actual configuration identities, never infer radio names or frequency bands.
WIRELESS_ERROR=false; WIFI_ROWS=; AP_PRESENT=0; AP_UP=0; STA_PRESENT=0; STA_UP=0
show=$(uci -q -X show wireless 2>/dev/null) || { show=; WIRELESS_ERROR=true; }
RADIOS=$(printf '%s\n' "$show" | awk -F= '$1 ~ /^wireless\.[A-Za-z0-9_]+$/ && $2=="wifi-device" {sub(/^wireless\./,"",$1); printf "%s ",$1}')
IFACES=$(printf '%s\n' "$show" | awk -F= '$1 ~ /^wireless\.[A-Za-z0-9_]+$/ && $2=="wifi-iface" {sub(/^wireless\./,"",$1); print $1}')
# The raw replies may contain credentials. Only explicitly selected fields below
# are emitted, with no dynamic shell evaluation or generic file read permission.
wjson=$(ubus call network.wireless status 2>/dev/null) || { wjson='{}'; WIRELESS_ERROR=true; }
wwan=$(ubus call network.interface.wwan status 2>/dev/null || printf '{}')
wwan_up=$(field "$wwan" '@.up' || :); wwan_device=$(field "$wwan" '@.l3_device' || :)
iface_count=0
for section in $IFACES; do
	identifier "$section" || { WIRELESS_ERROR=true; continue; }
	mode=$(get "wireless.$section.mode" || :)
	networks=$(get "wireless.$section.network" || :)
	case "$mode: $networks " in ap:*' lan '*) network=lan ;; sta:*' wwan '*) network=wwan ;; *) continue ;; esac
	disabled=$(get "wireless.$section.disabled" || :)
	case "$disabled" in ''|0) enabled=true ;; 1) enabled=false ;; *) enabled=false; WIRELESS_ERROR=true ;; esac
	section_enabled=$enabled
	radios=$(get "wireless.$section.device" || :)
	[ -n "$radios" ] || WIRELESS_ERROR=true
	for radio in $radios; do
		enabled=$section_enabled
		iface_count=$((iface_count+1))
		[ "$iface_count" -le 32 ] || { WIRELESS_ERROR=true; break; }
		identifier "$radio" || { WIRELESS_ERROR=true; continue; }
		case " $RADIOS " in *" $radio "*) ;; *) WIRELESS_ERROR=true; continue ;; esac
		if [ "$(get "wireless.$radio.disabled" || :)" = 1 ]; then enabled=false; fi
		ifname=-; phy=-; channel=null; frequency=null; running=false
		i=0
		while [ "$i" -lt 32 ]; do
			candidate=$(field "$wjson" "@.$radio.interfaces[$i].section") || break
			if [ "$candidate" = "$section" ]; then
				candidate_name=$(field "$wjson" "@.$radio.interfaces[$i].ifname" || :)
				if uplink_device_valid "$candidate_name"; then ifname=$candidate_name; fi
				break
			fi
			i=$((i+1))
		done
		if [ "$ifname" != - ]; then
			info=$(ubus call iwinfo info "{\"device\":\"$ifname\"}" 2>/dev/null || printf '{}')
			actual_phy=$(field "$info" '@.phy' || :)
			case "$actual_phy" in ''|*[!A-Za-z0-9_.-]*) ;; *) [ "${#actual_phy}" -gt 32 ] || phy=$actual_phy ;; esac
			actual_channel=$(field "$info" '@.channel' || :)
			actual_frequency=$(field "$info" '@.frequency' || :)
			if uplink_uint "$actual_channel" 1 233; then channel=$actual_channel; fi
			if uplink_uint "$actual_frequency" 1 65535; then frequency=$actual_frequency; fi
			if [ "$mode" = ap ] && [ "$(field "$wjson" "@.$radio.up" || :)" = true ]; then running=true; fi
			if [ "$mode" = sta ] && [ "$wwan_up" = true ] && [ "$wwan_device" = "$ifname" ]; then running=true; fi
		fi
		if [ "$enabled" = true ]; then
			if [ "$mode" = ap ]; then AP_PRESENT=1; [ "$running" != true ] || AP_UP=1
			else STA_PRESENT=1; [ "$running" != true ] || STA_UP=1; fi
		fi
		WIFI_ROWS="$WIFI_ROWS$section $radio $ifname $phy $mode $network $enabled $running $channel $frequency
"
	done
done
WIRELESS_MODE=unavailable
if [ "$AP_PRESENT" = 1 ]; then
	if [ "$STA_PRESENT" = 0 ]; then WIRELESS_MODE=ap_only
	elif [ "$STA_UP" = 1 ]; then WIRELESS_MODE=ap_client
	else WIRELESS_MODE=client_disconnected; fi
fi
[ "$AP_UP" = 1 ] || WIRELESS_ERROR=true

printf '{"schema_version":1,"active":"%s","previous":"%s","status_error":%s,"reconcile_error":%s,"last_event_error":%s,"foreign_default":%s,"interfaces":[' "$ACTIVE" "$PREVIOUS" "$STATUS_ERROR" "$RECONCILE_ERROR" "$EVENT_ERROR" "$FOREIGN"
separator=
while read -r net dev addr gw base effective health failures successes available link; do
	[ -n "$net" ] || continue
	[ "$dev" != - ] || dev=; [ "$addr" != - ] || addr=; [ "$gw" != - ] || gw=
	printf '%s{"name":"%s","device":"%s","address":"%s","gateway":"%s","base_metric":%s,"effective_metric":%s,"health":"%s","failures":%s,"successes":%s,"available":%s,"link":%s}' "$separator" "$net" "$dev" "$addr" "$gw" "$base" "$effective" "$health" "$failures" "$successes" "$available" "$link"
	separator=,
done <<EOF
$ROWS
EOF
printf '],"usb":{"state":"%s","device":"%s","driver":"%s","vid":"%s","pid":"%s","path":"%s"},"wireless":{"mode":"%s","error":%s,"interfaces":[' "$USB_STATE" "$USB_DEVICE" "$USB_DRIVER" "$USB_VID" "$USB_PID" "$USB_PATH" "$WIRELESS_MODE" "$WIRELESS_ERROR"
separator=
while read -r section radio ifname phy mode network enabled running channel frequency; do
	[ -n "$section" ] || continue
	shared=false
	if [ "$enabled" = true ]; then
		match=$(printf '%s\n' "$WIFI_ROWS" | awk -v radio="$radio" -v phy="$phy" -v mode="$mode" '$7=="true" && $5!=mode && ($2==radio || (phy!="-" && $4==phy)) {print "shared"}')
		[ -z "$match" ] || shared=true
	fi
	[ "$ifname" != - ] || ifname=; [ "$phy" != - ] || phy=
	printf '%s{"section":"%s","radio":"%s","ifname":"%s","phy":"%s","mode":"%s","network":"%s","enabled":%s,"up":%s,"channel":%s,"frequency":%s,"shared_phy":%s}' "$separator" "$section" "$radio" "$ifname" "$phy" "$mode" "$network" "$enabled" "$running" "$channel" "$frequency" "$shared"
	separator=,
done <<EOF
$WIFI_ROWS
EOF
printf ']}}\n'
