# Multi-device OpenWrt Project Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an AI-friendly, GitHub Actions-first repository scaffold for layered OpenWrt and ImmortalWrt builds targeting TR3000, x86_64, and Raspberry Pi.

**Architecture:** Machine-readable device and source manifests select ordered common, distribution, device, and optional local layers. Python standard-library tooling validates and queries manifests, thin Bash entry points provide a stable CI/user interface, and GitHub Actions owns validation plus the future Linux firmware build path without duplicating script logic.

**Tech Stack:** Git, JSON manifests, Python 3 standard library, Bash, GitHub Actions YAML, native OpenWrt configuration fragments.

**Spec:** `docs/superpowers/specs/2026-11-13-multi-device-openwrt-project-design.md`

## Global Constraints

- GitHub Actions on GitHub-hosted Ubuntu is the primary build environment; native Windows compilation is unsupported.
- Keep upstream source, firmware output, caches, logs, secrets, and local overrides untracked.
- Configuration precedence is exactly `common → distribution → device → local untracked override`.
- Do not guess unresolved hardware revisions, native profiles, or source revisions; reject unresolved values before a build.
- Use native OpenWrt `CONFIG_...` fragments rather than inventing a configuration language.
- Build workflow YAML orchestrates repository scripts and must not duplicate their build logic.
- Initial delivery validates and discovers targets but does not claim to produce verified firmware.
- Initialize Git locally, but do not configure a remote.

## Review Focus

- An unknown distribution/device pair must fail before checkout or compilation; covered by Task 2 validation tests.
- A manifest containing placeholders in required build fields must remain listable but be rejected as build-ready; covered by Task 2 tests.
- A path reference escaping the repository or pointing to a missing layer must fail validation; covered by Task 2 tests.
- Pull requests from forks must not receive secrets or write permissions; covered by Task 4 workflow assertions.
- Cleanup must reject targets outside `work/`, `output/`, and `cache/`; covered by Task 3 shell interface tests.

---

### Task 1: Repository guardrails and layered directory contract

**Files:**
- Create: `.gitignore`
- Create: `.editorconfig`
- Create: `AGENTS.md`
- Create: `local/README.md`
- Create: `configs/common/base.config`
- Create: `configs/common/packages.config`
- Create: `configs/distributions/openwrt.config`
- Create: `configs/distributions/immortalwrt.config`
- Create: `configs/devices/tr3000.config`
- Create: `configs/devices/x86-64.config`
- Create: `configs/devices/raspberry-pi.config`
- Create: `feeds/common.conf`
- Create: `feeds/openwrt.conf`
- Create: `feeds/immortalwrt.conf`
- Create placeholder README files under `overlays/` and `patches/` extension directories
- Test: `tests/structure/test_repository_contract.py`

**Interfaces:**
- Consumes: the approved design document.
- Produces: stable layer paths used by device manifests and `PROJECT_ROOT` discovery through the repository root.

- [ ] **Step 1: Initialize Git without configuring a remote**

Run: `git init`
Expected: a local repository exists and `git remote -v` prints no remotes.

- [ ] **Step 2: Write failing repository-contract tests**

Add `unittest` cases asserting required layer files exist, generated directories match `.gitignore`, `local/README.md` is trackable while `local/*` overrides are ignored, and `AGENTS.md` names the validation command and forbidden generated directories.

- [ ] **Step 3: Run the contract test and verify it fails**

Run: `python -m unittest tests.structure.test_repository_contract -v`
Expected: FAIL for missing guardrail and layer files.

- [ ] **Step 4: Create the guardrails and conservative layer skeleton**

Keep tracked config fragments empty except for comments and demonstrative, non-opinionated native syntax; document the four-layer precedence in `AGENTS.md` and forbid secrets/generated-tree edits.

- [ ] **Step 5: Run the contract test and verify it passes**

Run: `python -m unittest tests.structure.test_repository_contract -v`
Expected: PASS.

- [ ] **Step 6: Commit the repository contract**

```bash
git add .gitignore .editorconfig AGENTS.md local configs feeds overlays patches tests
git commit -m "chore: establish layered repository contract"
```

### Task 2: Source/device manifests and zero-dependency validation

