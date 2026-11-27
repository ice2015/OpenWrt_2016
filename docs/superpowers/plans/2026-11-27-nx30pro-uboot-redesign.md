# NX30 Pro Restricted-Recovery U-Boot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the existing NX30 Pro U-Boot candidate with a pinned Yuzhii DHCPD build that defaults to the 112M NMBM layout, retains the stock layout as a whitelist option, and exposes only recovery, BL2/FIP upgrade, TFTP/UART, and read-only backup features.

**Architecture:** Keep all boot-loader inputs under `devices/nx30pro/uboot/` and make `uboot-source-lock.json` the machine-readable source, layout, feature, and artifact contract. `build-uboot.sh` must apply only device-local patches, inspect the effective configuration and produced images, and emit provenance; the workflow remains a manual wrapper around that script.

**Tech Stack:** Yuzhii0718/bl-mt798x-dhcpd, MediaTek MT7981, U-Boot 2025, SP1/2025/SP2 ATF evaluation, POSIX shell, Python 3 `unittest`, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-11-27-nx30pro-firmware-uboot-redesign.md`

> **Execution status (2026-11-27, phase one):** Tasks 1–6 are implemented and committed
> (`2748192..ad3847e`, including one review fix pass). Task 7 is intentionally NOT executed:
> triggering GitHub Actions requires separate user authorization. This was static work only —
> no U-Boot was compiled and no device was touched. Evidence:
> `devices/nx30pro/docs/UBOOT-TEST-REPORT.md`.

## Global Constraints

- Default layout is exactly `immortalwrt-112m`; the only alternative is exactly `default`.
- Enable `MULTI_LAYOUT=1` and `FIXED_MTDPARTS=1`; never expose arbitrary `mtdparts` editing.
- Enable DHCPD, Web failsafe, firmware recovery, BL2/FIP upgrade, TFTP, UART, and read-only backup.
- Disable Factory write, raw Flash Editor, generic environment editing, Web terminal, Telnet, UBI management, and CPU/DDR overclocking.
- Pin repository, commit, ATF/U-Boot tree identity, toolchain identity, and expected artifacts; never build a moving branch.
- Keep all NX30PRO-only patches and configuration under `devices/nx30pro/`.
- Do not flash hardware, erase NAND, trigger GitHub Actions, or perform a local U-Boot build without separate user authorization.
- Run static repository validation on Windows; compilation is limited to GitHub Actions or Linux/WSL2.

## Review Focus

- A source update that silently removes or renames the NX30PRO board must fail lock preflight; Task 1 adds this contract test.
- A layout set containing a third label, a non-112M default, or mismatched Factory offsets must fail; Task 2 adds these tests.
- A final U-Boot config that re-enables any dangerous Web feature or overclock option must fail; Task 3 adds effective-config tests.
- A restricted selector that can write arbitrary environment keys or `mtdparts` must fail source/patch contract tests; Task 3 owns this boundary.
- Missing, oversized, empty, or misnamed BL2/FIP artifacts must fail before upload; Task 4 adds artifact tests.

---

### Task 1: Pin and describe the Yuzhii source candidate

**Files:**
- Modify: `devices/nx30pro/uboot/uboot-source-lock.json`
- Modify: `devices/nx30pro/build/uboot_lock.py`
- Test: `tests/structure/test_nx30pro_uboot_contract.py`
- Test: `tests/scripts/test_nx30pro_uboot_build.py`

**Interfaces:**
- Consumes: approved design and upstream read-only investigation evidence.
- Produces: `uboot-source-lock.json` fields `source.repository`, `source.commit`, `source.version`, `source.atf_tree`, `source.uboot_tree`, `board`, `features`, `layouts`, and `artifacts`; `uboot_lock.py check --lock PATH` validates them.

- [x] **Step 1: Add failing source-lock tests**

  Assert repository equals `https://github.com/Yuzhii0718/bl-mt798x-dhcpd`, commit is 40 lowercase hex characters, board is `h3c_magic-nx30-pro`, SoC is `mt7981`, and the selected ATF/U-Boot trees are recorded. Assert the old `hanwckf/bl-mt798x` repository is rejected.

