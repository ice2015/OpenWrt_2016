# OpenWrt Flash TR3000 Project Integration Design

## Intent

Extend the project-local `openwrt-flash` skill so it can safely interpret the Cudy TR3000 firmware and DHCP U-Boot artifacts actually produced by this repository's GitHub Actions workflows.

## Scope

- Add one project-specific reference page for Cudy TR3000 v1.
- Route Cudy TR3000, project GitHub Actions artifacts, Lite firmware, and DHCP U-Boot requests from `SKILL.md` to that page.
- Cover only the implemented 128 MiB outputs: the 112 MiB UBI Lite sysupgrade artifact and the independent multi-layout BL2/FIP artifact.
- Mark generic TR3000, TR3000 Full, TR3000 256 MiB, and new-flash-batch support as unavailable unless a matching workflow and verified artifact exist.
- Preserve the generic flashing workflow and keep firmware and bootloader authorization separate.

## Safety Boundaries

- Never present a successful Actions build as proof that an artifact is safe for a particular router.
- Never mix 128 MiB U-Boot Mod, factory 128 MiB, 256 MiB, or other UBI layouts.
- Do not invent MTD targets, offsets, erase/write commands, or recovery steps.
- Require hardware identity, current layout, NAND identity, backups, hashes, local recovery access, and an explicit destructive-write authorization before bootloader work.
- Treat the project's generic TR3000 manifest `UNRESOLVED` state as intentional and separate from the pinned Lite/U-Boot workflows.

## Approach

Keep repository-specific facts in `references/cudy-tr3000-project.md` and add a narrow routing row plus trigger keywords to `SKILL.md`. Add a repository test that asserts the reference, artifact names, workflow boundaries, unsupported variants, and safety language. Validate with baseline and revised-skill scenarios, then run the repository's required checks.

## Non-goals

- Do not add or change firmware/U-Boot build workflows.
- Do not resolve the generic TR3000 manifest.
- Do not add 256 MiB, Full, factory-layout, or new-NAND support.
- Do not provide executable flash-writing commands.

