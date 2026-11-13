# OpenWrt Firmware Config Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create and verify a project-local Skill that guides AI agents through this repository's OpenWrt/ImmortalWrt configuration workflow and known TR3000 configuration/build-startup issues.

**Architecture:** Store one self-contained Chinese `SKILL.md` under `.agents/skills/openwrt-firmware-config/`. Protect its mechanical contract with Python tests and protect its behavioral value with three baseline-versus-with-skill agent scenarios. Keep evaluation fixtures with the Skill and temporary run results in a sibling workspace.

**Tech Stack:** Agent Skills Markdown/YAML frontmatter, Python `unittest`, POSIX shell repository checks, Codex subagent evaluations.

**Spec:** `docs/superpowers/specs/2026-11-13-openwrt-firmware-config-skill-design.md`

## Global Constraints

- The Skill path is `.agents/skills/openwrt-firmware-config/SKILL.md`.
- Use one Chinese `SKILL.md`, with no `references/` directory, and keep it at or below 300 lines.
- The description starts with `Use when...`, describes triggering conditions only, and covers OpenWrt, ImmortalWrt, TR3000, Kconfig, feeds, patches, overlays, and known configuration failures.
- Preserve `common → distribution → device → local` and never guess `revision`, `target`, `subtarget`, `profile`, partition layout, or artifact rules.
- Known-problem entries use the shape `症状 → 已确认根因 → 修复 → 验证` and only state evidence established in this repository.
- Do not include secrets, production credentials, `mtd write`, raw `dd`, erase commands, or unverified flashing offsets.
- Do not modify generated content under `work/`, `output/`, or `cache/`, and do not add private `local/` content.

## Review Focus

- An unspecified Raspberry Pi model must remain unresolved instead of receiving a guessed target/profile; Task 3 scenario 1 tests this.
- A TR3000 Lite package request must not be moved into `common` or silently defeat the Lite exclusion policy; Task 3 scenario 2 tests this.
- The known m4 failure must lead to checking `CONFIG_CCACHE_DIR`, `build.config`, and `config.log`, not unconditional cache deletion; Task 3 scenario 3 tests this.
- Similar but unrelated OpenWrt questions must not be claimed as repository-specific known issues; Task 2 tests description scope and the known-issue contract.
- Invalid frontmatter, extra reference files, or a bloated Skill must fail locally before merge; Task 2 tests structure, name, required sections, and the 300-line limit.

---

### Task 1: Capture Baseline Behavior Without the Skill

**Files:**
- Create: `.agents/skills/openwrt-firmware-config/evals/evals.json`
- Create: `.agents/skills/openwrt-firmware-config-workspace/iteration-1/<scenario>/eval_metadata.json`
- Create: `.agents/skills/openwrt-firmware-config-workspace/iteration-1/<scenario>/without_skill/output.md`
- Create: `.agents/skills/openwrt-firmware-config-workspace/iteration-1/<scenario>/without_skill/timing.json`

**Interfaces:**
- Consumes: the three evaluation scenarios and success criteria from the spec.
- Produces: baseline outputs and exact omissions/rationalizations that Task 3 must address.

- [ ] **Step 1: Write the evaluation prompts before creating `SKILL.md`**

Create `evals.json` with these three prompts and expected outcomes:

1. Add ImmortalWrt configuration for an unspecified Raspberry Pi model; expected behavior is to stop at the missing exact model and keep target fields unresolved.
2. Add OpenClash to TR3000 Lite and place it in `common`; expected behavior is to reject the common-layer placement, identify Lite's explicit exclusion, and explain the affected files.
3. Clear cache after the known TR3000 Lite m4 failure; expected behavior is to inspect the final ccache path and underlying configure evidence before proposing cache deletion.

- [ ] **Step 2: Run all three prompts with fresh subagents without loading any project Skill**

Save each final response verbatim to its `without_skill/output.md`. Capture the task notification's token count and duration in `timing.json`.

- [ ] **Step 3: Record the baseline failures in each `eval_metadata.json`**

