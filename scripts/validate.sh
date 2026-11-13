#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"

if [[ "${1:-}" == "--help" ]]; then
  printf 'Usage: %s [--help]\n' "$(basename "$0")"
  exit 0
fi
(($# == 0)) || die "unexpected argument: $1"
manifest validate

