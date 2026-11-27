# NX30 Pro 112M Firmware Rebuild Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the NX30 Pro 112M firmware pipeline on a newly pinned hanwckf 21.02/Linux 5.4 source and compatible feeds, with hard gates for the approved core package stack and a partition contract matching the redesigned Yuzhii U-Boot.

**Architecture:** Treat the Galaxian 112M tree as a device-port reference, not the build base. `source-lock.json` records the selected hanwckf commit, compatible feed commits, package contract, image contract, and unresolved hardware facts; device-only patches/config/overlay are applied by `configure.sh`, while `build.sh` owns source acquisition, build invocation, and evidence packaging.

**Tech Stack:** hanwckf/immortalwrt-mt798x openwrt-21.02, Linux 5.4, OpenWrt Kconfig/buildroot, POSIX shell, Python 3 `unittest`, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-11-27-nx30pro-firmware-uboot-redesign.md`

## Global Constraints

- Source selection starts from a fresh `hanwckf/immortalwrt-mt798x` commit; the old Galaxian commit is reference evidence only.
- Default system layout is `immortalwrt-112m` and must exactly match the U-Boot plan's locked 112M table.
- Hard-gate packages: LuCI, HTTPS, Simplified Chinese, Argon with Bootstrap fallback, PassWall 4.68 + Xray Core/Plugin, DDNS, Tailscale, ZeroTier, Docker, and Argo Tunnel (`cloudflared`).
- Optional-but-reported packages: Cloudflare DDNS, FRPC, dnsmasq-full, SQM, NLBWMon, WOL, TTYD, SFTP, tcpdump, iperf3, and MTR.
- HomeProxy, sing-box, OpenClash, PassWall2, and AdGuard Home are excluded; WireGuard may remain `UNRESOLVED` on Linux 5.4.
- All nonessential network services are disabled by default; secrets and deployment identifiers never enter the image.
- A hard-gate package removed by real `make defconfig` invalidates the source/feed candidate before compilation.
- Do not trigger GitHub Actions, compile firmware, or flash hardware without separate user authorization.

## Review Focus

- Feeds that index a package but lack its dependencies must be rejected after `defconfig`; Tasks 1 and 3 test this exact old-Action failure.
- A 112M DTS/profile with a mismatched partition table, image limit, or artifact role must fail; Task 2 owns these tests.
- Package symbols containing hyphens must merge and survive final config auditing; Task 3 adds regression coverage.
- Default-disable overlay logic must cover every included nonessential service without writing secrets; Task 4 owns this boundary.
- A workflow success without final config, package list, hashes, source/feed locks, and logs must not count as an accepted candidate; Tasks 5 and 6 enforce the evidence set.

---

### Task 1: Synchronize requirements and select a build-ready source/feed set

**Files:**
- Modify: `devices/nx30pro/docs/Command_fix.md`
- Modify: `devices/nx30pro/source-lock.json`
- Modify: `manifests/sources.json`
- Modify: `devices/nx30pro/feeds.conf`
- Modify: `devices/nx30pro/build/firmware_lock.py`
- Test: `tests/structure/test_nx30pro_firmware_contract.py`
- Test: `tests/scripts/test_nx30pro_firmware_build.py`

**Interfaces:**
- Consumes: approved design and U-Boot plan Task 2 layout contract.
- Produces: `source-lock.json` source/feed/package schema; `firmware_lock.py check --lock PATH`; corrected `Command_fix.md` as the human-readable requirement source.

- [ ] **Step 1: Correct the human-readable requirement source**

  Replace HomeProxy/sing-box and no-Docker statements with the approved PassWall 4.68 + Xray, Docker, core hard gates, optional reported tools, Yuzhii U-Boot, restricted Web UI, and manual-only Actions boundary. Preserve the 112M/NMBM and no-automatic-flash requirements.

- [ ] **Step 2: Add failing source/feed lock tests**

  Assert the source repository is `https://github.com/hanwckf/immortalwrt-mt798x`, revision is a 40-character commit, branch is informational only, kernel is 5.4, and every feed has repository plus full commit. Reject the old Galaxian repository/commit as the active source.

- [ ] **Step 3: Add package-closure contract tests**

  Require every hard-gate package to name exact symbols, source feed, feed commit, expected version where pinned, and status `available`. A helper fixture where a package exists but a dependency is absent must fail `check`.

- [ ] **Step 4: Run focused tests and confirm failure**

  Run: `python -m unittest tests.structure.test_nx30pro_firmware_contract tests.scripts.test_nx30pro_firmware_build -v`