- [x] **Step 2: Run the focused tests and confirm failure**

  Run: `python -m unittest tests.structure.test_nx30pro_uboot_contract tests.scripts.test_nx30pro_uboot_build -v`

  Expected: FAIL because the existing lock points to `hanwckf/bl-mt798x` and the helper hard-codes that repository.

- [x] **Step 3: Replace the lock schema and helper expectations**

  Record the researched Yuzhii commit rather than `master`. Keep the U-Boot version decision explicit: select SP1 only after verifying Linux 5.4 compatibility evidence; otherwise leave the version `UNRESOLVED` and make `check` return the repository's build-not-ready status instead of guessing.

- [x] **Step 4: Run the focused tests**

  Expected: PASS for the selected complete candidate, or PASS for a test proving an `UNRESOLVED` version safely blocks build readiness.

- [x] **Step 5: Commit**

  ```bash
  git add devices/nx30pro/uboot/uboot-source-lock.json devices/nx30pro/build/uboot_lock.py tests/structure/test_nx30pro_uboot_contract.py tests/scripts/test_nx30pro_uboot_build.py
  git commit -m "build: pin NX30 Pro Yuzhii U-Boot source"
  ```

### Task 2: Encode the two-layout partition contract

**Files:**
- Modify: `devices/nx30pro/uboot/uboot-source-lock.json`
- Modify: `devices/nx30pro/build/uboot_lock.py`
- Test: `tests/structure/test_nx30pro_uboot_contract.py`
- Test: `tests/scripts/test_nx30pro_uboot_build.py`

**Interfaces:**
- Consumes: Task 1 lock schema.
- Produces: `layouts.default_label == "immortalwrt-112m"`; exactly two entries keyed `immortalwrt-112m` and `default`; `uboot_lock.py verify-layout-source --lock PATH --dts PATH`.

- [x] **Step 1: Add failing layout tests**

  Assert the 112M table is `1024k(bl2),512k(u-boot-env),2048k(Factory),2048k(fip),112M(ubi)`. Assert the stock table retains `pdt_data`, `pdt_data_1`, `exp`, and `plugin`. Assert both tables use the same BL2, environment, Factory, and FIP offsets and sizes; reject any third label.

- [x] **Step 2: Add failing DTS verification tests**

  Cover wrong default label, missing stock layout, changed Factory offset, arbitrary third layout, and physical-NAND addresses presented as NMBM logical addresses.

- [x] **Step 3: Run focused tests and confirm failure**

  Run: `python -m unittest tests.structure.test_nx30pro_uboot_contract tests.scripts.test_nx30pro_uboot_build -v`

- [x] **Step 4: Implement the two-layout lock and verifier**

  The verifier consumes the pinned upstream NX30PRO DTS and returns nonzero unless it contains exactly the locked whitelist. It must not synthesize a layout absent from the pinned source.

- [x] **Step 5: Run focused tests and commit**

  ```bash
  git add devices/nx30pro/uboot/uboot-source-lock.json devices/nx30pro/build/uboot_lock.py tests/structure/test_nx30pro_uboot_contract.py tests/scripts/test_nx30pro_uboot_build.py
  git commit -m "build: lock NX30 Pro selectable partition layouts"
  ```

### Task 3: Restrict the recovery Web UI and effective configuration

**Files:**
- Create: `devices/nx30pro/uboot/patches/0001-nx30pro-restrict-recovery-ui.patch`
- Modify: `devices/nx30pro/uboot/uboot-source-lock.json`
- Modify: `devices/nx30pro/build/uboot_lock.py`
- Test: `tests/structure/test_nx30pro_uboot_contract.py`
- Test: `tests/scripts/test_nx30pro_uboot_build.py`

**Interfaces:**
- Consumes: Task 2 layout whitelist.
- Produces: device patch implementing a selector that only writes the two locked layout labels; `uboot_lock.py verify-config --lock PATH --config PATH` and `verify-patch --lock PATH --patch PATH`.

