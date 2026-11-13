#!/bin/sh
set -eu

if [ "${1:-}" = --help ]; then
	printf 'Usage: %s [--help]\n' "$0"
	exit 0
fi
[ "$#" -eq 0 ] || {
	printf 'Error: unexpected argument: %s\n' "$1" >&2
	exit 2
}

printf '%s\n' \
	'Read-only TR3000 preflight; this script does not write flash or U-Boot environment.' \
	'' \
	'=== /etc/openwrt_release ==='
if [ -r /etc/openwrt_release ]; then
	cat /etc/openwrt_release
else
	printf '%s\n' 'Unavailable: /etc/openwrt_release'
fi

printf '\n%s\n' '=== /proc/mtd ==='
if [ -r /proc/mtd ]; then
	cat /proc/mtd
else
	printf '%s\n' 'Unavailable: /proc/mtd'
fi

printf '\n%s\n' '=== ubinfo -a ==='
if command -v ubinfo >/dev/null 2>&1; then
	ubinfo -a || printf '%s\n' 'ubinfo reported an error; inspect the device and output above.'
else
	printf '%s\n' 'Unavailable: install/use the target-supported ubi-utils package first.'
fi

printf '\n%s\n' '=== NAND, MTD and bad-block kernel messages ==='
if command -v dmesg >/dev/null 2>&1; then
	if ! dmesg | grep -Ei 'NAND|spi-nand|bad block|bad-block|MTD|mt7981'; then
		printf '%s\n' 'No matching kernel messages were found.'
	fi
else
	printf '%s\n' 'Unavailable: dmesg'
fi

printf '\n%s\n' '=== Runtime interfaces and routes ==='
if command -v ip >/dev/null 2>&1; then
	ip -br link
	ip -4 route show
else
	printf '%s\n' 'Unavailable: ip'
fi

printf '\n%s\n' \
	'=== Manual checks still required ===' \
	'Record the bootloader version and active boot/layout selection from the local UART or verified recovery UI.' \
	'Compare every observed partition label/size with the exact board revision and upstream DTS before any write.' \
	'Back up every partition with a verified device-specific read-only method; copy backups to another machine and verify SHA256 there.' \
	'Do not infer MTD names, offsets, image targets, or write commands from this report.'
