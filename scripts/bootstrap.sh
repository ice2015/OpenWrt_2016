#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"

if [[ "${1:-}" == "--help" ]]; then
  printf 'Usage: %s --distribution ID --device ID [--revision REV]\n' "$(basename "$0")"
  exit 0
fi
parse_target_args "$@"
require_build_ready
printf 'Bootstrap stage is not implemented in the initial scaffold.\n' >&2
exit 4

