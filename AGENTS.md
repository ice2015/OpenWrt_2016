# AI contributor guide

This repository describes reproducible OpenWrt and ImmortalWrt builds. Read the selected files under `manifests/` and `docs/configuration-layers.md` before changing a target.

## Rules

- Keep precedence as `common → distribution → device → local`.
- Put device-only changes under that device's config, overlay, or patch directory.
- Do not edit generated content under `work/`, `output/`, or `cache/`.
- Never commit secrets, private keys, passwords, Wi-Fi credentials, or files under `local/` other than its README.
- Preserve native OpenWrt `CONFIG_...` syntax and explain intentional overrides.
- Do not alter unrelated device profiles while working on one device.
- Leave unknown target profiles and source revisions explicitly unresolved; never guess values for firmware builds.

## Required checks

Run these commands after relevant changes:

```sh
bash scripts/validate.sh
python -m unittest discover -s tests -v
```

GitHub Actions is the primary build environment. Local firmware compilation is supported only from Linux or WSL2, not native Windows.

