# TR3000 Lite Multi-Uplink Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add optional Wi-Fi Client and approved RNDIS/CDC-Ether USB 4G uplinks while keeping the management AP alive and providing deterministic `wan → wwan → usbwan` failover.

**Architecture:** Keep netifd as owner of interface configuration and use one locked reconciliation loop for health state, effective metrics, WireGuard restart notifications and DDNS events. Standard LuCI wireless join handles SSID/password so secrets never appear in custom process arguments; a read-only Lite status page explains active uplink and links to the standard wireless page. USB hotplug accepts only netdevs whose USB parent driver is `rndis_host` or `cdc_ether`.

**Tech Stack:** POSIX shell, OpenWrt netifd/ubus/UCI/procd/hotplug, LuCI JavaScript, Python `unittest`.

**Spec:** `docs/superpowers/specs/2026-11-14-tr3000-lite-industrial-lan-management-design.md`

## Global Constraints

- Requires the completed local-management plan and its `luci-app-tr3000-lite` package.
- Management AP is always enabled; STA scan, join, failure or removal must not delete or permanently disable it.
- Interface priority is `wan` metric 10, `wwan` metric 20, `usbwan` metric 30.
- Wi-Fi Client uses DHCP and only explicit, user-selected encrypted SSIDs; no automatic open-network join.
- USB default support is limited to DHCP Ethernet devices driven by `rndis_host` or `cdc_ether`; do not add QMI, MBIM, NCM, ModemManager, serial dialer or vendor packages.
- Uplink state and logs must never include Wi-Fi passwords, SIM data or later DDNS/WireGuard credentials.
- Do not infer `radio0`/`radio1` bands; use actual UCI sections and runtime capabilities.

## Review Focus

- STA join/reconnect on a shared radio must leave at least one management AP section configured; Task 1 tests it.
- An unrelated USB Ethernet adapter must not be auto-claimed as `usbwan`; Task 2 tests driver/USB-parent filtering.
- DHCP renew or netifd route replacement during a health transition must converge without duplicate/deleted foreign routes; Task 3 tests reconciliation.
- ICMP-blocked but otherwise usable uplinks must be configurable with alternate probe targets and must not flap indefinitely; Task 3 tests thresholds and target validation.
- Rapid plug/unplug and concurrent daemon invocations must serialize and settle on the correct active interface; Tasks 2-3 test locks and event debounce.

---

## File Map

- `overlays/devices/tr3000-lite/files/etc/config/network` — `wwan` and `usbwan` DHCP interfaces/metrics.
- `overlays/devices/tr3000-lite/files/etc/config/lite-uplink-watch` — probes, thresholds and interface order.
- `scripts/lite-uplink-watch.sh` — locked health/reconciliation state machine.
- `scripts/tr3000-lite-uplink-status.sh` — read-only JSON status controller for LuCI and later remote orchestration.
- `overlays/devices/tr3000-lite/files/etc/hotplug.d/net/90-tr3000-lite-usbwan` — approved USB netdev attach/detach events.
- `overlays/devices/tr3000-lite/files/etc/init.d/lite-uplink-watch` — procd service.
- `packages/luci-app-tr3000-lite/.../uplinks.js` — status and standard wireless-page link.
- `tests/scripts/test_tr3000_lite_uplink.py`, `tests/scripts/test_tr3000_lite_usbwan.py` — state machine/hotplug tests.

### Task 1: Define safe AP+Client behavior

**Files:**
- Modify: `overlays/devices/tr3000-lite/files/etc/config/network`
- Create: `tests/scripts/test_tr3000_lite_wifi_client.py`
- Modify: `packages/luci-app-tr3000-lite/htdocs/luci-static/resources/view/tr3000-lite/industrial-lan.js`
- Modify: `packages/luci-app-tr3000-lite/root/usr/share/luci/menu.d/luci-app-tr3000-lite.json`
- Modify: `docs/LITE-README.md`

**Interfaces:**
- Consumes: management AP UCI sections from the local-management plan and standard LuCI `admin/network/wireless` join workflow.
- Produces: `network.wwan` DHCP metric 20 and a Lite menu/status link to the standard wireless configuration page.

- [ ] **Step 1: Write failing AP preservation tests**

Model UCI wireless fixtures with one/two radios and assert adding/removing a `mode='sta'`, `network='wwan'` section never removes, renames or disables existing `mode='ap'`, `network='mgmt'` sections. Assert the firmware creates no default/open STA profile and only an explicit standard-LuCI join can add a Client profile; document a warning before a user deliberately joins an open network.

- [ ] **Step 2: Run tests and verify failure**

Run: `python -m unittest tests.scripts.test_tr3000_lite_wifi_client -v`

Expected: FAIL because the contract helpers/tests are not implemented.

- [ ] **Step 3: Implement the UCI/network contract**

Keep `wwan` as DHCP, metric 20, disabled until a standard LuCI wireless join binds a STA. Add a Lite status/menu entry that explains AP-only, AP+Client and disconnected-Client states and links to `admin/network/wireless`; do not build a custom password-taking controller.