- [ ] **Step 5: Investigate and record the candidate set**

  Select a hanwckf commit and feed commits from the same 21.02 API generation. Use upstream files and feed dependency metadata as evidence; do not mark the lock build-ready until a disposable Linux/Actions `defconfig` probe is separately authorized and confirms every hard gate.

- [ ] **Step 6: Implement the new lock checks**

  An incomplete candidate remains `UNRESOLVED`; `check` returns the established build-not-ready status and prevents source download/build. Keep `manifests/sources.json` equal to the accepted source lock only after the candidate is proven.

- [ ] **Step 7: Run focused tests and commit**

  ```bash
  git add devices/nx30pro/docs/Command_fix.md devices/nx30pro/source-lock.json manifests/sources.json devices/nx30pro/feeds.conf devices/nx30pro/build/firmware_lock.py tests/structure/test_nx30pro_firmware_contract.py tests/scripts/test_nx30pro_firmware_build.py
  git commit -m "build: redefine NX30 Pro firmware source contract"
  ```

### Task 2: Port and verify the NX30 Pro 112M device definition

**Files:**
- Create: `devices/nx30pro/patches/0001-mediatek-add-nx30pro-112m-profile.patch`
- Rename or modify as needed: `devices/nx30pro/patches/0001-mediatek-nx30pro-wan-mac-source.patch`
- Modify: `manifests/devices/nx30pro.json`
- Modify: `devices/nx30pro/source-lock.json`
- Modify: `devices/nx30pro/build/firmware_lock.py`
- Test: `tests/structure/test_nx30pro_firmware_contract.py`
- Test: `tests/scripts/test_nx30pro_firmware_build.py`

**Interfaces:**
- Consumes: Task 1 pinned source and U-Boot plan `layouts.immortalwrt-112m`.
- Produces: one NX30PRO 112M profile, DTS, factory rule, sysupgrade rule, and manifest artifact patterns; `verify-device-tree` and `verify-image-rules` commands.

- [ ] **Step 1: Add failing partition/profile tests**

  Assert exact BL2/environment/Factory/FIP/112M UBI offsets and sizes, NMBM binding, unique NX30PRO profile, explicit image limit, and distinct factory/sysupgrade roles. Reject a copied profile for another device and reject the stock 64M table as the 112M profile.

- [ ] **Step 2: Add MAC/calibration safety tests**

  Require a documented WAN MAC source that works after `pdt_data_1` is absent, preserves the Factory partition, and never embeds a device MAC. Keep unknown real values `UNRESOLVED`.

- [ ] **Step 3: Run focused tests and confirm failure**

  Run: `python -m unittest tests.structure.test_nx30pro_firmware_contract tests.scripts.test_nx30pro_firmware_build -v`

- [ ] **Step 4: Create the minimal device port**

  Derive only NX30PRO DTS/profile changes from the Galaxian reference and rebase them onto Task 1's commit. Update the existing MAC patch against that exact source; renumber patches so ordering is deterministic.

- [ ] **Step 5: Implement source-level verifiers**

  `verify-device-tree` and `verify-image-rules` read the patched source tree and compare it with the lock; no regex may accept another profile or an approximate partition size.

- [ ] **Step 6: Run tests and commit**

  ```bash
  git add devices/nx30pro/patches manifests/devices/nx30pro.json devices/nx30pro/source-lock.json devices/nx30pro/build/firmware_lock.py tests/structure/test_nx30pro_firmware_contract.py tests/scripts/test_nx30pro_firmware_build.py
  git commit -m "feat: port NX30 Pro 112M firmware profile"
  ```

### Task 3: Implement final-config package gates

**Files:**
- Modify: `devices/nx30pro/config.config`
- Modify: `devices/nx30pro/source-lock.json`
- Modify: `devices/nx30pro/build/configure.sh`
- Modify: `devices/nx30pro/build/firmware_lock.py`
- Test: `tests/structure/test_nx30pro_firmware_contract.py`
- Test: `tests/scripts/test_nx30pro_firmware_build.py`

**Interfaces:**
- Consumes: Task 1 package contract and Task 2 profile.
- Produces: `firmware_lock.py verify-config --lock PATH --config PATH`; final config evidence separating hard gates, optional status, and exclusions.

- [ ] **Step 1: Add failing hard-gate tests**

  Require LuCI/HTTPS/Chinese/Argon/Bootstrap, exact PassWall 4.68 contract plus Xray Core/Plugin, DDNS, Tailscale, ZeroTier, Docker, and cloudflared after `defconfig`. Test each missing symbol independently and assert a nonzero result naming the requirement.

- [ ] **Step 2: Add merge and dependency regression tests**

  Cover hyphenated symbols, explicit `is not set` overrides, package-present/dependency-missing fixtures, and the old failure where PassWall/DDNS/ZeroTier/Docker/Argon disappear together.

