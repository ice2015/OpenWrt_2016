# TR3000-Lite 接入段与工业模式 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 TR3000 Lite 固件出厂即插即用——有线/无线都拿到 `192.168.10.x`、ping 通路由器、浏览器进 LuCI；工业段 `plant` 改为显式接管唯一 LAN 口，可随时切回。

**Architecture:** 保持 `common → distribution → device → local` 层级，全部改动只落在 Lite device 层（`overlays/devices/tr3000-lite/`、`scripts/tr3000-lite-*`、`packages/luci-app-tr3000-lite`）。网络结构改为「默认接入段 `lan`（br-lan = eth1 + 管理 AP）+ 可选工业段 `plant`」；`plant` 接管/交还 eth1 复用现有控制器事务框架（备份对 → 候选 → `fw4 check` → 应用 → 核验 → 回滚）。无线侧按真实驱动栈 mt_wifi 重写：受管 AP 绑定 `lan`、WPA2、每机随机凭据、禁用 mt_wifi 自带开放默认 AP，并加 init.d 自愈服务。

**Tech Stack:** POSIX shell + UCI/netifd/firewall4、OpenWrt LuCI（JavaScript view）、rpcd ACL JSON、Python `unittest`、`bash scripts/validate.sh`。

**Spec:** `docs/superpowers/specs/2026-11-18-tr3000-lite-lan-access-design.md`（同分支，已批准）

## Global Constraints

- 目标：Cudy TR3000 v1、128 MiB NAND、MT7981、`cudy_tr3000-v1-ubootmod`、112 MiB UBI。
- 只改 Lite device/variant 层；**不得**改动 `files/`（共享 rootfs，属 Full 画像）与 `configs/devices/` 其它设备。
- 固定地址：`lan` = `192.168.10.1/24`（netmask `255.255.255.0`），DHCP 池 `192.168.10.100-249`；`plant` 默认 `192.168.20.254/24`。
- WiFi 栈固定为 mt_wifi（`kmod-mt_wifi` + `mtwifi-cfg`）；**不得**引入 mac80211/mt76/mt7915e。
- 管理 AP：`network=lan`、`mode=ap`、`encryption=psk2`、`disabled=0`，SSID `TR3000-Lite-<MAC 末 6 位大写十六进制>`，key 为 32 位小写十六进制随机值，只存于 `0600` 的 `/etc/config/wireless`。
- 固件内**不得**含无线凭据、root 密码、WireGuard 密钥、Cloudflare token 或任何 `local/` 内容。
- 镜像内**不得**预置 `/etc/config/wireless`；`/etc/config/system` 等由上游生成的配置不得被 Lite 覆盖。
- 所有 shell 脚本必须通过 `sh -n`（`tests/scripts/test_scripts.py::test_lite_shell_scripts_are_posix_syntax`）。
- 提交前必须通过：`bash scripts/validate.sh`、`python3 -m unittest discover -s tests -v`、`git diff --check`。
- 固件编译只在 GitHub Actions（`build-lite.yml`）；本地不编译固件。

## Review Focus

以下五类输入/失败模式最可能咬人，每条都必须在对应 Task 的测试里被钉住：

1. **mt_wifi 每次 `/sbin/wifi config` 都会重建 radio 与开放默认 AP** —— 受管 AP 必须每次都被重新禁用，开放热点不得复活（Task 4/5）。
2. **重复执行首启脚本与自愈服务** —— 不得轮换 SSID/key、不得重复建 AP、不得因已存在而报错（Task 4/5）。
3. **在接入模式与工业模式之间来回切换** —— eth1 归属必须严格互斥，切换失败必须回滚到成对备份（Task 3）。
4. **`plant` 段默认地址与 `lan` 段不得同网段** —— `192.168.10.0/24` 与 `192.168.20.0/24` 必须同时出现在最终配置里且互不重叠（Task 1/3）。
5. **产物与证据文件不得携带凭据** —— 契约文件只写公开默认值，Artifact 不得出现 wireless/密钥/库存文件（Task 6）。

---

## File Map

- `overlays/devices/tr3000-lite/files/etc/config/network` — 接入段 `lan`、具名桥接 `br_lan`、`plant` 默认不接管。
- `overlays/devices/tr3000-lite/files/etc/config/dhcp` — `config dhcp 'lan'` 池；`plant`/`wan` 维持关闭。
- `overlays/devices/tr3000-lite/files/etc/config/firewall` — `lan` zone、`lan→wan` 转发、`lan→plant` 放行与 SNAT（源 `192.168.10.0/24`）。
- `overlays/devices/tr3000-lite/files/etc/uci-defaults/91-tr3000-lite-management-ap` — 首启生成受管 AP（mt_wifi 语义）。
- `overlays/devices/tr3000-lite/files/etc/init.d/tr3000-lite-wifi` — 无线自愈服务入口。
- `scripts/tr3000-lite-wifi.sh` — 无线幂等校验/修复逻辑（纯逻辑，可单测）。
- `scripts/tr3000-lite-plant.sh` — 控制器：`enable-plant` / `disable-plant` / `status --json` 扩展。
- `scripts/tr3000-lite-plant-lib.sh` — 纯函数：参数解析、JSON 串、地址工具。
- `scripts/configure-lite.sh` — 把新脚本/init.d 装进 Lite 源树。
- `scripts/build-lite.sh` — 产物契约 `lite-runtime-contract.txt`（schema_version=2）。
- `packages/luci-app-tr3000-lite/htdocs/luci-static/resources/view/tr3000-lite/industrial-lan.js` — 工业 LAN 页：接入段信息、模式切换、旧配置提示。
- `tests/structure/test_repository_contract.py`、`tests/scripts/test_scripts.py`、`tests/scripts/test_tr3000_lite_plant.py`、`tests/scripts/test_tr3000_lite_wifi.py`、`tests/scripts/test_lite_build_evidence.py` — 对应测试。

