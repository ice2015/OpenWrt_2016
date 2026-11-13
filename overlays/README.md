# Root filesystem overlays

Place shared files in `common/files/` and hardware-specific files in `devices/<device-id>/files/`. They are applied in common, distribution, device, then local order.

Do not store credentials or private network configuration in tracked overlays.

