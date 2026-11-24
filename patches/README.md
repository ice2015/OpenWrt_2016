# Patch layers

Store patches under `common/`, `distributions/<distribution-id>/`, or `devices/<device-id>/`. Prefix patch filenames with an ordering number such as `010-description.patch`.

New device-owned patches live under repository-root `devices/<device-id>/patches/` or `devices/<device-id>/<variant>/patches/`. TR3000 Lite's DDNS patch is in `devices/tr3000/lite/patches/ddns/`; legacy device patch-layer paths remain supported for unmigrated targets.

Every patch should state its upstream status and the source revision range it supports.