---

### Task 1: 接入段 `lan` 与 DHCP 默认值

**Files:**
- Modify: `overlays/devices/tr3000-lite/files/etc/config/network`
- Modify: `overlays/devices/tr3000-lite/files/etc/config/dhcp`
- Test: `tests/structure/test_repository_contract.py`
- Test: `tests/scripts/test_scripts.py`

**Interfaces:**
- Consumes: 无（首个任务）。
- Produces: 最终 `/etc/config/network` 段：`interface 'lan'`（device `br-lan`、proto `static`、`192.168.1.1`→**`192.168.10.1`**、netmask `255.255.255.0`）、具名 `config device 'br_lan'`（name `br-lan`、type `bridge`、`list ports 'eth1'`）、`interface 'plant'`（`option proto 'none'`，**无 device**）、`interface 'wan'/'wwan'/'usbwan'` 保持不变；`/etc/config/dhcp` 段：`dhcp 'lan'`（interface `lan`、start `100`、limit `150`、leasetime `12h`、dhcpv4 `server`、dhcpv6/ra/ndp `disabled`）、`dhcp 'plant'`、`dhcp 'wan'` 维持 ignore+全禁用。

- [ ] **Step 1: 写失败的结构契约测试**

在 `tests/structure/test_repository_contract.py` 新增：

```python
def test_lite_overlay_ships_reachable_access_segment(self) -> None:
    network = (ROOT / "overlays/devices/tr3000-lite/files/etc/config/network").read_text(encoding="utf-8")
    self.assertIn("config interface 'lan'", network)
    self.assertIn("option ipaddr '192.168.10.1'", network)
    self.assertIn("option netmask '255.255.255.0'", network)
    self.assertIn("config device 'br_lan'", network)
    self.assertIn("option name 'br-lan'", network)
    self.assertIn("list ports 'eth1'", network)
    # 工业段默认不接管唯一 LAN 口
    plant = network.split("config interface 'plant'", 1)[1]
    self.assertNotIn("option device", plant.split("config", 1)[0])
    self.assertIn("option proto 'none'", plant)

def test_lite_overlay_serves_dhcp_on_the_access_segment(self) -> None:
    dhcp = (ROOT / "overlays/devices/tr3000-lite/files/etc/config/dhcp").read_text(encoding="utf-8")
    self.assertIn("config dhcp 'lan'", dhcp)
    self.assertIn("option start '100'", dhcp)
    self.assertIn("option limit '150'", dhcp)
    self.assertIn("option dhcpv4 'server'", dhcp)
    self.assertNotIn("config dhcp 'mgmt'", dhcp)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m unittest tests.structure.test_repository_contract.RepositoryContractTests.test_lite_overlay_ships_reachable_access_segment tests.structure.test_repository_contract.RepositoryContractTests.test_lite_overlay_serves_dhcp_on_the_access_segment -v`
Expected: FAIL（当前 overlay 没有 `lan` 段）。

- [ ] **Step 3: 改写 overlay 的 network/dhcp**

`overlays/devices/tr3000-lite/files/etc/config/network` 写成（顺序固定，便于人工比对）：

```
config interface 'wan'
	option device 'eth0'
	option proto 'dhcp'
	option metric '10'

config interface 'wwan'
	option proto 'dhcp'
	option metric '20'
	option auto '0'

config interface 'usbwan'
	option proto 'dhcp'
	option metric '30'
	option auto '0'

config device 'br_lan'
	option name 'br-lan'
	option type 'bridge'
	list ports 'eth1'

config interface 'lan'
	option device 'br-lan'
	option proto 'static'
	option ipaddr '192.168.10.1'
	option netmask '255.255.255.0'

config interface 'plant'
	option proto 'none'
```

`overlays/devices/tr3000-lite/files/etc/config/dhcp`：在 `config dnsmasq` 之后插入

```
config dhcp 'lan'
	option interface 'lan'
	option start '100'
	option limit '150'
	option leasetime '12h'
	option dhcpv4 'server'
	option dhcpv6 'disabled'
	option ra 'disabled'
	option ndp 'disabled'
```

并删除 `config dhcp 'mgmt'` 段。

- [ ] **Step 4: 跑测试确认通过**

Run: `python3 -m unittest tests.structure.test_repository_contract -v`
Expected: PASS。

- [ ] **Step 5: 补一条 configure-lite 集成断言**

在 `tests/scripts/test_scripts.py` 新增 `test_lite_config_installs_reachable_access_segment()`（类 `ScriptInterfaceTests`）：调用既有 `run_lite_configure(lite_base_config())`，它返回 `(result, generated_config, installed_assets)`；断言 `installed_assets["files/etc/config/network"]` 含 `option ipaddr '192.168.10.1'`、`config device 'br_lan'`、`list ports 'eth1'`，`installed_assets["files/etc/config/dhcp"]` 含 `config dhcp 'lan'` 与 `option limit '150'`，且两者都不含 `mgmt`。

Run: `python3 -m unittest tests.scripts.test_scripts.ScriptInterfaceTests.test_lite_config_installs_reachable_access_segment -v`
Expected: PASS。

- [ ] **Step 6: 提交**

