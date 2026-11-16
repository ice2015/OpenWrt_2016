#!/bin/sh
# Pure typed DDNS metadata predicates, never provider API calls or log parsers.
ddns_uint() {
	case "${1:-}" in ''|*[!0-9]*|0[0-9]*) return 1 ;; esac
	[ "${#1}" -le 10 ]
}
ddns_valid_hostname() (
	name=${1:-}
	case "$name" in *.*) ;; *) return 1 ;; esac
	case "$name" in ''|.*|*.|*[!A-Za-z0-9.-]*) return 1 ;; esac
	[ "${#name}" -le 253 ] || return 1
	lite_valid_ipv4 "$name" && return 1
	IFS=.; set -- $name
	for label do
		case "$label" in ''|-*|*-) return 1 ;; esac
		[ "${#label}" -le 63 ] || return 1
	done
)
ddns_cloudflare_domain() (
	case "$1" in *@*@*|*/*|*[!A-Za-z0-9.@-]*) return 1 ;; *@*) ;; *) return 1 ;; esac
	prefix=${1%@*}; zone=${1#*@}
	ddns_valid_hostname "$zone" || return 1
	[ -n "$prefix" ] && fqdn="$prefix.$zone" || fqdn=$zone
	ddns_valid_hostname "$fqdn" || return 1
	[ "$(printf '%s' "$fqdn" | tr '[:upper:]' '[:lower:]')" = "$(printf '%s' "$2" | tr '[:upper:]' '[:lower:]')" ]
)
ddns_wan_scope() (
	[ -n "${1:-}" ] || { printf 'missing\n'; return; }
	set -f; IFS=.; set -- $1
	[ "$#" = 4 ] || { printf 'reserved\n'; return; }
	for octet do
		case "$octet" in ''|*[!0-9]*|0[0-9]*) printf 'reserved\n'; return ;; esac
		if [ "${#octet}" -gt 3 ] || [ "$octet" -gt 255 ]; then printf 'reserved\n'; return; fi
	done
	if [ "$1" = 127 ]; then printf 'loopback\n'
	elif [ "$1:$2" = 169:254 ]; then printf 'link_local\n'
	elif [ "$1" = 10 ] || [ "$1:$2" = 192:168 ] ||
		{ [ "$1" = 172 ] && [ "$2" -ge 16 ] && [ "$2" -le 31 ]; }; then printf 'private\n'
	elif [ "$1" = 100 ] && [ "$2" -ge 64 ] && [ "$2" -le 127 ]; then printf 'cgnat\n'
	elif [ "$1" = 0 ] || [ "$1" -ge 224 ] ||
		[ "$1:$2:$3" = 192:0:0 ] || [ "$1:$2:$3" = 192:0:2 ] ||
		[ "$1:$2:$3" = 192:88:99 ] || [ "$1:$2:$3" = 198:51:100 ] ||
		[ "$1:$2:$3" = 203:0:113 ] ||
		{ [ "$1" = 198 ] && [ "$2" -ge 18 ] && [ "$2" -le 19 ]; }; then printf 'reserved\n'
	else printf 'global\n'; fi
)
