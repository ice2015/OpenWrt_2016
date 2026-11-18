#!/bin/sh
# Lite-only paired network/firewall transaction. Reload and recovery are best effort.
set -u
# rpcd file.exec may supply environment values. Sanitize command discovery
# before dirname, library discovery or any other external command runs.
PATH=/usr/sbin:/usr/bin:/sbin:/bin
export PATH
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if [ -f "$SCRIPT_DIR/tr3000-lite-plant-lib.sh" ]; then
	. "$SCRIPT_DIR/tr3000-lite-plant-lib.sh"
else
	. /usr/lib/tr3000-lite/plant-lib.sh
fi
. "$SCRIPT_DIR/lite-common.sh"
[ "${1:-}" != --help ] || { plant_usage; exit 0; }

# Fixture variables are allowed only for the explicitly opted-in source script.
# The fixed RPC identity /usr/sbin/tr3000-lite-plant always uses the live root
# and fixed PATH, even when the caller supplies all fixture environment values.
ROOT=
if plant_test_mode_allowed "$0" "${PLANT_TEST_MODE:-}" &&
	[ -n "${PLANT_ROOT:-}" ] && [ -n "${PLANT_TEST_PATH:-}" ]; then
	ROOT=$PLANT_ROOT
	PATH=$PLANT_TEST_PATH
	export PATH
fi
CONFIG="$ROOT/etc/config"
BACKUPS="$ROOT/etc/tr3000-lite/backups"
LOCK="$ROOT/var/lock/tr3000-lite-plant"
CHECKS=ok; ROLLBACK=none; BACKUP_ID=; ADDRESS=
DEVICE=; CURRENT_ADDRESS=; CURRENT_NETMASK=; CURRENT_LUCI=0; CURRENT_MGMT=0
LOCKED=0; DIRTY=0; CANDIDATE=
OVERRIDE_INSTALLED=0; FW4_LOCKED=0
MODE=lan; LEGACY=0; AP_READY=false; TARGET_MODE=; PLANT_IP=; PLANT_PREFIX=
LAN_ADDRESS=; LAN_NETMASK=; LAN_CIDR=; LAN_DHCP_POOL=; PLANT_CIDR=; BRIDGE_PORTS=

get() { uci -q -c "$CONFIG" get "$1" 2>/dev/null; }

read_state() {
	DEVICE=$(get network.plant.device || :)
	CURRENT_ADDRESS=$(get network.plant.ipaddr || :)
	CURRENT_NETMASK=$(get network.plant.netmask || :)
	CURRENT_LUCI=$(get firewall.tr3000_lite_plant_luci.enabled || printf 0)
	CURRENT_MGMT=$(get firewall.tr3000_lite_lan_plant_tcp.enabled || printf 0)
	LAN_ADDRESS=$(get network.lan.ipaddr || :)
	LAN_NETMASK=$(get network.lan.netmask || :)
	BRIDGE_PORTS=$(get network.br_lan.ports || :)
	[ -n "$LAN_ADDRESS" ] && [ -n "$LAN_NETMASK" ] ||
		{ LAN_ADDRESS=$(plant_lan_cidr | cut -d/ -f1); LAN_NETMASK=$(plant_lan_netmask); }
	LAN_CIDR="$LAN_ADDRESS/$(plant_netmask_prefix "$LAN_NETMASK")"
	PLANT_CIDR=
	[ -n "$CURRENT_ADDRESS" ] && [ -n "$CURRENT_NETMASK" ] &&
		PLANT_CIDR=$(plant_network_cidr "$CURRENT_ADDRESS/$(plant_netmask_prefix "$CURRENT_NETMASK")")
	LAN_DHCP_POOL=$(lan_dhcp_pool)
	if [ -n "$DEVICE" ]; then MODE=plant; else MODE=lan; fi
	# A configuration without the access segment, or one that still carries the
	# retired management segment, predates this firmware and cannot be trusted.
	LEGACY=0
	[ -n "$(get network.lan.ipaddr || :)" ] || LEGACY=1
	[ -z "$(get network.mgmt.ipaddr || :)" ] || LEGACY=1
	[ -n "$DEVICE" ] && [ -z "$(get network.br_lan.name || :)" ] && LEGACY=1
	AP_READY=false
	safe_file "$ROOT/etc/tr3000-lite/management-ap.initialized" && AP_READY=true
}

