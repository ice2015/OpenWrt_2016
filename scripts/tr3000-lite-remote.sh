#!/bin/sh
# Fixed Lite authorization controller. No caller-selected paths or secret arguments.
PATH=/usr/sbin:/usr/bin:/sbin:/bin
export PATH
set -uf
usage() { printf 'Usage: %s status --json | sync | set-policy --allow-luci true|false --allow-plant true|false\n' "$0"; }
[ "${1:-}" != --help ] || { usage; exit 0; }
. /usr/sbin/lite-common.sh
. /usr/lib/tr3000-lite/plant-lib.sh
. /usr/lib/tr3000-lite/remote-lib.sh
OWNER_UID=0
CONFIG=/etc/config
PRIVATE=/etc/tr3000-lite
SHADOW=/etc/shadow
RUNTIME=/var/run/tr3000-lite/remote
LOCK=/var/lock/tr3000-lite-plant
OVERRIDES=/var/run/uci
DELTAS=/tmp/.uci
FW4_LOCK=/var/run/fw4.lock
LOCKED=0; FW_LOCKED=0; OVERRIDE=0; CANDIDATE=; DIRTY=0
RESULT=not_synchronized; DEGRADED=false
IDENTITY=; ROOT_OK=false; AP_OK=false; ID_OK=false; KEYS_OK=false; ENROLLED=false
DIRECT_CFG=false; VPS_CFG=false; DIRECT_ENABLED=false; VPS_ENABLED=false
DIRECT_ADDRESS=; VPS_ADDRESS=; DIRECT_PORT=0; DIRECT_SOURCES=; VPS_SOURCES=
PLANT_ADDRESS=; PLANT_CIDR=; PLANT_OK=false; SOURCES_OK=true; AUTH_READY=false
REQUEST_LUCI=false; REQUEST_PLANT=false; EFFECTIVE_LUCI=null; EFFECTIVE_PLANT=null
REMOTE_SECTION_PREFIX=tr3000_lite_remote_

