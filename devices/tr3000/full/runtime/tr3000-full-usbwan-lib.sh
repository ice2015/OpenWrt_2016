#!/bin/sh
# Sourced, read-only sysfs classifier. No fixed USB netdev or vendor assumptions.
tr3000_full_usbwan_name_valid() {
	case "$1" in ''|[-.]*|*[!A-Za-z0-9_.-]*) return 1 ;; esac
	[ "${#1}" -le 15 ]
}

# TSV: supported driver, USB VID, USB PID, stable device path relative to sysfs.
# Subshell keeps discovery variables out of callers and hotplug state.
tr3000_full_usbwan_classify() (
	[ "$#" -eq 2 ] || return 1
	tr3000_full_usbwan_name_valid "$1" || return 1
	sys=$(readlink -f "$2") || return 1
	[ -d "$sys/devices" ] || return 1
	device=$(readlink -f "$sys/class/net/$1/device") || return 1
	case "$device" in "$sys"/devices/*) ;; *) return 1 ;; esac
	[ -d "$device" ] || return 1
	driver=$(readlink -f "$device/driver") || return 1
	case "$driver" in
		"$sys"/bus/usb/drivers/rndis_host) driver=rndis_host ;;
		"$sys"/bus/usb/drivers/cdc_ether) driver=cdc_ether ;;
		*) return 1 ;;
	esac
	parent=$device
	while [ "$parent" != "$sys/devices" ]; do
		if [ -f "$parent/idVendor" ] && [ ! -L "$parent/idVendor" ] &&
			[ -f "$parent/idProduct" ] && [ ! -L "$parent/idProduct" ]; then
			vid=$(tr 'A-F' 'a-f' < "$parent/idVendor") || return 1
			pid=$(tr 'A-F' 'a-f' < "$parent/idProduct") || return 1
			case "$vid$pid" in *[!0-9a-f]*) return 1 ;; esac
			[ "${#vid}" -eq 4 ] && [ "${#pid}" -eq 4 ] || return 1
			path=${device#"$sys"}
			case "$path" in *[!A-Za-z0-9_./:-]*) return 1 ;; esac
			printf '%s\t%s\t%s\t%s\n' "$driver" "$vid" "$pid" "$path"
			return 0
		fi
		parent=${parent%/*}
	done
	return 1
)
