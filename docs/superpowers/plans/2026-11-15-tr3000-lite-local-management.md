# TR3000 Lite Local Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give TR3000 Lite a safe always-available management AP, an immediately active but editable `192.168.10.254/24` plant address, and a dedicated LuCI page that applies plant network/firewall changes with validation and rollback.

**Architecture:** Keep all behavior in a Lite-only overlay applied after the shared rootfs so Full remains unchanged. A fixed, parameter-validating shell controller owns plant status/validation/apply/restore; a minimal LuCI package may execute only that controller. Network and firewall updates use paired backups, candidate validation, post-apply checks, and best-effort rollback.

**Tech Stack:** POSIX shell, OpenWrt UCI/netifd/firewall4, LuCI JavaScript views, rpcd ACL JSON, Python `unittest`.

**Spec:** `docs/superpowers/specs/2026-11-14-tr3000-lite-industrial-lan-management-design.md`

## Global Constraints

- Target only Cudy TR3000 v1, 128 MiB NAND, `cudy_tr3000-v1-ubootmod`, 112 MiB UBI.
- Keep precedence `common → distribution → device → local`; this plan changes only the TR3000 Lite device/variant layer.
- Do not modify generated paths `work/`, `output/`, or `cache/`.
- Do not commit passwords, Wi-Fi keys, WireGuard keys, Cloudflare tokens, or files under `local/` except its README.
- `plant` starts as `eth1`, `192.168.10.254/24`; DHCPv4, DHCPv6, RA and odhcpd NDP proxy/service stay disabled.
- `mgmt` stays `192.168.77.1/24`, DHCP pool `.100-.149`; `mgmt` and `plant` are never bridged.
- Management AP is always enabled, encrypted, and must survive STA/uplink failures.
- Plant Web management means HTTPS 443 only; WAN management remains closed.
- Windows may edit files, run repository tests and Git; firmware compilation remains GitHub Actions/Linux.

## Review Focus

- Invalid, overlapping, network/broadcast or ARP-conflicting plant CIDR must leave both network and firewall unchanged; Task 2 tests each case.
- Empty root password or incomplete first-boot identity must keep plant Web management disabled; Task 4 tests the gate.
- Failure between network and firewall reload must restore the paired backup and report degraded recovery if verification fails; Task 2 tests both paths.
- Lite overlay installation must not change Full's shared `files/` behavior; Task 1 tests both configure scripts.
- Re-running first-boot/AP setup must preserve the existing SSID/key instead of rotating credentials; Task 4 tests idempotency.

---

## File Map

- `overlays/devices/tr3000-lite/files/etc/config/{network,dhcp,firewall,tr3000-lite}` — Lite-only default network and policy.
- `scripts/tr3000-lite-plant.sh` — fixed controller with `status`, `validate`, `apply`, and `restore` commands.
- `scripts/tr3000-lite-plant-lib.sh` — pure parsing, CIDR, rendering, backup-ID and JSON helpers shared by controller tests.
- `packages/luci-app-tr3000-lite/` — LuCI package, Industrial LAN view, menu and narrow ACL.
- `overlays/devices/tr3000-lite/files/etc/uci-defaults/91-tr3000-lite-management-ap` — idempotent random WPA2 management AP setup.
- `scripts/configure-lite.sh`, `configs/lite.seed` — inject the package/overlay and enforce final package selection.
- `tests/scripts/test_tr3000_lite_plant.py`, `tests/scripts/test_tr3000_lite_wifi.py` — controller and first-boot behavior tests.
- `tests/structure/test_repository_contract.py`, `tests/scripts/test_scripts.py` — integration/package/overlay contracts.

### Task 1: Establish the Lite-only overlay boundary

**Files:**
- Create: `overlays/devices/tr3000-lite/files/etc/config/network`
- Create: `overlays/devices/tr3000-lite/files/etc/config/dhcp`
- Create: `overlays/devices/tr3000-lite/files/etc/config/firewall`
- Create: `overlays/devices/tr3000-lite/files/etc/config/tr3000-lite`
- Modify: `scripts/configure-lite.sh`
- Modify: `tests/scripts/test_scripts.py`
- Modify: `tests/structure/test_repository_contract.py`