```bash
git add overlays/devices/tr3000-lite/files/etc/config/network overlays/devices/tr3000-lite/files/etc/config/dhcp tests/structure/test_repository_contract.py tests/scripts/test_scripts.py
git commit -m "feat(lite): ship a reachable access segment with DHCP"
```

---

### Task 2: 防火墙 zone 迁移到 `lan`

**Files:**
- Modify: `overlays/devices/tr3000-lite/files/etc/config/firewall`
- Test: `tests/structure/test_repository_contract.py`
- Test: `tests/scripts/native_remote_nft.py`（新增一个用例文件或在现有文件中追加）

**Interfaces:**
- Consumes: Task 1 的 `lan` 段与 `plant` 默认无地址状态。
- Produces: 防火墙 zone `lan`（`list network 'lan'`、`input ACCEPT`、`output ACCEPT`、`forward ACCEPT`）、`config forwarding`（`src lan`/`dest wan`）、zone `plant`/`wan`/`wg` 保持；规则 `tr3000_lite_lan_plant_icmp`、`tr3000_lite_lan_plant_tcp`、`tr3000_lite_lan_plant_snat_icmp`、`tr3000_lite_lan_plant_snat_tcp`（`src_ip 192.168.10.0/24`）；`mgmt` zone 与原 `tr3000_lite_mgmt_plant_*` 规则全部删除。

- [ ] **Step 1: 写失败的防火墙契约测试**

```python
def test_lite_firewall_allows_management_from_the_access_segment(self) -> None:
    fw = (ROOT / "overlays/devices/tr3000-lite/files/etc/config/firewall").read_text(encoding="utf-8")
    self.assertIn("config zone\n\toption name 'lan'", fw.replace("'lan'", "'lan'"))
    self.assertIn("list network 'lan'", fw)
    self.assertNotIn("'mgmt'", fw)
    self.assertNotIn("tr3000_lite_mgmt_plant", fw)
    self.assertIn("tr3000_lite_lan_plant_icmp", fw)
    self.assertIn("option src_ip '192.168.10.0/24'", fw)
```

（实现时把第一条断言改成按行匹配的稳定写法，例如先切分出 `config zone` 段再检查 `option name 'lan'`。）

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m unittest tests.structure.test_repository_contract.RepositoryContractTests.test_lite_firewall_allows_management_from_the_access_segment -v`
Expected: FAIL（当前仍有 `mgmt` zone）。

- [ ] **Step 3: 改写 overlay firewall**

在 `overlays/devices/tr3000-lite/files/etc/config/firewall`：

- 新增 zone：
  ```
  config zone
  	option name 'lan'
  	list network 'lan'
  	option input 'ACCEPT'
  	option output 'ACCEPT'
  	option forward 'ACCEPT'
  ```
- 保留 `config defaults`（`flow_offloading '0'` 等）与 `wan`/`plant`/`wg` zone 不变；
- 把原 `config forwarding`（`src mgmt` / `dest wan`）改为 `src lan` / `dest wan`；
- 删除 `Allow-management-DHCP`/`DNS`/`SSH`/`HTTPS` 四条 `mgmt` 规则（`lan` zone 的 `input ACCEPT` 已覆盖）；
- 把四条 `tr3000_lite_mgmt_plant_*` 规则改名为 `tr3000_lite_lan_plant_*`，`src_ip` 由 `192.168.77.0/24` 改为 `192.168.10.0/24`，`dest_ip` 仍为 `192.168.10.0/24`（Task 3 起由控制器按 plant CIDR 覆盖）；
- `tr3000_lite_plant_luci` 规则保持 `enabled '0'`。

- [ ] **Step 4: 跑测试确认通过**

Run: `python3 -m unittest tests.structure.test_repository_contract -v`
Expected: PASS。

- [ ] **Step 5: 用 native nft 用例锁住 zone 语义**

在 `tests/scripts/native_remote_nft.py` 追加一个用例：把 overlay 的 `firewall` 交给 `fw4` 生成 nftables 规则（复用现有用例的隔离 netns 夹具），断言生成的规则集中存在 `lan` zone 的 accept 链与 `192.168.10.0/24` 源地址的 SNAT 规则，且不存在 `mgmt` zone。

Run: `sudo python3 -m unittest tests.scripts.test_scripts -v -k nft`（或该文件既有的显式 gate 命令）
Expected: PASS（若环境无 sudo/netns，标记 skip 并在报告中说明）。

- [ ] **Step 6: 提交**

```bash
git add overlays/devices/tr3000-lite/files/etc/config/firewall tests/structure/test_repository_contract.py tests/scripts/native_remote_nft.py
git commit -m "feat(lite): move the management firewall zone to the access segment"
```

---

### Task 3: 控制器支持工业模式接管与交还

**Files:**
- Modify: `scripts/tr3000-lite-plant.sh`
- Modify: `scripts/tr3000-lite-plant-lib.sh`
- Test: `tests/scripts/test_tr3000_lite_plant.py`

**Interfaces:**
- Consumes: Task 1 的 `network.br_lan`（具名桥接段）与 `network.plant`；Task 2 的 `tr3000_lite_lan_plant_*` 规则名。
- Produces:
  - CLI 新增 `enable-plant --address IPV4/PREFIX [--force-local-console]` 与 `disable-plant`；`apply` 保留 `--allow-mgmt` 作为 `--allow-lan` 的兼容别名。
  - `status --json` 新增字段：`mode`（`lan`\|`plant`）、`lan_cidr`（`192.168.10.1/24`）、`lan_dhcp_pool`（`192.168.10.100-192.168.10.249`）、`plant_active`（0/1）、`plant_cidr`、`ap_ready`（0/1）、`legacy_config_detected`（0/1）。
  - `scripts/tr3000-lite-plant-lib.sh` 新增纯函数 `plant_lan_cidr()`（返回 `192.168.10.1/24`）、`plant_default_plant_cidr()`（返回 `192.168.20.254/24`）、`plant_is_plant_mode()`。

- [ ] **Step 1: 写失败的模式切换测试**

在 `tests/scripts/test_tr3000_lite_plant.py` 新增（沿用既有 `PLANT_ROOT` 夹具与 `run_controller` 辅助）：

```python
def test_enable_plant_moves_the_lan_port_to_plant(self):
    # 初始：network.br_lan 具名桥接含 list ports 'eth1'，network.plant proto none
    result = self.run_controller("enable-plant", "--address", "192.168.20.254/24")
    self.assertEqual(result.returncode, 0, result.stderr)
    network = (self.root/"etc/config/network").read_text()
    self.assertIn("config device 'br_lan'", network)
    self.assertNotIn("eth1", network.split("config interface 'plant'")[0])
    self.assertIn("option device 'eth1'", network)
    self.assertIn("option ipaddr '192.168.20.254'", network)

