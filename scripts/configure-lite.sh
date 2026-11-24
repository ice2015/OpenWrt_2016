#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
SOURCE_DIR=
BASE_CONFIG=
CCACHE_DIR_OVERRIDE=
SEED="$REPO_ROOT/configs/lite.seed"
LITE_OVERLAY="$REPO_ROOT/overlays/devices/tr3000-lite/files"
LOCAL_LUCI_PACKAGE="$REPO_ROOT/packages/luci-app-tr3000-lite"

usage() {
	printf 'Usage: %s --source-dir DIR --base-config FILE [--seed FILE] [--ccache-dir DIR]\n' "$0"
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
		--base-config)
			[ "$#" -ge 2 ] || fail "--base-config requires a value"
			BASE_CONFIG=$2
			shift 2
			;;
		--seed)
			[ "$#" -ge 2 ] || fail "--seed requires a value"
			SEED=$2
			shift 2
			;;
		--ccache-dir)
			[ "$#" -ge 2 ] || fail "--ccache-dir requires a value"
			CCACHE_DIR_OVERRIDE=$2
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
[ -n "$BASE_CONFIG" ] || fail "--base-config is required"
[ -d "$SOURCE_DIR/scripts" ] || fail "not an OpenWrt source tree: $SOURCE_DIR"
[ -f "$BASE_CONFIG" ] || fail "base config not found: $BASE_CONFIG"
[ -f "$SEED" ] || fail "Lite seed not found: $SEED"
[ -d "$LITE_OVERLAY" ] || fail "Lite overlay not found: $LITE_OVERLAY"
[ -f "$LOCAL_LUCI_PACKAGE/Makefile" ] || fail "Lite LuCI package not found: $LOCAL_LUCI_PACKAGE"
case "$CCACHE_DIR_OVERRIDE" in
	'') ;;
	/*) ;;
	*) fail "--ccache-dir must be an absolute Unix path" ;;
esac
case "$CCACHE_DIR_OVERRIDE" in
	*\"*) fail "--ccache-dir must not contain a double quote" ;;
esac

SOURCE_DIR=$(CDPATH= cd -- "$SOURCE_DIR" && pwd)
BASE_CONFIG=$(CDPATH= cd -- "$(dirname -- "$BASE_CONFIG")" && pwd)/$(basename -- "$BASE_CONFIG")
SEED=$(CDPATH= cd -- "$(dirname -- "$SEED")" && pwd)/$(basename -- "$SEED")
DTS="$SOURCE_DIR/target/linux/mediatek/dts/mt7981b-cudy-tr3000-v1-ubootmod.dts"
[ -f "$DTS" ] || fail "expected U-Boot Mod DTS not found: $DTS"
grep -Fq 'CONFIG_TARGET_mediatek_filogic_DEVICE_cudy_tr3000-v1-ubootmod=y' "$BASE_CONFIG" ||
	fail "base config does not select cudy_tr3000-v1-ubootmod"
grep -Fq 'reg = <0x5c0000 0x7000000>;' "$DTS" ||
	fail "upstream DTS is not the verified 112 MiB UBI layout"
if grep -Fq 'reg = <0x5c0000 0x7a40000>;' "$DTS"; then
	fail "refusing the 122 MiB DTS layout"
fi

TEMP_CONFIG=$(mktemp "$SOURCE_DIR/.config.lite.XXXXXX")
trap 'rm -f "$TEMP_CONFIG"' EXIT HUP INT TERM
awk -v ccache_dir="$CCACHE_DIR_OVERRIDE" '
	function key(line, value) {
		if (line ~ /^# CONFIG_[A-Za-z0-9_-]+ is not set$/) {
			sub(/^# /, "", line)
			sub(/ is not set$/, "", line)
			return line
		}
		if (line ~ /^CONFIG_[A-Za-z0-9_-]+=*/) {
			sub(/=.*/, "", line)
			return line
		}
		return ""
	}
	FNR == NR {
		line = $0
		symbol = key(line)
		if (ccache_dir != "" && symbol == "CONFIG_CCACHE_DIR")
			next
		if (symbol != "") {
			replacement[symbol] = line
			order[++count] = symbol
		}
		next
	}
	{
		symbol = key($0)
		if (ccache_dir != "" && symbol == "CONFIG_CCACHE_DIR")
			next
		if (symbol == "" || !(symbol in replacement))
			print
	}
	END {
		for (i = 1; i <= count; i++)
			print replacement[order[i]]
		if (ccache_dir != "")
			print "CONFIG_CCACHE_DIR=\"" ccache_dir "\""
	}
