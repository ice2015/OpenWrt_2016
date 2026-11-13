#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
. "$SCRIPT_DIR/lite-common.sh"

usage() {
	cat <<EOF
Usage:
  $0 enable --peer IPV4 --plant-cidr IPV4/PREFIX --plant-ip IPV4 --protocol tcp|udp --ports PORT[,PORT...]
  $0 disable --peer IPV4

Enables only listed destination ports for one authorized WireGuard peer.
EOF
}

if [ "${1:-}" = --help ]; then
	usage
	exit 0
fi
ACTION=${1:-}
[ -n "$ACTION" ] || {
	usage >&2
	exit 2
}
shift
PEER=
PLANT_CIDR=
PLANT_IP=
PROTOCOL=
PORTS=
ROLLBACK=0
FIREWALL_BACKUP=
restore_firewall() {
	if [ "$ROLLBACK" -eq 1 ]; then
		cp -p "$FIREWALL_BACKUP" /etc/config/firewall
		/etc/init.d/firewall reload >/dev/null 2>&1 ||
			printf '%s\n' 'Warning: firewall rollback reload failed; inspect it from the local console.' >&2
	fi
	if [ -n "$FIREWALL_BACKUP" ]; then
		rm -f "$FIREWALL_BACKUP"
	fi
}
begin_firewall_change() {
	[ -r /etc/config/firewall ] || lite_die "firewall config is not readable"
	FIREWALL_BACKUP="/tmp/firewall.before-lite-access.$$"
	umask 077
	cp -p /etc/config/firewall "$FIREWALL_BACKUP"
	ROLLBACK=1
	trap restore_firewall EXIT
	trap 'exit 1' HUP INT TERM
}
while [ "$#" -gt 0 ]; do
	case "$1" in
		--peer)
			[ "$#" -ge 2 ] || lite_die "--peer requires a value"
			PEER=$2
			shift 2
			;;
		--plant-cidr)
			[ "$#" -ge 2 ] || lite_die "--plant-cidr requires a value"
			PLANT_CIDR=$2
			shift 2
			;;
		--plant-ip)
			[ "$#" -ge 2 ] || lite_die "--plant-ip requires a value"
			PLANT_IP=$2
			shift 2
			;;
		--protocol)
			[ "$#" -ge 2 ] || lite_die "--protocol requires a value"
			PROTOCOL=$2
			shift 2
			;;
		--ports)
			[ "$#" -ge 2 ] || lite_die "--ports requires a value"
			PORTS=$2
			shift 2
			;;
		--help)
			usage
			exit 0
			;;
		*)
			lite_die "unknown argument: $1"
			;;
	esac
done

lite_valid_ipv4 "$PEER" || lite_die "invalid peer IPv4 address: $PEER"
PEER_TAG=$(printf '%s' "$PEER" | tr '.' '_')
lite_require uci
lite_require fw4

