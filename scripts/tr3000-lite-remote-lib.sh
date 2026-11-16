#!/bin/sh
# Pure Lite remote-validation helpers. Source lite-common.sh first.
remote_valid_source() {
	case "${1:-}" in */32) ;; *) return 1 ;; esac
	lite_valid_ipv4 "${1%/32}"
}

# Validate the COMPLETE candidate before returning even one authorized source.
# One source per line; empty input is an empty set, not an unrestricted zone.
remote_source_set() (
	set -f
	seen=
	while IFS= read -r source || [ -n "$source" ]; do
		remote_valid_source "$source" || return 1
		case " $seen " in *" $source "*) return 1 ;; esac
		seen="$seen $source"
	done
	for source in $seen; do printf '%s\n' "$source"; done | LC_ALL=C sort
)

# Serialization shape only; runtime enrollment must also validate real key/config
# identity and ownership. Never print key material from this predicate.
remote_key_format() {
	[ "$#" -eq 1 ] || return 1
	[ "${#1}" -eq 44 ] || return 1
	case "$1" in *=) ;; *) return 1 ;; esac
	case "${1%=}" in *[!A-Za-z0-9+/]*) return 1 ;; esac
}

remote_valid_id() {
	case "${1:-}" in ''|[-_]*|*[!A-Za-z0-9_-]*) return 1 ;; esac
	[ "${#1}" -le 64 ]
}

remote_parse() {
	REMOTE_COMMAND=${1:-}; ALLOW_LUCI=; ALLOW_PLANT=
	[ "$#" -gt 0 ] || return 1
	shift
	case "$REMOTE_COMMAND" in
		status) [ "$#" -eq 1 ] && [ "$1" = --json ] ;;
		sync) [ "$#" -eq 0 ] ;;
		set-policy)
			seen_luci=0; seen_plant=0
			while [ "$#" -gt 0 ]; do
				[ "$#" -ge 2 ] || return 1
				case "$2" in true|false) ;; *) return 1 ;; esac
				case "$1" in
					--allow-luci) [ "$seen_luci" = 0 ] || return 1; seen_luci=1; ALLOW_LUCI=$2 ;;
					--allow-plant) [ "$seen_plant" = 0 ] || return 1; seen_plant=1; ALLOW_PLANT=$2 ;;
					*) return 1 ;;
				esac
				shift 2
			done
			[ "$seen_luci:$seen_plant" = 1:1 ]
			;;
		*) return 1 ;;
	esac
}
