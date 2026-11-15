#!/bin/sh
# Lite-only paired network/firewall transaction. Reload and recovery are best effort.
set -u
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if [ -f "$SCRIPT_DIR/tr3000-lite-plant-lib.sh" ]; then
	. "$SCRIPT_DIR/tr3000-lite-plant-lib.sh"
else
	. /usr/lib/tr3000-lite/plant-lib.sh
fi
. "$SCRIPT_DIR/lite-common.sh"
[ "${1:-}" != --help ] || { plant_usage; exit 0; }

# A relocated root permits isolated integration tests; rpcd passes no environment.
ROOT=${PLANT_ROOT:-}
CONFIG="$ROOT/etc/config"
BACKUPS="$ROOT/etc/tr3000-lite/backups"
LOCK="$ROOT/var/lock/tr3000-lite-plant"
CHECKS=ok; ROLLBACK=none; BACKUP_ID=; ADDRESS=
DEVICE=; CURRENT_ADDRESS=; CURRENT_NETMASK=; CURRENT_LUCI=0; CURRENT_MGMT=0
LOCKED=0; DIRTY=0; CANDIDATE=
OVERRIDE_INSTALLED=0; FW4_LOCKED=0

get() { uci -q -c "$CONFIG" get "$1" 2>/dev/null; }

read_state() {
	DEVICE=$(get network.plant.device || :)
	CURRENT_ADDRESS=$(get network.plant.ipaddr || :)
	CURRENT_NETMASK=$(get network.plant.netmask || :)
	CURRENT_LUCI=$(get firewall.tr3000_lite_plant_luci.enabled || printf 0)
	CURRENT_MGMT=$(get firewall.tr3000_lite_mgmt_plant_tcp.enabled || printf 0)
}

emit() {
	printf '{"schema_version":1,"plant":{"device":'; plant_json_string "$DEVICE"
	printf ',"address":'; plant_json_string "$CURRENT_ADDRESS"
	printf ',"prefix":%s,"netmask":' "$(plant_netmask_prefix "$CURRENT_NETMASK")"
	plant_json_string "$CURRENT_NETMASK"
	printf ',"allow_luci":%s,"allow_mgmt":%s,"dhcp":"disabled"},"checks":' \
		"$([ "$CURRENT_LUCI" = 1 ] && printf true || printf false)" \
		"$([ "$CURRENT_MGMT" = 1 ] && printf true || printf false)"
	printf '{"result":'; plant_json_string "$CHECKS"
	printf '},"backup_id":'; plant_json_string "$BACKUP_ID"
	printf ',"rollback":'; plant_json_string "$ROLLBACK"; printf '}\n'
}

fail() { CHECKS=$2; read_state; emit; exit "$1"; }

safe_file() { [ -f "$1" ] && [ ! -L "$1" ]; }

check_paths() {
	for path in "$ROOT/etc" "$CONFIG" "$ROOT/etc/tr3000-lite" "$BACKUPS" "$ROOT/var/lock"; do
		[ ! -L "$path" ] || fail 3 unsafe_path
	done
	[ -d "$ROOT/tmp" ] && [ ! -L "$ROOT/tmp" ] || fail 3 unsafe_path
	# Pinned base-files creates var -> tmp, or a persistent var directory.
	# Only that exact OS alias is allowed; arbitrary runtime links fail closed.
	if [ -L "$ROOT/var" ]; then
		[ "$(readlink "$ROOT/var")" = tmp ] || fail 3 unsafe_path
	fi
	for package in network firewall; do safe_file "$CONFIG/$package" || fail 3 unsafe_config; done
	# On the device the controller and persistent backup parent must belong to root.
	[ -n "$ROOT" ] || [ "$(id -u)" = 0 ] || fail 3 root_required
	mkdir -p "$BACKUPS" "$ROOT/var/lock" || fail 3 backup_directory
	chmod 0700 "$ROOT/etc/tr3000-lite" "$BACKUPS" || fail 3 backup_permissions
	if [ -z "$ROOT" ]; then
		[ "$(stat -c %u "$ROOT/etc/tr3000-lite")" = 0 ] &&
		[ "$(stat -c %u "$BACKUPS")" = 0 ] || fail 3 backup_owner
		[ "$(stat -c %u "$ROOT/tmp")" = 0 ] || fail 3 unsafe_path
	fi
}

