# OpenWrt Flash TR3000 Project Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Teach the project-local `openwrt-flash` skill to safely interpret this repository's Cudy TR3000 Lite firmware and DHCP U-Boot GitHub Actions artifacts.

**Architecture:** Keep the general flashing workflow concise and route project-specific Cudy TR3000 requests to one focused reference page. Pin the reference to repository facts already enforced by workflows and scripts, and add structural tests so unsupported variants or unsafe artifact claims cannot silently appear.

**Tech Stack:** Markdown skill files, Python `unittest`, GitHub Actions workflow metadata

**Spec:** `docs/superpowers/specs/2026-11-13-openwrt-flash-tr3000-project-design.md`

## Global Constraints

- Preserve `common → distribution → device → local`; this task changes only the project-local skill and its test.
- Do not edit generated content under `work/`, `output/`, or `cache/`.
- Do not modify firmware/U-Boot workflows, manifests, configurations, packages, or unrelated user changes.
- Cover only Cudy TR3000 v1 128 MiB outputs already produced by `build-lite.yml` and `build-uboot.yml`.
- Do not add flash-writing commands, partition numbers, offsets, or claims of real-device validation.

## Review Focus

- A 256 MiB TR3000 request must be blocked from using either current project artifact.
- A post-batch-2544/new-NAND 128 MiB device must not be treated as covered without matching evidence.
- Lite sysupgrade and BL2/FIP must remain separate artifacts with separate authorization.
- Generic TR3000 `UNRESOLVED` must not be presented as resolved by the pinned Lite workflow.
- An Actions success must not be described as device compatibility or flashing proof.

---

### Task 1: Establish failing skill tests and baseline scenarios

**Files:**
- Create: `tests/skills/test_openwrt_flash_skill.py`
- Create: `.agents/skills/openwrt-flash-workspace/skill-snapshot/`
- Create: `.agents/skills/openwrt-flash-workspace/iteration-1/`

**Interfaces:**
- Consumes: existing `.agents/skills/openwrt-flash/` and repository workflows/docs.
- Produces: assertions and baseline evidence that fail because project-aware TR3000 guidance is absent.

- [ ] **Step 1: Snapshot the current skill before editing**

Copy the complete `openwrt-flash` directory to the workspace snapshot without modifying the source.

- [ ] **Step 2: Add the failing repository test**

Assert that `SKILL.md` routes Cudy TR3000 requests to `references/cudy-tr3000-project.md`; assert that the reference names both workflow/artifact pairs, distinguishes firmware from BL2/FIP, blocks 256 MiB/new-NAND/Full/generic unresolved use, and contains no executable raw-flash instructions.

- [ ] **Step 3: Run the focused test and verify RED**

Run: `python -m unittest tests.skills.test_openwrt_flash_skill -v`

Expected: FAIL because the reference and routing do not exist.

- [ ] **Step 4: Run three old-skill scenarios**

Test project Artifact selection for a verified 128 MiB U-Boot Mod router, rejection for a 256 MiB router, and separation of U-Boot build success from device flashing authorization. Save outputs and exact gaps under `iteration-1`.

### Task 2: Add the project-aware Cudy TR3000 reference

**Files:**
- Modify: `.agents/skills/openwrt-flash/SKILL.md`
- Create: `.agents/skills/openwrt-flash/references/cudy-tr3000-project.md`

**Interfaces:**
- Consumes: `.github/workflows/build-lite.yml`, `.github/workflows/build-uboot.yml`, `docs/LITE-README.md`, `docs/UBOOT-SAFETY.md`, and the design safety boundaries.
- Produces: a deterministic route and a project-specific decision/reference page.

- [ ] **Step 1: Update skill discovery and routing**

Make the description start with `Use when...`, include Cudy TR3000/project GitHub Actions artifact triggers only, and add one routing-table row to the new reference.

- [ ] **Step 2: Write the reference page**

Document exact implemented workflow names, artifact names, hardware/layout scope, artifact contents and roles, provenance/hash checks, preflight evidence, separate authorization, unsupported variants, and post-flash verification. Link to repository files using relative paths.

- [ ] **Step 3: Run the focused test and verify GREEN**

Run: `python -m unittest tests.skills.test_openwrt_flash_skill -v`

Expected: PASS.

### Task 3: Verify behavior and repository integrity

**Files:**
- Update: `.agents/skills/openwrt-flash-workspace/iteration-1/`

**Interfaces:**
- Consumes: revised skill and Task 1 scenarios.
- Produces: with-skill comparison evidence and repository verification results.

- [ ] **Step 1: Re-run the same three scenarios with the revised skill**

Verify correct artifact selection, explicit rejection of unsupported variants, and no bootloader write instructions without device evidence and authorization.

- [ ] **Step 2: Run skill-focused and complete repository tests**

Run:

```sh
bash scripts/validate.sh
python -m unittest discover -s tests -v
```

Expected: both commands pass; report any pre-existing failure by name without altering unrelated files.

- [ ] **Step 3: Review the final diff**

Confirm only the approved skill, its test/evaluation evidence, design, and plan changed; preserve the existing modification in `tests/scripts/test_scripts.py`.