- [x] **Step 1: Add failing feature-contract tests**

  Assert required effective symbols for DHCPD, Web failsafe, backup, TFTP and UART. Assert disabled symbols or absence for Factory write, Flash Editor, generic environment editor, Web console, Telnet, UBI manager, and all MT7981 overclock profiles.

- [x] **Step 2: Add failing selector-boundary tests**

  Assert the patch contains only the two layout labels, has no free-form `mtdparts` input, cannot write arbitrary environment keys, defaults to `immortalwrt-112m`, and warns before switching from stock to 112M.

- [x] **Step 3: Run tests and confirm failure**

  Run: `python -m unittest tests.structure.test_nx30pro_uboot_contract tests.scripts.test_nx30pro_uboot_build -v`

- [x] **Step 4: Determine the smallest upstream patch surface**

  Inspect the pinned source's Kconfig and Web handlers. If Kconfig can disable every dangerous feature independently, keep the patch limited to the whitelist selector; otherwise also remove the dangerous routes and handlers in this device-only patch. Record affected upstream paths and commit applicability in the patch header.

- [x] **Step 5: Implement verification and the minimal patch**

  `verify-config` inspects the post-`olddefconfig` output, not requested environment variables. `verify-patch` rejects generic environment and arbitrary partition editing interfaces.

- [x] **Step 6: Run tests and commit**

  ```bash
  git add devices/nx30pro/uboot/patches devices/nx30pro/uboot/uboot-source-lock.json devices/nx30pro/build/uboot_lock.py tests/structure/test_nx30pro_uboot_contract.py tests/scripts/test_nx30pro_uboot_build.py
  git commit -m "feat: restrict NX30 Pro U-Boot recovery interface"
  ```

### Task 4: Rebuild the U-Boot orchestration and artifact gates

**Files:**
- Modify: `devices/nx30pro/build/build-uboot.sh`
- Modify: `devices/nx30pro/build/uboot_lock.py`
- Test: `tests/scripts/test_nx30pro_uboot_build.py`

**Interfaces:**
- Consumes: Task 1 source lock, Task 2 layout verifier, Task 3 patch/config verifier.
- Produces: `build-uboot.sh --lock FILE --source-dir DIR --artifact-dir DIR [--check-only]`; artifact tree `images/`, `logs/`, `build-report.json`, `uboot-source-lock.json`, `FLASH-TARGETS.txt`.

- [x] **Step 1: Add failing orchestration tests**

  Test pinned revision mismatch, dirty source, missing board, patch apply failure, wrong default layout, dangerous effective feature, enabled overclock, and `--check-only` performing no build.

- [x] **Step 2: Add failing artifact tests**

  Reject empty, oversized, misnamed, duplicated, or structurally invalid BL2/FIP. Assert SHA256 and toolchain identity are recorded and that firmware images cannot be mislabeled as boot-loader images.

- [x] **Step 3: Run tests and confirm failure**

  Run: `python -m unittest tests.scripts.test_nx30pro_uboot_build -v`

- [x] **Step 4: Implement Yuzhii build orchestration**

  Apply device patches after verifying the pinned revision, select the locked board/version with `MULTI_LAYOUT=1` and `FIXED_MTDPARTS=1`, generate effective configuration, run all pre-build gates, invoke the upstream build entry, and inspect artifacts before moving them into `images/`.

- [x] **Step 5: Run tests and commit**

  ```bash
  git add devices/nx30pro/build/build-uboot.sh devices/nx30pro/build/uboot_lock.py tests/scripts/test_nx30pro_uboot_build.py
  git commit -m "build: rebuild NX30 Pro U-Boot orchestration"
  ```

### Task 5: Replace the manual U-Boot workflow

**Files:**
- Modify: `.github/workflows/build-nx30pro-uboot.yml`
- Modify: `tests/workflows/test_workflows.py`

