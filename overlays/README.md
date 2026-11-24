# Root filesystem overlays

Place shared files in `common/files/` and hardware-specific files in repository-root `devices/<device-id>/files/` (TR3000 uses `devices/tr3000/shared/files/` followed by `devices/tr3000/{lite,full}/files/`; legacy `overlays/devices/` remains valid for unmigrated devices). They are applied in common, distribution, device, then local order.

Do not store credentials or private network configuration in tracked overlays.

