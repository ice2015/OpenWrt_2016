# TR3000 Lite Dual Remote Access Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Provide conditional Cloudflare-DDNS WireGuard direct access, a reliable outbound VPS WireGuard path, remote LuCI/plant access controls, and a repeatable per-device staging workflow without embedding production secrets in the generic firmware.

**Architecture:** Use two independent WireGuard roles: UCI interface `wg_direct` listens for direct Windows peers; `wg_vps` initiates an outbound tunnel to the fixed VPS. A fail-closed synchronizer turns exact `/32` sources into firewall/SNAT rules for both roles, while standard pinned `ddns-scripts-cloudflare` updates an IPv4 DNS-only record. A two-phase staging workflow generates device keys on-device, validates a private inventory off-repo, applies the final bundle, and verifies VPS LuCI before release.

**Tech Stack:** OpenWrt WireGuard/UCI/firewall4, POSIX shell, `ddns-scripts` 2.8.2 from the pinned ImmortalWrt packages feed, Cloudflare API v4 extension, LuCI, Python 3 provisioning tools/tests.

**Spec:** `docs/superpowers/specs/2026-11-14-tr3000-lite-industrial-lan-management-design.md`

## Approved security clarification (2026-11-16)

User approved separating local enrollment from external acceptance. `/etc/tr3000-lite/enrolled` attests trusted local root/AP/identity/independent-key validation plus an authenticated staged VPS handshake. Only then may registered exact `/32` WireGuard peers receive HTTPS 443 access; plant access remains default-off. External HTTPS success creates a separate verified state, never inferred from local enrollment, DNS success or a UI checkbox. No production activation or flashing is authorized by this software-state clarification.

## Global Constraints

- Requires both local-management and multi-uplink plans to be complete.
- Generic firmware contains no production root password, WireGuard private key, Cloudflare token, VPS identity, hostname or customer route.
- Direct is preferred only when public UDP inbound has been verified; VPS is the staging/bootstrap and reliable CGNAT path.
- Cloudflare record is IPv4 A and DNS-only; this plan does not add `wan6`, AAAA or IPv6 WireGuard ingress.
- Remote Windows PC keeps `TR3000-<ID>-Direct` and `TR3000-<ID>-VPS` profiles and activates exactly one.
- Client routes contain the selected tunnel's router management `/32` and current plant CIDR; no `0.0.0.0/0`.
- Remote LuCI is HTTPS 443 only and requires nonempty root password plus completed device enrollment.
- “All configured peers” means an exact validated set of unique IPv4 `/32` addresses; one invalid/duplicate/wide entry fails the complete candidate sync closed.
- VPS must prevent device/customer lateral movement and route only registered Windows `/32` sources to the intended device.

## Review Focus

- `/24`, `0.0.0.0/0`, duplicate `/32` or malformed peer sources must leave no partial authorization; Task 2 tests candidate-set replacement.
- Empty root password, missing device identity or missing keys must keep listener/LuCI rules disabled; Tasks 2 and 5 test enrollment gates.
- Cloudflare API success with CGNAT/private WAN must not be reported as Direct reachable; Task 3 tests separate DNS and reachability states.
- Direct and VPS profiles active together must be documented/rejected by the staging output because they install the same plant route; Task 5 tests template metadata.
- Duplicate device IDs, hostnames, tunnel addresses or customer allocations must stop provisioning before any bundle is written; Task 4 tests inventory-wide uniqueness.

---

## File Map

- `configs/lite.seed`, `scripts/configure-lite.sh` — select pinned DDNS/LuCI packages and remote controllers.
- `overlays/devices/tr3000-lite/files/etc/config/{tr3000-lite-remote,ddns}` — disabled generic policy/config shells.
- `scripts/tr3000-lite-remote.sh`, `scripts/tr3000-lite-remote-lib.sh` — peer validation, status and firewall/SNAT synchronization.
- `overlays/devices/tr3000-lite/files/etc/hotplug.d/iface/96-tr3000-lite-remote-sync` — sync after WireGuard/network changes.
- `scripts/tr3000-lite-ddns-status.sh` — sanitized standard-DDNS status and Direct candidacy.
- `scripts/tr3000-lite-enroll.sh` — on-device prepare/apply/verify enrollment commands.
- `tools/tr3000_lite_provision.py` — off-device private inventory validation and final bundle/template rendering.
- `packages/luci-app-tr3000-lite/.../remote-access.js` — remote status/policy and generated AllowedIPs display.
- `docs/TR3000-LITE-PROVISIONING.md`, `docs/TR3000-LITE-REMOTE-ACCESS.md` — staging/VPS/Windows operating contracts.