- [ ] **Step 4: Add radio coexistence status**

Display the actual AP/STA radio and channel from ubus/UCI. Warn when AP and STA share a PHY that AP channel follows STA and scanning/reconnect may briefly interrupt management.

- [ ] **Step 5: Run focused tests**

Run: `python -m unittest tests.scripts.test_tr3000_lite_wifi_client tests.structure.test_repository_contract -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add overlays/devices/tr3000-lite/files/etc/config/network packages/luci-app-tr3000-lite tests/scripts/test_tr3000_lite_wifi_client.py docs/LITE-README.md
git commit -m "feat(lite): support optional Wi-Fi client uplink"
```

### Task 2: Add approved USB Ethernet hotplug

**Files:**
- Create: `overlays/devices/tr3000-lite/files/etc/hotplug.d/net/90-tr3000-lite-usbwan`
- Create: `scripts/tr3000-lite-usbwan-lib.sh`
- Create: `tests/scripts/test_tr3000_lite_usbwan.py`
- Modify: `scripts/configure-lite.sh`
- Modify: `tests/scripts/test_scripts.py`

**Interfaces:**
- Consumes: hotplug variables `ACTION`, `INTERFACE`, `DEVPATH`; sysfs netdev device/driver ancestry; UCI `network.usbwan`.
- Produces: attach/detach requests for exactly one approved `rndis_host`/`cdc_ether` USB netdev and status file `/var/run/tr3000-lite/usbwan.json` without secrets.

- [ ] **Step 1: Write failing classification tests**

Create fake sysfs trees and test `tr3000_lite_usbwan_classify NETDEV SYSFS_ROOT` returns approved driver, USB VID/PID and stable device path only for `rndis_host`/`cdc_ether` with a USB parent. Reject PCI Ethernet, virtual/TUN, `cdc_ncm`, `qmi_wwan`, `cdc_mbim`, missing driver and second simultaneous candidate.

- [ ] **Step 2: Write failing hotplug lifecycle tests**

Assert `add` binds the approved netdev to `network.usbwan` and requests `ifup usbwan`; `remove` only tears down the currently bound device; repeated events are idempotent; rapid events use one lock; no fixed `usb0` assumption appears.

- [ ] **Step 3: Run tests and verify failure**

Run: `python -m unittest tests.scripts.test_tr3000_lite_usbwan -v`

Expected: FAIL because classifier/hotplug files do not exist.

- [ ] **Step 4: Implement classifier and hotplug script**

Keep VID/PID in status for diagnostics but classify by the explicitly supported driver and USB ancestry. If multiple approved candidates exist, fail closed and require LuCI/CLI selection; never steal the WAN, plant or an existing non-USB interface.

- [ ] **Step 5: Install and verify scripts**

Install the library under `/usr/lib/tr3000-lite/usbwan-lib.sh` through `configure-lite.sh`. Add `tr3000-lite-usbwan-lib.sh` and the hotplug script to the exact `sh -n` list; do not add the sourced library to the executable `--help` list.

Run: `python -m unittest tests.scripts.test_tr3000_lite_usbwan tests.scripts.test_scripts -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add overlays/devices/tr3000-lite/files/etc/hotplug.d scripts/tr3000-lite-usbwan-lib.sh scripts/configure-lite.sh tests
git commit -m "feat(lite): add safe USB Ethernet uplink hotplug"
```

### Task 3: Refactor uplink health into a locked reconciler

**Files:**
- Modify: `scripts/lite-uplink-watch.sh`
- Create: `scripts/tr3000-lite-uplink-lib.sh`
- Create: `tests/scripts/test_tr3000_lite_uplink.py`
- Modify: `overlays/devices/tr3000-lite/files/etc/config/lite-uplink-watch`
- Modify: `overlays/devices/tr3000-lite/files/etc/init.d/lite-uplink-watch`

**Interfaces:**
- Consumes: ubus interface status for `wan`, `wwan`, `usbwan`; validated probe lists; netifd-owned default routes.
- Produces: `reconcile`, `daemon`, `status --json`; atomic state under `/var/run/tr3000-lite/uplink/`; event hook `/usr/lib/tr3000-lite/uplink-changed ACTIVE PREVIOUS` invoked only after a stable transition.

- [ ] **Step 1: Write failing state-machine tests**

Assert base metrics `10/20/30`; three consecutive failed rounds mark unhealthy; two successful rounds recover; invalid/non-IP probes fail config validation; no gateway/default route is unavailable; active uplink is the lowest-metric healthy interface.

- [ ] **Step 2: Write failing concurrency/reconciliation tests**

Use fake `ip`/`ubus` snapshots to assert an atomic lock prevents two reconcilers; DHCP-renewed gateways/source addresses are reread before every change; only routes matching the interface's current netifd status are replaced; foreign routes are untouched; rerunning converges without duplicates.

- [ ] **Step 3: Write failing event tests**

Assert the event hook fires once after stable `wan→wwan`, `wwan→usbwan`, and recovery transitions; no event fires during threshold waiting; hook failure is logged but does not corrupt state.

- [ ] **Step 4: Run tests and verify failure**

