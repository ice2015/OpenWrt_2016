#!/bin/sh
# Host compatibility entry; never installed into firmware.
REPO_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
exec sh "$REPO_ROOT/devices/tr3000/shared/runtime/plant-access.sh" "$@"