owned_file() {
	[ -f "$1" ] && [ ! -L "$1" ] && [ "$(stat -c %u "$1" 2>/dev/null)" = "$OWNER_UID" ]
}
safe_config() {
	owned_file "$1" || return 1
	case "$(stat -c %a "$1" 2>/dev/null)" in 600|640|644) return 0 ;; *) return 1 ;; esac
}
get() {
	package=${1%%.*}
	safe_config "$CONFIG/$package" || return 1
	uci -q -c "$CONFIG" -C '' get "$1" 2>/dev/null
}
pending() {
	for package in network firewall tr3000-lite-remote; do
		for p in "$OVERRIDES/$package" "$DELTAS/$package"; do
			[ ! -e "$p" ] && [ ! -L "$p" ] || return 0
		done
	done
	return 1
}
key_ready() (
	role=$1; keyname=$2
	owned_file "$CONFIG/network" && [ "$(stat -c %a "$CONFIG/network")" = 600 ] || return 1
	owned_file "$PRIVATE/keys/$keyname.key" && [ "$(stat -c %a "$PRIVATE/keys/$keyname.key")" = 600 ] || return 1
	key=$(get "network.$role.private_key" || :)
	remote_key_format "$key" && [ "$key" = "$(cat "$PRIVATE/keys/$keyname.key")" ] || return 1
	# Validate private key material through WireGuard stdin, never process argv.
	wg pubkey < "$PRIVATE/keys/$keyname.key" >/dev/null 2>&1
)
peer_names() {
	uci -q -X -c "$CONFIG" -C '' show network 2>/dev/null | awk -F= -v type="$1" '
		$1 ~ /^network\.[A-Za-z0-9_-]+$/ && $2==type {sub(/^network\./,"",$1); print $1}'
}
valid_host() (
	host=$1
	case "$host" in ''|[-.]*|*[-.]|*[!A-Za-z0-9.-]*) return 1 ;; esac
	[ "${#host}" -le 253 ] || return 1
	IFS=.; set -- $host
	for label do
		case "$label" in ''|-*|*-) return 1 ;; esac
		[ "${#label}" -le 63 ] || return 1
	done
)
collect_sources() {
	DIRECT_SOURCES=; VPS_SOURCES=; direct_input=; vps_input=
	for peer in $(peer_names wireguard_wg_direct); do
		pub=$(get "network.$peer.public_key" || :)
		remote_key_format "$pub" && [ "$(get "network.$peer.route_allowed_ips" || :)" = 1 ] || return 1
		ips=$(get "network.$peer.allowed_ips" || :); [ -n "$ips" ] || return 1
		for ip in $ips; do direct_input="$direct_input$ip
"; done
	done
	DIRECT_SOURCES=$(printf '%s' "$direct_input" | remote_source_set) || return 1
	vps_peers=$(peer_names wireguard_wg_vps)
	vps_count=0; vps_allowed=
	for peer in $vps_peers; do
		vps_count=$((vps_count+1)); [ "$vps_count" -eq 1 ] || return 1
		pub=$(get "network.$peer.public_key" || :)
		remote_key_format "$pub" || return 1
		[ "$(get "network.$peer.route_allowed_ips" || :)" = 1 ] || return 1
		ips=$(get "network.$peer.allowed_ips" || :); [ -n "$ips" ] || return 1
		for ip in $ips; do vps_input="$vps_input$ip
"; done
	done
	vps_allowed=$(printf '%s' "$vps_input" | remote_source_set) || return 1
	registered=$(get tr3000-lite-remote.access.vps_remote_source || :)
	vps_input=
	for ip in $registered; do
		printf '%s\n' "$vps_allowed" | grep -Fxq "$ip" || return 1
		vps_input="$vps_input$ip
"
	done
	VPS_SOURCES=$(printf '%s' "$vps_input" | remote_source_set) || return 1
	# Cross-path duplicates and malformed late entries reject the whole set.
	{ [ -z "$DIRECT_SOURCES" ] || printf '%s\n' "$DIRECT_SOURCES"; [ -z "$VPS_SOURCES" ] || printf '%s\n' "$VPS_SOURCES"; } | remote_source_set >/dev/null || return 1
	for ip in $DIRECT_SOURCES $vps_allowed; do
		[ "$ip" != "$DIRECT_ADDRESS" ] && [ "$ip" != "$VPS_ADDRESS" ] || return 1
		if [ "$PLANT_OK" = true ]; then
			lite_cidr_contains "$PLANT_CIDR" "${ip%/32}" && return 1
		fi
		lite_cidr_contains 192.168.77.0/24 "${ip%/32}" && return 1
	done
	for ip in $DIRECT_SOURCES; do printf '%s\n' "$vps_allowed" | grep -Fxq "$ip" && return 1; done
	return 0
}
refresh_transport() {
	DIRECT_ENABLED=false; VPS_ENABLED=false
	if [ "$AUTH_READY" = true ] && [ -n "$DIRECT_SOURCES" ] &&
		{ [ "$REQUEST_LUCI" = true ] || [ "$REQUEST_PLANT" = true ]; } &&
		[ "$(get tr3000-lite-remote.access.direct_enabled || :)" = 1 ] &&
		[ "$(get network.wg_direct.auto || :)" = 1 ]; then DIRECT_ENABLED=true; fi
	if [ "$ROOT_OK:$AP_OK:$ID_OK:$VPS_CFG" = true:true:true:true ] &&
		[ "$(get tr3000-lite-remote.access.vps_enabled || :)" = 1 ] && [ "$(get network.wg_vps.auto || :)" = 1 ]; then VPS_ENABLED=true; fi
	if pending; then DIRECT_ENABLED=false; VPS_ENABLED=false; fi
}
read_state() {
	REQUEST_LUCI=false; REQUEST_PLANT=false
	[ "$(get tr3000-lite-remote.access.allow_luci || :)" != 1 ] || REQUEST_LUCI=true
	[ "$(get tr3000-lite-remote.access.allow_plant || :)" != 1 ] || REQUEST_PLANT=true
	ROOT_OK=false; AP_OK=false; ID_OK=false; KEYS_OK=false; ENROLLED=false; IDENTITY=
	if owned_file "$SHADOW" && awk -F: '$1=="root" && $2!="" && $2!~/^[!*]/ {ok=1} END {exit !ok}' "$SHADOW"; then ROOT_OK=true; fi
	owned_file "$PRIVATE/management-ap.initialized" && AP_OK=true
	if owned_file "$PRIVATE/device-id"; then
		id=$(cat "$PRIVATE/device-id")
		if remote_valid_id "$id"; then IDENTITY=$id; ID_OK=true; fi
	fi
	owned_file "$PRIVATE/enrolled" && ENROLLED=true
	if [ -L "$PRIVATE" ] || [ -L "$PRIVATE/keys" ] ||
		[ "$(stat -c '%u:%a' "$PRIVATE" 2>/dev/null)" != "$OWNER_UID:700" ] ||
		[ "$(stat -c '%u:%a' "$PRIVATE/keys" 2>/dev/null)" != "$OWNER_UID:700" ]; then
		AP_OK=false; ID_OK=false; ENROLLED=false; IDENTITY=
	fi
	PLANT_ADDRESS=$(get network.plant.ipaddr || :); mask=$(get network.plant.netmask || :)
	prefix=$(plant_netmask_prefix "$mask"); PLANT_OK=false; PLANT_CIDR=
	if [ "$(get network.plant.proto || :)" = static ] && lite_valid_cidr "$PLANT_ADDRESS/$prefix" &&
		[ "$(get network.plant.device || :)" != "$(get network.wan.device || :)" ]; then
		PLANT_CIDR=$(plant_network_cidr "$PLANT_ADDRESS/$prefix"); PLANT_OK=true
	else PLANT_ADDRESS=; fi
	DIRECT_ADDRESS=$(get network.wg_direct.addresses || :)
	VPS_ADDRESS=$(get network.wg_vps.addresses || :)
	remote_valid_source "$DIRECT_ADDRESS" || DIRECT_ADDRESS=
	remote_valid_source "$VPS_ADDRESS" || VPS_ADDRESS=
	DIRECT_CFG=false; VPS_CFG=false; DIRECT_PORT=$(get network.wg_direct.listen_port || :)
	if [ "$(get network.wg_direct.proto || :)" = wireguard ] && [ -n "$DIRECT_ADDRESS" ] &&
		lite_valid_port "$DIRECT_PORT" && key_ready wg_direct direct; then DIRECT_CFG=true; else DIRECT_PORT=0; fi
	vps_peers=$(peer_names wireguard_wg_vps); set -- $vps_peers
	if [ "$#" -eq 1 ] && [ "$(get network.wg_vps.proto || :)" = wireguard ] && [ -n "$VPS_ADDRESS" ] &&
		valid_host "$(get "network.$1.endpoint_host" || :)" && lite_valid_port "$(get "network.$1.endpoint_port" || :)" &&
		lite_valid_port "$(get "network.$1.persistent_keepalive" || :)" && key_ready wg_vps vps; then VPS_CFG=true; fi
	if [ "$DIRECT_CFG" = true ] && [ "$VPS_CFG" = true ] && [ "$DIRECT_ADDRESS" != "$VPS_ADDRESS" ] &&
		[ "$(get network.wg_direct.private_key)" != "$(get network.wg_vps.private_key)" ]; then KEYS_OK=true; fi
	SOURCES_OK=true
	if ! collect_sources; then SOURCES_OK=false; DIRECT_SOURCES=; VPS_SOURCES=; fi
	AUTH_READY=false
	if [ "$ROOT_OK:$AP_OK:$ID_OK:$KEYS_OK:$ENROLLED:$PLANT_OK:$SOURCES_OK" = true:true:true:true:true:true:true ]; then AUTH_READY=true; fi
	refresh_transport
	RESULT=ok
	[ "$AUTH_READY" = true ] || RESULT=gates_not_ready
	[ "$SOURCES_OK" = true ] || RESULT=invalid_sources
	if pending; then RESULT=pending_state; DIRECT_ENABLED=false; VPS_ENABLED=false; fi
}
input_fingerprint() {
	for p in "$CONFIG/network" "$CONFIG/firewall" "$CONFIG/tr3000-lite-remote" "$SHADOW" \
		"$PRIVATE/device-id" "$PRIVATE/enrolled" "$PRIVATE/management-ap.initialized" "$PRIVATE/keys/direct.key" "$PRIVATE/keys/vps.key"; do
		if owned_file "$p"; then sha256sum "$p"; stat -c '%u:%a' "$p"; else printf 'missing:%s\n' "$p"; fi
	done
	for p in "$PRIVATE" "$PRIVATE/keys"; do
		if [ -d "$p" ] && [ ! -L "$p" ]; then stat -c '%n:%u:%a' "$p"; else printf 'unsafe:%s\n' "$p"; fi
	done
}
fingerprint() { input_fingerprint | sha256sum | awk '{print $1}'; }
runtime_safe() {
	[ -d "$RUNTIME" ] && [ ! -L "$RUNTIME" ] && [ ! -L /var/run/tr3000-lite ] &&
		[ "$(stat -c '%u:%a' "$RUNTIME" 2>/dev/null)" = "$OWNER_UID:700" ]
}
json_sources() {
	separator=
	for source in $1; do printf '%s"%s"' "$separator" "$source"; separator=,; done
}
emit() {
	printf '{"schema_version":1,"identity":"%s","enrolled":%s,"gates":{"root_password":%s,"ap_initialized":%s,"identity":%s,"keys":%s},' "$IDENTITY" "$ENROLLED" "$ROOT_OK" "$AP_OK" "$ID_OK" "$KEYS_OK"
	printf '"roles":{"wg_direct":{"configured":%s,"enabled":%s,"address":"%s"},"wg_vps":{"configured":%s,"enabled":%s,"address":"%s"}},' "$DIRECT_CFG" "$DIRECT_ENABLED" "$DIRECT_ADDRESS" "$VPS_CFG" "$VPS_ENABLED" "$VPS_ADDRESS"
	printf '"policy":{"allow_luci":%s,"allow_plant":%s},"effective":{"allow_luci":%s,"allow_plant":%s},' "$REQUEST_LUCI" "$REQUEST_PLANT" "$EFFECTIVE_LUCI" "$EFFECTIVE_PLANT"
	printf '"sources":{"direct":['; json_sources "$DIRECT_SOURCES"; printf '],"vps":['; json_sources "$VPS_SOURCES"
	printf ']},"plant":{"address":"%s","cidr":"%s"},"checks":{"result":"%s"},"degraded":%s}\n' "$PLANT_ADDRESS" "$PLANT_CIDR" "$RESULT" "$DEGRADED"
}
remove_override() {
	if [ "$OVERRIDE" = 1 ]; then rm -f "$OVERRIDES/firewall" || return 1; OVERRIDE=0; fi
	if [ "$FW_LOCKED" = 1 ]; then flock -u 9 || return 1; exec 9>&-; FW_LOCKED=0; fi
}
cleanup() {
	remove_override || :
	[ -z "$CANDIDATE" ] || rm -rf "$CANDIDATE"
	[ "$LOCKED" = 0 ] || rmdir "$LOCK"
}
trap cleanup EXIT
trap 'if [ "$LOCKED" = 1 ]; then fail_apply interrupted; else exit 3; fi' HUP INT TERM
stop_roles() {
	for role in wg_direct wg_vps; do
		if [ "$(get "network.$role.proto" || :)" = wireguard ]; then ifdown "$role" >/dev/null 2>&1 || :; fi
	done
}
fail_apply() {
	RESULT=$1; DEGRADED=true; EFFECTIVE_LUCI=null; EFFECTIVE_PLANT=null
	DIRECT_ENABLED=false; VPS_ENABLED=false
	remove_override || :
	# Keep only the deny candidate when old authorizations may be stale. Never
	# persist old-plant permissions merely to make recovery look successful.
	if [ -n "$CANDIDATE" ] && [ -f "$CANDIDATE/deny-firewall" ]; then
		cp -p "$CANDIDATE/deny-firewall" "$CONFIG/firewall" || :
	fi
	if runtime_safe && [ ! -L "$RUNTIME/applied" ]; then rm -f "$RUNTIME/applied" || :; fi
	stop_roles
	emit; exit 3
}
candidate_uci() { uci -q -c "$CANDIDATE" -C '' -t "$CANDIDATE/delta" "$@"; }
set_candidate() { candidate_uci set "$1" >/dev/null 2>&1 || fail_apply candidate_uci; }
add_list() { candidate_uci add_list "$1" >/dev/null 2>&1 || fail_apply candidate_uci; }
rule() {
	section=$1; type=$2; shift 2
	set_candidate "firewall.$section=$type"
	while [ "$#" -gt 0 ]; do set_candidate "firewall.$section.$1=$2"; shift 2; done
}
render_permissions() {
	for role in wg_direct wg_vps; do
		case "$role" in wg_direct) configured=$DIRECT_CFG; enabled=$DIRECT_ENABLED; sources=$DIRECT_SOURCES; address=$DIRECT_ADDRESS ;; *) configured=$VPS_CFG; enabled=$VPS_ENABLED; sources=$VPS_SOURCES; address=$VPS_ADDRESS ;; esac
		[ "$configured" = true ] || continue
		zone="${REMOTE_SECTION_PREFIX}zone_$role"
		rule "$zone" zone name "$role" input REJECT output ACCEPT forward REJECT
		add_list "firewall.$zone.network=$role"
		[ "$enabled" = true ] || continue
		index=0
		for source in $sources; do
			index=$((index+1)); name="${REMOTE_SECTION_PREFIX}${role}_$index"
			if [ "$APPLY_LUCI" = true ]; then
				rule "${name}_luci" rule src "$role" src_ip "$source" dest_ip "$address" proto tcp dest_port 443 family ipv4 target ACCEPT
			fi
			if [ "$APPLY_PLANT" = true ]; then
				for proto in icmp tcp; do
					rule "${name}_plant_$proto" rule src "$role" src_ip "$source" dest plant dest_ip "$PLANT_CIDR" proto "$proto" family ipv4 target ACCEPT
					[ "$proto" != icmp ] || set_candidate "firewall.${name}_plant_icmp.icmp_type=echo-request"
					rule "${name}_snat_$proto" nat src plant src_ip "$source" dest_ip "$PLANT_CIDR" snat_ip "$PLANT_ADDRESS" proto "$proto" family ipv4 target SNAT
				done
			fi
		done
	done
	if [ "$DIRECT_ENABLED" = true ] && [ -n "$DIRECT_SOURCES" ] &&
		{ [ "$APPLY_LUCI" = true ] || [ "$APPLY_PLANT" = true ]; }; then
		rule "${REMOTE_SECTION_PREFIX}direct_listener" rule src wan proto udp dest_port "$DIRECT_PORT" family ipv4 target ACCEPT
	fi
}

