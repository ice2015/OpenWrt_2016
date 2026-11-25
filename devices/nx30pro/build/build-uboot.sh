#!/bin/sh
# Build the NX30 Pro boot loader candidate from the locked source.
#
# This script only builds images; it performs no flash operation and never
# writes to a flash device. The produced images stay in the artifact
# directory and are marked as candidates until they are tested on hardware.
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
HELPER="$SCRIPT_DIR/uboot_lock.py"

LOCK=
SOURCE_DIR=
ARTIFACT_DIR=
CHECK_ONLY=

usage() {
	cat <<EOF
Usage: $0 --lock FILE --source-dir DIR --artifact-dir DIR [--check-only]

  --lock FILE         device source lock to build from
  --source-dir DIR    upstream checkout at the locked commit
  --artifact-dir DIR  directory that receives images, logs and the report
  --check-only        validate the lock and print the resolved build plan
EOF
}

fail() {
	printf 'Error: %s\n' "$*" >&2
	exit 1
}

while [ "$#" -gt 0 ]; do
	case "$1" in
		--lock)
			[ "$#" -ge 2 ] || fail "--lock requires a value"
			LOCK=$2
			shift 2
			;;
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
		--check-only)
			CHECK_ONLY=1
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

[ -n "$LOCK" ] || fail "--lock is required"
[ -f "$LOCK" ] || fail "source lock not found: $LOCK"
command -v python3 >/dev/null 2>&1 || fail "python3 is required"

if [ "$CHECK_ONLY" = "1" ]; then
	python3 "$HELPER" check --lock "$LOCK"
	exit 0
fi

[ -n "$SOURCE_DIR" ] || fail "--source-dir is required"
[ -n "$ARTIFACT_DIR" ] || fail "--artifact-dir is required"
[ -d "$SOURCE_DIR" ] || fail "source directory not found: $SOURCE_DIR"
[ -d "$SOURCE_DIR/.git" ] || fail "source directory is not a git checkout: $SOURCE_DIR"

mkdir -p "$ARTIFACT_DIR/logs" "$ARTIFACT_DIR/images"

PLAN_FILE="$ARTIFACT_DIR/logs/build-plan.json"
python3 "$HELPER" check --lock "$LOCK" > "$PLAN_FILE" || fail "the source lock is not build ready"

plan_value() {
	python3 - "$PLAN_FILE" "$1" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    plan = json.load(handle)
for key in sys.argv[2].split("."):
    plan = plan[key]
print(plan)
PY
}

EXPECTED_COMMIT=$(plan_value source_commit)
REPOSITORY=$(plan_value source_repository)
SOC=$(plan_value build_env.SOC)
BOARD=$(plan_value build_env.BOARD)
FIXED_MTDPARTS=$(plan_value build_env.FIXED_MTDPARTS)
MULTI_LAYOUT=$(plan_value build_env.MULTI_LAYOUT)
BL2_PARTITION_SIZE=$(python3 - "$PLAN_FILE" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    plan = json.load(handle)
for entry in plan["partition_table"]:
    if entry["label"] == "BL2":
        print(entry["size"])
        break
PY
)
FIP_PARTITION_SIZE=$(python3 - "$PLAN_FILE" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    plan = json.load(handle)
for entry in plan["partition_table"]:
    if entry["label"] == "FIP":
        print(entry["size"])
        break
PY
)

ACTUAL_COMMIT=$(git -C "$SOURCE_DIR" rev-parse HEAD)
[ "$ACTUAL_COMMIT" = "$EXPECTED_COMMIT" ] ||
	fail "the source checkout is at $ACTUAL_COMMIT, the lock pins $EXPECTED_COMMIT"

printf 'Pinned source: %s at %s\n' "$REPOSITORY" "$EXPECTED_COMMIT"
printf 'Build target: %s %s\n' "$SOC" "$BOARD"

python3 "$HELPER" patch --lock "$LOCK" --source-dir "$SOURCE_DIR" \
	> "$ARTIFACT_DIR/logs/device-patch.json" ||
	fail "the device partition patch could not be applied"

BUILD_LOG="$ARTIFACT_DIR/logs/build.log"
if (
	cd "$SOURCE_DIR"
	SOC="$SOC" BOARD="$BOARD" FIXED_MTDPARTS="$FIXED_MTDPARTS" \
		MULTI_LAYOUT="$MULTI_LAYOUT" ./build.sh
) > "$BUILD_LOG" 2>&1; then
	cat "$BUILD_LOG"
