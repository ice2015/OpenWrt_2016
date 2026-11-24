#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
DEVICE_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
REPO_ROOT=$(CDPATH= cd -- "$DEVICE_ROOT/../.." && pwd)
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
[ -f "$REPO_ROOT/devices/tr3000/lite/feeds.lock" ] || fail "feed lock file not found"
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
if command -v ccache >/dev/null 2>&1; then
	CCACHE_DIR="$CCACHE_DIR" ccache -M 5G >/dev/null 2>&1 || true
fi

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
done < "$REPO_ROOT/devices/tr3000/lite/feeds.lock"

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

# The shipped overlay must keep the operator access segment reachable: a
# factory device has to hand out an address, answer ping and serve LuCI.
ACCESS_NETWORK="$SOURCE_DIR/files/etc/config/network"
ACCESS_DHCP="$SOURCE_DIR/files/etc/config/dhcp"
[ -f "$ACCESS_NETWORK" ] || fail "Lite overlay is missing the access segment network configuration"
[ -f "$ACCESS_DHCP" ] || fail "Lite overlay is missing the access segment DHCP configuration"
for access_token in "config interface 'lan'" "option ipaddr '192.168.10.1'" \
	"config device 'br_lan'" "list ports 'eth1'"; do
	grep -Fq "$access_token" "$ACCESS_NETWORK" ||
		fail "Lite overlay access segment is incomplete: $access_token"
done
grep -Fq "config dhcp 'lan'" "$ACCESS_DHCP" ||
	fail "Lite overlay access segment has no DHCP configuration"
# The router's own resolver points at 127.0.0.1. Without a loopback interface
# dnsmasq cannot bind there, every name lookup of the device fails, NTP never
# synchronises the clock and TLS downloads break: the package manager dies.
grep -Fq "config interface 'loopback'" "$ACCESS_NETWORK" ||
	fail "Lite overlay has no loopback interface: the device cannot resolve names"
grep -Fq "option ipaddr '127.0.0.1'" "$ACCESS_NETWORK" ||
	fail "Lite overlay loopback interface has no loopback address"
[ ! -e "$REPO_ROOT/devices/tr3000/lite/files/etc/config/wireless" ] ||
	fail "Lite overlay must not ship a wireless configuration"

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

# The target repository index contains only target-specific packages, not the
# complete installed image. Use the profile manifest emitted by opkg list-installed.
IMAGE_MANIFESTS=$(find "$TARGET_DIR" -maxdepth 1 -type f \
	-name '*cudy_tr3000-v1-ubootmod.manifest' | sort)
[ "$(printf '%s\n' "$IMAGE_MANIFESTS" | awk 'NF { n++ } END { print n+0 }')" -eq 1 ] ||
	fail "expected exactly one image package manifest for cudy_tr3000-v1-ubootmod"
for package in luci-app-tr3000-lite wpad-openssl kmod-usb-net kmod-usb-net-rndis kmod-usb-net-cdc-ether; do
	awk -v package="$package" '$1 == package { found=1 } END { exit !found }' "$IMAGE_MANIFESTS" ||
		fail "image manifest is missing required package: $package"
done
if grep -Eq '^(ruby|libruby)([[:space:]]|$)' "$IMAGE_MANIFESTS"; then
	fail "image manifest contains excluded package ruby/libruby"
fi
IMAGE_USB_PACKAGES=$(awk '$1 ~ /^kmod-usb-net/ { print $1 }' "$IMAGE_MANIFESTS" | sort -u)
EXPECTED_USB_PACKAGES=$(printf '%s\n' kmod-usb-net kmod-usb-net-cdc-ether kmod-usb-net-rndis)
[ "$IMAGE_USB_PACKAGES" = "$EXPECTED_USB_PACKAGES" ] ||
	fail "image manifest contains an unexpected USB network package"
cp "$IMAGE_MANIFESTS" "$ARTIFACT_DIR/image-packages.manifest"
awk 'NF { print $1 }' "$IMAGE_MANIFESTS" | sort -u > "$ARTIFACT_DIR/packages-manifest.txt"
cp "$SOURCE_DIR/target/linux/mediatek/dts/mt7981b-cudy-tr3000-v1-ubootmod.dts" "$ARTIFACT_DIR/profile.dts"

# The public 24.10-SNAPSHOT feeds are a moving target: they are pruned by the
# mirrors and they no longer match the revisions this image was built from.
# Ship the repository this build produced together with its signing key so an
# operator can mirror it and install packages that match the pinned feeds.
PACKAGES_ARCH=$(sed -n 's/^CONFIG_TARGET_ARCH_PACKAGES="\(.*\)"$/\1/p' "$SOURCE_DIR/.config")
[ -n "$PACKAGES_ARCH" ] || fail "final config does not name the package architecture"
[ -f "$SOURCE_DIR/key-build.pub" ] || fail "build signing key not found: key-build.pub"
PACKAGE_REPO="$SOURCE_DIR/bin/packages/$PACKAGES_ARCH"
[ -d "$PACKAGE_REPO" ] || fail "build package repository not found: $PACKAGE_REPO"
for feed in base packages luci routing telephony; do
	[ -f "$PACKAGE_REPO/$feed/Packages.gz" ] ||
		fail "build package repository is missing the $feed feed index"
