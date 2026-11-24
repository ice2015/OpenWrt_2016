#!/bin/sh
# Staging and device enrollment tool for TR3000 Lite.
PATH="/usr/sbin:/usr/bin:/sbin:/bin:${PATH:-}"
export PATH
set -eu

usage() {
	printf 'Usage: %s prepare --device-id ID [--json] | apply --bundle DIR [--json] | verify [--json]\n' "$0"
}

ROOT_PREFIX="${ENROLL_ROOT:-}"
STATE="$ROOT_PREFIX/etc/tr3000-lite"
CONFIG="$ROOT_PREFIX/etc/config"

remote_valid_id() {
	case "${1:-}" in ''|[-_]*|*[!A-Za-z0-9_-]*) return 1 ;; esac
	[ "${#1}" -le 64 ]
}

cmd="${1:-}"
[ -n "$cmd" ] || { usage; exit 2; }
[ "$cmd" != "--help" ] && [ "$cmd" != "-h" ] || { usage; exit 0; }
shift

case "$cmd" in
	prepare)
		device_id=""
		json_output=false
		while [ "$#" -gt 0 ]; do
			case "$1" in
				--device-id)
					[ "$#" -ge 2 ] || { usage; exit 2; }
					device_id="$2"
					shift 2
					;;
				--json)
					json_output=true
					shift
					;;
				*)
					usage
					exit 2
					;;
			esac
		done
		[ -n "$device_id" ] || { usage; exit 2; }
		remote_valid_id "$device_id" || {
			printf 'Error: invalid device-id: %s\n' "$device_id" >&2
			exit 2
		}

		# Refuse if already enrolled
		if [ -f "$STATE/enrolled" ]; then
			printf 'Error: device is already enrolled\n' >&2
			exit 1
		fi

		mkdir -p "$STATE/keys"
		chmod 0700 "$STATE" "$STATE/keys" 2>/dev/null || :

		printf '%s\n' "$device_id" > "$STATE/device-id"
		chmod 0600 "$STATE/device-id"

		if [ ! -f "$STATE/keys/direct.key" ]; then
			wg genkey > "$STATE/keys/direct.key"
			chmod 0600 "$STATE/keys/direct.key"
		fi

		if [ ! -f "$STATE/keys/vps.key" ]; then
			wg genkey > "$STATE/keys/vps.key"
			chmod 0600 "$STATE/keys/vps.key"
		fi

		direct_pub=$(wg pubkey < "$STATE/keys/direct.key")
		vps_pub=$(wg pubkey < "$STATE/keys/vps.key")

		if [ "$json_output" = true ]; then
			printf '{"schema_version":1,"device_id":"%s","enrolled":false,"public_keys":{"direct":"%s","vps":"%s"}}\n' \
				"$device_id" "$direct_pub" "$vps_pub"
		else
			printf 'Device ID: %s\nDirect Public Key: %s\nVPS Public Key: %s\n' \
				"$device_id" "$direct_pub" "$vps_pub"
		fi
		;;

	apply)
		bundle_dir=""
		json_output=false
		while [ "$#" -gt 0 ]; do
			case "$1" in
				--bundle)
					[ "$#" -ge 2 ] || { usage; exit 2; }
					bundle_dir="$2"
					shift 2
					;;
				--json)
					json_output=true
					shift
					;;
				*)
					usage
					exit 2
					;;
			esac
		done
		[ -n "$bundle_dir" ] && [ -d "$bundle_dir" ] || {
			printf 'Error: invalid bundle directory\n' >&2
			exit 2
		}

		manifest="$bundle_dir/manifest.json"
		[ -f "$manifest" ] || {
			printf 'Error: missing manifest.json in bundle\n' >&2
			exit 1
		}

		# Read target device_id from manifest
		target_id=$(jsonfilter -i "$manifest" -e '@.device_id' 2>/dev/null || :)
		expected_id=""
		[ ! -f "$STATE/device-id" ] || expected_id=$(cat "$STATE/device-id")
		if [ -n "$expected_id" ] && [ "$target_id" != "$expected_id" ]; then
			printf 'Error: bundle device_id %s does not match device %s\n' "$target_id" "$expected_id" >&2
			exit 1
		fi

		# Verify files listed in manifest
		for f in "$bundle_dir"/*; do
			[ -f "$f" ] || continue
			fname=$(basename "$f")
			[ "$fname" != "manifest.json" ] || continue
			# Extract expected sha256 using jsonfilter
			expected_sha=$(jsonfilter -i "$manifest" -e "@.files['$fname'].sha256" 2>/dev/null || :)
			if [ -z "$expected_sha" ]; then
				printf 'Error: unlisted file in bundle: %s\n' "$fname" >&2
				exit 1
			fi
			actual_sha=$(sha256sum "$f" | cut -d ' ' -f1)
			if [ "$actual_sha" != "$expected_sha" ]; then
				printf 'Error: checksum mismatch for %s\n' "$fname" >&2
				exit 1
			fi
		done

		# Apply bundle files
		mkdir -p "$CONFIG"
		for f in "$bundle_dir"/*; do
			[ -f "$f" ] || continue
			fname=$(basename "$f")
			case "$fname" in
				manifest.json) ;;
				ddns|network|tr3000-lite-remote|firewall)
					cp -p "$f" "$CONFIG/$fname"
					chmod 0600 "$CONFIG/$fname"
					;;
			esac
		done

		if [ "$json_output" = true ]; then
			printf '{"schema_version":1,"success":true}\n'
		else
			printf 'Bundle applied successfully for device %s\n' "$target_id"
		fi
		;;

	verify)
		json_output=false
		while [ "$#" -gt 0 ]; do
			case "$1" in
				--json)
					json_output=true
					shift
					;;
				*)
					usage
					exit 2
					;;
			esac
		done

		# Gates check:
		# 1. Device ID exists
		[ -f "$STATE/device-id" ] || {
			printf 'Error: device-id missing\n' >&2
			exit 1
		}
		# 2. Keys exist
		[ -f "$STATE/keys/direct.key" ] && [ -f "$STATE/keys/vps.key" ] || {
			printf 'Error: device keys missing\n' >&2
			exit 1
		}
		# 3. AP initialized marker exists
		[ -f "$STATE/management-ap.initialized" ] || {
			printf 'Error: management AP not initialized\n' >&2
			exit 1
		}
		# 4. Check remote status
		remote_status=$(tr3000-lite-remote status --json 2>/dev/null || :)
		if [ -n "$remote_status" ]; then
			check_res=$(printf '%s\n' "$remote_status" | sed -n 's/.*"result"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n1)
			if [ "$check_res" != "ok" ]; then
				printf 'Error: remote controller status check failed: %s\n' "$check_res" >&2
				exit 1
			fi
		fi

		# Mark enrolled
		touch "$STATE/enrolled"
		chmod 0600 "$STATE/enrolled"

		if [ "$json_output" = true ]; then
			printf '{"schema_version":1,"verified":true,"enrolled":true}\n'
		else
			printf 'Device enrollment verified and completed.\n'
		fi
		;;

	*)
		usage
		exit 2
		;;
esac
