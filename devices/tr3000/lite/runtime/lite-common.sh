#!/bin/sh
# Repository-only library bridge; firmware installs shared/runtime/lite-common.sh.
. "$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE:-$0}")/../../shared/runtime" && pwd)/lite-common.sh"