lan_dhcp_pool() {
	pool_start=$(get dhcp.lan.start || :)
	pool_limit=$(get dhcp.lan.limit || :)
	[ -n "$pool_start" ] && [ -n "$pool_limit" ] || { printf '\n'; return 0; }
	pool_base=$(lite_ipv4_number "$LAN_ADDRESS") || { printf '\n'; return 0; }
	pool_mask=$(lite_prefix_mask "$(plant_netmask_prefix "$LAN_NETMASK")") || { printf '\n'; return 0; }
	pool_base=$((pool_base & pool_mask))
	printf '%s-%s\n' "$(plant_ipv4_dotted $((pool_base + pool_start)))" \
		"$(plant_ipv4_dotted $((pool_base + pool_start + pool_limit - 1)))"
}

emit() {
	printf '{"schema_version":2,"mode":'; plant_json_string "$MODE"
	printf ',"lan":{"cidr":'; plant_json_string "$LAN_CIDR"
	printf ',"netmask":'; plant_json_string "$LAN_NETMASK"
	printf ',"dhcp_pool":'; plant_json_string "$LAN_DHCP_POOL"
	printf '},"plant":{"device":'; plant_json_string "$DEVICE"
	printf ',"address":'; plant_json_string "$CURRENT_ADDRESS"
	printf ',"prefix":%s,"netmask":' "$(plant_netmask_prefix "$CURRENT_NETMASK")"
	plant_json_string "$CURRENT_NETMASK"
	printf ',"cidr":'; plant_json_string "$PLANT_CIDR"
	printf ',"active":%s,"allow_luci":%s,"allow_mgmt":%s,"dhcp":"disabled"},' \
		"$([ "$MODE" = plant ] && printf true || printf false)" \
		"$([ "$CURRENT_LUCI" = 1 ] && printf true || printf false)" \
		"$([ "$CURRENT_MGMT" = 1 ] && printf true || printf false)"
	printf '"ap_ready":%s,"legacy_config_detected":%s,"checks":' \
		"$([ "$AP_READY" = true ] && printf true || printf false)" \
		"$([ "$LEGACY" = 1 ] && printf true || printf false)"
	printf '{"result":'; plant_json_string "$CHECKS"
	printf '},"backup_id":'; plant_json_string "$BACKUP_ID"
	printf ',"rollback":'; plant_json_string "$ROLLBACK"; printf '}\n'
}

fail() {
	failure_code=$1; CHECKS=$2
	finalize_transaction || { CHECKS=backup_pruning; failure_code=3; }
	read_state; emit; exit "$failure_code"
}

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
	case "$TARGET_MODE" in
	plant)
		verify_ip=$(get network.plant.ipaddr) || return 1
		verify_mask=$(get network.plant.netmask) || return 1
		verify_prefix=$(plant_netmask_prefix "$verify_mask")
		[ "$verify_prefix" != null ] || return 1
		verify_device=$(get network.plant.device) || return 1
		lite_valid_ipv4 "$verify_ip" && lite_valid_iface "$verify_device" || return 1
		ip -4 addr show dev "$verify_device" | awk -v address="$verify_ip/$verify_prefix" '
			{ for (i=1; i<=NF; i++) if ($i == "inet" && $(i+1) == address) found=1 }
			END { exit !found }' || return 1
		# The industrial segment owns the port; the access bridge must not.
		case " $(get network.br_lan.ports || :) " in *" $verify_device "*) return 1 ;; esac
		;;
	lan)
		[ "$(get network.lan.ipaddr || :)" = "$(plant_lan_cidr | cut -d/ -f1)" ] || return 1
		[ "$(get network.lan.netmask || :)" = "$(plant_lan_netmask)" ] || return 1
		[ -z "$(get network.plant.device || :)" ] || return 1
		case " $(get network.br_lan.ports || :) " in *" $DEVICE "*) : ;; *) return 1 ;; esac
		;;
	esac
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
	finalize_transaction
	[ -z "$CANDIDATE" ] || rm -rf "$CANDIDATE"
	[ "$LOCKED" = 0 ] || rmdir "$LOCK"
}
trap cleanup EXIT
trap 'if [ "$DIRTY" != 0 ]; then recover; fi; fail 3 interrupted' HUP INT TERM

