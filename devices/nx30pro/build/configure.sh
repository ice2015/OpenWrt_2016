#!/bin/sh
# Prepare and validate the NX30 Pro firmware configuration.
#
# Order matters: the lock gate first, then the device patches, then the
# source level verifiers that read what the patches created, then the layer
# merge in the repository precedence common -> distribution -> device, then
# the real `make defconfig`, and only then the audit of the FINAL .config.
# The overlay is scanned for secrets and deployment values before it is copied
# into the tree. Nothing here compiles firmware; a missing hard gate stops the
# build before build.sh is allowed to start one. The script never touches
# another device and never edits the common or the distribution layer.
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
LOG_DIR=
PROBE=

usage() {
	printf 'Usage: %s --source-dir DIR [--lock FILE] [--config FILE] [--patch-dir DIR] [--overlay-dir DIR] [--log-dir DIR] [--probe]\n' "$0"
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
		--patch-dir)
			[ "$#" -ge 2 ] || fail "--patch-dir requires a value"
			PATCH_DIR=$2
			shift 2
			;;
		--overlay-dir)
			[ "$#" -ge 2 ] || fail "--overlay-dir requires a value"
			OVERLAY_DIR=$2
			shift 2
			;;
		--log-dir)
			[ "$#" -ge 2 ] || fail "--log-dir requires a value"
			LOG_DIR=$2
			shift 2
			;;
		--probe)
			PROBE=1
			shift
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

# An authorized defconfig probe audits the final .config and reports every
# missing hard gate instead of stopping at the first one.
PROBE_FLAG=
PROBE_CHECK_FLAG=
if [ "$PROBE" = "1" ]; then
	PROBE_FLAG=--probe
	PROBE_CHECK_FLAG=--allow-probe
fi

SOURCE_DIR=$(CDPATH= cd -- "$SOURCE_DIR" && pwd)
LOCK=$(CDPATH= cd -- "$(dirname -- "$LOCK")" && pwd)/$(basename -- "$LOCK")
DEVICE_CONFIG=$(CDPATH= cd -- "$(dirname -- "$DEVICE_CONFIG")" && pwd)/$(basename -- "$DEVICE_CONFIG")

# Every gate writes its evidence into the log directory of the caller, so a
# rejected configuration can be diagnosed from the uploaded logs alone.
evidence() {
	_name=$1
	shift
	if [ -n "$LOG_DIR" ]; then
		mkdir -p "$LOG_DIR"
		"$@" > "$LOG_DIR/$_name"
		_status=$?
		cat "$LOG_DIR/$_name"
		return $_status
	fi
	"$@"
}

python3 "$HELPER" check --lock "$LOCK" $PROBE_CHECK_FLAG >/dev/null || fail "the source lock is not build ready"

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
IMAGE_RULES="$SOURCE_DIR/target/linux/mediatek/image/mt7981.mk"

# Device patches. They apply to the locked source only, and they are what
# creates the ported profile, so every source level verifier runs after them.
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

# The ported device tree and the ported profile exist only after the patch
# loop, so both are compared with the lock here and not before.
[ -f "$DTS" ] || fail "the 112M device tree is missing: $DTS"
evidence device-tree.json python3 "$HELPER" verify-device-tree --lock "$LOCK" --dts "$DTS" ||
	fail "the 112M device tree does not carry the partition contract"
[ -f "$IMAGE_RULES" ] || fail "the image rules are missing: $IMAGE_RULES"
evidence image-rules.json python3 "$HELPER" verify-image-rules --lock "$LOCK" --image-rules "$IMAGE_RULES" ||
	fail "the image rules do not carry the locked profile, image limit and image roles"

