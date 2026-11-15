#!/bin/sh
# Pure helpers; runtime paths and side effects belong to the controller.
plant_test_mode_allowed() {
	case "$1" in
		/usr/sbin/tr3000-lite-plant) return 1 ;;
		tr3000-lite-plant.sh|*/tr3000-lite-plant.sh) [ "$2" = 1 ] ;;
		*) return 1 ;;
	esac
}

plant_json_string() {
	printf '%s' "$1" | awk '
		BEGIN { printf "\""; for (i=1; i<32; i++) control[sprintf("%c", i)]=i }
		{ if (NR > 1) printf "\\n"
		  for (i=1; i<=length($0); i++) {
			c=substr($0,i,1)
			if (c == "\\") printf "\\\\"
			else if (c == "\"") printf "\\\""
			else if (c in control) printf "\\u%04x", control[c]
			else printf "%s", c
		  }
		} END { printf "\"" }'
}

plant_usage() {
	printf 'Usage: %s status --json | validate --address IPV4/PREFIX | apply --address IPV4/PREFIX --allow-luci true|false --allow-mgmt true|false | restore --backup-id SAFE_ID\n' "$0"
}

plant_safe_id() {
	case "$1" in ''|*[!A-Za-z0-9_-]*) return 1 ;; esac
	[ "${#1}" -le 80 ]
}

plant_parse() {
	COMMAND=${1:-}; [ "$#" -gt 0 ] && shift
	ADDRESS=; ALLOW_LUCI=; ALLOW_MGMT=; BACKUP_ID=; JSON=
	while [ "$#" -gt 0 ]; do
		# Every option with a value requires a nonempty value; an empty first
		# occurrence must not evade the repeated-option checks below.
		case "$1" in
			--address|--allow-luci|--allow-mgmt|--backup-id) [ "$#" -ge 2 ] && [ -n "$2" ] || return 1 ;;
		esac
		case "$COMMAND:$1" in
			status:--json) [ -z "$JSON" ] || return 1; JSON=1; shift ;;
			validate:--address|apply:--address) [ "$#" -ge 2 ] && [ -z "$ADDRESS" ] || return 1; ADDRESS=$2; shift 2 ;;
			apply:--allow-luci) [ "$#" -ge 2 ] && [ -z "$ALLOW_LUCI" ] || return 1; ALLOW_LUCI=$2; shift 2 ;;
			apply:--allow-mgmt) [ "$#" -ge 2 ] && [ -z "$ALLOW_MGMT" ] || return 1; ALLOW_MGMT=$2; shift 2 ;;
			restore:--backup-id) [ "$#" -ge 2 ] && [ -z "$BACKUP_ID" ] || return 1; BACKUP_ID=$2; shift 2 ;;
			*) return 1 ;;
		esac
	done
	case "$COMMAND" in
		status) [ "$JSON" = 1 ] ;;
		validate) [ -n "$ADDRESS" ] ;;
		apply) [ -n "$ADDRESS" ] || return 1
			case "$ALLOW_LUCI:$ALLOW_MGMT" in true:true|true:false|false:true|false:false) return 0 ;; *) return 1 ;; esac ;;
		restore) plant_safe_id "$BACKUP_ID" ;;
		*) return 1 ;;
	esac
}

plant_network_cidr() {
	plant_number=$(lite_ipv4_number "${1%/*}")
	plant_mask=$(lite_prefix_mask "${1#*/}")
	plant_number=$((plant_number & plant_mask))
	printf '%s.%s.%s.%s/%s\n' $(((plant_number >> 24) & 255)) $(((plant_number >> 16) & 255)) $(((plant_number >> 8) & 255)) $((plant_number & 255)) "${1#*/}"
}

plant_netmask_prefix() {
	plant_prefix_index=0
	while [ "$plant_prefix_index" -le 32 ]; do
		if [ "$(lite_prefix_to_netmask "$plant_prefix_index")" = "$1" ]; then
			printf '%s\n' "$plant_prefix_index"
			return 0
		fi
		plant_prefix_index=$((plant_prefix_index+1))
	done
	printf 'null\n'
}

if [ "${1:-}" = --help ]; then plant_usage; fi