validate_address() {
	lite_valid_cidr "$ADDRESS" || fail 2 invalid_address
	PLANT_IP=${ADDRESS%/*}; PLANT_PREFIX=${ADDRESS#*/}
	lite_check_address_not_network_or_broadcast "$PLANT_IP" "$PLANT_PREFIX" || fail 2 unusable_host
	# The operator access subnet is reserved for the management segment.
	plant_n=$(lite_ipv4_number "$PLANT_IP"); plant_m=$(lite_prefix_mask "$PLANT_PREFIX")
	mgmt_n=$(lite_ipv4_number 192.168.10.0); mgmt_m=$(lite_prefix_mask 24)
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
	safe_file "$ROOT/etc/shadow" || fail 2 root_password_required
	awk -F: '$1 == "root" && $2 != "" && $2 !~ /^[!*]/ { found=1 } END { exit !found }' \
		"$ROOT/etc/shadow" || fail 2 root_password_required
}

# Handing the only LAN port to the industrial segment removes the wired
# recovery path, so the management AP must be ready unless the operator
# explicitly works from a local console.
ap_gate() {
	[ "$FORCE_LOCAL_CONSOLE" = true ] && return 0
	safe_file "$ROOT/etc/tr3000-lite/management-ap.initialized" || fail 2 management_not_initialized
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

finalize_transaction() {
	[ "$LOCKED" = 1 ] || return 0
	remove_override || return 1
	# The active rollback pair must survive until recovery has completed.
	[ "$DIRTY" = 0 ] || recover
	prune_backups
}

# -t permits commit, unlike -P; -C '' disables conf2dir overrides.
candidate_uci() { uci -q -c "$CANDIDATE" -C '' -t "$CANDIDATE/.uci" "$@"; }
candidate_set() { candidate_uci set "$1" >/dev/null 2>&1 || fail 3 candidate_uci; }
# Read the committed candidate value; pending deltas are not authoritative.
candidate_read() { uci -q -c "$CANDIDATE" -C '' get "$1" 2>/dev/null || :; }

# The only wired port belongs to the access bridge until the operator hands
# it over to the industrial segment.
plant_bridge_port() {
	for port in $(get network.br_lan.ports || :); do printf '%s\n' "$port"; return 0; done
	return 1
}

render_candidate() {
	mkdir "$CANDIDATE/.uci" || fail 3 candidate_directory
	for package in network firewall; do cp "$CONFIG/$package" "$CANDIDATE/$package" || fail 3 candidate_copy; done
	case "$TARGET_MODE" in
	plant)
		candidate_set "network.plant.device=$DEVICE"
		candidate_set "network.plant.proto=static"
		candidate_set "network.plant.ipaddr=$PLANT_IP"
		candidate_set "network.plant.netmask=$(lite_prefix_to_netmask "$PLANT_PREFIX")"
		case " $(candidate_read network.br_lan.ports) " in
			*" $DEVICE "*) candidate_uci delete "network.br_lan.ports" >/dev/null 2>&1 || fail 3 candidate_uci ;;
		esac
		;;
	lan)
		candidate_set "network.plant.proto=none"
		candidate_uci delete "network.plant.device" >/dev/null 2>&1 || :
		candidate_uci delete "network.plant.ipaddr" >/dev/null 2>&1 || :
		candidate_uci delete "network.plant.netmask" >/dev/null 2>&1 || :
		case " $(candidate_read network.br_lan.ports) " in
			*" $DEVICE "*) : ;;
			*) candidate_uci add_list "network.br_lan.ports=$DEVICE" >/dev/null 2>&1 || fail 3 candidate_uci ;;
		esac
		;;
	esac
	luci=0; [ "$ALLOW_LUCI" != true ] || luci=1
	mgmt=0; [ "$ALLOW_MGMT" != true ] || mgmt=1
	candidate_set "firewall.tr3000_lite_plant_luci.enabled=$luci"
	for proto in icmp tcp; do
		for section in "tr3000_lite_lan_plant_$proto" "tr3000_lite_lan_plant_snat_$proto"; do
			candidate_set "firewall.$section.enabled=$mgmt"
			candidate_set "firewall.$section.dest_ip=$(plant_network_cidr "$ADDRESS")"
		done
		candidate_set "firewall.tr3000_lite_lan_plant_snat_$proto.snat_ip=$PLANT_IP"
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