**Interfaces:**
- Consumes: Task 4 CLI and artifact layout.
- Produces: manual-only `NX30 Pro restricted-recovery U-Boot` workflow.

- [x] **Step 1: Add failing workflow tests**

  Assert only `workflow_dispatch` is present; the workflow pins action SHAs, installs the dependencies named by the lock, runs repository/static preflight before build, invokes Task 4's exact CLI, uploads candidate artifacts only on success, and uploads diagnostics with `if: always()`.

- [x] **Step 2: Assert forbidden behavior**

  Reject `push`, `pull_request`, schedules, flash commands, NAND erase commands, moving source refs, and paths belonging to other devices.

- [x] **Step 3: Run tests and confirm failure**

  Run: `python -m unittest tests.workflows.test_workflows -v`

- [x] **Step 4: Rewrite the workflow and run tests**

  Do not trigger it. Static YAML and contract tests are the only verification in this task.

- [x] **Step 5: Commit**

  ```bash
  git add .github/workflows/build-nx30pro-uboot.yml tests/workflows/test_workflows.py
  git commit -m "ci: replace NX30 Pro U-Boot workflow"
  ```

### Task 6: Document build, recovery, and validation boundaries

**Files:**
- Modify: `devices/nx30pro/docs/nx30pro-uboot-compatibility.md`
- Modify: `devices/nx30pro/docs/nx30pro-uboot-install-and-recovery.md`
- Create: `devices/nx30pro/docs/UBOOT-BUILD.md`
- Create: `devices/nx30pro/docs/UBOOT-TEST-REPORT.md`
- Modify: `devices/nx30pro/README.md`
- Test: `tests/structure/test_nx30pro_uboot_contract.py`

**Interfaces:**
- Consumes: Tasks 1–5 facts and artifact names.
- Produces: operator documentation that separates candidate build success from device validation.

- [x] **Step 1: Add failing documentation tests**

  Require source commit, two layouts, default label, restricted UI feature list, backup-first warning, NMBM logical-address wording, artifact roles, and explicit `UNRESOLVED` hardware facts. Reject claims of completed real-device validation and executable destructive flash commands.

- [x] **Step 2: Run tests and confirm failure**

  Run: `python -m unittest tests.structure.test_nx30pro_uboot_contract -v`

- [x] **Step 3: Update documentation**

  Include an authorization gate for any future Action run. `UBOOT-TEST-REPORT.md` starts as static/preflight-only and gains Action run IDs, URLs, hashes, and device results only when those events actually occur.

- [x] **Step 4: Run repository checks**

  Run: `bash scripts/validate.sh`

  Run: `python -m unittest discover -s tests -v`

  Expected: PASS. These commands do not compile U-Boot and do not trigger Actions.

- [x] **Step 5: Commit**

  ```bash
  git add devices/nx30pro/docs devices/nx30pro/README.md tests/structure/test_nx30pro_uboot_contract.py
  git commit -m "docs: define NX30 Pro restricted U-Boot recovery"
  ```

### Task 7: Authorized remote build and evidence capture

**Files:**
- Modify after an authorized run: `devices/nx30pro/docs/UBOOT-TEST-REPORT.md`

**Interfaces:**
- Consumes: explicit user authorization issued after Tasks 1–6, completed workflow, and `gh` CLI.
- Produces: recorded Action run ID/URL, artifact hashes, toolchain identity, effective config evidence, and remaining device-test gaps.

- [ ] **Step 1: Stop unless the user explicitly authorizes an Action run**

  Expected without authorization: no command is run and this task remains unchecked.

- [ ] **Step 2: Trigger exactly the manual U-Boot workflow after authorization**

  Record the command and returned run ID. Do not trigger the firmware workflow in this task.

- [ ] **Step 3: Inspect status and logs with `gh`**

  Verify the effective feature/layout checks and both artifacts. A green job without those evidence lines is not acceptance.

- [ ] **Step 4: Update the test report and commit evidence**

  Keep all true hardware behavior marked `UNRESOLVED` until separately authorized device testing.

