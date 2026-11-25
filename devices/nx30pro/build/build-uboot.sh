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

mkdir -p "$ARTIFACT_DIR/logs" "$ARTIFACT_DIR/staging"

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

partition_size() {
	python3 - "$PLAN_FILE" "$1" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    plan = json.load(handle)
for entry in plan["partition_table"]:
    if entry["label"] == sys.argv[2]:
        print(entry["size"])
        break
PY
}

EXPECTED_COMMIT=$(plan_value source_commit)
REPOSITORY=$(plan_value source_repository)
SOC=$(plan_value build_env.SOC)
BOARD=$(plan_value build_env.BOARD)
FIXED_MTDPARTS=$(plan_value build_env.FIXED_MTDPARTS)
MULTI_LAYOUT=$(plan_value build_env.MULTI_LAYOUT)
UBOOT_TREE=$(plan_value uboot_tree)
BL2_PARTITION_SIZE=$(partition_size BL2)
FIP_PARTITION_SIZE=$(partition_size FIP)

# Every check that has to pass before the build may start: the pinned commit,
# a clean checkout, no output of an earlier run, the trees the pinned build
# script really uses and an installed cross compiler.
python3 "$HELPER" preflight --lock "$LOCK" --source-dir "$SOURCE_DIR" \
	> "$ARTIFACT_DIR/logs/preflight.json" ||
	fail "the preflight checks failed, the build was not started"

printf 'Pinned source: %s at %s\n' "$REPOSITORY" "$EXPECTED_COMMIT"
printf 'Build target: %s %s\n' "$SOC" "$BOARD"

PATCH_FILE="$ARTIFACT_DIR/logs/device-patch.json"
python3 "$HELPER" patch --lock "$LOCK" --source-dir "$SOURCE_DIR" > "$PATCH_FILE" ||
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

# The configuration that was really compiled has to carry the 112M partition
# table. A patch that landed in a tree that the build does not use is caught
# here.
python3 "$HELPER" effective-config --lock "$LOCK" \
	--config "$SOURCE_DIR/$UBOOT_TREE/.config" ||
	fail "the compiled configuration does not carry the 112M partition table"

OUTPUT_DIR="$SOURCE_DIR/output"
[ -d "$OUTPUT_DIR" ] || fail "the boot loader build produced no output directory"

FIP_NAME=$(basename "$(python3 - "$LOCK" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    lock = json.load(handle)
print(lock["artifacts"]["fip"].split("/")[-1])
PY
)")
BL2_NAME=$(basename "$(python3 - "$LOCK" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    lock = json.load(handle)
print(lock["artifacts"]["bl2"].split("/")[-1])
PY
)")
[ -s "$OUTPUT_DIR/$FIP_NAME" ] || fail "the build did not produce $FIP_NAME"
[ -s "$OUTPUT_DIR/$BL2_NAME" ] || fail "the build did not produce $BL2_NAME"

# The images stay in the staging directory until both inspections and the
# build report succeeded. A rejected image is never published as a candidate.
install -m 0644 "$OUTPUT_DIR/$FIP_NAME" "$ARTIFACT_DIR/staging/"
install -m 0644 "$OUTPUT_DIR/$BL2_NAME" "$ARTIFACT_DIR/staging/"

python3 "$HELPER" inspect --kind fip --path "$ARTIFACT_DIR/staging/$FIP_NAME" \
	--max-size "$FIP_PARTITION_SIZE" > "$ARTIFACT_DIR/logs/fip-inspection.json" ||
	fail "the FIP image does not match the expected boot loader package"
python3 "$HELPER" inspect --kind bl2 --path "$ARTIFACT_DIR/staging/$BL2_NAME" \
	--max-size "$BL2_PARTITION_SIZE" > "$ARTIFACT_DIR/logs/bl2-inspection.json" ||
	fail "the BL2 image does not match the expected boot loader package"

python3 "$HELPER" toolchain --out "$ARTIFACT_DIR/logs/toolchain.json" ||
	fail "the toolchain identity could not be recorded"

BUILD_ENV_JSON=$(printf '{"SOC":"%s","BOARD":"%s","FIXED_MTDPARTS":"%s","MULTI_LAYOUT":"%s"}' \
	"$SOC" "$BOARD" "$FIXED_MTDPARTS" "$MULTI_LAYOUT")

python3 "$HELPER" report \
	--lock "$LOCK" \
	--out "$ARTIFACT_DIR/build-report.json" \
	--toolchain-file "$ARTIFACT_DIR/logs/toolchain.json" \
	--build-env "$BUILD_ENV_JSON" \
	--artifact "fip:$ARTIFACT_DIR/staging/$FIP_NAME:fip:$FIP_PARTITION_SIZE" \
	--artifact "bl2:$ARTIFACT_DIR/staging/$BL2_NAME:bl2:$BL2_PARTITION_SIZE" ||
	fail "the build report could not be written"

mkdir -p "$ARTIFACT_DIR/images"
install -m 0644 "$ARTIFACT_DIR/staging/$FIP_NAME" "$ARTIFACT_DIR/images/"
install -m 0644 "$ARTIFACT_DIR/staging/$BL2_NAME" "$ARTIFACT_DIR/images/"
rm -rf "$ARTIFACT_DIR/staging"

(cd "$ARTIFACT_DIR/images" && sha256sum *.bin) > "$ARTIFACT_DIR/images/SHA256SUMS"
cp "$LOCK" "$ARTIFACT_DIR/uboot-source-lock.json"

cat > "$ARTIFACT_DIR/FLASH-TARGETS.txt" <<'EOF'
These files are boot loader candidates built from the pinned source. They are
not system images, they were not tested on hardware and they are not flashed
by this build.

The addresses below are NMBM logical addresses of the 112M partition contract,
not physical NAND addresses.

BL2: MediaTek ATF BL2 preloader for SPI-NAND boot. Write target: the bl2
     partition at NMBM logical 0x000000, 1 MiB.
FIP: ATF FIP package that carries BL31 and BL33 (U-Boot). Write target: the
     fip partition at NMBM logical 0x380000, 2 MiB.

The system factory image of the selected system belongs into the ubi
partition at NMBM logical 0x580000 and is not part of this build. Do not
rename either boot loader image as a recovery image. The web failsafe entry
of the boot loader serves http://192.168.1.1/ and accepts the same two
images; it does not replace an independent recovery path or a backup of the
factory device.
EOF

printf 'Candidate images are in %s\n' "$ARTIFACT_DIR/images"
