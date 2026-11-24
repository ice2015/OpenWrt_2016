#!/bin/sh
set -eu

SOURCE_DIR=
ARTIFACT_DIR=

usage() {
	printf 'Usage: %s --source-dir DIR --artifact-dir DIR\n' "$0"
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
		--artifact-dir)
			[ "$#" -ge 2 ] || fail "--artifact-dir requires a value"
			ARTIFACT_DIR=$2
			shift 2
			;;
		--help)
			usage
			exit 0
			;;
		*)
			fail "unknown argument: $1"
			;;
	esac
done

[ -n "$SOURCE_DIR" ] || fail "--source-dir is required"
[ -n "$ARTIFACT_DIR" ] || fail "--artifact-dir is required"
[ -f "$SOURCE_DIR/build.sh" ] || fail "pinned DHCP U-Boot build.sh not found"
mkdir -p "$ARTIFACT_DIR/logs" "$ARTIFACT_DIR/images"
if [ -f "$SOURCE_DIR/LICENSE" ]; then
	cp "$SOURCE_DIR/LICENSE" "$ARTIFACT_DIR/UPSTREAM-LICENSE"
else
	printf '%s\n' \
		'No root LICENSE file is present in the pinned DHCP U-Boot repository revision.' \
		'Inspect the source tree component licenses before redistribution.' \
		> "$ARTIFACT_DIR/UPSTREAM-LICENSE-STATUS.txt"
fi
git -C "$SOURCE_DIR" show -s --format='%H%n%T%n%aI%n%s' > "$ARTIFACT_DIR/uboot-commit.txt"

if (
	cd "$SOURCE_DIR"
	SILENT=Y SOC=mt7981 BOARD=cudy_tr3000-v1 VERSION=2025 MULTI_LAYOUT=1 ./build.sh
) > "$ARTIFACT_DIR/logs/build.log" 2>&1; then
	cat "$ARTIFACT_DIR/logs/build.log"
else
	cat "$ARTIFACT_DIR/logs/build.log" >&2
	fail "pinned DHCP U-Boot build failed"
fi

OUTPUT_DIR="$SOURCE_DIR/output"
[ -d "$OUTPUT_DIR" ] || fail "U-Boot output directory not found"
BL2_IMAGE=$(find "$OUTPUT_DIR" -maxdepth 1 -type f \
	-name 'bl2-mt7981_cudy_tr3000-v1_2025*.bin' -size +0c)
FIP_IMAGE=$(find "$OUTPUT_DIR" -maxdepth 1 -type f \
	-name 'fip-mt7981_cudy_tr3000-v1_2025*-multi-layout*.bin' -size +0c)
[ "$(printf '%s\n' "$BL2_IMAGE" | grep -c . || :)" -eq 1 ] ||
	fail "expected exactly one non-empty MT7981 TR3000 BL2 image"
[ "$(printf '%s\n' "$FIP_IMAGE" | grep -c . || :)" -eq 1 ] ||
	fail "expected exactly one non-empty multi-layout TR3000 FIP image"
install -m 0644 "$BL2_IMAGE" "$ARTIFACT_DIR/images/"
install -m 0644 "$FIP_IMAGE" "$ARTIFACT_DIR/images/"
file "$ARTIFACT_DIR"/images/*
(cd "$ARTIFACT_DIR/images" && sha256sum *.bin) > "$ARTIFACT_DIR/images/SHA256SUMS"
cat > "$ARTIFACT_DIR/FLASH-TARGETS.txt" <<'EOF'
Build target: Cudy TR3000 v1, MT7981, DHCP U-Boot 2025, 128 MiB multi-layout.
BL2: boot preloader image; its exact flash target must be identified from the installed hardware's verified partition map.
FIP: U-Boot/FIP image; its exact flash target must be identified from the installed hardware's verified partition map.
No standalone recovery image is emitted by this build; do not rename BL2 or FIP as a recovery image.
These files are not automatically flashed and are not interchangeable with firmware sysupgrade images.
EOF