remote_parse "$@" || { RESULT=invalid_arguments; emit; exit 2; }
[ "$(id -u)" = "$OWNER_UID" ] || { RESULT=root_required; emit; exit 3; }
read_state
if [ "$REMOTE_COMMAND" = status ]; then
	cache_valid=0
	if ! pending && runtime_safe && owned_file "$RUNTIME/applied"; then
		read -r saved_fp saved_luci saved_plant saved_result < "$RUNTIME/applied" || :
		if [ "${saved_fp:-}" = "$(fingerprint)" ]; then
			case "${saved_luci:-}:${saved_plant:-}" in true:true|true:false|false:true|false:false)
				if [ "$saved_luci:$saved_plant" = false:false ] || [ "$AUTH_READY" = true ]; then
					EFFECTIVE_LUCI=$saved_luci; EFFECTIVE_PLANT=$saved_plant; cache_valid=1
				fi ;;
			esac
		fi
	fi
	[ "$cache_valid" = 1 ] || [ "$RESULT" != ok ] || RESULT=not_synchronized
	emit; exit 0
fi
for p in "$CONFIG" "$PRIVATE" "$PRIVATE/keys" /var/lock /var/run/tr3000-lite "$RUNTIME" "$OVERRIDES" "$DELTAS" "$FW4_LOCK"; do
	[ ! -L "$p" ] || fail_apply unsafe_path
