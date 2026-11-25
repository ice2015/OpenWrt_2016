#!/bin/sh
# Build the NX30 Pro firmware candidate from the locked source.
#
# The script fetches the pinned source and the pinned feeds, prepares the
# configuration, builds the images and writes the build report. It never
# flashes anything and it never writes to a flash device.
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
DEVICE_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
REPO_ROOT=$(CDPATH= cd -- "$DEVICE_ROOT/../.." && pwd)
HELPER="$SCRIPT_DIR/firmware_lock.py"

LOCK="$DEVICE_ROOT/source-lock.json"
SOURCE_DIR=
ARTIFACT_DIR=
FEED_DIR=
JOBS=

usage() {
	printf 'Usage: %s --artifact-dir DIR [--source-dir DIR] [--feed-dir DIR] [--lock FILE] [--jobs N]\n' "$0"
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
		--feed-dir)
			[ "$#" -ge 2 ] || fail "--feed-dir requires a value"
			FEED_DIR=$2
			shift 2
			;;
		--artifact-dir)
			[ "$#" -ge 2 ] || fail "--artifact-dir requires a value"
			ARTIFACT_DIR=$2
			shift 2
			;;
		--jobs)
			[ "$#" -ge 2 ] || fail "--jobs requires a value"
			JOBS=$2
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

[ -n "$ARTIFACT_DIR" ] || fail "--artifact-dir is required"
[ -f "$LOCK" ] || fail "source lock not found: $LOCK"
command -v python3 >/dev/null 2>&1 || fail "python3 is required"
command -v git >/dev/null 2>&1 || fail "git is required"

mkdir -p "$ARTIFACT_DIR/logs" "$ARTIFACT_DIR/images"

LOCK=$(CDPATH= cd -- "$(dirname -- "$LOCK")" && pwd)/$(basename -- "$LOCK")
PLAN_FILE="$ARTIFACT_DIR/logs/build-plan.json"
python3 "$HELPER" check --lock "$LOCK" > "$PLAN_FILE" || fail "the source lock is not build ready"

lock_value() {
	python3 - "$LOCK" "$1" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    lock = json.load(handle)
value = lock
for key in sys.argv[2].split("."):
    value = value[key]
print(value)
PY
}

SOURCE_REPOSITORY=$(lock_value source.repository)
LOCK_REVISION=$(lock_value source.revision)
PROFILE=$(lock_value target.profile)
SUBTARGET=$(lock_value target.subtarget)
TARGET=$(lock_value target.target)
IMAGE_SIZE_KIB=$(lock_value image.image_size_kib)

# The caller may pin the revision as well. When it does, both records have to
# agree, so a stale workflow cannot build another input.
if [ -n "${SOURCE_REVISION:-}" ] && [ "$SOURCE_REVISION" != "$LOCK_REVISION" ]; then
	fail "the pinned revision $SOURCE_REVISION does not match the lock $LOCK_REVISION"
fi

if [ -z "$JOBS" ]; then
	# The runner has four cores and about seven gigabytes of memory. The Go
	# and container builds of this base need more memory than a plain build,
	# so the parallelism stays below the core count.
	JOBS=$(nproc 2>/dev/null || printf '2')
	[ "$JOBS" -gt 3 ] && JOBS=3
fi

# The source is prepared in a clean directory. A checkout that carries local
# changes or an earlier build is refused, so that a result can always be
# attributed to the pinned commit.
if [ -z "$SOURCE_DIR" ]; then
	SOURCE_DIR="$ARTIFACT_DIR/source"
fi
mkdir -p "$SOURCE_DIR"
if [ ! -d "$SOURCE_DIR/.git" ]; then
	printf 'Cloning the pinned source %s\n' "$LOCK_REVISION"
	git clone --filter=blob:none --no-checkout "$SOURCE_REPOSITORY" "$SOURCE_DIR" ||
		fail "the source could not be cloned"
fi
git -C "$SOURCE_DIR" checkout --detach "$LOCK_REVISION" ||
	fail "the pinned source revision could not be checked out"
ACTUAL_REVISION=$(git -C "$SOURCE_DIR" rev-parse HEAD)
[ "$ACTUAL_REVISION" = "$LOCK_REVISION" ] ||
	fail "the source checkout is at $ACTUAL_REVISION, the lock pins $LOCK_REVISION"
if [ -n "$(git -C "$SOURCE_DIR" status --porcelain)" ]; then
	fail "the source checkout carries local changes"
fi
if [ -d "$SOURCE_DIR/output" ] && [ -n "$(ls -A "$SOURCE_DIR/output" 2>/dev/null)" ]; then
	fail "the source directory holds output of an earlier build"
fi

# The feeds are pinned to their commits, so the build input does not drift
# with the moving branches.
if [ -z "$FEED_DIR" ]; then
	FEED_DIR="$ARTIFACT_DIR/feeds"
