#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
SOURCE_DIR=
UPSTREAM_DIR=
ARTIFACT_DIR=
JOBS=4

usage() {
	printf 'Usage: %s --source-dir DIR --upstream-dir DIR --artifact-dir DIR [--jobs N]\n' "$0"
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
		--upstream-dir)
			[ "$#" -ge 2 ] || fail "--upstream-dir requires a value"
			UPSTREAM_DIR=$2
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

[ -n "$SOURCE_DIR" ] || fail "--source-dir is required"
[ -n "$UPSTREAM_DIR" ] || fail "--upstream-dir is required"
[ -n "$ARTIFACT_DIR" ] || fail "--artifact-dir is required"
case "$JOBS" in
	''|*[!0-9]*|0) fail "--jobs must be a positive integer" ;;
esac
[ -f "$REPO_ROOT/feeds/devices/tr3000-lite.lock" ] || fail "feed lock file not found"
[ -f "$UPSTREAM_DIR/config/128muboot.config" ] || fail "pinned upstream 128muboot.config not found"
[ -f "$UPSTREAM_DIR/LICENSE" ] || fail "pinned upstream LICENSE not found"
[ -d "$SOURCE_DIR/scripts" ] || fail "not an OpenWrt source tree: $SOURCE_DIR"

mkdir -p "$ARTIFACT_DIR/logs" "$ARTIFACT_DIR/firmware"
cp "$UPSTREAM_DIR/LICENSE" "$ARTIFACT_DIR/UPSTREAM-LICENSE"
git -C "$UPSTREAM_DIR" show -s --format='%H%n%T%n%aI%n%s' > "$ARTIFACT_DIR/upstream-project-commit.txt"
git -C "$SOURCE_DIR" show -s --format='%H%n%T%n%aI%n%s' > "$ARTIFACT_DIR/source-commit.txt"
FEED_ROOT=${FEED_ROOT:-"$SOURCE_DIR/.feeds-pinned"}
DOWNLOAD_DIR=${DOWNLOAD_DIR:-"$SOURCE_DIR/dl"}
CCACHE_DIR=${CCACHE_DIR:-"$SOURCE_DIR/.ccache"}
mkdir -p "$FEED_ROOT" "$DOWNLOAD_DIR" "$CCACHE_DIR"

FEEDS_CONF="$SOURCE_DIR/feeds.conf"
: > "$FEEDS_CONF"
: > "$ARTIFACT_DIR/feeds.txt"
while read -r NAME REPOSITORY REVISION; do
	[ -n "$NAME" ] || continue
	case "$REVISION" in
		*[!0-9a-f]*|'') fail "invalid feed revision for $NAME" ;;
	esac
	[ "${#REVISION}" -eq 40 ] || fail "feed revision must be a full commit SHA: $NAME"
	FEED_DIR="$FEED_ROOT/$NAME"
	if [ -d "$FEED_DIR/.git" ]; then
		git -C "$FEED_DIR" fetch --no-tags "$REPOSITORY" "$REVISION"
	else
		git clone --filter=blob:none --no-checkout "$REPOSITORY" "$FEED_DIR"
	fi
	git -C "$FEED_DIR" checkout --detach "$REVISION"
	[ "$(git -C "$FEED_DIR" rev-parse HEAD)" = "$REVISION" ] ||
		fail "feed checkout mismatch: $NAME"
	printf 'src-link %s %s\n' "$NAME" "$FEED_DIR" >> "$FEEDS_CONF"
	printf '%s %s %s\n' "$NAME" "$REPOSITORY" "$REVISION" >> "$ARTIFACT_DIR/feeds.txt"
done < "$REPO_ROOT/feeds/devices/tr3000-lite.lock"

(
	cd "$SOURCE_DIR"
	./scripts/feeds update -a
	./scripts/feeds install -a
)
sh "$SCRIPT_DIR/configure-lite.sh" \
	--source-dir "$SOURCE_DIR" \
	--base-config "$UPSTREAM_DIR/config/128muboot.config" \
	--ccache-dir "$CCACHE_DIR"
cp "$SOURCE_DIR/.config" "$ARTIFACT_DIR/build.config"

if [ -n "${SOURCE_SHA:-}" ]; then
	SOURCE_DATE_EPOCH=$(git -C "$SOURCE_DIR" show -s --format=%ct "$SOURCE_SHA")
	export SOURCE_DATE_EPOCH
