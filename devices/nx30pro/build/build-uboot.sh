#!/bin/sh
# Build the NX30 Pro restricted-recovery boot loader candidate from the locked
# source.
#
# This script only builds images; it performs no flash operation and never
# writes to a flash device. The produced images stay in the artifact directory
# and are marked as candidates until they are tested on hardware.
#
# Every gate runs before the upstream build is invoked, and every gate writes
# its own evidence into <artifact-dir>/logs so that a rejected build can be
# diagnosed from the uploaded diagnostics alone.
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
HELPER="$SCRIPT_DIR/uboot_lock.py"
REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/../../.." && pwd)

LOCK=
SOURCE_DIR=
ARTIFACT_DIR=
CHECK_ONLY=

usage() {
	cat <<EOF
Usage: $0 --lock FILE --source-dir DIR --artifact-dir DIR [--check-only] [--repo-root DIR]

  --lock FILE         device source lock to build from
  --source-dir DIR    upstream checkout at the locked commit
  --artifact-dir DIR  directory that receives images, logs and the report
  --check-only        validate the lock and print the resolved build plan
  --repo-root DIR     repository root the recorded device patches live in
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
		--repo-root)
			[ "$#" -ge 2 ] || fail "--repo-root requires a value"
			REPO_ROOT=$2
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
command -v git >/dev/null 2>&1 || fail "git is required"

if [ "$CHECK_ONLY" = "1" ]; then
	python3 "$HELPER" check --lock "$LOCK"
	exit 0
fi

[ -n "$SOURCE_DIR" ] || fail "--source-dir is required"
[ -n "$ARTIFACT_DIR" ] || fail "--artifact-dir is required"
[ -d "$SOURCE_DIR" ] || fail "source directory not found: $SOURCE_DIR"

mkdir -p "$ARTIFACT_DIR/logs"
LOGS="$ARTIFACT_DIR/logs"

PLAN_FILE="$LOGS/build-plan.json"
python3 "$HELPER" check --lock "$LOCK" > "$PLAN_FILE" ||
	fail "the source lock is not build ready"

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

UBOOT_TREE=$(plan_value uboot_tree)
BOARD_DTS=$(plan_value board.dts)
PATCH_PATH=$(python3 - "$LOCK" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    lock = json.load(handle)
patches = lock["source"]["patches"]
print(patches[0]["path"] if patches else "")
PY
)

# Gate 1: the checkout is the pinned commit, carries the trees the pinned build
# script really builds, the board files of the locked layout whitelist, and no
# output of an earlier run.
python3 "$HELPER" preflight --lock "$LOCK" --source-dir "$SOURCE_DIR" \
	--repo-root "$REPO_ROOT" > "$LOGS/preflight.json" ||
	fail "the preflight checks failed, the build was not started"

# Gate 2: the layout whitelist really exists in the pinned device tree.
python3 "$HELPER" verify-layout-source --lock "$LOCK" \
	--dts "$SOURCE_DIR/$UBOOT_TREE/$BOARD_DTS" > "$LOGS/layout-source.json" ||
	fail "the pinned device tree does not carry the locked layout whitelist"

# Gate 3: the device patch satisfies the recovery contract and applies to the
# pinned tree, then it is applied.
[ -n "$PATCH_PATH" ] || fail "the lock records no device patch"
python3 "$HELPER" verify-patch --lock "$LOCK" \
	--patch "$REPO_ROOT/$PATCH_PATH" --source-dir "$SOURCE_DIR" \
	> "$LOGS/device-patch-verify.json" ||
	fail "the device patch does not satisfy the recovery contract"

python3 "$HELPER" patch --lock "$LOCK" --source-dir "$SOURCE_DIR" \
	--repo-root "$REPO_ROOT" > "$LOGS/device-patch.json" ||
	fail "the device patch could not be applied"

# Gate 4: the cross compiler exists. The upstream build script reports success
# for a missing compiler in some paths, so this is checked before it runs.
python3 "$HELPER" toolchain --out "$LOGS/toolchain.json" ||
	fail "the toolchain identity could not be recorded"

printf 'Pinned source: %s at %s\n' "$(plan_value source_repository)" \
	"$(plan_value source_commit)"
printf 'Build target: %s %s (%s)\n' "$(plan_value build_env.SOC)" \
	"$(plan_value build_env.BOARD)" "$(plan_value version)"

# The build parameters come from the lock, never from the environment of the
# caller, so a workflow cannot silently build another variant.
python3 - "$PLAN_FILE" > "$LOGS/build-env.sh" <<'PY'
import json
import shlex
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    plan = json.load(handle)
for key, value in sorted((plan.get("build_env") or {}).items()):
    print("export %s=%s" % (key, shlex.quote(str(value))))
PY
# shellcheck disable=SC1091
. "$LOGS/build-env.sh"

BUILD_LOG="$LOGS/build.log"
if ( cd "$SOURCE_DIR" && ./build.sh ) > "$BUILD_LOG" 2>&1; then
	cat "$BUILD_LOG"
else
	cat "$BUILD_LOG" >&2
	fail "the pinned boot loader build failed"
fi

# Gate 5: the configuration that was really compiled carries the locked feature
# set. A patch that landed in a tree the build does not use is caught here.
python3 "$HELPER" verify-config --lock "$LOCK" \
	--config "$SOURCE_DIR/$UBOOT_TREE/.config" > "$LOGS/effective-config.json" ||
	fail "the compiled configuration does not carry the locked recovery feature set"

# Gate 6: resolve and inspect the produced images before anything is published.
OUTPUT_DIR="$SOURCE_DIR/output"
python3 "$HELPER" artifacts --lock "$LOCK" --output-dir "$OUTPUT_DIR" \
	> "$LOGS/artifacts.json" ||
	fail "the build did not produce the locked boot loader images"

BUILD_ENV_JSON=$(cat "$LOGS/build-env.sh" | python3 -c '
import json
import shlex
import sys

env = {}
for line in sys.stdin.read().splitlines():
    if not line.startswith("export "):
        continue
    key, _, value = line[len("export "):].partition("=")
    env[key] = shlex.split(value)[0]
print(json.dumps(env, sort_keys=True))
')

python3 "$HELPER" publish --lock "$LOCK" --artifact-dir "$ARTIFACT_DIR" \
	--output-dir "$OUTPUT_DIR" --toolchain-file "$LOGS/toolchain.json" \
	--build-env "$BUILD_ENV_JSON" ||
	fail "the candidate images could not be published"

printf 'Candidate images are in %s\n' "$ARTIFACT_DIR/images"