done
mkdir -p "$ARTIFACT_DIR/package-repo"
cp -R "$PACKAGE_REPO" "$ARTIFACT_DIR/package-repo/arch"
TARGET_PACKAGES="$SOURCE_DIR/bin/targets/mediatek/filogic/packages"
if [ -d "$TARGET_PACKAGES" ]; then
	cp -R "$TARGET_PACKAGES" "$ARTIFACT_DIR/package-repo/target"
fi
cp "$SOURCE_DIR/key-build.pub" "$ARTIFACT_DIR/key-build.pub"

: > "$ARTIFACT_DIR/firmware/SHA256SUMS"
IMAGE_COUNT=0
while IFS= read -r IMAGE; do
	[ -n "$IMAGE" ] || continue
	sh "$SCRIPT_DIR/verify-image.sh" --source-dir "$SOURCE_DIR" --image "$IMAGE"
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
grep -Fxq 'CONFIG_PACKAGE_luci-app-tr3000-lite=y' "$ARTIFACT_DIR/selected-packages.txt" ||
	fail "final selected packages do not include luci-app-tr3000-lite"
# Capture the same final config used for the package evidence above.
cp "$SOURCE_DIR/.config" "$ARTIFACT_DIR/build.config"
# Expected public defaults only: never read device wireless, shadow or private UCI.
# This describes the shipped policy; it does not assert a successful device boot.
cat > "$ARTIFACT_DIR/lite-runtime-contract.txt" <<'EOF'
schema_version=2
evidence_kind=expected-defaults-not-live-state
lan_interface=lan
lan_device=br-lan
lan_cidr=192.168.10.1/24
lan_dhcp_pool=192.168.10.100-192.168.10.249
plant_interface=plant
plant_device=eth1
plant_default_mode=inactive
plant_default_cidr=192.168.20.254/24
plant_dhcpv4_dhcpv6_ra_ndp=off
lan_to_plant_protocols=icmp-echo,tcp
lan_to_plant_snat=plant-address
lan_plant_bridged=0
luci_package=luci-app-tr3000-lite
allow_luci=0
allow_mgmt=1
allow_wireguard=0
plant_https_port=443
plant_https_gate=root-password-and-explicit-enable
wan_management=off
wireless_stack=mt_wifi
management_ap_network=lan
management_ap_encryption=psk2
management_ap_default_open_ap=disabled
uplink_order=wan,wwan,usbwan
uplink_metrics=10,20,30
uplink_interval_seconds=15
uplink_fail_rounds=3
uplink_recover_rounds=2
uplink_daemon=/usr/sbin/lite-uplink-watch
uplink_status=/usr/sbin/tr3000-lite-uplink-status
uplink_event_hook=/usr/lib/tr3000-lite/uplink-changed
usb_drivers=rndis_host,cdc_ether
usb_hotplug=/etc/hotplug.d/net/90-tr3000-lite-usbwan
usb_multiple_candidates=fail-closed
usb_periodic_rescan=on-daemon-round
wireless_client_config=standard-luci-only
allow_wireguard_direct=0
allow_wireguard_vps=0
remote_controller=/usr/sbin/tr3000-lite-remote
ddns_status=/usr/sbin/tr3000-lite-ddns-status
enroll_script=/usr/sbin/tr3000-lite-enroll
remote_schema_version=1
ddns_schema_version=1
enroll_schema_version=1
EOF
if find "$ARTIFACT_DIR" -type f \( -name '*.bundle' -o -name '*.key' -o -name '*token*' -o -name '*inventory*' \) | grep -q .; then
	fail "forbidden secret or staging file entered the Artifact directory"
fi
if [ -f "$TARGET_DIR/packages/Packages.manifest" ]; then
	grep '^Package: ' "$TARGET_DIR/packages/Packages.manifest" |
		sed 's/^Package: //' | sort -u > "$ARTIFACT_DIR/target-package-index.txt"
fi
cat > "$ARTIFACT_DIR/README.txt" <<EOF
Build type: TR3000-Lite, 128 MiB NAND, U-Boot Mod, 112 MiB UBI layout
Device profile: cudy_tr3000-v1-ubootmod
Images in firmware/ are sysupgrade images, not universal factory/U-Boot flashing images.
lite-runtime-contract.txt records public expected defaults, not live hardware verification.
image-packages.manifest is the complete profile image package/version list; packages-manifest.txt is its name-only view.
target-package-index.txt, if present, is only the target-specific package repository index.
package-repo/arch/<feed> and package-repo/target hold this build's own opkg repository; key-build.pub is its signing key.
profile.dts is the final verified 112 MiB profile source; actual writable overlay capacity still requires hardware checks.
Source SHA: ${SOURCE_SHA:-not-supplied}
Wrapper/config SHA: $(git -C "$UPSTREAM_DIR" rev-parse HEAD)
EOF