**Interfaces:**
- Consumes: shared rootfs copied from `files/`.
- Produces: Lite source tree where `overlays/devices/tr3000-lite/files/` is copied last; UCI sections `network.plant`, `network.mgmt`, `dhcp.plant`, zones `plant`/`mgmt`, and policy config `tr3000-lite.plant`.

- [ ] **Step 1: Write failing overlay contract tests**

Add `test_lite_config_installs_lite_overlay_after_shared_files()` and extend `run_lite_configure()` to return installed assets and file contents. Assert Lite has `network.plant.proto='static'`, IP `192.168.10.254`, netmask `255.255.255.0`, while `run_full_configure()` still receives the current shared config without a Lite-only package or overlay path.

- [ ] **Step 2: Run the focused tests and verify failure**

Run: `python -m unittest tests.scripts.test_scripts.ScriptInterfaceTests.test_lite_config_installs_lite_overlay_after_shared_files tests.structure.test_repository_contract.RepositoryContractTests.test_tr3000_lite_overlay_is_device_scoped -v`

Expected: FAIL because the overlay and copy step do not exist.

- [ ] **Step 3: Add the four Lite UCI configs**

Set `plant` to `eth1`, static `192.168.10.254/24`; keep `mgmt` on a separate `br-mgmt`; keep plant DHCP/RA/NDP services disabled; include a disabled plant-to-router HTTPS rule and enabled `mgmt → plant` ICMP/TCP rules with explicit SNAT to the plant address. Store toggles as `tr3000-lite.plant.allow_luci='0'`, `allow_mgmt='1'`, and `allow_wireguard='0'` for Plan 3. The controller may enable plant HTTPS only after confirming a nonempty root password.

- [ ] **Step 4: Install the Lite overlay after shared files**

In `configure-lite.sh`, copy the shared `files/` first, then copy `overlays/devices/tr3000-lite/files/.` over `$SOURCE_DIR/files/`. Reject a missing overlay directory. Do not alter `configure-full.sh`.

- [ ] **Step 5: Run focused and regression tests**

Run: `python -m unittest tests.scripts.test_scripts tests.structure.test_repository_contract -v`

Expected: PASS, including an assertion that Full content is unchanged.

- [ ] **Step 6: Commit**

```bash
git add overlays/devices/tr3000-lite scripts/configure-lite.sh tests/scripts/test_scripts.py tests/structure/test_repository_contract.py
git commit -m "feat(lite): add device-scoped management network overlay"
```

### Task 2: Build the transactional plant controller

**Files:**
- Create: `scripts/tr3000-lite-plant-lib.sh`
- Create: `scripts/tr3000-lite-plant.sh`
- Create: `tests/scripts/test_tr3000_lite_plant.py`
- Modify: `scripts/configure-lite.sh`
- Modify: `tests/scripts/test_scripts.py`

**Interfaces:**
- Consumes: `lite-common.sh`, UCI configs from Task 1, commands `uci`, `ubus`, `ip`, `arping`, `fw4`.
- Produces: `/usr/sbin/tr3000-lite-plant` with exact commands `status --json`, `validate --address IPV4/PREFIX`, `apply --address IPV4/PREFIX --allow-luci true|false --allow-mgmt true|false`, and `restore --backup-id SAFE_ID`.

- [ ] **Step 1: Write failing CLI/validation tests**

Test exact exit codes and JSON keys `schema_version`, `plant`, `checks`, `backup_id`, `rollback`. Cover valid `192.168.10.254/24`; invalid IPv4; `/31`; network/broadcast address; overlap with `192.168.77.0/24`; WAN-device reuse; ARP conflict/failure; unknown/repeated options; unsafe backup IDs.

- [ ] **Step 2: Write failing transaction tests**

Using fake `uci`, `ubus`, `fw4`, `ip`, and `arping` executables in a temporary `PATH`, assert: candidate `fw4 check` happens before commit; network/firewall backups are paired and mode `0600`; network reload failure restores both; firewall reload failure restores both; post-apply missing plant IP restores both; only five backup pairs remain.

- [ ] **Step 3: Run tests and verify failure**

Run: `python -m unittest tests.scripts.test_tr3000_lite_plant -v`

Expected: FAIL because the controller does not exist.

- [ ] **Step 4: Implement the library and controller interfaces**

