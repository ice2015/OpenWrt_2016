#!/bin/sh
set -eu

usage() {
	printf 'Usage: %s status [--json]\n' "$0"
	printf '       %s enable|disable wireguard|tailscale|sing-box|cloudflared\n' "$0"
}

usage_fail() {
	printf 'Error: %s\n' "$*" >&2
	exit 2
}

known_service() {
	case "$1" in
		wireguard|tailscale|sing-box|cloudflared) return 0 ;;
		*) return 1 ;;
	esac
}

json_boolean() {
	if "$@" >/dev/null 2>&1; then
		printf true
	else
		printf false
	fi
}

init_installed() {
	[ -x "/etc/init.d/$1" ]
}

init_enabled() {
	init_installed "$1" && "/etc/init.d/$1" enabled
}

init_running() {
	init_installed "$1" && command -v ubus >/dev/null 2>&1 &&
		ubus call service list "{\"name\":\"$1\"}" 2>/dev/null |
		grep -Eq '"running"[[:space:]]*:[[:space:]]*true'
}

wireguard_section() {
	command -v uci >/dev/null 2>&1 || return 1
	uci show firewall 2>/dev/null |
		sed -n "s/^\(firewall\.[^.]*\)\.name='Allow-WireGuard-listener-disabled-by-default'$/\1/p" |
		head -n 1
}

wireguard_installed() {
	command -v uci >/dev/null 2>&1 &&
		[ "$(uci -q get network.wg.proto 2>/dev/null || :)" = wireguard ]
}

wireguard_enabled() {
	SECTION=$(wireguard_section) || return 1
	[ -n "$SECTION" ] || return 1
	[ "$(uci -q get "$SECTION.enabled" 2>/dev/null || printf 0)" = 1 ]
}

wireguard_running() {
	command -v ifstatus >/dev/null 2>&1 &&
		ifstatus wg 2>/dev/null | grep -Eq '"up"[[:space:]]*:[[:space:]]*true'
}

print_json_status() {
	printf '{'
	printf '"wireguard":{"installed":%s,"enabled":%s,"running":%s},' \
		"$(json_boolean wireguard_installed)" \
		"$(json_boolean wireguard_enabled)" \
		"$(json_boolean wireguard_running)"
	printf '"tailscale":{"installed":%s,"enabled":%s,"running":%s},' \
		"$(json_boolean init_installed tailscale)" \
		"$(json_boolean init_enabled tailscale)" \
		"$(json_boolean init_running tailscale)"
	printf '"sing-box":{"installed":%s,"enabled":%s,"running":%s},' \
		"$(json_boolean init_installed sing-box)" \
		"$(json_boolean init_enabled sing-box)" \
		"$(json_boolean init_running sing-box)"
	printf '"cloudflared":{"installed":%s,"enabled":%s,"running":%s}' \
		"$(json_boolean init_installed cloudflared)" \
		"$(json_boolean init_enabled cloudflared)" \
		"$(json_boolean init_running cloudflared)"
	printf '}\n'
}

set_wireguard() {
	ACTION=$1
	SECTION=$(wireguard_section) || usage_fail "firewall configuration is unavailable"
	[ -n "$SECTION" ] || usage_fail "WireGuard listener firewall rule was not found"
	if [ "$ACTION" = enable ]; then
		wireguard_installed || usage_fail "network.wg is not configured"
		uci set "$SECTION.enabled=1"
	else
		uci set "$SECTION.enabled=0"
	fi
	uci commit firewall
	command -v fw4 >/dev/null 2>&1 || usage_fail "fw4 is required"
	fw4 check
	/etc/init.d/firewall reload
	if [ "$ACTION" = enable ]; then
		ifup wg
	else
		ifdown wg >/dev/null 2>&1 || :
	fi
}

ACTION=${1:-}
[ -n "$ACTION" ] || { usage >&2; exit 2; }
shift
case "$ACTION" in
	status)
		[ "$#" -eq 0 ] || { [ "$#" -eq 1 ] && [ "$1" = --json ]; } || usage_fail "status accepts only --json"
		print_json_status
		;;
	enable|disable)
		[ "$#" -eq 1 ] || usage_fail "$ACTION requires exactly one service"
		SERVICE=$1
		known_service "$SERVICE" || usage_fail "unknown service: $SERVICE"
		if [ "$SERVICE" = wireguard ]; then
			set_wireguard "$ACTION"
		else
			if ! init_installed "$SERVICE"; then
				[ "$ACTION" = disable ] && exit 0
				usage_fail "service is not installed: $SERVICE"
			fi
			if [ "$ACTION" = enable ]; then
				"/etc/init.d/$SERVICE" enable
				"/etc/init.d/$SERVICE" start
			else
				"/etc/init.d/$SERVICE" stop >/dev/null 2>&1 || :
				"/etc/init.d/$SERVICE" disable
			fi
		fi
		;;
	--help) usage ;;
	*) usage_fail "unknown action: $ACTION" ;;
esac