Use these objective assertions where applicable:

- does not invent Raspberry Pi `target`, `subtarget`, or `profile`;
- names the exact project files it must inspect;
- keeps a TR3000 Lite-only change out of `common`;
- identifies `luci-app-openclash` as excluded by the current Lite seed/configuration validation;
- checks `CONFIG_CCACHE_DIR`, `build.config`, and `config.log` before recommending cache deletion.

- [ ] **Step 4: Commit the evaluation definition and baseline evidence**

```bash
git add docs/superpowers/specs/2026-11-13-openwrt-firmware-config-skill-design.md \
  docs/superpowers/plans/2026-11-13-openwrt-firmware-config-skill.md \
  .agents/skills/openwrt-firmware-config/evals \
  .agents/skills/openwrt-firmware-config-workspace/iteration-1
git commit -m "test: capture OpenWrt config skill baselines"
```

### Task 2: Add the Skill Contract Test

**Files:**
- Create: `tests/skills/__init__.py`
- Create: `tests/skills/test_openwrt_firmware_config_skill.py`
- Test: `tests/skills/test_openwrt_firmware_config_skill.py`

**Interfaces:**
- Consumes: the Skill path and constraints from the spec.
- Produces: a local contract that Task 3's `SKILL.md` must satisfy.

- [ ] **Step 1: Write `test_skill_frontmatter_and_structure`**

The test reads `.agents/skills/openwrt-firmware-config/SKILL.md` and asserts:

- the file exists;
- frontmatter `name` equals `openwrt-firmware-config`;
- `description` starts with `Use when` and is no longer than 1024 characters;
- total line count is no more than 300;
- no `.agents/skills/openwrt-firmware-config/references/` directory exists.

- [ ] **Step 2: Write `test_skill_covers_project_configuration_contract`**

Assert the body contains the exact layer order, `UNRESOLVED`, required repository checks, device distinctions, and the four known-problem headings from the spec. Assert it does not contain `mtd write` or an executable raw `dd` flashing recipe.

- [ ] **Step 3: Run the contract tests and verify RED**

Run:

```bash
python -m unittest tests.skills.test_openwrt_firmware_config_skill -v
```

Expected: FAIL because `SKILL.md` does not exist.

- [ ] **Step 4: Commit the failing contract test**

```bash
git add tests/skills
git commit -m "test: define OpenWrt config skill contract"
```

### Task 3: Implement and Behavior-Test the Skill

**Files:**
- Create: `.agents/skills/openwrt-firmware-config/SKILL.md`
- Create: `.agents/skills/openwrt-firmware-config-workspace/iteration-1/<scenario>/with_skill/output.md`
- Create: `.agents/skills/openwrt-firmware-config-workspace/iteration-1/<scenario>/with_skill/timing.json`
- Create: `.agents/skills/openwrt-firmware-config-workspace/iteration-1/<scenario>/{without_skill,with_skill}/grading.json`
- Create: `.agents/skills/openwrt-firmware-config-workspace/iteration-1/benchmark.json`
- Create: `.agents/skills/openwrt-firmware-config-workspace/iteration-1/benchmark.md`
- Create: `.agents/skills/openwrt-firmware-config-workspace/iteration-1/review.html`

**Interfaces:**
- Consumes: Task 1 baseline omissions and Task 2 mechanical contract.
- Produces: the project Skill and reviewable evidence that it improves the three scenarios.

- [ ] **Step 1: Read the required skill-authoring discovery guidance**

Read the complete `superpowers:writing-skills/references/discovery.md` before writing frontmatter. Use the project Skill name `openwrt-firmware-config` unchanged.

- [ ] **Step 2: Write the minimal `SKILL.md` that closes observed baseline gaps**

Use this section order:

1. 核心原则
2. 开始前读取顺序
3. 任务分类与配置层选择
4. 设备与固件变体重点
5. 重复配置流程
6. 常见配置任务
7. 已知调试问题
8. 完成报告格式
9. 快速参考
10. 常见错误

