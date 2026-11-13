#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
SOURCE_DIR=
BASE_CONFIG=
CCACHE_DIR_OVERRIDE=
SEED="$REPO_ROOT/configs/full.seed"
INCLUDE_TAILSCALE=true
INCLUDE_SINGBOX=true
INCLUDE_CLOUDFLARED=false

usage() {
	printf 'Usage: %s --source-dir DIR --base-config FILE [--seed FILE] [--ccache-dir DIR] [--include-tailscale true|false] [--include-singbox true|false] [--include-cloudflared true|false]\n' "$0"
}

fail() {
	printf 'Error: %s\n' "$*" >&2
	exit 1
}

usage_fail() {
	printf 'Error: %s\n' "$*" >&2
	exit 2
}

valid_boolean() {
	[ "$1" = true ] || [ "$1" = false ]
}

while [ "$#" -gt 0 ]; do
	case "$1" in
		--source-dir)
			[ "$#" -ge 2 ] || usage_fail "--source-dir requires a value"
			SOURCE_DIR=$2
			shift 2
			;;
		--base-config)
			[ "$#" -ge 2 ] || usage_fail "--base-config requires a value"
			BASE_CONFIG=$2
			shift 2
			;;
		--seed)
			[ "$#" -ge 2 ] || usage_fail "--seed requires a value"
			SEED=$2
			shift 2
			;;
		--ccache-dir)
			[ "$#" -ge 2 ] || usage_fail "--ccache-dir requires a value"
			CCACHE_DIR_OVERRIDE=$2
			shift 2
			;;
		--include-tailscale)
			[ "$#" -ge 2 ] || usage_fail "--include-tailscale requires a value"
			INCLUDE_TAILSCALE=$2
			shift 2
			;;
		--include-singbox)
			[ "$#" -ge 2 ] || usage_fail "--include-singbox requires a value"
			INCLUDE_SINGBOX=$2
			shift 2
			;;
		--include-cloudflared)
			[ "$#" -ge 2 ] || usage_fail "--include-cloudflared requires a value"
			INCLUDE_CLOUDFLARED=$2
			shift 2
			;;
		--help)
			usage
			exit 0
			;;
		*) usage_fail "unknown argument: $1" ;;
	esac
done

for VALUE in "$INCLUDE_TAILSCALE" "$INCLUDE_SINGBOX" "$INCLUDE_CLOUDFLARED"; do
	valid_boolean "$VALUE" || usage_fail "include switches must be true or false"