# The configuration layers are the ones the repository manifest declares for
# this device, merged in the documented precedence common -> distribution ->
# device. The device layer comes last so it overrides both earlier layers,
# and the merged seed is what the real `make defconfig` expands.
CONFIG_LAYERS=$(python3 - "$REPO_ROOT" "$LOCK" <<'PY'
import json
import subprocess
import sys

repo_root, lock_path = sys.argv[1], sys.argv[2]
with open(lock_path, encoding="utf-8") as handle:
    lock = json.load(handle)
resolved = subprocess.run(
    [
        sys.executable,
        repo_root + "/tools/manifest.py",
        "resolve",
        "--distribution",
        lock["distribution"],
        "--device",
        lock["device"],
    ],
    capture_output=True,
    text=True,
)
if resolved.returncode != 0:
    sys.stderr.write(resolved.stderr)
    sys.exit(resolved.returncode)
for layer in json.loads(resolved.stdout)["config_layers"]:
    print(layer if layer.startswith("/") else repo_root + "/" + layer)
PY
) || fail "the repository manifest names no configuration layer for this device"
[ -n "$CONFIG_LAYERS" ] || fail "the repository manifest names no configuration layer"

# --config replaces the device layer, which the manifest lists last.
if [ "$(printf '%s\n' "$CONFIG_LAYERS" | tail -n 1)" != "$DEVICE_CONFIG" ]; then
	CONFIG_LAYERS=$(printf '%s\n' "$CONFIG_LAYERS" | sed '$d')
	CONFIG_LAYERS=$(printf '%s\n%s\n' "$CONFIG_LAYERS" "$DEVICE_CONFIG")
fi

merge_layers() {
	_out=$1
	shift
	for _layer in $CONFIG_LAYERS; do
		[ -f "$_layer" ] || fail "a configuration layer is missing: $_layer"
		set -- "$@" "$_layer"
	done
	[ "$#" -ge 2 ] || fail "the device layer cannot be merged on its own"
	printf 'Merging configuration layers (common -> distribution -> device):\n'
	for _layer in "$@"; do
		printf '  %s\n' "$_layer"
	done
	python3 "$HELPER" merge-config --out "$_out" "$@"
}

TEMP_CONFIG=$(mktemp "$SOURCE_DIR/.config.nx30pro.XXXXXX")
trap 'rm -f "$TEMP_CONFIG"' EXIT HUP INT TERM
merge_layers "$TEMP_CONFIG"
cp "$TEMP_CONFIG" "$SOURCE_DIR/.config"

# Evidence of what defconfig received. Without it a final configuration that
# lost a requested package cannot be diagnosed: nothing shows whether the seed
# asked for it or defconfig dropped it.
keep_evidence() {
	if [ -n "$LOG_DIR" ]; then
		mkdir -p "$LOG_DIR"
		cp "$1" "$LOG_DIR/$2"
	fi
}
keep_evidence "$TEMP_CONFIG" seed.config
keep_evidence "$SOURCE_DIR/.config" pre-defconfig.config

(
	cd "$SOURCE_DIR"
	./scripts/feeds update -a
	# The feeds have to be installed into the package tree before defconfig,
	# otherwise the packages of the requirement table do not exist as symbols.
	./scripts/feeds install -a -f
	make defconfig
)

if [ -n "$LOG_DIR" ]; then
	mkdir -p "$LOG_DIR"
	# What defconfig changed relative to the seed it was given.
	diff -u "$LOG_DIR/pre-defconfig.config" "$SOURCE_DIR/.config" \
		> "$LOG_DIR/defconfig-diff.txt" || true
fi

evidence final-config.json python3 "$HELPER" verify-config --lock "$LOCK" --config "$SOURCE_DIR/.config" $PROBE_FLAG ||
	{
		_status=$?
		if [ "$PROBE" = "1" ] && [ "$_status" -eq 4 ]; then
			# A probe reports which hard gates `make defconfig` dropped. The
			# audit is already in the log directory, so the caller can publish
			# it; the verdict travels in this distinct status.
			printf 'Error: the defconfig probe found hard gates missing from the final .config\n' >&2
			exit 4
		fi
		fail "the built configuration does not match the source lock"
	}


# The device overlay belongs into the image, so it is scanned for secrets and
# deployment values first and copied only when the scan found nothing.
if [ -d "$OVERLAY_DIR" ]; then
	evidence overlay.json python3 "$HELPER" verify-overlay --overlay-dir "$OVERLAY_DIR" ||
		fail "the device overlay carries a secret or a deployment value"
	mkdir -p "$SOURCE_DIR/files"
	cp -R "$OVERLAY_DIR/." "$SOURCE_DIR/files/"
fi

printf 'NX30 Pro configuration validated for the 112M profile.\n'