done
mkdir -p "$RUNTIME" /var/lock "$OVERRIDES" || fail_apply runtime_directory
chmod 0700 /var/run/tr3000-lite "$RUNTIME" || fail_apply runtime_permissions
mkdir "$LOCK" 2>/dev/null || { RESULT=busy; emit; exit 3; }
LOCKED=1
pending && fail_apply pending_state
for package in network firewall tr3000-lite-remote; do safe_config "$CONFIG/$package" || fail_apply unsafe_config; done
# Recompute after serialization, not before another plant/USB transaction finishes.
read_state
input_fp=$(fingerprint)
CANDIDATE=$(mktemp -d "$RUNTIME/candidate.XXXXXX") || fail_apply candidate_directory
mkdir "$CANDIDATE/delta" || fail_apply candidate_directory
for package in firewall tr3000-lite-remote; do cp -p "$CONFIG/$package" "$CANDIDATE/$package" || fail_apply candidate_copy; done
owned_sections=$(candidate_uci -X show firewall 2>/dev/null | awk -F= '$1 ~ /^firewall\.tr3000_lite_remote_[A-Za-z0-9_]+$/ {sub(/^firewall\./,"",$1); print $1}')
for section in $owned_sections; do candidate_uci delete "firewall.$section" >/dev/null 2>&1 || fail_apply candidate_uci; done
candidate_uci commit firewall >/dev/null 2>&1 || fail_apply candidate_commit
cp -p "$CANDIDATE/firewall" "$CANDIDATE/deny-firewall" || fail_apply candidate_copy
APPLY_LUCI=false; APPLY_PLANT=false; return_code=0
if [ "$REMOTE_COMMAND" = set-policy ] && [ "$AUTH_READY" != true ] &&
	{ [ "$ALLOW_LUCI" = true ] || [ "$ALLOW_PLANT" = true ]; }; then
	return_code=2