def test_disable_plant_returns_the_lan_port_to_the_bridge(self):
    self.run_controller("enable-plant", "--address", "192.168.20.254/24")
    result = self.run_controller("disable-plant")
    self.assertEqual(result.returncode, 0, result.stderr)
    network = (self.root/"etc/config/network").read_text()
    self.assertIn("list ports 'eth1'", network)
    self.assertIn("option proto 'none'", network)

def test_enable_plant_requires_a_ready_management_ap(self):
    # 夹具中不写 /etc/tr3000-lite/management-ap.initialized
    result = self.run_controller("enable-plant", "--address", "192.168.20.254/24")
    self.assertNotEqual(result.returncode, 0)
    # 显式强制时允许
    forced = self.run_controller("enable-plant", "--address", "192.168.20.254/24", "--force-local-console")
    self.assertEqual(forced.returncode, 0, forced.stderr)

def test_status_reports_the_current_mode(self):
    payload = json.loads(self.run_controller("status", "--json").stdout)
    self.assertEqual(payload["mode"], "lan")
    self.assertEqual(payload["lan_cidr"], "192.168.10.1/24")
    self.assertEqual(payload["plant_active"], 0)

def test_access_and_plant_subnets_never_overlap(self):
    self.run_controller("enable-plant", "--address", "192.168.20.254/24")
    payload = json.loads(self.run_controller("status", "--json").stdout)
    self.assertEqual(payload["lan_cidr"], "192.168.10.1/24")
    self.assertEqual(payload["plant_cidr"], "192.168.20.254/24")
    self.assertNotEqual(payload["lan_cidr"].rsplit(".", 1)[0], payload["plant_cidr"].rsplit(".", 1)[0])
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m unittest tests.scripts.test_tr3000_lite_plant -v`
Expected: FAIL（`enable-plant` 未知命令、`status` 无 `mode` 字段）。

- [ ] **Step 3: 实现参数解析与纯函数**

`scripts/tr3000-lite-plant-lib.sh`：

- `plant_usage` 改为：
  ```
  Usage: %s status --json | validate --address IPV4/PREFIX | apply --address IPV4/PREFIX --allow-luci true|false --allow-lan true|false | enable-plant --address IPV4/PREFIX [--force-local-console] | disable-plant | restore --backup-id SAFE_ID
  ```
- `plant_parse`：新增 `COMMAND` 值 `enable-plant`（接受 `--address` 与可选 `--force-local-console`）与 `disable-plant`（不接受任何选项）；`apply` 同时接受 `--allow-lan` 与 `--allow-mgmt`（二者互斥，映射到同一变量 `ALLOW_LAN`）；重复选项必须仍然报错。
- 新增：
  ```sh
  plant_lan_cidr() { printf '192.168.10.1/24\n'; }
  plant_default_plant_cidr() { printf '192.168.20.254/24\n'; }
  ```
  `plant_is_plant_mode()` 依据候选/实时 `network.plant.device` 是否为 `eth1` 返回 0/1。

- [ ] **Step 4: 实现状态读取与模式判定**

`scripts/tr3000-lite-plant.sh`：

- `read_state` 增加读取 `network.br_lan.ports`、`network.plant.device`、`network.plant.proto`、`network.lan.ipaddr`，并据此计算 `MODE`（`plant` 当且仅当 `network.plant.device` 为 `eth1`），同时计算 `LEGACY_CONFIG`（`network.lan` 不存在、或 `network.mgmt` 存在、或 `network.plant.device=eth1` 而 `network.br_lan` 不存在 → 1）。
- `validate_address` 的管理网段重叠检查由 `192.168.77.0/24` 改为 `192.168.10.0/24`（复用 `lite_ipv4_number`/`lite_prefix_mask`）。

- [ ] **Step 5: 实现模式事务与状态输出**

`scripts/tr3000-lite-plant.sh`：

- `render_candidate` 按目标模式渲染：
  - 接入模式（默认）：`network.br_lan.ports` 含 `eth1`；`network.plant.proto=none`、删除 `network.plant.device`。
  - 工业模式：`network.br_lan.ports` 先 `delete` 再无 `add_list`（即无成员）；`network.plant.device=eth1`、`proto=static`、`ipaddr`/`netmask` 来自 `--address`。
  - UCI 列表语义：清空成员必须用 `delete network.br_lan.ports`，不得写 `option ports ''`。
  - `lan` 段的地址与 DHCP 段**不得**被控制器改动。
- 新增 `enable-plant`/`disable-plant` 分支，沿用既有顺序：`lock → prepare_candidate → read_state → validate_address → management_gate → backup_pair → render_candidate → check_candidate → install_candidate → finalize_transaction → read_state → emit`；`enable-plant` 额外要求 `ap_ready`（`/etc/tr3000-lite/management-ap.initialized` 存在且为普通文件），除非传入 `--force-local-console`。
- `verify_live` 增加断言：接入模式下 `network.plant` 无 `eth1` 且 br-lan 含 `eth1`；工业模式下 `network.plant.device=eth1` 且 br-lan 不含 `eth1`；`network.lan` 地址恒为 `192.168.10.1/24`。
- `status` 的 `emit` 增加 §Interfaces 列出的字段（含 `legacy_config_detected`）。

- [ ] **Step 6: 跑测试确认通过**

Run: `python3 -m unittest tests.scripts.test_tr3000_lite_plant -v`
Expected: PASS（含既有用例不回归）。

- [ ] **Step 7: 提交**

```bash
git add scripts/tr3000-lite-plant.sh scripts/tr3000-lite-plant-lib.sh tests/scripts/test_tr3000_lite_plant.py
git commit -m "feat(lite): add industrial mode takeover and handover of the lan port"
```

---

### Task 4: mt_wifi 兼容的管理 AP

**Files:**
- Modify: `overlays/devices/tr3000-lite/files/etc/uci-defaults/91-tr3000-lite-management-ap`
- Test: `tests/scripts/test_tr3000_lite_wifi.py`

**Interfaces:**
- Consumes: Task 1 的 `network.lan`（AP 绑定目标）。
- Produces: 首启后 `/etc/config/wireless` 满足：每个 radio 恰好一个受管段 `tr3000_lite_mgmt_<radio>`（`device=<radio>`、`mode=ap`、`network=lan`、`encryption=psk2`、`disabled=0`、`ssid=TR3000-Lite-<6 位大写 hex>`、`key=<32 位小写 hex>`）；mt_wifi 默认开放段（`encryption` 为空/`none`/`open` 且 `mode=ap`）被写 `disabled=1`；成功后才写 `/etc/tr3000-lite/management-ap.initialized`。

- [ ] **Step 1: 把测试夹具改成 mt_wifi 形态**

在 `tests/scripts/test_tr3000_lite_wifi.py` 中新增夹具状态（保留既有 mac80211 夹具作为对照，不删除）：

```python
MTWIFI_STATE = {
    "wireless.radio0": "wifi-device",
    "wireless.radio1": "wifi-device",
    "wireless.default_radio0": "wifi-iface",
    "wireless.default_radio0.device": "radio0",
    "wireless.default_radio0.mode": "ap",
    "wireless.default_radio0.network": "lan",
    "wireless.default_radio0.ssid": "ImmortalWrt-2.4G",
    "wireless.default_radio0.encryption": "none",
    "wireless.default_radio1": "wifi-iface",
    "wireless.default_radio1.device": "radio1",
    "wireless.default_radio1.mode": "ap",
    "wireless.default_radio1.network": "lan",
    "wireless.default_radio1.ssid": "ImmortalWrt-5G",
    "wireless.default_radio1.encryption": "none",
}
```

并让 `run_ap` 支持传入该状态。

- [ ] **Step 2: 写失败的行为测试**

```python
def test_mtwifi_default_open_aps_are_disabled(self):
    self.run_ap(state=MTWIFI_STATE)
    state = self.load()
    self.assertEqual(state["wireless.default_radio0.disabled"], "1")
    self.assertEqual(state["wireless.default_radio1.disabled"], "1")

