#!/usr/bin/env bash
set -Eeuo pipefail

COMMON_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="$(cd -- "$COMMON_DIR/../.." && pwd -P)"
PYTHON_BIN="${PYTHON:-python3}"

die() {
  local message="$1"
  local status="${2:-2}"
  printf 'Error: %s\n' "$message" >&2
  exit "$status"
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "required command not found: $1"
}

manifest() {
  "$PYTHON_BIN" "$PROJECT_ROOT/tools/manifest.py" --root "$PROJECT_ROOT" "$@"
}

parse_target_args() {
  DISTRIBUTION=""
  DEVICE=""
  REVISION=""
  while (($#)); do
    case "$1" in
      --distribution)
        (($# >= 2)) || die "--distribution requires a value"
        DISTRIBUTION="$2"
        shift 2
        ;;
      --device)
        (($# >= 2)) || die "--device requires a value"
        DEVICE="$2"
        shift 2
        ;;
      --revision)
        (($# >= 2)) || die "--revision requires a value"
        REVISION="$2"
        shift 2
        ;;
      *)
        die "unknown argument: $1"
        ;;
    esac
  done
  [[ -n "$DISTRIBUTION" ]] || die "--distribution is required"
  [[ -n "$DEVICE" ]] || die "--device is required"
}

require_build_ready() {
  local arguments=(
    resolve
    --distribution "$DISTRIBUTION"
    --device "$DEVICE"
    --require-build-ready
  )
  if [[ -n "$REVISION" ]]; then
    arguments+=(--revision "$REVISION")
  fi
  manifest "${arguments[@]}"
}

assert_generated_root() {
  case "$1" in
    work|output|cache) ;;
    *) die "expected one of: work, output, cache" ;;
  esac
  local target="$PROJECT_ROOT/$1"
  [[ ! -L "$target" ]] || die "refusing to clean symlink: $target"
  printf '%s\n' "$target"
}