else
	if [ "$REMOTE_COMMAND" = set-policy ]; then
		REQUEST_LUCI=$ALLOW_LUCI; REQUEST_PLANT=$ALLOW_PLANT
		for flag in luci plant; do
			case "$flag" in luci) value=$REQUEST_LUCI ;; *) value=$REQUEST_PLANT ;; esac
			[ "$value" != true ] && value=0 || value=1
			set_candidate "tr3000-lite-remote.access.allow_$flag=$value"
		done
	fi
fi
refresh_transport
if [ "$AUTH_READY" = true ] && {
	{ [ "$DIRECT_ENABLED" = true ] && [ -n "$DIRECT_SOURCES" ]; } ||
	{ [ "$VPS_ENABLED" = true ] && [ -n "$VPS_SOURCES" ]; }
}; then
	APPLY_LUCI=$REQUEST_LUCI; APPLY_PLANT=$REQUEST_PLANT
fi
[ "$SOURCES_OK" = true ] || return_code=2
render_permissions
for package in firewall tr3000-lite-remote; do candidate_uci commit "$package" >/dev/null 2>&1 || fail_apply candidate_commit; done
[ "$input_fp" = "$(fingerprint)" ] || fail_apply input_changed
cache_valid=0
if owned_file "$RUNTIME/applied"; then
	read -r saved_fp saved_luci saved_plant saved_result < "$RUNTIME/applied" || :
	[ "${saved_fp:-}" != "$input_fp" ] || cache_valid=1