### Task 1: Select the pinned Cloudflare DDNS packages

**Files:**
- Modify: `configs/lite.seed`
- Modify: `scripts/configure-lite.sh`
- Modify: `tests/scripts/test_scripts.py`
- Create: `overlays/devices/tr3000-lite/files/etc/config/ddns`

**Interfaces:**
- Consumes: pinned packages feed commit `171d5f9203379f77693807d7283515a873f95df9` and LuCI feed commit `cc142cd196d425d9f14f9c18f072913730b642ce`.
- Produces: selected packages `ddns-scripts`, `ddns-scripts-cloudflare`, `luci-app-ddns`; disabled IPv4-only UCI section `ddns.tr3000_direct` using service `cloudflare.com-v4`.

- [ ] **Step 1: Write failing package/config tests**

Extend `lite_base_config()` and assertions so final `.config` must contain the three exact packages. Assert generic `/etc/config/ddns` has `enabled='0'`, `use_ipv6='0'`, no hostname/token/zone and no placeholder that could be mistaken for a credential.

- [ ] **Step 2: Run tests and verify failure**

Run: `python -m unittest tests.scripts.test_scripts.ScriptInterfaceTests.test_lite_config_selects_cloudflare_ddns_packages -v`

Expected: FAIL because packages/config are absent.

- [ ] **Step 3: Select and validate the packages**

Add exact `CONFIG_PACKAGE_...=y` entries and required-package checks. Do not add a floating feed or custom Cloudflare updater; use the pinned extension verified by the feed commit.

- [ ] **Step 4: Add the disabled generic DDNS section**

Configure IPv4 only and ensure DDNS remains disabled until staging supplies a hostname and token and enrollment gates pass. Preserve DNS-only proxy state as a provisioning prerequisite; the updater changes address content, not Cloudflare proxy mode.

- [ ] **Step 5: Run tests**

Run: `python -m unittest tests.scripts.test_scripts -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add configs/lite.seed scripts/configure-lite.sh overlays/devices/tr3000-lite/files/etc/config/ddns tests/scripts/test_scripts.py
git commit -m "feat(lite): include pinned Cloudflare DDNS support"
```

### Task 2: Implement dual WireGuard authorization synchronization

**Files:**
- Create: `overlays/devices/tr3000-lite/files/etc/config/tr3000-lite-remote`
- Create: `scripts/tr3000-lite-remote-lib.sh`
- Create: `scripts/tr3000-lite-remote.sh`
- Create: `overlays/devices/tr3000-lite/files/etc/hotplug.d/iface/96-tr3000-lite-remote-sync`
- Create: `tests/scripts/test_tr3000_lite_remote.py`
- Modify: `scripts/configure-lite.sh`
- Modify: `tests/scripts/test_scripts.py`

**Interfaces:**
- Consumes: UCI `network.wg_direct`, `network.wg_vps`, exact direct peer AllowedIPs, explicit `list vps_remote_source 'IPV4/32'`, current plant CIDR/IP, root-password/enrollment markers.
- Produces: `/usr/sbin/tr3000-lite-remote` commands `status --json`, `sync`, `set-policy --allow-luci true|false --allow-plant true|false`; owned firewall sections prefixed `tr3000_lite_remote_` only.

- [ ] **Step 1: Write failing source-set tests**

Test zero, one and many direct/VPS `/32` sources; reject duplicates across paths, `/24`, `/0`, IPv6, malformed entries and a Peer with no exact `/32`. Assert any invalid candidate yields zero new rules and preserves the last known-good set only when it still matches current plant; otherwise fail closed.

- [ ] **Step 2: Write failing firewall/SNAT tests**

Assert policy-off produces no allow/SNAT sections; LuCI policy allows TCP 443 to router only; plant policy allows ICMP Echo and TCP to current plant CIDR and creates SNAT to current plant IP for every exact source; UDP and other destinations remain denied; only owned-prefix sections are replaced.

