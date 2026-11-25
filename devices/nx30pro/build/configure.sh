#!/bin/sh
# Prepare and validate the NX30 Pro firmware configuration.
#
# The script merges the device layer into the source tree, applies the device
# patches, runs the real defconfig and checks the configuration that the
# build produced. It never touches another device and never changes the
# common or the distribution layer.
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
DEVICE_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
REPO_ROOT=$(CDPATH= cd -- "$DEVICE_ROOT/../.." && pwd)
HELPER="$SCRIPT_DIR/firmware_lock.py"

SOURCE_DIR=
LOCK="$DEVICE_ROOT/source-lock.json"
DEVICE_CONFIG="$DEVICE_ROOT/config.config"
PATCH_DIR="$DEVICE_ROOT/patches"
OVERLAY_DIR="$DEVICE_ROOT/files"

usage() {
	printf 'Usage: %s --source-dir DIR [--lock FILE] [--config FILE]\n' "$0"
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
		--lock)
			[ "$#" -ge 2 ] || fail "--lock requires a value"
			LOCK=$2
			shift 2
			;;
		--config)
			[ "$#" -ge 2 ] || fail "--config requires a value"
			DEVICE_CONFIG=$2
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
[ -d "$SOURCE_DIR" ] || fail "source directory not found: $SOURCE_DIR"
[ -d "$SOURCE_DIR/scripts" ] || fail "not an OpenWrt source tree: $SOURCE_DIR"
[ -f "$LOCK" ] || fail "source lock not found: $LOCK"
[ -f "$DEVICE_CONFIG" ] || fail "device configuration not found: $DEVICE_CONFIG"
command -v python3 >/dev/null 2>&1 || fail "python3 is required"

SOURCE_DIR=$(CDPATH= cd -- "$SOURCE_DIR" && pwd)
LOCK=$(CDPATH= cd -- "$(dirname -- "$LOCK")" && pwd)/$(basename -- "$LOCK")
DEVICE_CONFIG=$(CDPATH= cd -- "$(dirname -- "$DEVICE_CONFIG")" && pwd)/$(basename -- "$DEVICE_CONFIG")

python3 "$HELPER" check --lock "$LOCK" >/dev/null || fail "the source lock is not build ready"

EXPECTED_REVISION=$(python3 - "$LOCK" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    print(json.load(handle)["source"]["revision"])
PY
)
ACTUAL_REVISION=$(git -C "$SOURCE_DIR" rev-parse HEAD)
[ "$ACTUAL_REVISION" = "$EXPECTED_REVISION" ] ||
	fail "the source tree is at $ACTUAL_REVISION, the lock pins $EXPECTED_REVISION"

# The device layer may only touch the device. Every other device of the same
# source tree keeps its own configuration.
if grep -E '^CONFIG_TARGET_' "$DEVICE_CONFIG" | grep -qv '^CONFIG_TARGET_mediatek'; then
	fail "the device configuration names another target"
fi
grep -Fq 'CONFIG_TARGET_mediatek_mt7981_DEVICE_h3c_nx30pro_112M=y' "$DEVICE_CONFIG" ||
	fail "the device configuration does not select the 112M profile"

DTS="$SOURCE_DIR/target/linux/mediatek/files-5.4/arch/arm64/boot/dts/mediatek/mt7981-h3c-nx30pro-112M.dts"
[ -f "$DTS" ] || fail "the 112M device tree is missing: $DTS"
for entry in "label = \"BL2\"; reg = <0x00 0x100000>;" \
	"label = \"u-boot-env\"; reg = <0x100000 0x80000>;" \
	"label = \"Factory\"; reg = <0x180000 0x200000>;" \
	"label = \"FIP\"; reg = <0x380000 0x200000>;" \
	"label = \"ubi\"; reg = <0x580000 0x7000000>;"
do
	grep -Fq "$entry" "$DTS" || fail "the 112M device tree does not carry the partition contract: $entry"
done

IMAGE_RULES="$SOURCE_DIR/target/linux/mediatek/image/mt7981.mk"
grep -Fq 'define Device/h3c_nx30pro_112M' "$IMAGE_RULES" ||
	fail "the image rules do not define h3c_nx30pro_112M"
grep -Fq 'IMAGE_SIZE := 110592k' "$IMAGE_RULES" ||
	fail "the image rules do not carry the 108 MiB image limit"

# Device patches. They apply to the locked source only.
if [ -d "$PATCH_DIR" ]; then
	for patch in "$PATCH_DIR"/*.patch; do
		[ -f "$patch" ] || continue
		git -C "$SOURCE_DIR" apply --check "$patch" ||
			fail "the device patch does not apply to the locked source: $patch"
		git -C "$SOURCE_DIR" apply "$patch" ||
			fail "the device patch could not be applied: $patch"
		printf 'Applied device patch: %s\n' "$(basename -- "$patch")"
	done
fi

# The device layer is merged over the configuration of the source tree. Only
# the device layer symbols are replaced, every other symbol of the source
# stays as it is.
TEMP_CONFIG=$(mktemp "$SOURCE_DIR/.config.nx30pro.XXXXXX")
trap 'rm -f "$TEMP_CONFIG"' EXIT HUP INT TERM
[ -f "$SOURCE_DIR/.config" ] || : > "$SOURCE_DIR/.config"
awk '
	function key(line) {
		if (line ~ /^# CONFIG_[A-Za-z0-9_-]+ is not set$/) {
			sub(/^# /, "", line)
			sub(/ is not set$/, "", line)
			return line
		}
		if (line ~ /^CONFIG_[A-Za-z0-9_-]+=/) {
			sub(/=.*/, "", line)
			return line
		}
		return ""
	}
	FNR == NR {
		symbol = key($0)
		if (symbol != "") {
			replacement[symbol] = $0
			order[++count] = symbol
		}
		next
	}
	{
		symbol = key($0)
		if (symbol == "" || !(symbol in replacement))
			print
	}
	END {
		for (i = 1; i <= count; i++)
			print replacement[order[i]]
	}
' "$DEVICE_CONFIG" "$SOURCE_DIR/.config" > "$TEMP_CONFIG"
cp "$TEMP_CONFIG" "$SOURCE_DIR/.config"

(
	cd "$SOURCE_DIR"
	./scripts/feeds update -a
	make defconfig
)

python3 "$HELPER" verify-config --lock "$LOCK" --config "$SOURCE_DIR/.config" ||
	fail "the built configuration does not match the source lock"

# The device overlay belongs into the image. It holds no secret.
if [ -d "$OVERLAY_DIR" ]; then
	mkdir -p "$SOURCE_DIR/files"
	cp -R "$OVERLAY_DIR/." "$SOURCE_DIR/files/"
fi

printf 'NX30 Pro configuration validated for the 112M profile.\n'