else
	cat "$BUILD_LOG" >&2
	fail "the pinned boot loader build failed"
fi

OUTPUT_DIR="$SOURCE_DIR/output"
[ -d "$OUTPUT_DIR" ] || fail "the boot loader build produced no output directory"

FIP_IMAGE=$(find "$OUTPUT_DIR" -maxdepth 1 -type f -name '*fip*.bin' -size +0c)
BL2_IMAGE=$(find "$OUTPUT_DIR" -maxdepth 1 -type f -name '*bl2*.bin' -size +0c)
[ "$(printf '%s\n' "$FIP_IMAGE" | grep -c . || :)" -eq 1 ] ||
	fail "expected exactly one non-empty FIP image"
[ "$(printf '%s\n' "$BL2_IMAGE" | grep -c . || :)" -eq 1 ] ||
	fail "expected exactly one non-empty BL2 image"

install -m 0644 "$FIP_IMAGE" "$ARTIFACT_DIR/images/"
install -m 0644 "$BL2_IMAGE" "$ARTIFACT_DIR/images/"

FIP_FILE=$(find "$ARTIFACT_DIR/images" -maxdepth 1 -type f -name '*fip*.bin')
BL2_FILE=$(find "$ARTIFACT_DIR/images" -maxdepth 1 -type f -name '*bl2*.bin')

python3 "$HELPER" inspect --kind fip --path "$FIP_FILE" --max-size "$FIP_PARTITION_SIZE" \
	> "$ARTIFACT_DIR/logs/fip-inspection.json" ||
	fail "the FIP image does not match the expected boot loader package"
python3 "$HELPER" inspect --kind bl2 --path "$BL2_FILE" --max-size "$BL2_PARTITION_SIZE" \
	> "$ARTIFACT_DIR/logs/bl2-inspection.json" ||
	fail "the BL2 image does not match the expected boot loader package"

TOOLCHAIN_VERSION=$(aarch64-linux-gnu-gcc --version 2>/dev/null | head -1 || printf 'UNRESOLVED')
TOOLCHAIN_PACKAGE=$(dpkg-query -W -f='${Version}' gcc-aarch64-linux-gnu 2>/dev/null || printf 'UNRESOLVED')

BUILD_ENV_JSON=$(printf '{"SOC":"%s","BOARD":"%s","FIXED_MTDPARTS":"%s","MULTI_LAYOUT":"%s"}' \
	"$SOC" "$BOARD" "$FIXED_MTDPARTS" "$MULTI_LAYOUT")

python3 "$HELPER" report \
	--lock "$LOCK" \
	--out "$ARTIFACT_DIR/build-report.json" \
	--toolchain-version "$TOOLCHAIN_VERSION (package $TOOLCHAIN_PACKAGE)" \
	--build-env "$BUILD_ENV_JSON" \
	--artifact "fip:$FIP_FILE:fip:$FIP_PARTITION_SIZE" \
	--artifact "bl2:$BL2_FILE:bl2:$BL2_PARTITION_SIZE" ||
	fail "the build report could not be written"

(cd "$ARTIFACT_DIR/images" && sha256sum *.bin) > "$ARTIFACT_DIR/images/SHA256SUMS"
cp "$LOCK" "$ARTIFACT_DIR/uboot-source-lock.json"

cat > "$ARTIFACT_DIR/FLASH-TARGETS.txt" <<'EOF'
These files are boot loader candidates built from the pinned source. They are
not system images, they were not tested on hardware and they are not flashed
by this build.

BL2: MediaTek ATF BL2 preloader for SPI-NAND boot. Write target: the bl2
     partition at 0x000000, 1 MiB, of the 112M partition contract.
FIP: ATF FIP package that carries BL31 and BL33 (U-Boot). Write target: the
     fip partition at 0x380000, 2 MiB, of the 112M partition contract.

The system factory image of the selected system belongs into the ubi
partition at 0x580000 and is not part of this build. Do not rename either
boot loader image as a recovery image. The web failsafe entry of the boot
loader serves http://192.168.1.1/ and accepts the same two images; it does
not replace an independent recovery path or a backup of the factory device.
EOF

printf 'Candidate images are in %s\n' "$ARTIFACT_DIR/images"