- [ ] **Step 3: Add optional/exclusion tests**

  Record Cloudflare DDNS, FRPC, dnsmasq-full, SQM, NLBWMon, WOL, TTYD, SFTP, tcpdump, iperf3, and MTR as present/partial/unavailable with evidence. Explicitly exclude HomeProxy, sing-box, OpenClash, PassWall2, and AdGuard Home; keep WireGuard `UNRESOLVED` unless proven.

- [ ] **Step 4: Run focused tests and confirm failure**

  Run: `python -m unittest tests.structure.test_nx30pro_firmware_contract tests.scripts.test_nx30pro_firmware_build -v`

- [ ] **Step 5: Implement the device config and verifier**

  Merge only common → distribution → NX30PRO device layers in order, then run feeds installation and real `make defconfig`. Verify the resulting `.config`; never validate only the seed. Fail before compilation when a hard gate is absent.

- [ ] **Step 6: Run tests and commit**

  ```bash
  git add devices/nx30pro/config.config devices/nx30pro/source-lock.json devices/nx30pro/build/configure.sh devices/nx30pro/build/firmware_lock.py tests/structure/test_nx30pro_firmware_contract.py tests/scripts/test_nx30pro_firmware_build.py
  git commit -m "feat: enforce NX30 Pro firmware package contract"
  ```

### Task 4: Disable services safely by default

**Files:**
- Modify: `devices/nx30pro/files/etc/uci-defaults/90-nx30pro-defaults`
- Create as required: `devices/nx30pro/files/etc/config/` service templates without credentials
- Test: `tests/structure/test_nx30pro_firmware_contract.py`

**Interfaces:**
- Consumes: Task 3 included services.
- Produces: first-boot defaults that disable every nonessential included service and contain no secret/deployment data.

- [ ] **Step 1: Add failing overlay tests**

  Require disabled defaults for PassWall, DDNS, Tailscale, ZeroTier, Docker, cloudflared, and every optional service actually selected. Reject tunnel tokens, domains, Wi-Fi credentials, passwords, private keys, public IPs, and device MAC values.

- [ ] **Step 2: Run the focused test and confirm failure**

  Run: `python -m unittest tests.structure.test_nx30pro_firmware_contract -v`

- [ ] **Step 3: Implement idempotent first-boot defaults**

  Guard absent packages, commit only changed UCI packages, and remove the defaults script only after successful application. Provide comments/placeholders rather than secrets for cloudflared and DDNS deployment.

- [ ] **Step 4: Run tests and commit**

  ```bash
  git add devices/nx30pro/files tests/structure/test_nx30pro_firmware_contract.py
  git commit -m "feat: secure NX30 Pro service defaults"
  ```

### Task 5: Rebuild firmware orchestration and evidence output

**Files:**
- Modify: `devices/nx30pro/build/build.sh`
- Modify: `devices/nx30pro/build/configure.sh`
- Modify: `devices/nx30pro/build/firmware_lock.py`
- Test: `tests/scripts/test_nx30pro_firmware_build.py`

**Interfaces:**
- Consumes: Tasks 1–4 source, feed, partition, package, and overlay contracts.
- Produces: `build.sh --lock FILE --source-dir DIR --feed-dir DIR --artifact-dir DIR [--check-only]`; artifact tree with images, final config, package manifest, feed lock, hashes, logs, and report.

- [ ] **Step 1: Add failing pre-build tests**

  Cover revision mismatch, dirty source, feed mismatch, patch failure, partition mismatch, missing hard gate, secret-bearing overlay, and `--check-only` performing no download or build.

- [ ] **Step 2: Add failing artifact tests**

  Reject absent/empty/duplicate/oversized factory or sysupgrade artifacts, swapped image roles, missing metadata, and an evidence bundle lacking final `.config`, feed commits, package list, SHA256, or build logs.

- [ ] **Step 3: Run focused tests and confirm failure**

  Run: `python -m unittest tests.scripts.test_nx30pro_firmware_build -v`

- [ ] **Step 4: Implement the build stages**

  Separate source checkout, patch/config preflight, download, compile, image inspection, and evidence packaging. Preserve logs when any stage fails. Do not let artifact packaging claim success when only configuration succeeded.

- [ ] **Step 5: Run tests and commit**

  ```bash
  git add devices/nx30pro/build tests/scripts/test_nx30pro_firmware_build.py
  git commit -m "build: rebuild NX30 Pro firmware orchestration"
  ```

### Task 6: Replace the manual firmware workflow

**Files:**
- Modify: `.github/workflows/build-nx30pro.yml`
- Modify: `tests/workflows/test_workflows.py`

