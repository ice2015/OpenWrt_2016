#!/bin/sh
# Lite-only validation/parsing/decision helpers; no network configuration writes.
uplink_uint() (
	case "$1" in ''|*[!0-9]*|0[0-9]*) return 1 ;; esac
	[ "${#1}" -le 5 ] && [ "$1" -ge "$2" ] && [ "$1" -le "$3" ]
)

uplink_device_valid() {
	case "$1" in ''|[-.]*|*[!A-Za-z0-9_.-]*) return 1 ;; esac
	[ "${#1}" -le 15 ]
}

# Independent consecutive failure/success counters, not one reused counter.
uplink_health() (
	old=$1; failures=$2; successes=$3; good=$4; down=$5; up=$6
	uplink_uint "$failures" 0 100 || failures=0
	uplink_uint "$successes" 0 100 || successes=0
	case "$old" in healthy|unhealthy) ;; *) old=healthy; failures=0; successes=0 ;; esac
	if [ "$good" = 1 ]; then
		failures=0
		if [ "$old" = unhealthy ]; then
			successes=$((successes+1))
			if [ "$successes" -ge "$up" ]; then old=healthy; successes=0; fi
		else successes=0; fi
	else
		successes=0
		if [ "$old" != unhealthy ]; then
			failures=$((failures+1))
			if [ "$failures" -ge "$down" ]; then old=unhealthy; failures=0; fi
		else failures=0; fi
	fi
	printf '%s %s %s\n' "$old" "$failures" "$successes"
)

uplink_field() { printf '%s' "$1" | jsonfilter -e "$2" 2>/dev/null; }

# Pinned netifd7901e66c dumps active routes, metric and preferred source.
# Never choose a gateway from the first unrelated kernel route on a device.
uplink_snapshot() (
	name=$1; base=$2
	status=$(ubus call "network.interface.$name" status 2>/dev/null) || return 1
	[ "$(uplink_field "$status" '@.up')" = true ] &&
		[ "$(uplink_field "$status" '@.proto')" = dhcp ] || return 1
	device=$(uplink_field "$status" '@.l3_device') || return 1
	address=$(uplink_field "$status" "@['ipv4-address'][0].address") || return 1
	uplink_device_valid "$device" && lite_valid_ipv4 "$address" || return 1
	metric=$(uplink_field "$status" '@.metric' || :)
	[ "$metric" = "$base" ] || return 1
	for protected in lan; do
		[ "$device" != "$(uci -q get "network.$protected.device" 2>/dev/null || :)" ] || return 1
	done
	gateway=-; source=-; count=0; i=0
	while [ "$i" -lt 32 ]; do
		target=$(uplink_field "$status" "@.route[$i].target") || break
		mask=$(uplink_field "$status" "@.route[$i].mask" || :)
		if [ "$target" = 0.0.0.0 ] && [ "$mask" = 0 ]; then
			count=$((count+1)); [ "$count" -eq 1 ] || return 1
			gateway=$(uplink_field "$status" "@.route[$i].nexthop" || :)
			lite_valid_ipv4 "$gateway" || gateway=-
			table=$(uplink_field "$status" "@.route[$i].table" || :)
			proto=$(uplink_field "$status" "@.route[$i].proto" || :)
			route_metric=$(uplink_field "$status" "@.route[$i].metric" || :)
			type=$(uplink_field "$status" "@.route[$i].type" || :)
			[ -z "$table" ] || [ "$table" = 254 ] || return 1
			[ -z "$proto" ] || [ "$proto" = 4 ] || return 1
			[ -z "$type" ] || [ "$type" = 1 ] || return 1
			[ -z "$route_metric" ] || [ "$route_metric" = "$base" ] || return 1
			preferred=$(uplink_field "$status" "@.route[$i].source" || :)
			case "$preferred" in
				''|0.0.0.0/0) source=- ;;
				"$address/32") source=$address ;;
				*) return 1 ;;
			esac
		fi
		i=$((i+1))
	done
	printf '%s %s %s %s\n' "$device" "$address" "$gateway" "$source"
)

# Canonical kernel default fingerprint: device gateway preferred-source metric proto.
# Unknown/multipath formats fail closed before any route replacement.
uplink_kernel_routes() (
	kernel_output=$(ip -4 route show table main default) || return 1
	printf '%s\n' "$kernel_output" | awk '
		BEGIN { OFS=" " }
		NF {
			if ($1 != "default") { print "INVALID"; next }
			dev=""; gw=""; src="-"; metric=0; proto="boot"; bad=0
			for (i=2;i<=NF;i++) {
				if ($i=="via") gw=$(++i)
				else if ($i=="dev") dev=$(++i)
				else if ($i=="src") src=$(++i)
				else if ($i=="metric") metric=$(++i)
				else if ($i=="proto") proto=$(++i)
				else if ($i=="onlink" || $i=="linkdown") continue
				else bad=1
			}
			if (bad || dev=="" || gw=="") print "INVALID"
			else print dev,gw,src,metric,proto
		}'
)

uplink_fingerprint_valid() (
	[ "$#" -eq 5 ] && uplink_device_valid "$1" && lite_valid_ipv4 "$2" &&
		{ [ "$3" = - ] || lite_valid_ipv4 "$3"; } &&
		uplink_uint "$4" 1 65535 && [ "$5" = static ]
)