**Files:**
- Create: `manifests/sources.json`
- Create: `manifests/devices/tr3000.json`
- Create: `manifests/devices/x86-64.json`
- Create: `manifests/devices/raspberry-pi.json`
- Create: `tools/manifest.py`
- Create: `tests/manifest/test_manifest.py`

**Interfaces:**
- Consumes: stable repository layer paths from Task 1.
- Produces: `load_catalog(root: Path) -> Catalog`, `validate_catalog(catalog: Catalog, root: Path) -> list[str]`, `list_targets(catalog: Catalog) -> list[Target]`, and CLI commands `validate`, `list`, and `resolve --distribution ID --device ID --require-build-ready`.

- [ ] **Step 1: Write failing manifest tests**

Test parsing the three device IDs, deterministic distribution/device listing, invalid JSON, duplicate IDs, unknown distributions, missing/escaping layer paths, unsupported pairs, and build-readiness rejection for explicit `UNRESOLVED` source revision/profile fields.

- [ ] **Step 2: Run manifest tests and verify they fail**

Run: `python -m unittest tests.manifest.test_manifest -v`
Expected: FAIL because `tools.manifest` and manifests do not exist.

- [ ] **Step 3: Implement immutable manifest data types and catalog loading**

In `tools/manifest.py`, define `Source`, `Device`, `Target`, and `Catalog` dataclasses; use only `json`, `argparse`, `dataclasses`, and `pathlib` from the standard library.

- [ ] **Step 4: Implement catalog validation and CLI behavior**

Return all structural errors from `validate_catalog`; make CLI exit `0` only for valid requests, `2` for schema/reference errors, and `3` when `--require-build-ready` encounters an explicit unresolved field.

- [ ] **Step 5: Add initial manifests without guessing hardware values**

Use stable IDs `openwrt`, `immortalwrt`, `tr3000`, `x86-64`, and `raspberry-pi`; set unknown revisions/profiles to the exact string `UNRESOLVED`; reference ordered common, distribution, and device layers.

- [ ] **Step 6: Run manifest and repository tests**

Run: `python -m unittest discover -s tests -v`
Expected: PASS, including unresolved entries that validate structurally but fail only when build readiness is requested.

- [ ] **Step 7: Commit manifests and validation**

```bash
git add manifests tools tests
git commit -m "feat: add device manifests and validation"
```

### Task 3: Stable Bash command interface and safe workspace handling

**Files:**
- Create: `scripts/lib/common.sh`
- Create: `scripts/list-targets.sh`
- Create: `scripts/validate.sh`
- Create: `scripts/bootstrap.sh`
- Create: `scripts/prepare.sh`
- Create: `scripts/build.sh`
- Create: `scripts/clean.sh`
- Create: `tests/scripts/test_scripts.py`

**Interfaces:**
- Consumes: Task 2 CLI commands and exit codes.
- Produces: Bash commands accepting `--distribution ID`, `--device ID`, optional `--revision REV`, and `--help`; `build.sh` exits before network/build activity when manifest resolution is not build-ready.

- [ ] **Step 1: Write failing command-interface tests**

Use `unittest` plus `subprocess` to assert all scripts support `--help`, run from outside the repository, propagate manifest exit codes, reject unresolved builds before creating `work/`, and make `clean.sh` reject paths outside the three allowed generated roots.

- [ ] **Step 2: Run script tests and verify they fail**

Run: `python -m unittest tests.scripts.test_scripts -v`
Expected: FAIL because scripts do not exist.

- [ ] **Step 3: Implement shared root discovery and argument helpers**

In `scripts/lib/common.sh`, derive an absolute repository root from the script location, require Bash strict mode, and provide `die`, `require_command`, and allowed-generated-path checks.

- [ ] **Step 4: Implement discovery and validation wrappers**

Make `list-targets.sh` and `validate.sh` thin wrappers around `python3 tools/manifest.py`; preserve its stdout, stderr, and exit status.

- [ ] **Step 5: Implement safe build-stage skeletons**

Make `bootstrap.sh`, `prepare.sh`, and `build.sh` resolve with `--require-build-ready` before any network or filesystem mutation, print the future native OpenWrt stage clearly, and exit with a documented non-success status until implemented rather than reporting a false build.

