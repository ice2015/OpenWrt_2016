#!/bin/sh
set -eu

SOURCE_DIR=
IMAGE=
MAX_BYTES=104857600

usage() {
	printf 'Usage: %s --source-dir DIR --image FILE [--max-bytes N]\n' "$0"
}

fail() {
	printf 'Error: %s\n' "$*" >&2
	exit 1
}

while [ "$#" -gt 0 ]; do
	case "$1" in
		--source-dir)
			[ "$#" -ge 2 ] || fail "--source-dir requires a value"
			SOURCE_DIR=$2
			shift 2
			;;
		--image)
			[ "$#" -ge 2 ] || fail "--image requires a value"
			IMAGE=$2
			shift 2
			;;
		--max-bytes)
			[ "$#" -ge 2 ] || fail "--max-bytes requires a value"
			MAX_BYTES=$2
			shift 2
			;;
		--help)
			usage
			exit 0
			;;
		*) fail "unknown argument: $1" ;;
	esac
done

[ -n "$SOURCE_DIR" ] || fail "--source-dir is required"
[ -n "$IMAGE" ] || fail "--image is required"
case "$MAX_BYTES" in
	''|*[!0-9]*|0) fail "--max-bytes must be a positive integer" ;;
esac
[ -f "$SOURCE_DIR/.config" ] || fail "source .config not found"
[ -s "$IMAGE" ] || fail "image is missing or empty: $IMAGE"

BASENAME=$(basename -- "$IMAGE")
case "$BASENAME" in
	*cudy_tr3000-v1-ubootmod*sysupgrade.bin) ;;
	*) fail "image filename is not a TR3000 U-Boot Mod sysupgrade image: $BASENAME" ;;
esac

[ "$(grep -c '^CONFIG_TARGET_mediatek_filogic_DEVICE_.*=y$' "$SOURCE_DIR/.config")" -eq 1 ] ||
	fail "final config must select exactly one mediatek filogic device profile"
grep -Fq 'CONFIG_TARGET_mediatek_filogic_DEVICE_cudy_tr3000-v1-ubootmod=y' "$SOURCE_DIR/.config" ||
	fail "final config does not select cudy_tr3000-v1-ubootmod"
DTS="$SOURCE_DIR/target/linux/mediatek/dts/mt7981b-cudy-tr3000-v1-ubootmod.dts"
[ -f "$DTS" ] || fail "verified profile DTS not found"
grep -Fq 'reg = <0x5c0000 0x7000000>;' "$DTS" ||
	fail "DTS is not the verified 112 MiB UBI layout"
if grep -Fq 'reg = <0x5c0000 0x7a40000>;' "$DTS"; then
	fail "DTS contains the refused 122 MiB layout"
fi

SIZE=$(wc -c < "$IMAGE" | tr -d '[:space:]')
[ "$SIZE" -le "$MAX_BYTES" ] ||
	fail "image size $SIZE exceeds safe limit $MAX_BYTES bytes"
ARCHIVE_LIST=$(mktemp)
trap 'rm -f "$ARCHIVE_LIST"' EXIT HUP INT TERM
tar --force-local -tf "$IMAGE" > "$ARCHIVE_LIST" 2>/dev/null ||
	fail "image is not a readable sysupgrade tar archive"
grep -Eq '^sysupgrade-cudy_tr3000-v1-ubootmod/CONTROL$' "$ARCHIVE_LIST" ||
	fail "sysupgrade archive does not contain the expected profile CONTROL entry"

printf 'Verified %s (%s bytes) for TR3000 128M / 112M UBI.\n' "$BASENAME" "$SIZE"
