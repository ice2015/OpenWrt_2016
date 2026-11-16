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

# nftables payloads are DROP-only guards placed before fw4's established accept.
# Valid traffic falls through to normal UCI policy; these never grant access.
remote_nft_sources() (
	validated=$(printf '%s' "$1" | remote_source_set) || return 1
	[ -n "$validated" ] || return 1
	printf '{ '; separator=
	for source in $validated; do printf '%s%s' "$separator" "$source"; separator=', '; done
	printf ' }'
)
remote_guard_input() (
	case "$1:$2" in wg_direct:true|wg_direct:false|wg_vps:true|wg_vps:false) ;; *) return 2 ;; esac
	role=$1
	if [ "$2" = false ]; then printf 'iifname "%s" tcp dport 443 drop\n' "$role"; return; fi
	sources=$(remote_nft_sources "$3") && remote_valid_source "$4" || return 2
	printf 'iifname "%s" meta nfproto != ipv4 tcp dport 443 drop\n' "$role"
	printf 'iifname "%s" tcp dport 443 ip saddr != %s drop\n' "$role" "$sources"
	printf 'iifname "%s" tcp dport 443 ip daddr != %s drop\n' "$role" "$4"
)
remote_guard_forward() (
	case "$1:$2" in wg_direct:true|wg_direct:false|wg_vps:true|wg_vps:false) ;; *) return 2 ;; esac
	role=$1
	if [ "$2" = false ]; then printf 'iifname "%s" drop\noifname "%s" drop\n' "$role" "$role"; return; fi
	sources=$(remote_nft_sources "$3") && lite_valid_cidr "$4" || return 2
	printf 'iifname "%s" meta nfproto != ipv4 drop\n' "$role"
	printf 'iifname "%s" ip saddr != %s drop\n' "$role" "$sources"
	printf 'iifname "%s" ip daddr != %s drop\n' "$role" "$4"
	printf 'iifname "%s" meta l4proto != { tcp, icmp } drop\n' "$role"
	printf 'iifname "%s" ip protocol icmp icmp type != echo-request drop\n' "$role"
	printf 'oifname "%s" meta nfproto != ipv4 drop\n' "$role"
	printf 'oifname "%s" ip saddr != %s drop\n' "$role" "$4"
	printf 'oifname "%s" ip daddr != %s drop\n' "$role" "$sources"
	printf 'oifname "%s" ct state != { established, related } drop\n' "$role"
	printf 'oifname "%s" ct direction != reply drop\n' "$role"
	printf 'oifname "%s" meta l4proto != { tcp, icmp } drop\n' "$role"
)

# Atomic replacement cannot follow an existing leaf symlink. Callers validate
# the fixed, root-owned private parent before using this internal helper.
remote_install_guard() (
	tmp_guard=$(mktemp "$(dirname "$2")/.remote-guard.XXXXXX") || return 1
	trap 'rm -f "$tmp_guard"' EXIT
	chmod 0600 "$tmp_guard" && cp "$1" "$tmp_guard" && mv -f "$tmp_guard" "$2"
)