done
[ -n "$SOURCE_DIR" ] || usage_fail "--source-dir is required"
[ -n "$BASE_CONFIG" ] || usage_fail "--base-config is required"
[ -d "$SOURCE_DIR/scripts" ] || fail "not an OpenWrt source tree: $SOURCE_DIR"
[ -f "$BASE_CONFIG" ] || fail "base config not found: $BASE_CONFIG"
[ -f "$SEED" ] || fail "Full seed not found: $SEED"
case "$CCACHE_DIR_OVERRIDE" in
	'') ;;
	/*) ;;
	*) usage_fail "--ccache-dir must be an absolute Unix path" ;;
esac
case "$CCACHE_DIR_OVERRIDE" in
	*\"*) usage_fail "--ccache-dir must not contain a double quote" ;;
esac

SOURCE_DIR=$(CDPATH= cd -- "$SOURCE_DIR" && pwd)
BASE_CONFIG=$(CDPATH= cd -- "$(dirname -- "$BASE_CONFIG")" && pwd)/$(basename -- "$BASE_CONFIG")
SEED=$(CDPATH= cd -- "$(dirname -- "$SEED")" && pwd)/$(basename -- "$SEED")
DTS="$SOURCE_DIR/target/linux/mediatek/dts/mt7981b-cudy-tr3000-v1-ubootmod.dts"
[ -f "$DTS" ] || fail "expected U-Boot Mod DTS not found: $DTS"
grep -Fq 'CONFIG_TARGET_mediatek_filogic_DEVICE_cudy_tr3000-v1-ubootmod=y' "$BASE_CONFIG" ||
	fail "base config does not select cudy_tr3000-v1-ubootmod"
[ "$(grep -c '^CONFIG_TARGET_mediatek_filogic_DEVICE_.*=y$' "$BASE_CONFIG")" -eq 1 ] ||
	fail "base configuration must select exactly one mediatek filogic device profile"
grep -Fq 'reg = <0x5c0000 0x7000000>;' "$DTS" ||
	fail "upstream DTS is not the verified 112 MiB UBI layout"
if grep -Fq 'reg = <0x5c0000 0x7a40000>;' "$DTS"; then
	fail "refusing the 122 MiB DTS layout; expected 112 MiB"
fi

LOCAL_LUCI_PACKAGE="$REPO_ROOT/packages/luci-app-tr3000-full"
[ -f "$LOCAL_LUCI_PACKAGE/Makefile" ] || fail "local Full LuCI package is missing"
mkdir -p "$SOURCE_DIR/package/luci-app-tr3000-full"
cp -R "$LOCAL_LUCI_PACKAGE/." "$SOURCE_DIR/package/luci-app-tr3000-full/"
mkdir -p "$SOURCE_DIR/files"
cp -R "$REPO_ROOT/files/." "$SOURCE_DIR/files/"
mkdir -p "$SOURCE_DIR/files/root/scripts" "$SOURCE_DIR/files/usr/sbin"
for SCRIPT in plant-profile.sh plant-access.sh preflight.sh lite-common.sh singbox-rollback.sh; do
	install -m 0755 "$SCRIPT_DIR/$SCRIPT" "$SOURCE_DIR/files/root/scripts/$SCRIPT"
done
install -m 0755 "$SCRIPT_DIR/service-toggle.sh" "$SOURCE_DIR/files/usr/sbin/tr3000-full-service"
install -m 0755 "$SCRIPT_DIR/lite-uplink-watch.sh" "$SOURCE_DIR/files/usr/sbin/lite-uplink-watch"
install -m 0644 "$SCRIPT_DIR/lite-common.sh" "$SOURCE_DIR/files/usr/sbin/lite-common.sh"
install -m 0755 "$REPO_ROOT/files/etc/init.d/lite-uplink-watch" \
	"$SOURCE_DIR/files/etc/init.d/lite-uplink-watch"
install -m 0755 "$REPO_ROOT/files/etc/uci-defaults/90-lite-uplink-watch" \
	"$SOURCE_DIR/files/etc/uci-defaults/90-lite-uplink-watch"
install -m 0755 "$REPO_ROOT/files/etc/uci-defaults/95-tr3000-full-services" \
	"$SOURCE_DIR/files/etc/uci-defaults/95-tr3000-full-services"

DYNAMIC_SEED=$(mktemp "$SOURCE_DIR/.config.full-options.XXXXXX")
TEMP_CONFIG=$(mktemp "$SOURCE_DIR/.config.full.XXXXXX")
trap 'rm -f "$DYNAMIC_SEED" "$TEMP_CONFIG"' EXIT HUP INT TERM
cp "$SEED" "$DYNAMIC_SEED"
for ENTRY in \
	"tailscale:$INCLUDE_TAILSCALE" \
	"sing-box:$INCLUDE_SINGBOX" \
	"cloudflared:$INCLUDE_CLOUDFLARED"
do
	PACKAGE=${ENTRY%%:*}
	VALUE=${ENTRY#*:}
	if [ "$VALUE" = true ]; then
		printf 'CONFIG_PACKAGE_%s=y\n' "$PACKAGE" >> "$DYNAMIC_SEED"
	else
		printf '# CONFIG_PACKAGE_%s is not set\n' "$PACKAGE" >> "$DYNAMIC_SEED"
	fi
done

awk -v ccache_dir="$CCACHE_DIR_OVERRIDE" '
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
		line = $0
		symbol = key(line)
		if (ccache_dir != "" && symbol == "CONFIG_CCACHE_DIR")
			next
		if (symbol != "") {
			if (!(symbol in seen)) {
				order[++count] = symbol
				seen[symbol] = 1
			}
			replacement[symbol] = line
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
' "$DYNAMIC_SEED" "$BASE_CONFIG" > "$TEMP_CONFIG"

cp "$TEMP_CONFIG" "$SOURCE_DIR/.config"
(
	cd "$SOURCE_DIR"
	make defconfig
)

grep -Fq 'CONFIG_TARGET_mediatek_filogic_DEVICE_cudy_tr3000-v1-ubootmod=y' "$SOURCE_DIR/.config" ||
	fail "make defconfig changed the selected device profile"
[ "$(grep -c '^CONFIG_TARGET_mediatek_filogic_DEVICE_.*=y$' "$SOURCE_DIR/.config")" -eq 1 ] ||
	fail "configuration must select exactly one mediatek filogic device profile"
for PACKAGE in \
	ca-bundle curl ip-full iputils-arping kmod-tun kmod-usb-net \
	kmod-usb-net-cdc-ether kmod-usb-net-rndis kmod-wireguard luci \
	luci-app-tr3000-full luci-i18n-base-zh-cn luci-proto-wireguard \
	luci-ssl-openssl luci-theme-bootstrap openssh-server openssh-sftp-server \
	tcpdump-mini ubi-utils wireguard-tools
do
	grep -Fq "CONFIG_PACKAGE_$PACKAGE=y" "$SOURCE_DIR/.config" ||
		fail "required Full package was not selected: $PACKAGE"
done
for ENTRY in \
	"tailscale:$INCLUDE_TAILSCALE" \
	"sing-box:$INCLUDE_SINGBOX" \
	"cloudflared:$INCLUDE_CLOUDFLARED"
do
	PACKAGE=${ENTRY%%:*}
	VALUE=${ENTRY#*:}
	if [ "$VALUE" = true ]; then
		grep -Fq "CONFIG_PACKAGE_$PACKAGE=y" "$SOURCE_DIR/.config" ||
			fail "requested Full package was not selected: $PACKAGE"
	elif grep -Fq "CONFIG_PACKAGE_$PACKAGE=y" "$SOURCE_DIR/.config"; then
		fail "disabled Full package remained selected: $PACKAGE"
	fi
done
for PACKAGE in \
	adguardhome docker dockerd luci-app-aurora-config luci-app-bandix \
	luci-app-dockerman luci-app-openclash luci-app-passwall luci-app-upnp \
	luci-theme-aurora miniupnpd dropbear
do
	if grep -Fq "CONFIG_PACKAGE_$PACKAGE=y" "$SOURCE_DIR/.config"; then
		fail "excluded package remained selected after defconfig: $PACKAGE"
	fi
done

printf 'Full configuration validated for the 112 MiB U-Boot Mod profile.\n'