- [ ] **Step 3: Write failing enrollment/root gates**

Assert missing `/etc/tr3000-lite/enrolled`, empty root password, missing interface key or missing device identity disables Direct listener rule and both remote LuCI policies. `wg_vps` may initiate only after its complete staged config exists.

- [ ] **Step 4: Run tests and verify failure**

Run: `python -m unittest tests.scripts.test_tr3000_lite_remote -v`

Expected: FAIL because the synchronizer does not exist.

- [ ] **Step 5: Implement locked candidate synchronization**

Use a lock, parse exact UCI sources, generate candidate owned UCI sections, run `fw4 check`, then commit/reload. Never open an entire WireGuard zone. Keep UCI interface names exactly `wg_direct` and `wg_vps`; update the existing uplink event hook to restart only enabled/configured WireGuard roles.

- [ ] **Step 6: Install hotplug/reload synchronization**

Trigger `sync` after `wg_direct`, `wg_vps`, plant and firewall changes with debounce; repeated events are idempotent. Add source scripts to syntax/help tests.

- [ ] **Step 7: Run focused and regression tests**

Run: `python -m unittest tests.scripts.test_tr3000_lite_remote tests.scripts.test_scripts -v`

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add overlays/devices/tr3000-lite/files/etc/config/tr3000-lite-remote overlays/devices/tr3000-lite/files/etc/hotplug.d scripts/tr3000-lite-remote*.sh scripts/configure-lite.sh tests
git commit -m "feat(lite): synchronize dual WireGuard access safely"
```

### Task 3: Add sanitized Cloudflare/DDNS and Direct status

**Files:**
- Create: `scripts/tr3000-lite-ddns-status.sh`
- Create: `tests/scripts/test_tr3000_lite_ddns.py`
- Modify: `scripts/configure-lite.sh`
- Modify: `scripts/tr3000-lite-uplink-lib.sh`

**Interfaces:**
- Consumes: standard `/etc/init.d/ddns`/UCI state, active uplink event, WAN IPv4, configured DDNS hostname; never returns token.
- Produces: `/usr/sbin/tr3000-lite-ddns-status --json` keys `configured`, `enabled`, `hostname`, `record_type`, `last_update`, `last_error`, `wan_scope`, `direct_candidate`; uplink event restarts/forces DDNS update with debounce.

- [ ] **Step 1: Write failing status classification tests**

Assert RFC1918, `100.64.0.0/10`, loopback, link-local and absent WAN addresses yield `direct_candidate=false`; global unicast IPv4 yields `true` but never `reachable=true`. Assert record type is always `A`; no token or password appears in stdout/stderr.

- [ ] **Step 2: Write failing event/debounce tests**

Assert stable uplink transitions trigger one standard DDNS update after debounce; repeated same-uplink events do not hammer the API; updater failures use bounded exponential retry with jitter and remain visible in sanitized status.

- [ ] **Step 3: Run tests and verify failure**

Run: `python -m unittest tests.scripts.test_tr3000_lite_ddns -v`

Expected: FAIL because the status/event integration does not exist.

- [ ] **Step 4: Implement status and event integration**

Wrap standard ddns-scripts rather than duplicate Cloudflare API calls. Report DNS update success separately from Direct reachability; only an authenticated Direct handshake can later prove reachability.

- [ ] **Step 5: Install and run tests**

Run: `python -m unittest tests.scripts.test_tr3000_lite_ddns tests.scripts.test_tr3000_lite_uplink -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add scripts/tr3000-lite-ddns-status.sh scripts/tr3000-lite-uplink-lib.sh scripts/configure-lite.sh tests/scripts/test_tr3000_lite_ddns.py
git commit -m "feat(lite): expose safe Cloudflare DDNS status"
```

### Task 4: Build the two-phase staging workflow

**Files:**
- Create: `scripts/tr3000-lite-enroll.sh`
- Create: `tools/tr3000_lite_provision.py`
- Create: `tests/scripts/test_tr3000_lite_enroll.py`
- Create: `tests/tools/test_tr3000_lite_provision.py`
- Modify: `.gitignore`
- Modify: `scripts/configure-lite.sh`

**Interfaces:**
- Consumes: private inventory JSON outside tracked files; fields `device_id`, `ddns_hostname`, `direct_address`, `direct_listen_port`, `vps_address`, `vps_endpoint`, `vps_public_key`, `remote_peers[]`; root password is set interactively and is not an inventory field.
- Produces: on-device `/etc/tr3000-lite/keys/{direct,vps}.key` mode `0600`; public `prepare --json` report; private final bundle with manifest/SHA256; VPS peer snippet; Windows Direct/VPS templates without client private keys; local enrollment marker after trusted local gates and authenticated VPS handshake; separate external-verification evidence only after real external HTTPS acceptance.

- [ ] **Step 1: Write failing prepare tests**

Assert `prepare --device-id ID --json` validates the ID, generates two distinct keys via `wg genkey`, stores private keys `0600`, returns only public keys/device facts, is idempotent, and refuses to overwrite a completed enrollment.

- [ ] **Step 2: Write failing inventory uniqueness tests**

For `tr3000_lite_provision.py validate --inventory FILE`, assert duplicate device ID, hostname, Direct/VPS address, remote `/32`, invalid endpoint/port, non-DNS name, wide route, missing public key or cross-customer overlap fails before creating output. Valid inventory exits 0 and prints no secret.

- [ ] **Step 3: Write failing render/apply tests**

Assert `render --device-id ID --output DIR` creates mode-`0600` device bundle and exact public VPS/Windows templates; Direct and VPS templates share plant CIDR but contain distinct management address/endpoint metadata and `exclusive_group=<device-id>`; apply verifies manifest hashes, ownership, schema and target device ID before changing UCI/token files.

- [ ] **Step 4: Write failing verify/gate tests**

Assert local enrollment completes only when root password is nonempty, AP initialized, device identity and both distinct device keys validate, and authenticated VPS handshake is recent. Remote HTTPS is still forbidden before that marker. Assert external verification is a separate state requiring actual remote HTTPS success; local enrollment alone must never mark external acceptance passed. Cloudflare may remain disabled until its token/hostname are supplied, but the bundle must record this and Direct remains closed.

- [ ] **Step 5: Run tests and verify failure**

Run: `python -m unittest tests.scripts.test_tr3000_lite_enroll tests.tools.test_tr3000_lite_provision -v`

Expected: FAIL because enrollment/provisioning tools do not exist.

- [ ] **Step 6: Implement prepare/validate/render/apply/verify**

Write private output only to an explicit path; document `local/provisioning/` as the default ignored location but never silently choose it. Use JSON schema version 1 and full SHA256 manifest. Never accept plaintext root password, Windows private key or shell fragments in inventory.

- [ ] **Step 7: Install device enrollment tool and ignore private outputs**

Install `/usr/sbin/tr3000-lite-enroll`; add only precise provisioning output patterns to `.gitignore`, not broad directories that could hide source files.

- [ ] **Step 8: Run tests**

Run: `python -m unittest tests.scripts.test_tr3000_lite_enroll tests.tools.test_tr3000_lite_provision tests.scripts.test_scripts -v`

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add scripts/tr3000-lite-enroll.sh tools/tr3000_lite_provision.py tests .gitignore scripts/configure-lite.sh
git commit -m "feat(lite): add per-device secure staging workflow"
```