def test_managed_ap_binds_the_access_segment_with_wpa2(self):
    self.run_ap(state=MTWIFI_STATE)
    state = self.load()
    ap = state["wireless.tr3000_lite_mgmt_radio0"]
    self.assertEqual(ap, "wifi-iface")
    self.assertEqual(state["wireless.tr3000_lite_mgmt_radio0.network"], "lan")
    self.assertEqual(state["wireless.tr3000_lite_mgmt_radio0.encryption"], "psk2")
    self.assertEqual(state["wireless.tr3000_lite_mgmt_radio0.mode"], "ap")
    self.assertEqual(state["wireless.tr3000_lite_mgmt_radio0.disabled"], "0")
    self.assertEqual(len(state["wireless.tr3000_lite_mgmt_radio0.key"]), 32)

def test_ssid_suffix_uses_the_radio_mac(self):
    self.run_ap(state=MTWIFI_STATE, mac="aa:bb:cc:dd:ee:ff")
    state = self.load()
    self.assertEqual(state["wireless.tr3000_lite_mgmt_radio0.ssid"], "TR3000-Lite-DDEEFF")

def test_repeated_run_keeps_the_same_identity(self):
    self.run_ap(state=MTWIFI_STATE)
    first = self.load()
    self.run_ap(state=MTWIFI_STATE)
    second = self.load()
    self.assertEqual(first["wireless.tr3000_lite_mgmt_radio0.ssid"], second["wireless.tr3000_lite_mgmt_radio0.ssid"])
    self.assertEqual(first["wireless.tr3000_lite_mgmt_radio0.key"], second["wireless.tr3000_lite_mgmt_radio0.key"])