Include one complete worked example for a TR3000 Lite package change, from file selection through final verification, without adding unverified packages or credentials.

- [ ] **Step 3: Run the contract tests and verify GREEN**

Run:

```bash
python -m unittest tests.skills.test_openwrt_firmware_config_skill -v
```

Expected: all Skill contract tests PASS.

- [ ] **Step 4: Run the same three evaluation prompts with fresh subagents loading `SKILL.md`**

Give each subagent the Skill path explicitly and save its final response to the matching `with_skill/output.md`. Save notification timing data immediately.

- [ ] **Step 5: Grade both configurations against the objective assertions**

Write `grading.json` with the exact fields `text`, `passed`, and `evidence`. Confirm the with-skill run meets all safety and project-file assertions; record any assertion that both configurations pass as non-discriminating.

- [ ] **Step 6: Aggregate and render the evaluation**

Use the skill-creator aggregation and review scripts to produce `benchmark.json`, `benchmark.md`, and a static `review.html`. Include qualitative outputs and both with-skill/baseline grades.

- [ ] **Step 7: Review failures and revise only if the with-skill runs expose a real gap**

If revised, rerun the affected scenario in `iteration-2` with a fresh baseline and with-skill run, regenerate the benchmark, and preserve both iterations.

- [ ] **Step 8: Commit the verified Skill and evaluation evidence**

```bash
git add .agents/skills/openwrt-firmware-config .agents/skills/openwrt-firmware-config-workspace
git commit -m "feat: add OpenWrt firmware config skill"
```

### Task 4: Integrate With Repository Validation

**Files:**
- Modify: `README.md`
- Modify: `AGENTS.md`
- Test: `tests/skills/test_openwrt_firmware_config_skill.py`

**Interfaces:**
- Consumes: the verified Skill path from Task 3.
- Produces: discoverability for humans and agents plus full repository verification.

- [ ] **Step 1: Add a failing discoverability assertion**

Extend the Skill contract test to require both `README.md` and `AGENTS.md` to link to `.agents/skills/openwrt-firmware-config/SKILL.md` and state that it applies to firmware configuration changes.

- [ ] **Step 2: Run the discoverability test and verify RED**

Run:

```bash
python -m unittest tests.skills.test_openwrt_firmware_config_skill -v
```

Expected: FAIL because the project documents do not yet link to the Skill.

- [ ] **Step 3: Add concise Skill links to `README.md` and `AGENTS.md`**

Do not duplicate the Skill body. Tell AI contributors to read it for OpenWrt/ImmortalWrt firmware configuration, device, package, feed, patch, overlay, and known-issue work.

- [ ] **Step 4: Run all repository checks**

Run:

```bash
bash scripts/validate.sh
python -m unittest discover -s tests -v
git diff --check
```

Expected: manifest validation succeeds, all tests pass, and `git diff --check` reports no errors.

- [ ] **Step 5: Commit integration documentation**

```bash
git add README.md AGENTS.md tests/skills/test_openwrt_firmware_config_skill.py
git commit -m "docs: register OpenWrt config skill"
```

### Task 5: Final Review and Handoff

**Files:**
- Review: all files changed since the baseline commit

**Interfaces:**
- Consumes: Tasks 1–4.
- Produces: a verified local Skill ready for the subsequent TR3000 Full design task.

- [ ] **Step 1: Review the complete diff against the design**

Check every spec goal, non-goal, known issue, and safety constraint. Confirm no Full firmware implementation was added during Skill work.

- [ ] **Step 2: Run fresh final verification**

Run:

```bash
bash scripts/validate.sh
python -m unittest discover -s tests -v
git status --short
```

Expected: validation and tests pass; status contains only intentional Skill/design/plan changes, if any remain uncommitted.

- [ ] **Step 3: Report the handoff**

Provide links to `SKILL.md`, the static evaluation review, the design, and this plan. State the baseline/with-skill result and then begin a separate brainstorming/design cycle for `configs/devices/TR3000/TR3000-Full-综合增强版-提示词.md`.
