# TR3000 Full Firmware Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a reproducible, independent TR3000-Full GitHub Actions build with safe industrial-network defaults and a standard LuCI Bootstrap management page.

**Architecture:** Reuse the already verified TR3000 128 MiB U-Boot Mod source, profile, 112 MiB UBI layout, pinned feeds, and industrial-network helpers without changing Lite. A Full-only seed, configuration script, build script, local LuCI package, and workflow own all Full behavior. Optional packages are selected at build time; all remote-access services remain disabled at runtime until an administrator explicitly enables them.

**Tech Stack:** POSIX shell, OpenWrt Kconfig, firewall4/UCI, LuCI JavaScript views, GitHub Actions, Python `unittest` contract tests.

**Spec:** `configs/devices/TR3000/TR3000-Full-综合增强版-提示词.md`

## Global Constraints

- Target only Cudy TR3000 128 MiB NAND / 512 MiB RAM / MT7981 with `cudy_tr3000-v1-ubootmod` and the verified 112 MiB UBI DTS range `0x7000000`.
- Never mix the 128M-Ubootmod image with factory 128M, 256M, or 122 MiB layouts.
- Use pinned upstream project, firmware source, Actions, and full feed commit SHAs.
- Default build includes Tailscale and sing-box; cloudflared defaults off and is controlled by a build input.
- Tailscale, sing-box, cloudflared, and WireGuard listener/remote access remain disabled by default at runtime.
- Keep `plant` DHCPv4, DHCPv6, RA, and NDP disabled; do not embed site IPs, VPN keys, tokens, UUIDs, or Wi-Fi secrets.
- Use standard LuCI Bootstrap; explicitly exclude Aurora, OpenClash, PassWall, UPnP, AdGuard Home, Docker, and Bandix.
- GitHub Actions is the authoritative compilation environment; native Windows only edits, validates, and runs repository tests.
- Do not modify the existing Lite or U-Boot build behavior.

## Review Focus

- A false optional input must remove its package even when the upstream base config selected it.
- A true optional input must select the package and fail configuration if `make defconfig` cannot keep it selected.
- An unknown boolean or malformed ccache path must fail before mutating the source `.config`.
- The final firmware artifact must be a non-empty `cudy_tr3000-v1-ubootmod` sysupgrade image and must pass size/layout/profile gates before packaging.
- LuCI actions must be admin-ACL protected, invoke only the fixed service controller, and never accept arbitrary command paths.

---

### Task 1: Full configuration contract

**Files:**
- Create: `configs/full.seed`
- Create: `feeds/devices/tr3000-full.lock`
- Create: `scripts/configure-full.sh`
- Modify: `tests/scripts/test_scripts.py`

**Interfaces:**
- Consumes: upstream `config/128muboot.config`, pinned source tree, `CCACHE_DIR`, and boolean include switches.
- Produces: validated source `.config` plus installed Full overlay/local LuCI package inputs for Task 2.

- [ ] Write failing tests for default package selection, false/true optional overrides, invalid booleans, hyphenated symbols, ccache override, unique profile, and 112 MiB DTS enforcement.
- [ ] Run the focused script tests and confirm they fail because `configure-full.sh` does not exist.
- [ ] Add the Full seed, copied pinned feed lock, and `configure-full.sh --source-dir DIR --base-config FILE [--seed FILE] [--ccache-dir DIR] [--include-tailscale BOOL] [--include-singbox BOOL] [--include-cloudflared BOOL]`.
- [ ] Run the focused tests and the complete script test module; expect all pass.
- [ ] Commit the task.

### Task 2: Full build, image gates, and workflow

**Files:**
- Create: `scripts/verify-image.sh`
- Create: `scripts/build-full.sh`
- Create: `.github/workflows/build-full.yml`
- Modify: `tests/scripts/test_scripts.py`
- Modify: `tests/workflows/test_workflows.py`