```

- [ ] **Step 3: 跑测试确认失败**

Run: `python3 -m unittest tests.scripts.test_tr3000_lite_wifi -v`
Expected: FAIL（当前脚本把 AP 绑到 `mgmt`，且未按 mt_wifi 命名段处理 `device` 标量）。

- [ ] **Step 4: 改造首启脚本**

`overlays/devices/tr3000-lite/files/etc/uci-defaults/91-tr3000-lite-management-ap`：

- 受管 AP 的 `network` 由 `mgmt` 改为 `lan`；
- 设备列表解析改为基于 `uci show wireless` 输出（兼容标量 `device` 与列表 `device`），**删除** `uci -d` 用法；
- 开放默认 AP 判定：`encryption` 为空/`none`/`open` 且 `mode=ap` 且不是受管段 → 写 `disabled=1`；
- SSID 后缀优先取无线设备自身 MAC（`/sys/class/net/ra*/address`、`/sys/class/net/mtwifi*/address`），**不得**取 `eth0`/`eth1` 的 MAC；取不到时沿用持久化的 `/etc/tr3000-lite/ap-suffix`；
- 受管段命名保持 `tr3000_lite_mgmt_<radio>`；
- 保留全部既有安全纪律（符号链接检查、锁、临时目录、`umask 077`、`/etc/config/wireless` 0600、日志不含 SSID/key、成功后才写 marker）。

- [ ] **Step 5: 跑测试确认通过**

Run: `python3 -m unittest tests.scripts.test_tr3000_lite_wifi -v`
Expected: PASS。

- [ ] **Step 6: 提交**

```bash
git add overlays/devices/tr3000-lite/files/etc/uci-defaults/91-tr3000-lite-management-ap tests/scripts/test_tr3000_lite_wifi.py
git commit -m "fix(lite): make the management AP work on the mtwifi stack"
```

---

### Task 5: 无线自愈服务与就绪标记

**Files:**
- Create: `scripts/tr3000-lite-wifi.sh`
- Create: `overlays/devices/tr3000-lite/files/etc/init.d/tr3000-lite-wifi`
- Modify: `scripts/configure-lite.sh`
- Test: `tests/scripts/test_tr3000_lite_wifi.py`
- Test: `tests/scripts/test_scripts.py`

**Interfaces:**
- Consumes: Task 4 的首启脚本行为与受管 AP 规格。
- Produces:
  - `scripts/tr3000-lite-wifi.sh`：`status --json`（输出 `ready`、`open_aps_disabled`、`managed_aps`、`ssid_present`、`key_present`）、`repair`（幂等修复 + `/sbin/wifi reload` + 复核 + 写 marker）。退出码 0=就绪，1=未就绪（可重试），2=用法错误。
  - `overlays/devices/tr3000-lite/files/etc/init.d/tr3000-lite-wifi`：procd 服务，`START=20`，`STOP=10`，执行 `tr3000-lite-wifi repair`，失败不阻断启动。
  - `scripts/configure-lite.sh` 把 `tr3000-lite-wifi.sh` 装到 `files/usr/sbin/tr3000-lite-wifi`（0755），把 init.d 装到 `files/etc/init.d/tr3000-lite-wifi`（0755）。

- [ ] **Step 1: 写失败的自愈测试**

在 `tests/scripts/test_tr3000_lite_wifi.py` 新增：

```python
def test_repair_restores_a_missing_managed_ap(self):
    state = dict(MTWIFI_STATE)
    self.run_ap(state=state)
    broken = {k: v for k, v in state.items() if not k.startswith("wireless.tr3000_lite_mgmt_")}
    self.save_state(broken)
    result = self.run_repair()
    self.assertEqual(result.returncode, 0, result.stderr)
    self.assertIn("wireless.tr3000_lite_mgmt_radio0", self.load())

def test_repair_disables_a_resurrected_open_ap(self):
    state = dict(MTWIFI_STATE)
    self.run_ap(state=state)
    resurrected = dict(self.load())
    resurrected["wireless.default_radio0.disabled"] = "0"
    self.save_state(resurrected)
    self.run_repair()
    self.assertEqual(self.load()["wireless.default_radio0.disabled"], "1")

def test_marker_is_written_only_after_verification(self):
    self.assertFalse(self.marker().exists())
    result = self.run_repair()
    self.assertEqual(result.returncode, 0, result.stderr)
    self.assertTrue(self.marker().is_file())
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m unittest tests.scripts.test_tr3000_lite_wifi -v`
Expected: FAIL（`scripts/tr3000-lite-wifi.sh` 不存在）。

- [ ] **Step 3: 实现 `scripts/tr3000-lite-wifi.sh`**

- 纯 POSIX shell，`set -eu`，`PATH` 固定；
- 读取 `/etc/config/wireless`（不存在 → 退出 1，不创建文件）；
- `status`：用 `uci show wireless` 判断每个 radio 是否有且仅有一个受管段、属性是否匹配、开放默认段是否已 `disabled=1`，输出 JSON；
- `repair`：缺受管段则按 Task 4 的规格创建（SSID/key 复用既有值，没有则生成并写 0600）；开放段被复活则写 `disabled=1`；`uci commit wireless`；调用 `/sbin/wifi reload`（不存在则跳过并记日志）；复核 `status` 通过后写 `/etc/tr3000-lite/management-ap.initialized`（0600），否则删除该 marker 并退出 1；
- 任何路径都不得把 SSID/key 写进日志或 stdout。

- [ ] **Step 4: 实现 init.d 服务并安装**

`overlays/devices/tr3000-lite/files/etc/init.d/tr3000-lite-wifi`：

```sh
#!/bin/sh /etc/rc.common
START=20
STOP=10