fi
mkdir -p "$FEED_DIR"
python3 - "$LOCK" "$FEED_DIR/feeds.conf" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    lock = json.load(handle)
with open(sys.argv[2], "w", encoding="utf-8") as handle:
    for feed in lock["feeds"]:
        handle.write(
            "src-git-full %s %s;%s\n" % (feed["id"], feed["repository"], feed["revision"])
        )
PY
cp "$FEED_DIR/feeds.conf" "$SOURCE_DIR/feeds.conf"

printf 'Building %s/%s/%s from %s\n' "$TARGET" "$SUBTARGET" "$PROFILE" "$LOCK_REVISION"

CONFIGURE_LOG="$ARTIFACT_DIR/logs/configure.log"
if ! sh "$SCRIPT_DIR/configure.sh" --source-dir "$SOURCE_DIR" --lock "$LOCK" \
	> "$CONFIGURE_LOG" 2>&1; then
	cat "$CONFIGURE_LOG" >&2
	fail "the configuration of the firmware failed"
fi
cat "$CONFIGURE_LOG"

BUILD_LOG="$ARTIFACT_DIR/logs/build.log"
if (
	cd "$SOURCE_DIR"
	make download -j "$JOBS"
	make -j "$JOBS"
) > "$BUILD_LOG" 2>&1; then
	tail -20 "$BUILD_LOG"
else
	tail -60 "$BUILD_LOG" >&2
	fail "the firmware build failed, the first stable error is in the build log"
fi

IMAGE_DIR="$SOURCE_DIR/bin/targets/$TARGET/$SUBTARGET"
[ -d "$IMAGE_DIR" ] || fail "the build produced no image directory"

FACTORY_IMAGE=$(find "$IMAGE_DIR" -maxdepth 1 -type f -name "$PROFILE-factory.bin" -size +0c)
SYSUPGRADE_IMAGE=$(find "$IMAGE_DIR" -maxdepth 1 -type f -name "$PROFILE-sysupgrade.bin" -size +0c)
[ "$(printf '%s\n' "$FACTORY_IMAGE" | grep -c . || :)" -eq 1 ] ||
	fail "expected exactly one non-empty factory image"
[ "$(printf '%s\n' "$SYSUPGRADE_IMAGE" | grep -c . || :)" -eq 1 ] ||
	fail "expected exactly one non-empty sysupgrade image"

# The factory image has to fit the 112 MiB UBI area. The limit of the image
# rules is the upper bound of the file.
FACTORY_SIZE_KIB=$(( ($(wc -c < "$FACTORY_IMAGE") + 1023) / 1024 ))
[ "$FACTORY_SIZE_KIB" -le "$IMAGE_SIZE_KIB" ] ||
	fail "the factory image is $FACTORY_SIZE_KIB KiB and does not fit the $IMAGE_SIZE_KIB KiB limit"

install -m 0644 "$FACTORY_IMAGE" "$ARTIFACT_DIR/images/"
install -m 0644 "$SYSUPGRADE_IMAGE" "$ARTIFACT_DIR/images/"
cp "$SOURCE_DIR/.config" "$ARTIFACT_DIR/logs/final.config"
cp "$SOURCE_DIR/feeds.lock" "$ARTIFACT_DIR/logs/feeds.lock" 2>/dev/null || true
if [ -f "$SOURCE_DIR/tmp/.packageinfo" ]; then
	grep -E '^(Package|Version):' "$SOURCE_DIR/tmp/.packageinfo" > "$ARTIFACT_DIR/logs/package-info.txt" || true
fi

BUILD_ENV_JSON=$(printf '{"profile":"%s","target":"%s","subtarget":"%s","jobs":"%s"}' \
	"$PROFILE" "$TARGET" "$SUBTARGET" "$JOBS")

python3 "$HELPER" report \
	--lock "$LOCK" \
	--out "$ARTIFACT_DIR/build-report.json" \
	--build-env "$BUILD_ENV_JSON" \
	--artifact "factory:$ARTIFACT_DIR/images/$PROFILE-factory.bin" \
	--artifact "sysupgrade:$ARTIFACT_DIR/images/$PROFILE-sysupgrade.bin" \
	--packages "$ARTIFACT_DIR/logs/package-info.txt" \
	--final-config "$ARTIFACT_DIR/logs/final.config" ||
	fail "the build report could not be written"

(cd "$ARTIFACT_DIR/images" && sha256sum *.bin) > "$ARTIFACT_DIR/images/SHA256SUMS"
cp "$LOCK" "$ARTIFACT_DIR/source-lock.json"

cat > "$ARTIFACT_DIR/IMAGE-ROLES.txt" <<EOF
factory image: $PROFILE-factory.bin, the UBI image that the boot loader
writes into the ubi partition. It is not a boot loader image.
sysupgrade image: $PROFILE-sysupgrade.bin, the archive that the LuCI upgrade
page or the sysupgrade command consumes. It is not a boot loader image.
The boot loader images are built by devices/nx30pro/build/build-uboot.sh and
are not part of this build.
The partition offsets of the boot loader contract are NMBM logical addresses.
EOF

printf 'Firmware candidates are in %s\n' "$ARTIFACT_DIR/images"
