#!/bin/sh

lite_die() {
	printf 'Error: %s\n' "$*" >&2
	exit 2
}

lite_require() {
	command -v "$1" >/dev/null 2>&1 || lite_die "required command not found: $1"
}

lite_valid_ipv4() {
	case "${1:-}" in
		''|.*|*.|*..*|*[!0-9.]*)
			return 1
			;;
	esac
	OLD_IFS=$IFS
	IFS=.
	set -- $1
	IFS=$OLD_IFS
	[ "$#" -eq 4 ] || return 1
	for OCTET do
		case "$OCTET" in
			0|[1-9]|[1-9][0-9]|[1-9][0-9][0-9]) ;;
			*) return 1 ;;
		esac
		[ "$OCTET" -le 255 ] || return 1
	done
	set -- $1
	[ "$1" -ge 1 ] && [ "$1" -le 223 ] && [ "$1" -ne 127 ]
}

lite_valid_cidr() {
	case "${1:-}" in
		*/*) ;;
		*) return 1 ;;
	esac
	case "$1" in
		*//*|*/*/*) return 1 ;;
	esac
	IP=${1%/*}
	PREFIX=${1#*/}
	lite_valid_ipv4 "$IP" || return 1
	case "$PREFIX" in
		''|0*|*[!0-9]*) return 1 ;;
	esac
	[ "${#PREFIX}" -le 2 ] && [ "$PREFIX" -ge 1 ] && [ "$PREFIX" -le 30 ]
}

lite_valid_iface() {
	case "${1:-}" in
		''|*[!A-Za-z0-9_.:-]*) return 1 ;;
		*) return 0 ;;
	esac
}

lite_valid_port() {
	case "${1:-}" in
		''|*[!0-9]*) return 1 ;;
		0|0[0-9]*|[0-9][0-9][0-9][0-9][0-9][0-9]*) return 1 ;;
	esac
	[ "$1" -ge 1 ] && [ "$1" -le 65535 ]
}

lite_ipv4_number() {
	OLD_IFS=$IFS
	IFS=.
	set -- $1
	IFS=$OLD_IFS
	printf '%s\n' "$((($1 * 16777216) + ($2 * 65536) + ($3 * 256) + $4))"
}

lite_prefix_mask() {
	PREFIX=$1
	MASK=0
	for OCTET_INDEX in 1 2 3 4; do
		if [ "$PREFIX" -ge 8 ]; then
			OCTET=255
			PREFIX=$((PREFIX - 8))
		elif [ "$PREFIX" -gt 0 ]; then
			OCTET=$((256 - (1 << (8 - PREFIX))))
			PREFIX=0
		else
			OCTET=0
		fi
		MASK=$((MASK * 256 + OCTET))
	done
	printf '%s\n' "$MASK"
}

lite_cidr_contains() {
	CIDR=$1
	ADDRESS=$2
	PREFIX=${CIDR#*/}
	NETWORK_NUMBER=$(lite_ipv4_number "${CIDR%/*}")
	ADDRESS_NUMBER=$(lite_ipv4_number "$ADDRESS")
	MASK=$(lite_prefix_mask "$PREFIX")
	[ $((NETWORK_NUMBER & MASK)) -eq "$NETWORK_NUMBER" ] &&
		[ $((ADDRESS_NUMBER & MASK)) -eq "$NETWORK_NUMBER" ]
}

lite_check_address_not_network_or_broadcast() {
	ADDRESS_NUMBER=$(lite_ipv4_number "$1")
	MASK=$(lite_prefix_mask "$2")
	NETWORK=$((ADDRESS_NUMBER & MASK))
	BROADCAST=$((NETWORK | (4294967295 ^ MASK)))
	[ "$ADDRESS_NUMBER" -ne "$NETWORK" ] &&
		[ "$ADDRESS_NUMBER" -ne "$BROADCAST" ]
}

lite_prefix_to_netmask() {
	PREFIX=$1
	MASK=$(lite_prefix_mask "$PREFIX")
	printf '%s.%s.%s.%s\n' \
		$(((MASK >> 24) & 255)) \
		$(((MASK >> 16) & 255)) \
		$(((MASK >> 8) & 255)) \
		$((MASK & 255))
}

lite_cidr_matches_netmask() {
	CIDR=$1
	NETMASK=$2
	PREFIX=${CIDR#*/}
	[ "$(lite_prefix_to_netmask "$PREFIX")" = "$NETMASK" ]
}

lite_reject_route_overlap() {
	CIDR=$1
	PLANT_DEVICE=$2
	PLANT_NETWORK=$(lite_ipv4_number "${CIDR%/*}")
	PLANT_PREFIX=${CIDR#*/}
	PLANT_MASK=$(lite_prefix_mask "$PLANT_PREFIX")
	ROUTES=$(ip -4 route show) || lite_die "could not inspect active IPv4 routes"
	while IFS= read -r ROUTE_LINE; do
		set -- $ROUTE_LINE
		[ "$#" -gt 0 ] || continue
		ROUTE=${1:-}
		[ "$ROUTE" != default ] || continue
		ROUTE_DEVICE=
		shift
		while [ "$#" -gt 1 ]; do
			if [ "$1" = dev ]; then
				ROUTE_DEVICE=$2
				break
			fi
			shift
		done
		[ -n "$ROUTE_DEVICE" ] || continue
		[ "$ROUTE_DEVICE" = "$PLANT_DEVICE" ] && continue
		case "$ROUTE" in
			*/*) ROUTE_PREFIX=${ROUTE#*/}; ROUTE_IP=${ROUTE%/*} ;;
			*) ROUTE_PREFIX=32; ROUTE_IP=$ROUTE ;;
		esac
		lite_valid_ipv4 "$ROUTE_IP" || continue
		case "$ROUTE_PREFIX" in
			''|*[!0-9]*) continue ;;
		esac
		[ "$ROUTE_PREFIX" -ge 0 ] && [ "$ROUTE_PREFIX" -le 32 ] || continue
		ROUTE_MASK=$(lite_prefix_mask "$ROUTE_PREFIX")
		ROUTE_NETWORK=$(lite_ipv4_number "$ROUTE_IP")
		if [ $((PLANT_NETWORK & ROUTE_MASK)) -eq $((ROUTE_NETWORK & ROUTE_MASK)) ] ||
			[ $((ROUTE_NETWORK & PLANT_MASK)) -eq $((PLANT_NETWORK & PLANT_MASK)) ]; then
			lite_die "plant subnet overlaps an active route on $ROUTE_DEVICE ($ROUTE)"
		fi
	done <<EOF
$ROUTES
EOF
}