lock() {
	check_paths
	mkdir "$LOCK" 2>/dev/null || fail 3 busy
	LOCKED=1
	CANDIDATE=$(mktemp -d "$ROOT/var/lock/tr3000-lite-candidate.XXXXXX") || fail 3 candidate_directory
}

verify_live() {
	verify_ip=$(get network.plant.ipaddr) || return 1
	verify_mask=$(get network.plant.netmask) || return 1
	verify_prefix=$(plant_netmask_prefix "$verify_mask")
	[ "$verify_prefix" != null ] || return 1
	verify_device=$(get network.plant.device) || return 1
	lite_valid_ipv4 "$verify_ip" && lite_valid_iface "$verify_device" || return 1
	ip -4 addr show dev "$verify_device" | awk -v address="$verify_ip/$verify_prefix" '
		{ for (i=1; i<=NF; i++) if ($i == "inet" && $(i+1) == address) found=1 }
		END { exit !found }' || return 1
	ip -4 route show >/dev/null 2>&1 && fw4 check >/dev/null 2>&1
}

recover() {
	ROLLBACK=restored
	for package in network firewall; do
		cp "$BACKUPS/$BACKUP_ID.$package" "$CONFIG/$package" || ROLLBACK=degraded
	done
	ubus call network reload >/dev/null 2>&1 || ROLLBACK=degraded
	fw4 reload >/dev/null 2>&1 || ROLLBACK=degraded
	verify_live || ROLLBACK=degraded
	DIRTY=0
}

cleanup() {
	remove_override
	[ "$DIRTY" = 0 ] || recover
	[ -z "$CANDIDATE" ] || rm -rf "$CANDIDATE"
	[ "$LOCKED" = 0 ] || rmdir "$LOCK"
}
trap cleanup EXIT
trap 'if [ "$DIRTY" != 0 ]; then recover; fi; fail 3 interrupted' HUP INT TERM

validate_address() {
	lite_valid_cidr "$ADDRESS" || fail 2 invalid_address
	PLANT_IP=${ADDRESS%/*}; PLANT_PREFIX=${ADDRESS#*/}
	lite_check_address_not_network_or_broadcast "$PLANT_IP" "$PLANT_PREFIX" || fail 2 unusable_host
	# The management subnet is reserved even when its AP currently has no route.
	plant_n=$(lite_ipv4_number "$PLANT_IP"); plant_m=$(lite_prefix_mask "$PLANT_PREFIX")
	mgmt_n=$(lite_ipv4_number 192.168.77.0); mgmt_m=$(lite_prefix_mask 24)
	[ $((plant_n & mgmt_m)) -ne "$mgmt_n" ] &&
		[ $((mgmt_n & plant_m)) -ne $((plant_n & plant_m)) ] || fail 2 management_overlap
	lite_valid_iface "$DEVICE" || fail 2 invalid_device
	[ "$DEVICE" != "$(get network.wan.device || :)" ] || fail 2 wan_device
	ip link show dev "$DEVICE" >/dev/null 2>&1 || fail 2 missing_device
	(lite_reject_route_overlap "$ADDRESS" "$DEVICE") >/dev/null 2>&1 || fail 2 route_overlap
	arping -D -c 3 -I "$DEVICE" "$PLANT_IP" >/dev/null 2>&1 || fail 2 arp_conflict_or_failure
}

