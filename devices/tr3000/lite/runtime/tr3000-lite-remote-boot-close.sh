#!/bin/sh
# Runs before firewall/network startup, including the first boot after upgrade.
PATH=/usr/sbin:/usr/bin:/sbin:/bin
export PATH
set -uf
[ "${1:-}" != --help ] || { printf 'Usage: %s (internal early-boot barrier)\n' "$0"; exit 0; }
[ "$#" = 0 ] || exit 2
OWNER_UID=0
PRIVATE=/etc/tr3000-lite
[ "$(id -u)" = "$OWNER_UID" ] || exit 3
[ ! -L "$PRIVATE" ] || exit 3
umask 077
mkdir -p "$PRIVATE" || exit 3
[ "$(stat -c %u "$PRIVATE")" = "$OWNER_UID" ] || exit 3
chmod 0700 "$PRIVATE" || exit 3
. /usr/sbin/lite-common.sh
. /usr/lib/tr3000-lite/remote-lib.sh
scratch=$(mktemp -d "$PRIVATE/.boot-close.XXXXXX") || exit 3
trap 'rm -rf "$scratch"' EXIT
for chain in input forward; do
	for role in wg_direct wg_vps; do
		"remote_guard_$chain" "$role" false '' '' || exit 3
	done > "$scratch/$chain" || exit 3
	remote_install_guard "$scratch/$chain" "$PRIVATE/remote-$chain.nft" || exit 3
done