### Task 5: Add remote-access LuCI status and controls

**Files:**
- Create: `packages/luci-app-tr3000-lite/htdocs/luci-static/resources/view/tr3000-lite/remote-access.js`
- Modify: `packages/luci-app-tr3000-lite/root/usr/share/luci/menu.d/luci-app-tr3000-lite.json`
- Modify: `packages/luci-app-tr3000-lite/root/usr/share/rpcd/acl.d/luci-app-tr3000-lite.json`
- Modify: `tests/structure/test_repository_contract.py`

**Interfaces:**
- Consumes: fixed controllers `/usr/sbin/tr3000-lite-remote`, `/usr/sbin/tr3000-lite-ddns-status`, existing uplink status.
- Produces: LuCI route `admin/network/tr3000-lite/remote-access`; independent `allow_luci` and `allow_plant` total switches; current exact client `AllowedIPs` display/copy text.

- [ ] **Step 1: Write failing ACL/view tests**

Assert ACL adds only the two fixed controllers; page does not read key/token files; shows enrollment, Direct DNS candidate/handshake, VPS handshake, active uplink, exact authorized `/32` list and current plant CIDR. Assert the two policy switches are independent and disabled until enrollment/root gates pass.

- [ ] **Step 2: Write failing route-template tests**

For plant `192.168.10.254/24`, assert displayed client route is management `/32` plus `192.168.10.0/24`; after plant change it displays the new CIDR and a “Windows AllowedIPs update required” warning. No full-tunnel route appears.