start() {
	/usr/sbin/tr3000-lite-wifi repair || logger -t tr3000-lite-wifi "management AP repair pending"
}
```

`scripts/configure-lite.sh` 增加安装两处资产（参照既有 `install -m 0755` 调用）。

- [ ] **Step 5: 跑测试确认通过**

Run: `python3 -m unittest tests.scripts.test_tr3000_lite_wifi tests.scripts.test_scripts -v`
Expected: PASS。

- [ ] **Step 6: 提交**

```bash
git add scripts/tr3000-lite-wifi.sh overlays/devices/tr3000-lite/files/etc/init.d/tr3000-lite-wifi scripts/configure-lite.sh tests/scripts/test_tr3000_lite_wifi.py tests/scripts/test_scripts.py
git commit -m "feat(lite): heal the management AP and publish its readiness marker"
```

---

### Task 6: LuCI 页面反映接入段与模式切换

**Files:**
- Modify: `packages/luci-app-tr3000-lite/htdocs/luci-static/resources/view/tr3000-lite/industrial-lan.js`
- Modify: `packages/luci-app-tr3000-lite/htdocs/luci-static/resources/view/tr3000-lite/uplinks.js`
- Test: `tests/structure/test_repository_contract.py`

**Interfaces:**
- Consumes: Task 3 的 `status --json` 字段（`mode`、`lan_cidr`、`lan_dhcp_pool`、`plant_active`、`plant_cidr`、`ap_ready`、`legacy_config_detected`）与新命令 `enable-plant` / `disable-plant`。
- Produces: 工业 LAN 页在接入模式下提供「启用 plant 模式」，在工业模式下提供「退回接入模式」；页面任何位置不再出现 `mgmt` 字样。

- [ ] **Step 1: 写失败的视图契约测试**

在 `tests/structure/test_repository_contract.py` 新增：

```python
def test_lite_luci_view_exposes_the_access_segment_and_mode_switch(self) -> None:
    view = (ROOT / "packages/luci-app-tr3000-lite/htdocs/luci-static/resources/view/tr3000-lite/industrial-lan.js").read_text(encoding="utf-8")
    self.assertIn("enable-plant", view)
    self.assertIn("disable-plant", view)
    self.assertIn("lan_cidr", view)
    self.assertIn("legacy_config_detected", view)
    self.assertNotIn("mgmt", view)
    uplinks = (ROOT / "packages/luci-app-tr3000-lite/htdocs/luci-static/resources/view/tr3000-lite/uplinks.js").read_text(encoding="utf-8")
    self.assertNotIn("192.168.77", uplinks)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m unittest tests.structure.test_repository_contract.RepositoryContractTests.test_lite_luci_view_exposes_the_access_segment_and_mode_switch -v`
Expected: FAIL（视图仍用 `mgmt` 且无模式切换）。

- [ ] **Step 3: 改造工业 LAN 页**

`industrial-lan.js`：

- 读 `status.mode`、`status.lan_cidr`、`status.lan_dhcp_pool`、`status.ap_ready`、`status.legacy_config_detected`；
- `legacy_config_detected` 为真时，在页面顶部插入一条醒目的错误提示（“检测到旧版配置结构，请用不保留配置的方式重新刷机（sysupgrade -n）”），并禁用模式切换按钮；
- `mode === 'lan'`：展示接入段信息（`lan_cidr`、DHCP 池）与 plant 地址输入框 + 「启用 plant 模式」按钮 → 调用 `enable-plant --address <CIDR>`；`ap_ready` 为假时按钮禁用并提示“管理 AP 未就绪，请先用有线接入或等待 AP 自愈”；
- `mode === 'plant'`：保留现有地址/掩码/放行开关表单，调用 `apply --address … --allow-luci … --allow-lan …`（`--allow-mgmt` 仍被控制器接受）；新增「退回接入模式」按钮 → 调用 `disable-plant`；
- 保持既有错误处理（控制器非零退出时展示 stderr，不静默）。

`uplinks.js`：把 `mgmt` / `192.168.77` 字样改为 `lan` / `192.168.10.0/24`。

- [ ] **Step 4: 跑测试确认通过**

Run: `python3 -m unittest tests.structure.test_repository_contract -v`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add packages/luci-app-tr3000-lite/htdocs/luci-static/resources/view/tr3000-lite/industrial-lan.js packages/luci-app-tr3000-lite/htdocs/luci-static/resources/view/tr3000-lite/uplinks.js tests/structure/test_repository_contract.py
git commit -m "feat(lite): show the access segment and the industrial mode switch in LuCI"
```

---

### Task 7: 产物契约与构建证据

**Files:**
- Modify: `scripts/build-lite.sh`
- Test: `tests/scripts/test_lite_build_evidence.py`

**Interfaces:**
- Consumes: Task 1–3 的最终配置与控制器字段。
- Produces: `lite-runtime-contract.txt` 升级到 `schema_version=2`，字段见 §Interfaces；构建脚本对 overlay 的三条硬断言（见 Step 3）。

- [ ] **Step 1: 写失败的证据测试**

在 `tests/scripts/test_lite_build_evidence.py` 新增：

```python
def test_runtime_contract_reports_the_access_segment(self):
    contract = self.contract_text()
    self.assertIn("schema_version=2", contract)
    self.assertIn("lan_interface=lan", contract)
    self.assertIn("lan_device=br-lan", contract)
    self.assertIn("lan_cidr=192.168.10.1/24", contract)
    self.assertIn("lan_dhcp_pool=192.168.10.100-192.168.10.249", contract)
    self.assertIn("plant_default_cidr=192.168.20.254/24", contract)
    self.assertIn("wireless_stack=mt_wifi", contract)
    self.assertIn("management_ap_network=lan", contract)
    self.assertNotIn("mgmt_cidr", contract)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m unittest tests.scripts.test_lite_build_evidence -v`
