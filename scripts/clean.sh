#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"

if [[ "${1:-}" == "--help" ]]; then
  printf 'Usage: %s {work|output|cache}\n' "$(basename "$0")"
  exit 0
fi
(($# == 1)) || die "expected one of: work, output, cache"
target="$(assert_generated_root "$1")"
if [[ -e "$target" ]]; then
  rm -rf -- "$target"
  printf 'Removed %s\n' "$target"
else
  printf 'Nothing to remove: %s\n' "$target"
fi