install_candidate() {
	DIRTY=1
	for package in network firewall; do
		cp "$CANDIDATE/$package" "$CONFIG/$package" || fail 3 commit_failed
	done
	ubus call network reload >/dev/null 2>&1 || fail 3 network_reload
	fw4 reload >/dev/null 2>&1 || fail 3 firewall_reload
	verify_live || fail 3 post_apply_verification
	DIRTY=0
}

plant_parse "$@" || fail 2 invalid_arguments
read_state
case "$COMMAND" in
	status) emit ;;
	validate) validate_address; emit ;;
	apply)
		lock; prepare_candidate; read_state; validate_address; management_gate; backup_pair
		TARGET_MODE=plant; render_candidate
		check_candidate
		install_candidate
		finalize_transaction || fail 3 backup_pruning
		read_state; emit
		;;
	enable-plant)
		lock; prepare_candidate; read_state
		[ "$MODE" = lan ] || fail 2 already_plant_mode
		DEVICE=$(plant_bridge_port) || fail 2 no_lan_port
		validate_address
		ap_gate
		ALLOW_MGMT=true
		ALLOW_LUCI=$([ "$CURRENT_LUCI" = 1 ] && printf true || printf false)
		management_gate
		backup_pair; TARGET_MODE=plant; render_candidate
		check_candidate
		install_candidate
		finalize_transaction || fail 3 backup_pruning
		read_state; emit
		;;
	disable-plant)
		lock; prepare_candidate; read_state
		[ "$MODE" = plant ] || fail 2 already_lan_mode
		ALLOW_MGMT=false
		ALLOW_LUCI=$([ "$CURRENT_LUCI" = 1 ] && printf true || printf false)
		management_gate
		backup_pair; TARGET_MODE=lan; render_candidate
		check_candidate
		install_candidate
		finalize_transaction || fail 3 backup_pruning
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
		# The restored snapshot decides which segment owns the wired port.
		restore_device=$(candidate_read network.plant.device)
		if [ -n "$restore_device" ]; then
			TARGET_MODE=plant; DEVICE=$restore_device
		else
			TARGET_MODE=lan; DEVICE=$(plant_bridge_port || printf eth1)
		fi
		# Restoring an older HTTPS-enabled policy must pass today's staging gate.
		# Missing, invalid and enabled values all require the gate. Only an
		# explicitly disabled fw4 boolean may bypass it.
		case "$(candidate_uci get firewall.tr3000_lite_plant_luci.enabled)" in
			0|false|no|off) ALLOW_LUCI=false ;;
			*) ALLOW_LUCI=true ;;
		esac
		management_gate
		check_candidate
		# Candidate already contains the selected snapshot; create a fresh pair
		# of today's live configs for recovery if this restore transaction fails.
		backup_pair
		install_candidate
		ROLLBACK=restored
		finalize_transaction || fail 3 backup_pruning
		read_state
		emit
		;;
esac
