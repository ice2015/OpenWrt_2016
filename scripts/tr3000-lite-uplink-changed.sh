#!/bin/sh
# Public transition notification. Remote/DDNS consumers are added in stage 3.
PATH=/usr/sbin:/usr/bin:/sbin:/bin
export PATH
if [ "${1:-}" = --help ]; then
	printf 'Usage: %s ACTIVE PREVIOUS\n' "$0"
	exit 0
fi
[ "$#" -eq 2 ] || exit 2
for network in "$1" "$2"; do
	case "$network" in ''|wan|wwan|usbwan) ;; *) exit 2 ;; esac
done
ubus send tr3000-lite.uplink-changed \
	"{\"schema_version\":1,\"active\":\"$1\",\"previous\":\"$2\"}"