- [ ] **Step 3: Run tests and verify failure**

Run: `python -m unittest tests.structure.test_repository_contract.RepositoryContractTests.test_lite_remote_access_view_has_narrow_acl -v`

Expected: FAIL because the view does not exist.

- [ ] **Step 4: Implement the view**

Use only sanitized JSON. Require confirmation before policy changes, show Direct as conditional and VPS as bootstrap/fallback, and state that Direct/VPS Windows profiles must not be active simultaneously.

- [ ] **Step 5: Run tests**

Run: `python -m unittest tests.structure.test_repository_contract tests.scripts.test_tr3000_lite_remote tests.scripts.test_tr3000_lite_ddns -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add packages/luci-app-tr3000-lite tests/structure/test_repository_contract.py
git commit -m "feat(lite): add dual remote access controls"
```

### Task 6: Document, build and truth-device verify remote access

**Files:**
- Create: `docs/TR3000-LITE-PROVISIONING.md`
- Create: `docs/TR3000-LITE-REMOTE-ACCESS.md`
- Modify: `docs/LITE-README.md`
- Modify: `docs/WIREGUARD-VPS-ROUTING.md`
- Modify: `docs/TEST-PLAN.md`
- Modify: `scripts/build-lite.sh`

**Interfaces:**
- Consumes: Tasks 1-5 and prior plans.
- Produces: reproducible staging/VPS/Windows contracts and complete build evidence.

- [ ] **Step 1: Document the staging runbook**

Cover Artifact/SHA verification, exact-device gate, setting the initial root password through a trusted UART/local console before any empty-password network management is enabled, prepare report, private inventory, VPS registration, final bundle apply, Cloudflare DNS-only record/Token, VPS LuCI verification, device ledger, revocation and sysupgrade/factory-reset behavior. Mark production values as external inputs.

- [ ] **Step 2: Document VPS and Windows contracts**

Give exact Direct/VPS roles, unique device/customer address allocation requirements, IP forwarding/firewall isolation, `/32` routes, PersistentKeepalive, Direct-first/VPS-fallback manual switch, handshake success checks, route cleanup and plant AllowedIPs edit workflow. Use placeholders only.

- [ ] **Step 3: Add automated failure cases to TEST-PLAN**

Include empty root password, un-enrolled Direct listener, duplicate inventory, wide peer source, Cloudflare rate/API failure, private/CGNAT WAN, VPS down/recovery, simultaneous Windows profiles, cross-customer route attempt and credential redaction.

- [ ] **Step 4: Add truth-device cases**

On backed-up lab hardware, verify staging from a clean image, VPS bootstrap through Ethernet/STA/RNDIS uplinks, remote LuCI, DDNS A update, Direct only on a proven public UDP path, Direct failure plus manual VPS switch, plant CIDR change plus Windows AllowedIPs edit, revoked Peer/Token and power-loss recovery. Never test against production PLCs.

- [ ] **Step 5: Extend Artifact evidence**

Record package selection, generic-disabled remote configs, controller paths and schema versions; assert no bundle, key, token, hostname inventory or `local/` file enters the Artifact.

- [ ] **Step 6: Run required local verification**

Run: `bash scripts/validate.sh`

Run: `python -m unittest discover -s tests -v`

Run: `git diff --check`

Run a focused secret scan over tracked files and confirm only placeholders/field names remain.

Expected: all commands exit 0.

- [ ] **Step 7: Build in GitHub Actions**

Trigger `build-lite.yml` on the implementation branch, watch to success, download and verify the Artifact. Confirm `ddns-scripts`, `ddns-scripts-cloudflare`, `luci-app-ddns`, `luci-app-tr3000-lite`, both remote controllers and no production credentials; inspect image size and overlay margin.

- [ ] **Step 8: Commit**

```bash
git add docs scripts/build-lite.sh
git commit -m "docs(lite): add dual remote access runbooks"
```
