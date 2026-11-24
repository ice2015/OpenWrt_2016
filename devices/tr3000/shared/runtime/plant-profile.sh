#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
. "$SCRIPT_DIR/lite-common.sh"

usage() {
	printf 'Usage: %s --device IFACE --address IPV4/PREFIX\n' "$0"
	printf 'Example: %s --device eth1 --address 192.168.10.254/24\n' "$0"
}

DEVICE=
ADDRESS=
while [ "$#" -gt 0 ]; do
	case "$1" in
		--device)
			[ "$#" -ge 2 ] || lite_die "--device requires a value"
			DEVICE=$2
			shift 2
			;;
		--address)
			[ "$#" -ge 2 ] || lite_die "--address requires a value"
			ADDRESS=$2
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

[ -n "$DEVICE" ] || lite_die "--device is required; confirm the physical mapping first"
[ -n "$ADDRESS" ] || lite_die "--address is required; no plant address is preconfigured"
lite_valid_iface "$DEVICE" || lite_die "invalid network device: $DEVICE"
lite_valid_cidr "$ADDRESS" || lite_die "invalid IPv4 address/prefix: $ADDRESS"
lite_require ip
lite_require uci
lite_require arping

ip link show dev "$DEVICE" >/dev/null 2>&1 || lite_die "device does not exist: $DEVICE"
WAN_DEVICE=$(uci -q get network.wan.device 2>/dev/null || :)
[ "$DEVICE" != "$WAN_DEVICE" ] || lite_die "plant device cannot be the configured WAN device"

lite_reject_route_overlap "$ADDRESS" "$DEVICE"
PLANT_IP=${ADDRESS%/*}
PREFIX=${ADDRESS#*/}
lite_check_address_not_network_or_broadcast "$PLANT_IP" "$PREFIX" ||
	lite_die "plant address must be a usable host address, not the subnet or broadcast address"

printf 'Checking for an IPv4 address conflict on %s...\n' "$DEVICE"
if arping -D -c 3 -I "$DEVICE" "$PLANT_IP"; then
	:
else
	lite_die "address conflict or arping failure; no configuration was changed"
fi

NETMASK=$(lite_prefix_to_netmask "$PREFIX")
BACKUP="/root/network.before-plant-profile.$(date +%Y%m%d%H%M%S).$$"
cp -p /etc/config/network "$BACKUP"
ROLLBACK=1
restore_network() {
	if [ "${ROLLBACK:-0}" -eq 1 ]; then
		cp -p "$BACKUP" /etc/config/network
		ubus call network reload >/dev/null 2>&1 ||
			printf '%s\n' 'Warning: automatic network reload failed; restore the saved network config locally.' >&2
	fi
}
trap restore_network EXIT
trap 'exit 1' HUP INT TERM

uci batch <<EOF
set network.plant=interface
set network.plant.device='$DEVICE'
set network.plant.proto='static'
set network.plant.ipaddr='$PLANT_IP'
set network.plant.netmask='$NETMASK'
EOF
uci commit network
ubus call network reload
ROLLBACK=0
printf 'Plant profile applied. Previous network config: %s\n' "$BACKUP"