**Interfaces:**
- Consumes: Task 1 configuration interface, pinned source/project SHAs, and boolean workflow inputs.
- Produces: provenance, logs, final config/package manifests, checksums, and only gated Full sysupgrade artifacts.

- [ ] Write failing tests for script help/syntax, image rejection/acceptance boundaries, typed workflow inputs, pinned sources/actions, safe permissions, and data-only input passing.
- [ ] Run focused tests and confirm failure on missing scripts/workflow.
- [ ] Implement `verify-image.sh` with explicit profile, DTS, non-empty sysupgrade, maximum-size, and filename gates; implement `build-full.sh` using the Full lock/configuration path.
- [ ] Add `build-full.yml` with booleans `include_tailscale=true`, `include_singbox=true`, `include_cloudflared=false`, and `release=false`; keep release creation out until a separately gated publishing job is implemented.
- [ ] Run focused tests and complete workflow/script modules; expect all pass.
- [ ] Commit the task.

### Task 3: Standard LuCI management and runtime-safe defaults

**Files:**
- Create: `packages/luci-app-tr3000-full/Makefile`
- Create: `packages/luci-app-tr3000-full/root/usr/share/luci/menu.d/luci-app-tr3000-full.json`
- Create: `packages/luci-app-tr3000-full/root/usr/share/rpcd/acl.d/luci-app-tr3000-full.json`
- Create: `packages/luci-app-tr3000-full/htdocs/luci-static/resources/view/tr3000-full/services.js`
- Create: `scripts/service-toggle.sh`
- Create: `files/etc/uci-defaults/95-tr3000-full-services`
- Modify: `scripts/configure-full.sh`
- Modify: `tests/scripts/test_scripts.py`
- Modify: `tests/structure/test_repository_contract.py`

**Interfaces:**
- Consumes: fixed service IDs `wireguard`, `tailscale`, `sing-box`, `cloudflared` and OpenWrt procd/UCI/firewall interfaces.
- Produces: `/usr/sbin/tr3000-full-service` JSON status and enable/disable actions used only by the LuCI admin page.

- [ ] Write failing tests for fixed service allow-list behavior, no arbitrary command execution, safe defaults, LuCI menu/ACL/view package structure, and copied Full-only assets.
- [ ] Run focused tests and confirm they fail on missing service controller/package.
- [ ] Implement the service controller, first-boot disable policy, and Bootstrap-compatible LuCI JavaScript page with an admin-only fixed executable ACL.
- [ ] Extend `configure-full.sh` to install only Full runtime assets and the local LuCI package into the source tree.
- [ ] Run focused tests and all script/structure tests; expect all pass.
- [ ] Commit the task.

### Task 4: Operator documentation and repository integration

**Files:**
- Create: `docs/FULL-README.md`
- Create: `docs/WIREGUARD-SNAT.md`
- Create: `docs/TAILSCALE.md`
- Create: `docs/SINGBOX-SPLIT-ROUTING.md`
- Create: `docs/CLOUDFLARED-ACCESS.md`
- Modify: `docs/TEST-PLAN.md`
- Modify: `README.md`
- Modify: `tests/structure/test_repository_contract.py`

**Interfaces:**
- Consumes: Tasks 1-3 commands, defaults, package switches, and artifact naming.
- Produces: Chinese build/deploy/rollback/safety guidance and discoverable repository links.

- [ ] Write failing repository-contract tests for required Full documents and README local-link resolution.
- [ ] Run the focused structure tests and confirm missing-document failure.
- [ ] Document Actions operation, artifact interpretation, standard LuCI usage, first-boot injection, WireGuard SNAT authorization, Tailscale ACL/routes, sing-box exclusions/rollback, cloudflared Access boundaries, U-Boot/layout warnings, and CI/simulator/device test distinctions.
- [ ] Run structure tests, `bash scripts/validate.sh`, the full unit suite, and `git diff --check`.
- [ ] Commit the task and request one whole-change review.