Run: `python -m unittest tests.scripts.test_tr3000_lite_uplink -v`

Expected: FAIL against the current direct delete/add implementation.

- [ ] **Step 5: Implement the library/reconciler**

Separate parsing/state decisions in `tr3000-lite-uplink-lib.sh`. Use `mkdir` lock, atomic state-file rename, current ubus data, `ip route replace` for the exact owned default rather than blind delete/add, and periodic reconciliation after netifd events. Keep configurable probes per interface.

- [ ] **Step 6: Update procd service**

Run `lite-uplink-watch daemon`; add reload triggers for `network` and `lite-uplink-watch`; preserve respawn. Do not busy-loop faster than the existing 15-second interval.

- [ ] **Step 7: Run tests**

Run: `python -m unittest tests.scripts.test_tr3000_lite_uplink tests.scripts.test_scripts -v`

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add scripts/lite-uplink-watch.sh scripts/tr3000-lite-uplink-lib.sh overlays/devices/tr3000-lite/files/etc tests
git commit -m "refactor(lite): reconcile multi-uplink health safely"
```

### Task 4: Expose read-only uplink status in LuCI

**Files:**
- Create: `scripts/tr3000-lite-uplink-status.sh`
- Create: `packages/luci-app-tr3000-lite/htdocs/luci-static/resources/view/tr3000-lite/uplinks.js`
- Modify: `packages/luci-app-tr3000-lite/root/usr/share/luci/menu.d/luci-app-tr3000-lite.json`
- Modify: `packages/luci-app-tr3000-lite/root/usr/share/rpcd/acl.d/luci-app-tr3000-lite.json`
- Modify: `scripts/configure-lite.sh`
- Modify: `tests/structure/test_repository_contract.py`

**Interfaces:**
- Consumes: Task 3 `status --json`, USB status from Task 2, wireless UCI/ubus status.
- Produces: fixed read-only controller `/usr/sbin/tr3000-lite-uplink-status` and LuCI route `admin/network/tr3000-lite/uplinks`.

- [ ] **Step 1: Write failing ACL/view tests**

Assert ACL adds execute permission only for the fixed read-only controller; the view shows interface, type, link, DHCP address, gateway, base/effective metric, health, active marker and USB driver/VID/PID; no Wi-Fi key or command line is rendered.

- [ ] **Step 2: Run tests and verify failure**

Run: `python -m unittest tests.structure.test_repository_contract.RepositoryContractTests.test_lite_uplink_view_is_read_only -v`

Expected: FAIL because the view/controller do not exist.

- [ ] **Step 3: Implement status controller and view**

Controller accepts only `--json` and composes existing sanitized status. View includes actions that navigate to standard LuCI Wireless/Interfaces pages, not custom secret-bearing shell arguments.

- [ ] **Step 4: Run integration tests**

Run: `python -m unittest tests.structure.test_repository_contract tests.scripts.test_scripts -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/tr3000-lite-uplink-status.sh packages/luci-app-tr3000-lite scripts/configure-lite.sh tests
git commit -m "feat(lite): add multi-uplink status page"
```

### Task 5: Document and verify the multi-uplink milestone

**Files:**
- Modify: `docs/LITE-README.md`
- Modify: `docs/TEST-PLAN.md`
- Modify: `docs/WIREGUARD-VPS-ROUTING.md`
- Modify: `scripts/build-lite.sh`

**Interfaces:**
- Consumes: Tasks 1-4.
- Produces: complete AP+STA/USB/failover operating contract and Artifact evidence.

- [ ] **Step 1: Document supported and unsupported uplinks**

Describe AP always on, standard LuCI STA join, shared-radio disruption, saved approved profiles, RNDIS/CDC-Ether-only USB scope, multiple-device fail-closed behavior, and `10/20/30` thresholds. Explicitly exclude QMI/MBIM/NCM/serial claims.

- [ ] **Step 2: Add truth-device test cases**

Add exact cases for AP survival during STA scans/reconnect, Ethernet/STA/USB loss/recovery, DHCP renew during health transitions, ICMP-blocked alternate probes, unrelated USB Ethernet rejection, multiple USB candidates and rapid unplug/replug.

- [ ] **Step 3: Extend Artifact contract**

Record selected USB drivers, interface order, probe thresholds and installed hotplug/status paths in the sanitized runtime contract.

- [ ] **Step 4: Run required verification**

Run: `bash scripts/validate.sh`

Run: `python -m unittest discover -s tests -v`

Run: `git diff --check`

Expected: all exit 0; no secrets in diff.

- [ ] **Step 5: Run the Lite workflow and inspect Artifact**

Run: `gh workflow run build-lite.yml --ref <implementation-branch>` and watch the resulting run. Confirm final `.config` still contains only `kmod-usb-net`, `kmod-usb-net-rndis`, `kmod-usb-net-cdc-ether` for default USB 4G support and the sysupgrade still matches the 112 MiB profile.

- [ ] **Step 6: Commit**

```bash
git add docs scripts/build-lite.sh
git commit -m "docs(lite): define multi-uplink operating contract"
```