fi
export CCACHE_DIR DOWNLOAD_DIR

DOWNLOAD_OK=0
ATTEMPT=1
while [ "$ATTEMPT" -le 3 ]; do
	if (cd "$SOURCE_DIR" && make download -j"$JOBS" V=s) \
		> "$ARTIFACT_DIR/logs/download.log" 2>&1; then
		cat "$ARTIFACT_DIR/logs/download.log"
		DOWNLOAD_OK=1
		break
	fi
	cat "$ARTIFACT_DIR/logs/download.log" >&2
	if [ "$ATTEMPT" -lt 3 ]; then
		printf 'Download attempt %s failed; retrying.\n' "$ATTEMPT" >&2
		sleep $((ATTEMPT * 15))
	fi
	ATTEMPT=$((ATTEMPT + 1))
done
[ "$DOWNLOAD_OK" -eq 1 ] || fail "all source download attempts failed"

if (cd "$SOURCE_DIR" && make -j"$JOBS" V=s) \
	> "$ARTIFACT_DIR/logs/build.log" 2>&1; then
	cat "$ARTIFACT_DIR/logs/build.log"
else
	cat "$ARTIFACT_DIR/logs/build.log" >&2
	printf '%s\n' 'Parallel build failed; retrying serially.' >&2
	(cd "$SOURCE_DIR" && make -j1 V=s) \
		> "$ARTIFACT_DIR/logs/build-serial-retry.log" 2>&1 || {
			cat "$ARTIFACT_DIR/logs/build-serial-retry.log" >&2
			fail "serial build retry failed"
		}
	cat "$ARTIFACT_DIR/logs/build-serial-retry.log"
fi

TARGET_DIR="$SOURCE_DIR/bin/targets/mediatek/filogic"
[ -d "$TARGET_DIR" ] || fail "expected target output directory not found"
IMAGE_LIST=$(find "$TARGET_DIR" -maxdepth 1 -type f \
	-name '*cudy_tr3000-v1-ubootmod*sysupgrade.bin' -size +0c | sort)
[ -n "$IMAGE_LIST" ] || fail "no non-empty 112 MiB U-Boot Mod sysupgrade image found"
grep -Fq 'CONFIG_TARGET_mediatek_filogic_DEVICE_cudy_tr3000-v1-ubootmod=y' "$SOURCE_DIR/.config" ||
	fail "final config does not select the expected device profile"
grep -Fq 'reg = <0x5c0000 0x7000000>;' \
	"$SOURCE_DIR/target/linux/mediatek/dts/mt7981b-cudy-tr3000-v1-ubootmod.dts" ||
	fail "final DTS is not the expected 112 MiB UBI layout"

: > "$ARTIFACT_DIR/firmware/SHA256SUMS"
IMAGE_COUNT=0
while IFS= read -r IMAGE; do
	[ -n "$IMAGE" ] || continue
	file "$IMAGE"
	install -m 0644 "$IMAGE" "$ARTIFACT_DIR/firmware/"
	(
		cd "$ARTIFACT_DIR/firmware"
		sha256sum "$(basename "$IMAGE")"
	) >> "$ARTIFACT_DIR/firmware/SHA256SUMS"
	IMAGE_COUNT=$((IMAGE_COUNT + 1))
done <<EOF
$IMAGE_LIST
EOF
[ "$IMAGE_COUNT" -gt 0 ] || fail "no firmware image was packaged"
grep '^CONFIG_PACKAGE_.*=y$' "$SOURCE_DIR/.config" | sort > "$ARTIFACT_DIR/selected-packages.txt"
if [ -f "$TARGET_DIR/packages/Packages.manifest" ]; then
	grep '^Package: ' "$TARGET_DIR/packages/Packages.manifest" |
		sed 's/^Package: //' | sort -u > "$ARTIFACT_DIR/packages-manifest.txt"
fi
cat > "$ARTIFACT_DIR/README.txt" <<EOF
Build type: TR3000-Lite, 128 MiB NAND, U-Boot Mod, 112 MiB UBI layout
Device profile: cudy_tr3000-v1-ubootmod
Images in firmware/ are sysupgrade images, not universal factory/U-Boot flashing images.
Source SHA: ${SOURCE_SHA:-not-supplied}
Wrapper/config SHA: $(git -C "$UPSTREAM_DIR" rev-parse HEAD)
EOF