management_gate() {
	[ "$ALLOW_LUCI" != true ] && return 0
	safe_file "$ROOT/etc/tr3000-lite/management-ap.initialized" || fail 2 management_not_initialized
	safe_file "$ROOT/etc/shadow" || fail 2 root_password_required
	awk -F: '$1 == "root" && $2 != "" && $2 !~ /^[!*]/ { found=1 } END { exit !found }' \
		"$ROOT/etc/shadow" || fail 2 root_password_required
}

backup_pair() {
	BACKUP_ID=$(date +%Y%m%d%H%M%S)-$$
	for package in network firewall; do
		[ ! -e "$BACKUPS/$BACKUP_ID.$package" ] && [ ! -L "$BACKUPS/$BACKUP_ID.$package" ] || fail 3 backup_exists
	done
	for package in network firewall; do
		(umask 077; set -C; cat "$CONFIG/$package" > "$BACKUPS/$BACKUP_ID.$package") || fail 3 backup_failed
		chmod 0600 "$BACKUPS/$BACKUP_ID.$package" || fail 3 backup_permissions
	done
}

prune_backups() {
	# Names are generated by this controller; refuse foreign/symlink entries.
	for file in "$BACKUPS"/*; do
		[ -e "$file" ] || continue
		[ ! -L "$file" ] || return 1
		name=${file##*/}; id=${name%.*}
		plant_safe_id "$id" || return 1
		case "$name" in *.network|*.firewall) ;; *) return 1 ;; esac
	done
	count=0
	for file in $(LC_ALL=C ls -1t "$BACKUPS"/*.network 2>/dev/null); do
		count=$((count+1)); [ "$count" -gt 5 ] || continue
		id=${file##*/}; id=${id%.network}
		rm -f "$BACKUPS/$id.network" "$BACKUPS/$id.firewall" || return 1
	done
}

# -t permits commit, unlike -P; -C '' disables conf2dir overrides.
candidate_uci() { uci -q -c "$CANDIDATE" -C '' -t "$CANDIDATE/.uci" "$@"; }
candidate_set() { candidate_uci set "$1" >/dev/null 2>&1 || fail 3 candidate_uci; }

render_candidate() {
	mkdir "$CANDIDATE/.uci" || fail 3 candidate_directory
	for package in network firewall; do cp "$CONFIG/$package" "$CANDIDATE/$package" || fail 3 candidate_copy; done
	candidate_set "network.plant.proto=static"
	candidate_set "network.plant.ipaddr=$PLANT_IP"
	candidate_set "network.plant.netmask=$(lite_prefix_to_netmask "$PLANT_PREFIX")"
	luci=0; [ "$ALLOW_LUCI" != true ] || luci=1
	mgmt=0; [ "$ALLOW_MGMT" != true ] || mgmt=1
	candidate_set "firewall.tr3000_lite_plant_luci.enabled=$luci"
	for proto in icmp tcp; do
		for section in "tr3000_lite_mgmt_plant_$proto" "tr3000_lite_mgmt_plant_snat_$proto"; do
			candidate_set "firewall.$section.enabled=$mgmt"
			candidate_set "firewall.$section.dest_ip=$(plant_network_cidr "$ADDRESS")"
		done
		candidate_set "firewall.tr3000_lite_mgmt_plant_snat_$proto.snat_ip=$PLANT_IP"
	done
	for package in network firewall; do
		candidate_uci commit "$package" || fail 3 candidate_commit
		safe_file "$CANDIDATE/$package" || fail 3 candidate_commit
	done
}

remove_override() {
	if [ "$OVERRIDE_INSTALLED" = 1 ]; then
		rm -f "$ROOT/var/run/uci/firewall" || return 1
		OVERRIDE_INSTALLED=0
	fi
	if [ "$FW4_LOCKED" = 1 ]; then
		flock -u 9 || return 1
		exec 9>&-
		FW4_LOCKED=0
	fi
}