- [ ] **Step 6: Implement scoped cleanup**

Require an explicit one-of `work`, `output`, or `cache` argument, resolve it below the repository root, and refuse symlinks or any path outside those roots before deletion.

- [ ] **Step 7: Run the full test suite**

Run: `python -m unittest discover -s tests -v`
Expected: PASS.

- [ ] **Step 8: Commit the command interface**

```bash
git add scripts tests
git commit -m "feat: add safe build command interface"
```

### Task 4: GitHub Actions validation and build orchestration

**Files:**
- Create: `.github/workflows/validate.yml`
- Create: `.github/workflows/build.yml`
- Create: `.github/workflows/reusable-build.yml`
- Create: `tests/workflows/test_workflows.py`

**Interfaces:**
- Consumes: Task 3 `scripts/validate.sh`, `scripts/list-targets.sh`, and `scripts/build.sh` behavior.
- Produces: PR/push validation, manual build dispatch inputs `distribution`, `device`, and `source_revision`, and reusable build inputs of the same names.

- [ ] **Step 1: Write failing workflow contract tests**

Assert validation runs on pull requests with read-only contents permission, manual build has constrained distribution/device inputs, reusable build declares typed inputs, job timeouts and concurrency are set, no `pull_request_target` exists, and workflows invoke repository scripts rather than native build commands directly.

- [ ] **Step 2: Run workflow tests and verify they fail**

Run: `python -m unittest tests.workflows.test_workflows -v`
Expected: FAIL because workflows do not exist.

- [ ] **Step 3: Implement the validation workflow**

Use GitHub-hosted Ubuntu, minimal `contents: read`, Python 3, `scripts/validate.sh`, and the full standard-library test suite; do not expose secrets.

- [ ] **Step 4: Implement manual and reusable build workflows**

Forward typed inputs into `reusable-build.yml`; validate before cache or checkout work; call `scripts/build.sh`; reserve cache/artifact steps behind successful build-stage conditions so the initial unresolved skeleton fails honestly.

- [ ] **Step 5: Run the full test suite**

Run: `python -m unittest discover -s tests -v`
Expected: PASS.

- [ ] **Step 6: Commit GitHub Actions orchestration**

```bash
git add .github tests
git commit -m "ci: add manifest-driven build workflows"
```

### Task 5: Human and AI operating documentation

**Files:**
- Create: `README.md`
- Create: `docs/architecture.md`
- Create: `docs/configuration-layers.md`
- Create: `docs/adding-a-device.md`
- Modify: `tests/structure/test_repository_contract.py`

**Interfaces:**
- Consumes: exact commands and paths produced by Tasks 1–4.
- Produces: a task-oriented entry point for users and AI agents with no undocumented setup assumptions.

- [ ] **Step 1: Extend documentation contract tests and verify failure**

Assert README links resolve, the three initial devices and two distributions are named, Actions is identified as the primary builder, unresolved profiles are explained, and the add-device guide contains a validation command that works from repository root.

Run: `python -m unittest tests.structure.test_repository_contract -v`
Expected: FAIL for missing documents.

- [ ] **Step 2: Write the user entry point and architecture documentation**

Document repository map, layer precedence, generated directories, local/CI roles, initial scaffold limitations, and copyable validation/list/manual Actions instructions.

- [ ] **Step 3: Write the add-device procedure**

Specify manifest creation, native target/profile verification, device fragment/overlay/patch placement, local validation, and build-readiness checks without requiring core script changes.

- [ ] **Step 4: Run all automated checks**

Run: `python -m unittest discover -s tests -v`
Expected: PASS.

- [ ] **Step 5: Run user-facing smoke checks**

Run: `bash scripts/validate.sh` and `bash scripts/list-targets.sh`
Expected: validation succeeds structurally; listing deterministically shows the supported OpenWrt/ImmortalWrt combinations and unresolved build-readiness state.

- [ ] **Step 6: Verify repository hygiene**

Run: `git status --short --ignored` and `git remote -v`
Expected: generated/private paths are ignored, no unexpected files exist, and no remote is configured.

- [ ] **Step 7: Commit documentation**

```bash
git add README.md docs tests/structure/test_repository_contract.py
git commit -m "docs: explain multi-device build workflow"
```