' "$SEED" "$BASE_CONFIG" > "$TEMP_CONFIG"

mkdir -p "$SOURCE_DIR/package/luci-app-tr3000-lite"
cp -R "$LOCAL_LUCI_PACKAGE/." "$SOURCE_DIR/package/luci-app-tr3000-lite/"
cp "$TEMP_CONFIG" "$SOURCE_DIR/.config"
(
	cd "$SOURCE_DIR"
	make defconfig
)

grep -Fq 'CONFIG_TARGET_mediatek_filogic_DEVICE_cudy_tr3000-v1-ubootmod=y' "$SOURCE_DIR/.config" ||
	fail "make defconfig changed the selected device profile"
[ "$(grep -c '^CONFIG_TARGET_mediatek_filogic_DEVICE_.*=y$' "$SOURCE_DIR/.config")" -eq 1 ] ||
	fail "configuration must select exactly one mediatek filogic device profile"
for package in \
	ca-bundle coreutils-stat curl ddns-scripts ddns-scripts-cloudflare ip-full iputils-arping kmod-usb-net kmod-usb-net-cdc-ether \
	kmod-usb-net-rndis kmod-wireguard luci luci-app-ddns luci-app-tr3000-lite \
	luci-i18n-base-zh-cn luci-proto-wireguard luci-ssl-openssl \
	openssh-server openssh-sftp-server tcpdump-mini ubi-utils wireguard-tools wpad-openssl
do
	grep -Fq "CONFIG_PACKAGE_$package=y" "$SOURCE_DIR/.config" ||
		fail "required Lite package was not selected: $package"
done
grep -Fq 'CONFIG_BUSYBOX_CUSTOM=y' "$SOURCE_DIR/.config" ||
	fail "required Lite busybox configuration missing: CONFIG_BUSYBOX_CUSTOM"
grep -Fq 'CONFIG_BUSYBOX_CONFIG_TIMEOUT=y' "$SOURCE_DIR/.config" ||
	fail "required Lite busybox configuration missing: CONFIG_BUSYBOX_CONFIG_TIMEOUT"
if grep -E '^CONFIG_PACKAGE_wpad-[^=]+=[ym]$' "$SOURCE_DIR/.config" | grep -Fvx 'CONFIG_PACKAGE_wpad-openssl=y' >/dev/null; then
	fail "conflicting wpad provider selected after defconfig"
fi
for package in \
	adguardhome cloudflared docker dockerd kmod-usb-net-ipheth \
	luci-app-aurora-config luci-app-bandix luci-app-dockerman \
	luci-app-openclash luci-app-passwall luci-app-upnp \
	luci-app-mwan3 luci-theme-aurora miniupnpd mwan3 sing-box tailscale dropbear \
	ruby libruby tcpdump
do
	if grep -Fq "CONFIG_PACKAGE_$package=y" "$SOURCE_DIR/.config"; then
		fail "excluded package remained selected after defconfig: $package"
	fi
done

mkdir -p "$SOURCE_DIR/files"
cp -R "$REPO_ROOT/files/." "$SOURCE_DIR/files/"
mkdir -p "$SOURCE_DIR/files/root/scripts"
# Only the read-only preflight helper belongs on the Lite image. plant-profile.sh
# and plant-access.sh are the Full-era single-tunnel helpers: they bypass the
# paired network/firewall transaction, the backup/rollback and the management AP
# gate, and their example address now sits inside the Lite access segment.
for script in preflight.sh; do
	install -m 0755 "$SCRIPT_DIR/$script" "$SOURCE_DIR/files/root/scripts/$script"
done
mkdir -p "$SOURCE_DIR/files/usr/sbin" "$SOURCE_DIR/files/etc/init.d" "$SOURCE_DIR/files/etc/uci-defaults"
install -m 0755 "$SCRIPT_DIR/tr3000-lite-uplink-watch.sh" \
	"$SOURCE_DIR/files/root/scripts/lite-uplink-watch.sh"
install -m 0755 "$SCRIPT_DIR/tr3000-lite-uplink-watch.sh" \
	"$SOURCE_DIR/files/usr/sbin/lite-uplink-watch"
install -m 0644 "$SCRIPT_DIR/lite-common.sh" \
	"$SOURCE_DIR/files/usr/sbin/lite-common.sh"
mkdir -p "$SOURCE_DIR/files/usr/lib/tr3000-lite"
install -m 0755 "$SCRIPT_DIR/tr3000-lite-plant.sh" \
	"$SOURCE_DIR/files/usr/sbin/tr3000-lite-plant"