prepare_candidate() {
	# Pinned libuci reads conf2dir before confdir. fw4's no-argument cursor
	# consumes /var/run/uci/firewall, then /tmp/.uci/firewall deltas.
	# UCI_CONFIG_DIR is NOT honored by that cursor.
	if [ -L "$ROOT/var/run" ]; then
		# The alternate pinned layout is a real var with run -> /tmp/run.
		[ ! -L "$ROOT/var" ] && [ "$(readlink "$ROOT/var/run")" = /tmp/run ] &&
			[ -d "$ROOT/tmp/run" ] && [ ! -L "$ROOT/tmp/run" ] || fail 3 unsafe_path
	fi
	for path in "$ROOT/var/run/uci" "$ROOT/tmp" "$ROOT/tmp/.uci" "$ROOT/var/run/fw4.lock"; do
		[ ! -L "$path" ] || fail 3 unsafe_path
	done
	mkdir -p "$ROOT/var/run/uci" || fail 3 candidate_directory
	if command -v flock >/dev/null 2>&1; then
		exec 9>"$ROOT/var/run/fw4.lock"
		flock -x 9 || fail 3 firewall_busy
		FW4_LOCKED=1
	fi
	# Refuse both packages before any UCI candidate edits. Changing confdir
	# alone does not isolate the default saved deltas or runtime overrides.
	for package in network firewall; do
		for file in "$ROOT/var/run/uci/$package" "$ROOT/tmp/.uci/$package"; do
			[ ! -e "$file" ] && [ ! -L "$file" ] || fail 3 pending_firewall_state
		done
	done
}

check_candidate() {
	# noclobber avoids replacing a file created after the existence check.
	(umask 077; set -C; cat "$CANDIDATE/firewall" > "$ROOT/var/run/uci/firewall") || fail 3 candidate_override
	OVERRIDE_INSTALLED=1
	fw4 check >/dev/null 2>&1 || { remove_override; fail 3 candidate_firewall; }
	remove_override || fail 3 candidate_cleanup
}

plant_parse "$@" || fail 2 invalid_arguments
read_state
case "$COMMAND" in
	status) emit ;;
	validate) validate_address; emit ;;
	apply)
		lock; prepare_candidate; read_state; validate_address; management_gate; backup_pair; render_candidate
		check_candidate
		DIRTY=1
		for package in network firewall; do
			cp "$CANDIDATE/$package" "$CONFIG/$package" || { recover; fail 3 commit_failed; }
		done
		ubus call network reload >/dev/null 2>&1 || { recover; fail 3 network_reload; }
		fw4 reload >/dev/null 2>&1 || { recover; fail 3 firewall_reload; }
		verify_live || { recover; fail 3 post_apply_verification; }
		DIRTY=0
		prune_backups || fail 3 backup_pruning
		read_state; emit
		;;
	restore)
		lock; prepare_candidate
		for package in network firewall; do
			safe_file "$BACKUPS/$BACKUP_ID.$package" || fail 2 invalid_backup
			[ "$(stat -c %a "$BACKUPS/$BACKUP_ID.$package")" = 600 ] || fail 2 backup_permissions
			[ -n "$ROOT" ] || [ "$(stat -c %u "$BACKUPS/$BACKUP_ID.$package")" = 0 ] || fail 2 backup_owner
			cp "$BACKUPS/$BACKUP_ID.$package" "$CANDIDATE/$package" || fail 3 candidate_copy
		done
		# Restoring an older HTTPS-enabled policy must pass today's staging gate.
		ALLOW_LUCI=false
		[ "$(candidate_uci get firewall.tr3000_lite_plant_luci.enabled)" != 1 ] || ALLOW_LUCI=true
		management_gate
		remove_override || fail 3 candidate_cleanup
		DIRTY=1; recover; read_state
		[ "$ROLLBACK" = restored ] || fail 3 recovery_failed
		emit
		;;
esac