case "$ACTION" in
	disable)
		[ -z "$PLANT_CIDR$PLANT_IP$PROTOCOL$PORTS" ] ||
			lite_die "disable accepts only --peer"
		FOUND=0
		SECTIONS=$(uci show firewall | sed -n 's/^firewall\.\(lite_.*\)=.*/\1/p')
		for SECTION in $SECTIONS; do
			case "$SECTION" in
				"lite_snat_$PEER_TAG"|"lite_allow_${PEER_TAG}_"*)
					FOUND=1
					;;
			esac
		done
		if [ "$FOUND" -eq 1 ]; then
			begin_firewall_change
			for SECTION in $SECTIONS; do
				case "$SECTION" in
					"lite_snat_$PEER_TAG"|"lite_allow_${PEER_TAG}_"*)
						uci -q delete "firewall.$SECTION"
						;;
				esac
			done
			uci commit firewall
			fw4 check
			/etc/init.d/firewall reload
			ROLLBACK=0
			printf 'Removed Lite access rules for peer %s.\n' "$PEER"
		else
			printf 'No Lite access rules found for peer %s.\n' "$PEER"
		fi
		;;
	enable)
		lite_valid_cidr "$PLANT_CIDR" || lite_die "invalid --plant-cidr"
		lite_valid_ipv4 "$PLANT_IP" || lite_die "invalid --plant-ip"
		lite_cidr_contains "$PLANT_CIDR" "$PLANT_IP" ||
			lite_die "--plant-ip is not inside --plant-cidr"
		lite_valid_ipv4 "$PEER" || lite_die "invalid --peer"
		case "$PROTOCOL" in
			tcp|udp) ;;
			*) lite_die "--protocol must be tcp or udp" ;;
		esac
		case "$PORTS" in
			''|,*|*,|*,,*) lite_die "--ports must be a comma-separated list of individual ports" ;;
		esac
		SEEN_PORTS=' '
		for PORT in $(printf '%s' "$PORTS" | tr ',' ' '); do
			lite_valid_port "$PORT" || lite_die "invalid destination port: $PORT"
			case "$SEEN_PORTS" in
				*" $PORT "*) lite_die "--ports contains a duplicate port: $PORT" ;;
			esac
			SEEN_PORTS="$SEEN_PORTS$PORT "
		done
		[ "$(uci -q get network.wg.proto 2>/dev/null || :)" = wireguard ] ||
			lite_die "configure the wg WireGuard interface before enabling access"
		lite_require wg
		wg show wg0 allowed-ips | grep -Fq " $PEER/32" ||
			lite_die "wg0 does not contain the authorized peer $PEER/32"
		PLANT_DEVICE=$(uci -q get network.plant.device 2>/dev/null || :)
		[ -n "$PLANT_DEVICE" ] || lite_die "configure the plant device before enabling access"
		PLANT_CONFIGURED_IP=$(uci -q get network.plant.ipaddr 2>/dev/null || :)
		[ "$PLANT_CONFIGURED_IP" = "$PLANT_IP" ] ||
			lite_die "--plant-ip does not match the active plant profile"
		PLANT_CONFIGURED_MASK=$(uci -q get network.plant.netmask 2>/dev/null || :)
		lite_cidr_matches_netmask "$PLANT_CIDR" "$PLANT_CONFIGURED_MASK" ||
			lite_die "--plant-cidr does not match the active plant profile"
		ip -4 addr show dev "$PLANT_DEVICE" |
			grep -Fq "inet $PLANT_IP/" ||
			lite_die "plant IP is not active on $PLANT_DEVICE"
		lite_reject_route_overlap "$PLANT_CIDR" "$PLANT_DEVICE"
		begin_firewall_change
		SECTIONS=$(uci show firewall | sed -n 's/^firewall\.\(lite_.*\)=.*/\1/p')
		for SECTION in $SECTIONS; do
			case "$SECTION" in
				"lite_snat_$PEER_TAG"|"lite_allow_${PEER_TAG}_"*)
					uci -q delete "firewall.$SECTION"
					;;
			esac
		done
		NAT_SECTION="lite_snat_$PEER_TAG"
		uci set "firewall.$NAT_SECTION=nat"
		uci set "firewall.$NAT_SECTION.name=lite-wg-snat-$PEER_TAG"
		uci set "firewall.$NAT_SECTION.family=ipv4"
		uci set "firewall.$NAT_SECTION.src=wg"
		uci set "firewall.$NAT_SECTION.dest=plant"
		uci set "firewall.$NAT_SECTION.src_ip=$PEER"
		uci set "firewall.$NAT_SECTION.dest_ip=$PLANT_CIDR"
		uci set "firewall.$NAT_SECTION.target=SNAT"
		uci set "firewall.$NAT_SECTION.snat_ip=$PLANT_IP"
		uci set "firewall.$NAT_SECTION.proto=$PROTOCOL"
		for PORT in $(printf '%s' "$PORTS" | tr ',' ' '); do
			RULE_SECTION="lite_allow_${PEER_TAG}_${PROTOCOL}_${PORT}"
			uci set "firewall.$RULE_SECTION=rule"
			uci set "firewall.$RULE_SECTION.name=lite-wg-to-plant-${PEER_TAG}-${PORT}"
			uci set "firewall.$RULE_SECTION.family=ipv4"
			uci set "firewall.$RULE_SECTION.src=wg"
			uci set "firewall.$RULE_SECTION.dest=plant"
			uci set "firewall.$RULE_SECTION.src_ip=$PEER"
			uci set "firewall.$RULE_SECTION.dest_ip=$PLANT_CIDR"
			uci set "firewall.$RULE_SECTION.proto=$PROTOCOL"
			uci set "firewall.$RULE_SECTION.dest_port=$PORT"
			uci set "firewall.$RULE_SECTION.target=ACCEPT"
		done
		uci commit firewall
		fw4 check
		/etc/init.d/firewall reload
		ROLLBACK=0
		printf 'Enabled %s access for peer %s to %s on %s ports %s.\n' \
			"$PROTOCOL" "$PEER" "$PLANT_CIDR" "$PLANT_IP" "$PORTS"
		;;
	*)
		usage >&2
		exit 2
		;;
esac