fi
if [ "$cache_valid" = 0 ] || ! cmp -s "$CONFIG/firewall" "$CANDIDATE/firewall" ||
	! cmp -s "$CONFIG/tr3000-lite-remote" "$CANDIDATE/tr3000-lite-remote"; then
	if command -v flock >/dev/null 2>&1; then exec 9>"$FW4_LOCK"; flock -x 9 || fail_apply firewall_busy; FW_LOCKED=1; fi
	[ ! -e "$OVERRIDES/firewall" ] && [ ! -L "$OVERRIDES/firewall" ] || fail_apply pending_state
	(umask 077; set -C; cat "$CANDIDATE/firewall" > "$OVERRIDES/firewall") || fail_apply candidate_override
	OVERRIDE=1
	fw4 check >/dev/null 2>&1 || fail_apply candidate_firewall
	remove_override || fail_apply candidate_cleanup
	[ "$input_fp" = "$(fingerprint)" ] || fail_apply input_changed
	for package in firewall tr3000-lite-remote; do cp -p "$CANDIDATE/$package" "$CONFIG/$package" || fail_apply config_install; done
	fw4 reload >/dev/null 2>&1 || fail_apply firewall_reload
	fw4 check >/dev/null 2>&1 || fail_apply firewall_verification
fi
# Publish only a successfully applied public permission state, never key material.
tmp=$(mktemp "$RUNTIME/.applied.XXXXXX") || fail_apply state_write
printf '%s %s %s %s\n' "$(fingerprint)" "$APPLY_LUCI" "$APPLY_PLANT" "$RESULT" > "$tmp" &&
	mv -f "$tmp" "$RUNTIME/applied" || fail_apply state_write
EFFECTIVE_LUCI=$APPLY_LUCI; EFFECTIVE_PLANT=$APPLY_PLANT
emit
exit "$return_code"