Expected: FAIL（契约仍是 `schema_version=1` 且含 `mgmt_cidr`）。

- [ ] **Step 3: 更新契约与构建断言**

`scripts/build-lite.sh` 的 `lite-runtime-contract.txt` 块改为：

```
schema_version=2
evidence_kind=expected-defaults-not-live-state
lan_interface=lan
lan_device=br-lan
lan_cidr=192.168.10.1/24
lan_dhcp_pool=192.168.10.100-192.168.10.249
plant_interface=plant
plant_device=eth1
plant_default_cidr=192.168.20.254/24
plant_default_mode=inactive
plant_dhcpv4_dhcpv6_ra_ndp=off
lan_to_plant_protocols=icmp-echo,tcp
lan_to_plant_snat=plant-address
lan_plant_bridged=0
luci_package=luci-app-tr3000-lite
allow_luci=0
allow_lan=1
allow_wireguard=0
plant_https_port=443
plant_https_gate=root-password-and-explicit-enable
wan_management=off
wireless_stack=mt_wifi
management_ap_network=lan
management_ap_encryption=psk2
management_ap_default_open_ap=disabled
management_ap_heal_service=/etc/init.d/tr3000-lite-wifi
uplink_order=wan,wwan,usbwan
uplink_metrics=10,20,30
uplink_interval_seconds=15
uplink_fail_rounds=3
uplink_recover_rounds=2
uplink_daemon=/usr/sbin/lite-uplink-watch
uplink_status=/usr/sbin/tr3000-lite-uplink-status
uplink_event_hook=/usr/lib/tr3000-lite/uplink-changed
usb_drivers=rndis_host,cdc_ether
usb_hotplug=/etc/hotplug.d/net/90-tr3000-lite-usbwan
usb_multiple_candidates=fail-closed
usb_periodic_rescan=on-daemon-round
wireless_client_config=standard-luci-only
allow_wireguard_direct=0
allow_wireguard_vps=0
remote_controller=/usr/sbin/tr3000-lite-remote
ddns_status=/usr/sbin/tr3000-lite-ddns-status
enroll_script=/usr/sbin/tr3000-lite-enroll
remote_schema_version=1
ddns_schema_version=1
enroll_schema_version=1
```

并在构建脚本里追加三条断言（任一不满足即 `fail`）：
1. Lite overlay 的 `etc/config/network` 含 `config interface 'lan'`、`option ipaddr '192.168.10.1'`、`config device 'br_lan'`、`list ports 'eth1'`；
2. Lite overlay 的 `etc/config/dhcp` 含 `config dhcp 'lan'`；
3. Lite overlay **不含** `etc/config/wireless`（固件不带无线配置）。

- [ ] **Step 4: 跑测试确认通过**

Run: `python3 -m unittest tests.scripts.test_lite_build_evidence -v`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add scripts/build-lite.sh tests/scripts/test_lite_build_evidence.py
git commit -m "feat(lite): publish the access segment runtime contract"
```

---

### Task 8: 全量回归与分支自检

**Files:**
- Modify: 无（仅在回归暴露问题时回头修对应任务的文件）。

**Interfaces:**
- Consumes: Task 1–6 的全部产物。
- Produces: 干净的工作树与可复核的验证记录。

- [ ] **Step 1: 跑仓库校验**

Run: `bash scripts/validate.sh`
Expected: `Manifest catalog is valid.`，退出码 0。

- [ ] **Step 2: 跑全量测试**

Run: `python3 -m unittest discover -s tests -v`
Expected: 全部通过（既有 218 项 + 本计划新增项），无 ERROR/FAIL。

- [ ] **Step 3: 语法与空白检查**

Run: `sh -n scripts/tr3000-lite-plant.sh scripts/tr3000-lite-plant-lib.sh scripts/tr3000-lite-wifi.sh && sh -n overlays/devices/tr3000-lite/files/etc/uci-defaults/91-tr3000-lite-management-ap overlays/devices/tr3000-lite/files/etc/init.d/tr3000-lite-wifi && git diff --check`
Expected: 无输出，退出码 0。

- [ ] **Step 4: 凭据扫描**

Run: `git grep -n -i -E "(password|passwd|secret|token|private_key)[[:space:]]*=[[:space:]]*['\"][^'\"]{6,}" -- ':!docs/**' ':!tests/**'`
Expected: 无命中（仅占位符与字段名）。

- [ ] **Step 5: 记录状态**

在提交信息或 PR 描述中写明：本分支已完成 Task 1–6；真机验收项见 `docs/TEST-PLAN.md`（Plan 2 补齐 T1–T10 文本）；固件编译需在 GitHub Actions 执行。

---

## 后续计划（本计划不含）

- **Plan 2（文档与交付）**：文档更新（`docs/LITE-README.md`、`docs/TEST-PLAN.md` 的 T1–T10 真机清单、新增 `docs/TR3000-LITE-LAN-ACCESS.md`、`docs/TR3000-LITE-PROVISIONING.md` / `docs/TR3000-LITE-REMOTE-ACCESS.md` / `docs/WIREGUARD-VPS-ROUTING.md` / `docs/SINGBOX-SPLIT-ROUTING.md` 中的 192.168.77 → 192.168.10 与 “必须不保留配置刷机” 说明）、GitHub Actions `build-lite.yml` 在本分支的构建与产物核对（镜像内 `/etc/config/network` 含 `lan`、`/etc/config/dhcp` 含 `config dhcp 'lan'`、镜像内无 `/etc/config/wireless`、产物契约 `schema_version=2`）。