install -m 0644 "$SCRIPT_DIR/tr3000-lite-plant-lib.sh" \
	"$SOURCE_DIR/files/usr/lib/tr3000-lite/plant-lib.sh"
install -m 0644 "$SCRIPT_DIR/tr3000-lite-usbwan-lib.sh" \
	"$SOURCE_DIR/files/usr/lib/tr3000-lite/usbwan-lib.sh"
install -m 0644 "$SCRIPT_DIR/tr3000-lite-uplink-lib.sh" \
	"$SOURCE_DIR/files/usr/lib/tr3000-lite/uplink-lib.sh"
install -m 0755 "$SCRIPT_DIR/tr3000-lite-uplink-changed.sh" \
	"$SOURCE_DIR/files/usr/lib/tr3000-lite/uplink-changed"
install -m 0755 "$SCRIPT_DIR/tr3000-lite-uplink-status.sh" \
	"$SOURCE_DIR/files/usr/sbin/tr3000-lite-uplink-status"
install -m 0755 "$SCRIPT_DIR/tr3000-lite-remote.sh" \
	"$SOURCE_DIR/files/usr/sbin/tr3000-lite-remote"
install -m 0644 "$SCRIPT_DIR/tr3000-lite-remote-lib.sh" \
	"$SOURCE_DIR/files/usr/lib/tr3000-lite/remote-lib.sh"
install -m 0755 "$SCRIPT_DIR/tr3000-lite-remote-boot-close.sh" \
	"$SOURCE_DIR/files/usr/lib/tr3000-lite/remote-boot-close"
install -m 0755 "$SCRIPT_DIR/tr3000-lite-ddns-status.sh" \
	"$SOURCE_DIR/files/usr/sbin/tr3000-lite-ddns-status"
install -m 0644 "$SCRIPT_DIR/tr3000-lite-ddns-lib.sh" \
	"$SOURCE_DIR/files/usr/lib/tr3000-lite/ddns-lib.sh"
# The self-healing controller repairs the radio on every later boot; it runs
# the same first-boot implementation from a permanent path.
install -m 0755 "$SCRIPT_DIR/tr3000-lite-wifi.sh" \
	"$SOURCE_DIR/files/usr/sbin/tr3000-lite-wifi"
install -m 0755 "$LITE_OVERLAY/etc/init.d/tr3000-lite-wifi" \
	"$SOURCE_DIR/files/etc/init.d/tr3000-lite-wifi"
install -m 0755 "$LITE_OVERLAY/etc/uci-defaults/91-tr3000-lite-management-ap" \
	"$SOURCE_DIR/files/usr/sbin/tr3000-lite-wifi-ap"
install -m 0755 "$SCRIPT_DIR/tr3000-lite-ddns-event.sh" \
	"$SOURCE_DIR/files/usr/lib/tr3000-lite/ddns-event"
install -m 0755 "$SCRIPT_DIR/tr3000-lite-enroll.sh" \
	"$SOURCE_DIR/files/usr/sbin/tr3000-lite-enroll"
install -m 0755 "$REPO_ROOT/files/etc/init.d/lite-uplink-watch" \
	"$SOURCE_DIR/files/etc/init.d/lite-uplink-watch"
install -m 0755 "$REPO_ROOT/files/etc/uci-defaults/90-lite-uplink-watch" \
	"$SOURCE_DIR/files/etc/uci-defaults/90-lite-uplink-watch"
# Device/variant overrides deliberately win over the shared rootfs and assets.
cp -R "$LITE_OVERLAY/." "$SOURCE_DIR/files/"
# The Full variant's first-boot service defaults do not apply to the Lite
# image: tr3000-full-service is not installed there, so every call is a no-op.
rm -f "$SOURCE_DIR/files/etc/uci-defaults/95-tr3000-full-services"
# The deprecated Full-era helpers must not reach the Lite image.
for legacy in plant-profile.sh plant-access.sh; do
	[ ! -e "$SOURCE_DIR/files/root/scripts/$legacy" ] ||
		fail "deprecated Full-era helper reached the Lite image: $legacy"
done
[ ! -e "$SOURCE_DIR/files/etc/uci-defaults/95-tr3000-full-services" ] ||
	fail "Full variant first-boot defaults reached the Lite image"
[ -f "$SOURCE_DIR/files/etc/ssh/sshd_config.d/99-tr3000-lite.conf" ] ||
	fail "Lite SSH drop-in is missing: openssh-server denies root password login by default"
printf 'Lite configuration validated for the 112 MiB U-Boot Mod profile.\n'