Keep parsing and JSON escaping in `tr3000-lite-plant-lib.sh`; use `mkdir` as an atomic lock; use a root-owned backup directory under `/etc/tr3000-lite/backups`; reject symlinks; call existing CIDR/route helpers rather than duplicating them. Treat reload as best-effort transaction plus explicit post-apply verification, not ACID.

- [ ] **Step 5: Install the fixed controller**

Install the controller as `/usr/sbin/tr3000-lite-plant` and the library as `/usr/lib/tr3000-lite/plant-lib.sh`; add both source scripts to syntax/help tests. `--help` must return 0 and contain `Usage:`.

- [ ] **Step 6: Run focused and repository tests**

Run: `python -m unittest tests.scripts.test_tr3000_lite_plant tests.scripts.test_scripts -v`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add scripts/tr3000-lite-plant*.sh scripts/configure-lite.sh tests/scripts/test_tr3000_lite_plant.py tests/scripts/test_scripts.py
git commit -m "feat(lite): add safe industrial LAN controller"
```

### Task 3: Add the Industrial LAN LuCI package

**Files:**
- Create: `packages/luci-app-tr3000-lite/Makefile`
- Create: `packages/luci-app-tr3000-lite/htdocs/luci-static/resources/view/tr3000-lite/industrial-lan.js`
- Create: `packages/luci-app-tr3000-lite/root/usr/share/luci/menu.d/luci-app-tr3000-lite.json`
- Create: `packages/luci-app-tr3000-lite/root/usr/share/rpcd/acl.d/luci-app-tr3000-lite.json`
- Modify: `configs/lite.seed`
- Modify: `scripts/configure-lite.sh`
- Modify: `tests/structure/test_repository_contract.py`
- Modify: `tests/scripts/test_scripts.py`

**Interfaces:**
- Consumes: `/usr/sbin/tr3000-lite-plant` from Task 2.
- Produces: LuCI route `admin/network/tr3000-lite/industrial-lan`; package `luci-app-tr3000-lite`; ACL allowing only fixed-controller execution.

- [ ] **Step 1: Write failing package/ACL tests**

Assert the menu has no custom auth bypass, depends on ACL `luci-app-tr3000-lite`, ACL write access equals `{ "/usr/sbin/tr3000-lite-plant": ["exec"] }`, has no arbitrary file read/write and the view never invokes `/bin/sh` or `uci` directly.

- [ ] **Step 2: Write failing view contract tests**

Assert the view calls `status --json`, `validate --address`, and `apply`; renders address/prefix, permanent DHCP-off status, plant HTTPS and mgmt access toggles; disables apply until validation succeeds; warns that the current session may disconnect; does not display secrets.

- [ ] **Step 3: Run focused tests and verify failure**

Run: `python -m unittest tests.structure.test_repository_contract.RepositoryContractTests.test_lite_luci_package_is_admin_only_and_uses_fixed_controller -v`

Expected: FAIL because the package does not exist.

- [ ] **Step 4: Implement and inject the package**

Follow the existing Full package layout. Copy it into `$SOURCE_DIR/package/luci-app-tr3000-lite` before `make defconfig`, select `CONFIG_PACKAGE_luci-app-tr3000-lite=y`, and add it to Lite's required-package check. Depend on `+luci-base +rpcd-mod-file` only.

- [ ] **Step 5: Run package integration tests**

Run: `python -m unittest tests.structure.test_repository_contract tests.scripts.test_scripts -v`

Expected: PASS and the fake configured source contains `package/luci-app-tr3000-lite/Makefile`.

- [ ] **Step 6: Commit**

```bash
git add packages/luci-app-tr3000-lite configs/lite.seed scripts/configure-lite.sh tests
git commit -m "feat(lite): add industrial LAN LuCI page"
```

### Task 4: Create the always-on encrypted management AP

**Files:**
- Create: `overlays/devices/tr3000-lite/files/etc/uci-defaults/91-tr3000-lite-management-ap`
- Create: `tests/scripts/test_tr3000_lite_wifi.py`
- Modify: `configs/lite.seed`
- Modify: `scripts/configure-lite.sh`
- Modify: `tests/scripts/test_scripts.py`
- Modify: `docs/LITE-README.md`

**Interfaces:**
- Consumes: existing upstream `wifi-device` sections, `mgmt` network from Task 1, root password state.
- Produces: one idempotent AP per usable radio, shared SSID `TR3000-Lite-<stable suffix>`, shared 32-hex-character WPA2 key, and `/etc/tr3000-lite/management-ap.initialized` marker.

- [ ] **Step 1: Write failing first-boot tests**

With fake `uci`, `/dev/urandom`, MAC and password-state inputs, assert: no open AP; 16 random bytes become 32 hex characters; all detected radios receive one `mode='ap'`, `network='mgmt'`, `encryption='psk2'` section; no radio case fails closed; existing nonempty SSID/key are preserved; second run creates no duplicate sections or key rotation.

- [ ] **Step 2: Write failing management gate test**

Assert plant HTTPS and remote-management toggles remain disabled until a nonempty root password is detected and the AP initialization marker exists. The script may create the AP before the password is set, but must not open remote or plant LuCI.

- [ ] **Step 3: Run tests and verify failure**

Run: `python -m unittest tests.scripts.test_tr3000_lite_wifi -v`

Expected: FAIL because the defaults script does not exist.

- [ ] **Step 4: Implement the idempotent defaults script**

Use actual UCI `wifi-device` sections rather than hard-coded radio bands; derive the stable suffix from the first valid device/radio MAC and persist a random fallback if unavailable. Never print the key. Delete the uci-defaults script only after a successful commit and marker write.

Explicitly keep `CONFIG_PACKAGE_wpad-openssl=y`, already selected by the pinned `128muboot.config`, and add it to `configure-lite.sh` required-package checks so AP+STA capability cannot silently disappear after a baseline change. Reject conflicting alternative `wpad-*` providers in the final `.config` test.

- [ ] **Step 5: Run focused and full local checks**

Run: `python -m unittest tests.scripts.test_tr3000_lite_wifi tests.scripts.test_scripts -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add overlays/devices/tr3000-lite/files/etc/uci-defaults/91-tr3000-lite-management-ap configs/lite.seed scripts/configure-lite.sh tests/scripts/test_tr3000_lite_wifi.py tests/scripts/test_scripts.py docs/LITE-README.md
git commit -m "feat(lite): enable persistent encrypted management AP"
```

### Task 5: Update contracts and verify the local-management milestone

**Files:**
- Modify: `docs/LITE-README.md`
- Modify: `docs/TEST-PLAN.md`
- Modify: `docs/cudy-tr3000-uboot-flashing-record.md`
- Modify: `scripts/build-lite.sh`

**Interfaces:**
- Consumes: Tasks 1-4.
- Produces: accurate operating docs and Artifact evidence that the Lite package/config is present.

- [ ] **Step 1: Update documentation assertions**

Replace obsolete claims that plant has no IP, no AP exists, and mgmt cannot reach plant. Document default `192.168.10.254/24`, mandatory manual conflict confirmation before HUB connection, HTTPS-only plant management, AP credential initialization, CIDR change/rollback and unverified hardware items.

- [ ] **Step 2: Extend build Artifact evidence**

Add a sanitized `lite-runtime-contract.txt` containing expected interface names, default CIDRs, package name and policy flags, never credentials. Verify `selected-packages.txt` contains `luci-app-tr3000-lite`.

- [ ] **Step 3: Run required local verification**

Run: `bash scripts/validate.sh`

Expected: exit 0 and `Manifest catalog is valid.`

Run: `python -m unittest discover -s tests -v`

Expected: all tests PASS.

- [ ] **Step 4: Run diff and secret checks**

Run: `git diff --check`

Run: `git status --short`

Run: `rg -n -i "privatekey|api[_ -]?token|password\s*=|psk\s*=" --glob '!docs/superpowers/**' --glob '!tests/**' .`

Expected: no production secret; only intentional placeholders/config field names.

- [ ] **Step 5: Trigger and inspect the Lite GitHub Actions build**

Run: `gh workflow run build-lite.yml --ref <implementation-branch>`

Then: `gh run watch <run-id> --exit-status`

Expected: success. Download `tr3000-lite-128m-ubootmod-112m`; confirm final `build.config`, selected packages, runtime contract, target profile, 112 MiB DTS and sysupgrade SHA256. Do not claim bootability until truth-device tests pass.

- [ ] **Step 6: Commit**

```bash
git add docs scripts/build-lite.sh
git commit -m "docs(lite): define local management deployment contract"
```