**Interfaces:**
- Consumes: Task 5 CLI and artifact layout.
- Produces: manual-only `NX30 Pro 112M firmware candidate` workflow.

- [ ] **Step 1: Add failing workflow tests**

  Assert only `workflow_dispatch`, pinned action SHAs, sufficient disk cleanup, source/tool dependencies, repository tests before build, exact Task 5 CLI, success-only candidate upload, and `always()` diagnostics upload.

- [ ] **Step 2: Assert forbidden behavior**

  Reject push/PR/schedule triggers, flash/NAND commands, moving source/feed branches, generated-directory edits, and references to other device build scripts.

- [ ] **Step 3: Run tests and confirm failure**

  Run: `python -m unittest tests.workflows.test_workflows -v`

- [ ] **Step 4: Rewrite workflow and run tests**

  Do not trigger it. Static YAML and contract tests are the only verification in this task.

- [ ] **Step 5: Commit**

  ```bash
  git add .github/workflows/build-nx30pro.yml tests/workflows/test_workflows.py
  git commit -m "ci: replace NX30 Pro firmware workflow"
  ```

### Task 7: Write build, install, recovery, and test documents

**Files:**
- Create: `devices/nx30pro/docs/BUILD.md`
- Create: `devices/nx30pro/docs/FLASH.md`
- Create: `devices/nx30pro/docs/RECOVERY.md`
- Create: `devices/nx30pro/docs/TEST-REPORT.md`
- Modify: `devices/nx30pro/docs/nx30pro-firmware-compatibility.md`
- Modify: `devices/nx30pro/docs/nx30pro-firmware-install-and-validation.md`
- Modify: `devices/nx30pro/README.md`
- Test: `tests/structure/test_nx30pro_firmware_contract.py`

**Interfaces:**
- Consumes: Tasks 1–6 facts and U-Boot plan outputs.
- Produces: operator documents with explicit candidate/Action/device validation states.

- [ ] **Step 1: Add failing documentation tests**

  Require source/feed commits, exact package status table, two layouts, image roles, backup-first boundary, U-Boot pairing, default-disabled services, authorization gates, and `UNRESOLVED` hardware facts. Reject hard-coded credentials and claims of successful Actions or hardware validation without run/device evidence.

- [ ] **Step 2: Run tests and confirm failure**

  Run: `python -m unittest tests.structure.test_nx30pro_firmware_contract -v`

- [ ] **Step 3: Write the documents**

  `FLASH.md` and `RECOVERY.md` describe targets and prerequisites but contain no unverified raw offsets or executable destructive commands. `TEST-REPORT.md` begins with static/preflight evidence only.

- [ ] **Step 4: Run complete static verification**

  Run: `bash scripts/validate.sh`

  Run: `python -m unittest discover -s tests -v`

  Expected: PASS. These commands do not compile firmware and do not trigger Actions.

- [ ] **Step 5: Commit**

  ```bash
  git add devices/nx30pro/docs devices/nx30pro/README.md tests/structure/test_nx30pro_firmware_contract.py
  git commit -m "docs: define NX30 Pro firmware build and validation"
  ```

### Task 8: Authorized defconfig probe, remote build, and evidence capture

**Files:**
- Modify after authorized evidence exists: `devices/nx30pro/source-lock.json`
- Modify after authorized evidence exists: `manifests/sources.json`
- Modify after authorized evidence exists: `devices/nx30pro/docs/TEST-REPORT.md`

**Interfaces:**
- Consumes: explicit user authorization, completed Tasks 1–7, and `gh` CLI.
- Produces: build-ready source/feed lock, Action run evidence, artifact hashes, final package/config proof, and remaining device-test gaps.

- [ ] **Step 1: Stop unless the user explicitly authorizes a probe or Action run**

  Expected without authorization: no command is run; unresolved source/feed candidates remain build-blocked and this task stays unchecked.

- [ ] **Step 2: Run the smallest authorized Linux/Action defconfig probe**

  Prove every hard-gate package survives real `make defconfig`. If any fails, reject the candidate and return to Task 1 instead of weakening the contract.

- [ ] **Step 3: Finalize locks only from successful probe evidence**

  Record exact source/feed commits and package versions; run all static tests again.

- [ ] **Step 4: Trigger exactly the manual firmware workflow after separate authorization**

  Record run ID/URL. Do not trigger the U-Boot workflow unless separately authorized.

- [ ] **Step 5: Inspect status, logs, and artifacts with `gh`**

  Verify final config, package manifest, images, size, hashes, and logs. A green job missing evidence is not acceptance.

- [ ] **Step 6: Update `TEST-REPORT.md` and commit evidence**

  Keep runtime and hardware behavior `UNRESOLVED` until separately authorized device testing.

