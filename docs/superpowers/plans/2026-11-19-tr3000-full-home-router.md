# TR3000 Full 家用路由器改造 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 TR3000 Full 从工业远程维护网关改造成出厂可达的家用路由器：删除 plant/mgmt，集成 sing-box(HomeProxy)/WireGuard/Cloudflare Tunnel/DDNS(Cloudflare)/Argon 主题与三上行故障切换。

**Architecture:** Full 自建 `overlays/devices/tr3000-full/`（方案 A，Lite 完全不动）。网络底座与 mt_wifi 管理 AP 从 Lite 已验证实现按 token 改名复制，漂移守卫测试锁住纯改名文件；上行五件套按 Full 语义改写四处。科学上网/穿透/DDNS/主题全部用固定 feed 里的上游包，Full 专属 LuCI 只做状态+开关页。

**Tech Stack:** POSIX shell、OpenWrt Kconfig/UCI/firewall4、LuCI JS 视图、GitHub Actions、Python `unittest` 契约测试。

**Spec:** `docs/superpowers/specs/2026-11-19-tr3000-full-home-router-design.md`（执行者必须同时读 spec；E1–E16 是已核实事实，D1–D12 是已批准决策）

## Global Constraints

- 只改 Full；`scripts/configure-lite.sh`、`overlays/devices/tr3000-lite/`、`configs/lite.seed`、Lite 测试的断言值一律不动。
- 固定值：`lan` = `192.168.10.1/24`，DHCP 池 `192.168.10.100-249`（start 100 / limit 150）；上行 metric `wan:10 wwan:20 usbwan:30`；镜像上限 `104857600` 字节不放宽。
- 源码/feeds 固定 SHA 不变：上游 `cc777dfa…`、源码 `ec9ef10e…`、luci `cc142cd1…`、packages `171d5f92…`。
- 固件、overlay、`files/`、Artifact、CI 日志不得含无线凭据、root 密码、token、私钥；overlay 与 `files/` 不得出现 `/etc/config/wireless`。
- 每个任务完成后运行 `bash scripts/validate.sh` 与 `python -m unittest discover -s tests`（全量约 15 分钟；任务内先跑聚焦模块）。
- 固件编译只在 GitHub Actions；本地不编译。
- token 改名映射（下文简称 **RENAME**）：`tr3000-lite→tr3000-full`、`tr3000_lite→tr3000_full`、`TR3000-Lite→TR3000-Full`；上行套件额外映射 `lite-uplink-watch→tr3000-full-uplink-watch`（UCI 配置名/服务名/状态路径）。`lite-common.sh` 与 `lite_valid_*` 等共享 helper 名**不改**。

## Review Focus

1. 保留旧工业配置升级 → 必须显式提示旧结构且不自动改写（Task 5 的 legacy 测试）。
2. homeproxy 与 sing-box 本体两套服务抢端口/nft → 首启必须同时禁用两者（Task 5 测试）。
3. 用户自建 Wi-Fi 中继 STA 被 AP 修复破坏 → 修复后 STA 原样保留（Task 2 测试）。
4. USB 多候选/受保护接口被抢占 → fail-closed，不碰 `lan`（Task 3 测试）。
5. 新包组合撞 100 MiB 门禁 → 门禁值与调用不变，超限构建失败（Task 6 测试）。
6. 凭据进入 overlay/Artifact → 结构测试与 build 门禁双重禁止（Task 1/6 测试）。

## 与 spec 的两处实施裁量（builder call，已在交付时声明）

- spec §6.1 文件树里的 `config/tr3000-full`（运行策略文件）**不创建**：服务默认关闭由 `95-tr3000-full-services` 强制并有测试锁住，无消费者的空配置文件违反 YAGNI。
- usbwan 热插拔的网络事务锁 `/var/lock/tr3000-lite-plant` 在 Full 改名为 `/var/lock/tr3000-full-network`（Full 无 plant 控制器，锁语义是"网络文件写锁"）；同文件 :90 的受保护接口集合 `wan plant mgmt wwan` 改为 `wan lan wwan`。两处均列为上行套件语义差异（Task 3 表）。

---

### Task 1: Full overlay 网络底座与 files/ 归位

**Files:**
- Create: `overlays/devices/tr3000-full/files/etc/config/network`
- Create: `overlays/devices/tr3000-full/files/etc/config/dhcp`
- Create: `overlays/devices/tr3000-full/files/etc/config/firewall`
- Create: `overlays/devices/tr3000-full/files/etc/config/ddns`
- Move: `files/etc/tr3000-full/examples/cloudflared.yml.example` → `overlays/devices/tr3000-full/files/etc/tr3000-full/examples/cloudflared.yml.example`
- Move: `files/etc/uci-defaults/95-tr3000-full-services` → `overlays/devices/tr3000-full/files/etc/uci-defaults/95-tr3000-full-services`（内容 Task 5 再改）
- Delete: `files/etc/config/network`、`files/etc/config/dhcp`、`files/etc/config/firewall`、`files/etc/tr3000-full/examples/sing-box.json.example`
- Modify: `scripts/configure-full.sh`（overlay 装配）
- Test: `tests/structure/test_repository_contract.py`、`tests/scripts/test_scripts.py`

**Interfaces:**
- Produces: `FULL_OVERLAY="$REPO_ROOT/overlays/devices/tr3000-full/files"`（configure-full.sh 内变量）；装配顺序 `cp -R files/. → cp -R "$FULL_OVERLAY/."`（后者覆盖前者）。后续任务向 overlay 加文件即自动入镜像。
- Produces: overlay `network` 含具名 `config device 'br_lan'`（ports=eth1）与 `config interface 'lan'`；`wan/wwan/usbwan` 三段与 Lite overlay 同值；**无 plant/mgmt**。
- Produces: overlay `firewall` 含 `lan`/`wan`/`wg` 三 zone、`lan→wan` 转发、spec §6.6 的四条 wg 规则（`tr3000_full_wg_mgmt`/`tr3000_full_wg_icmp`/`tr3000_full_wg_listener` 全部 `enabled 0`）与 `wg→lan` 转发；无 `wg→wan` 转发、无任何 `tr3000_lite_*` 段。

- [ ] **Step 1: 写失败的结构测试**

在 `tests/structure/test_repository_contract.py` 新增（复用文件内既有 `uci_sections` 导入方式）：

```python
def test_full_overlay_ships_home_router_network(self) -> None:
    overlay = ROOT / "overlays/devices/tr3000-full/files/etc/config"
    network = (overlay / "network").read_text(encoding="utf-8")
    self.assertIn("config interface 'lan'", network)
    self.assertIn("option ipaddr '192.168.10.1'", network)
    self.assertIn("config device 'br_lan'", network)
    self.assertIn("list ports 'eth1'", network)
    self.assertNotIn("plant", network)
    self.assertNotIn("mgmt", network)
    dhcp = (overlay / "dhcp").read_text(encoding="utf-8")
    self.assertIn("config dhcp 'lan'", dhcp)
    self.assertIn("option start '100'", dhcp)
    self.assertIn("option limit '150'", dhcp)

def test_full_firewall_keeps_tunnels_closed_by_default(self) -> None:
    from tests.scripts.test_scripts import uci_sections
    overlay = ROOT / "overlays/devices/tr3000-full/files/etc/config"
    firewall = uci_sections((overlay / "firewall").read_text(encoding="utf-8"))
    sections = {s[".name"]: s for s in firewall if s[".name"]}
    zones = {s["name"]: s for s in firewall if s[".type"] == "zone"}
    self.assertEqual("ACCEPT", zones["lan"]["input"])
    self.assertNotIn("plant", zones); self.assertNotIn("mgmt", zones)
    for name in ("tr3000_full_wg_mgmt", "tr3000_full_wg_icmp", "tr3000_full_wg_listener"):
        self.assertEqual("0", sections[name]["enabled"])
    self.assertTrue(any(s[".type"] == "forwarding" and s["src"] == "wg" and s["dest"] == "lan" for s in firewall))
    self.assertFalse(any(s[".type"] == "forwarding" and s["src"] == "wg" and s["dest"] == "wan" for s in firewall))
    self.assertFalse(any(n.startswith("tr3000_lite_") for n in sections))

def test_full_only_assets_left_the_shared_rootfs(self) -> None:
    for name in ("network", "dhcp", "firewall"):
        self.assertFalse((ROOT / "files/etc/config" / name).exists())
    self.assertFalse((ROOT / "files/etc/tr3000-full/examples/sing-box.json.example").exists())
    self.assertFalse((ROOT / "files/etc/config/wireless").exists())
    self.assertFalse((ROOT / "overlays/devices/tr3000-full/files/etc/config/wireless").exists())
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m unittest tests.structure.test_repository_contract -v 2>&1 | tail -20`
Expected: 新增三个用例 FAIL（overlay 不存在 / shared 文件仍在）。

- [ ] **Step 3: 建 overlay 并归位 files/**

`git mv` 三个 config 到 overlay 路径后按 spec §6.2/§6.6 重写内容（network/dhcp 以 Lite overlay 同名文件为蓝本去掉 plant 段；firewall 按 Interfaces 块）。`ddns` 模板：

```uci
config ddns 'global'
	option ddns_dateformat '%F %R'
	option ddns_loglines '250'
	option upd_privateip '0'

config service 'cloudflare_v4'
	option enabled '0'
	option use_ipv6 '0'
	option use_https '1'
	option service_name 'cloudflare.com-v4'
	option interface 'wan'
	option ip_source 'network'
	option ip_network 'wan'
```

（无 lookup_host/domain/username/password——凭据留空由管理员填。）`git mv` cloudflared 示例与 95-services；`git rm` sing-box 示例。

- [ ] **Step 4: configure-full.sh 装配 overlay**

在 `cp -R "$REPO_ROOT/files/." "$SOURCE_DIR/files/"` 之后加：

```sh
FULL_OVERLAY="$REPO_ROOT/overlays/devices/tr3000-full/files"
[ -d "$FULL_OVERLAY" ] || fail "Full overlay not found: $FULL_OVERLAY"
cp -R "$FULL_OVERLAY/." "$SOURCE_DIR/files/"
```

删除 `95-tr3000-full-services` 的旧 install 行（overlay 已带）。同时更新 `tests/scripts/test_scripts.py` 中 Full 资产断言：`full_assets[f"files/etc/config/{config}"]` 的期望值改为读 `overlays/devices/tr3000-full/files/etc/config/{config}`。

- [ ] **Step 5: 跑聚焦测试确认通过**

Run: `python3 -m unittest tests.structure.test_repository_contract tests.scripts.test_scripts -v 2>&1 | tail -10`
Expected: PASS（Lite 用例不受影响——Lite overlay 本就覆盖这三份）。

- [ ] **Step 6: 全量校验并提交**

```bash
bash scripts/validate.sh && python -m unittest discover -s tests
git add -A overlays/devices/tr3000-full files scripts/configure-full.sh tests
git commit -m "feat(full): ship the home-router network overlay and retire the plant segment"
```

---

### Task 2: mt_wifi 管理 AP（纯改名复制 + 漂移守卫）

**Files:**
- Create: `scripts/tr3000-full-wifi.sh`（← `scripts/tr3000-lite-wifi.sh` RENAME）
- Create: `overlays/devices/tr3000-full/files/etc/uci-defaults/91-tr3000-full-management-ap`（← Lite 同名 91 文件 RENAME）
- Create: `overlays/devices/tr3000-full/files/etc/init.d/tr3000-full-wifi`（← Lite init.d RENAME）
- Modify: `scripts/configure-full.sh`
- Test: `tests/scripts/test_tr3000_full_drift.py`（新）、`tests/scripts/test_tr3000_full_wifi.py`（新）

**Interfaces:**
- Produces: 镜像内 `/usr/sbin/tr3000-full-wifi`（`status --json | repair`）、`/usr/sbin/tr3000-full-wifi-ap`（首启实现常驻副本）、init.d `tr3000-full-wifi`（START=20）。
- Produces: 就绪标记 `/etc/tr3000-full/management-ap.initialized`；受管 AP 标记 option `tr3000_full_managed=1`；SSID `TR3000-Full-<6 hex>`；`network=lan`、`encryption=psk2`。
- Consumes: Task 1 的 overlay 装配（新文件放进 overlay 即入镜像）。

- [ ] **Step 1: 写失败的漂移守卫测试**

```python
"""Full copies of the Lite wifi trio must stay token-identical (spec D2)."""
import unittest
from tests.scripts.test_scripts import ROOT

PAIRS = [
    ("scripts/tr3000-lite-wifi.sh", "scripts/tr3000-full-wifi.sh"),
    ("overlays/devices/tr3000-lite/files/etc/uci-defaults/91-tr3000-lite-management-ap",
     "overlays/devices/tr3000-full/files/etc/uci-defaults/91-tr3000-full-management-ap"),
    ("overlays/devices/tr3000-lite/files/etc/init.d/tr3000-lite-wifi",
     "overlays/devices/tr3000-full/files/etc/init.d/tr3000-full-wifi"),
]

def rename(text: str) -> str:
    for old, new in (("tr3000-lite", "tr3000-full"),
                     ("tr3000_lite", "tr3000_full"),
                     ("TR3000-Lite", "TR3000-Full")):
        text = text.replace(old, new)
    return text

class FullWifiDriftTests(unittest.TestCase):
    def test_full_wifi_copies_match_lite_after_token_rename(self) -> None:
        for lite, full in PAIRS:
            with self.subTest(pair=full):
                expected = rename((ROOT / lite).read_text(encoding="utf-8"))
                self.assertEqual(expected, (ROOT / full).read_text(encoding="utf-8"))
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m unittest tests.scripts.test_tr3000_full_drift -v`
Expected: FAIL（Full 文件不存在）。

- [ ] **Step 3: 生成三个改名副本**

```bash
for pair in "scripts/tr3000-lite-wifi.sh scripts/tr3000-full-wifi.sh" \
  "overlays/devices/tr3000-lite/files/etc/uci-defaults/91-tr3000-lite-management-ap overlays/devices/tr3000-full/files/etc/uci-defaults/91-tr3000-full-management-ap" \
  "overlays/devices/tr3000-lite/files/etc/init.d/tr3000-lite-wifi overlays/devices/tr3000-full/files/etc/init.d/tr3000-full-wifi"; do
  set -- $pair
  sed -e 's/tr3000-lite/tr3000-full/g' -e 's/tr3000_lite/tr3000_full/g' -e 's/TR3000-Lite/TR3000-Full/g' "$1" > "$2"
  chmod --reference="$1" "$2"
done
```

- [ ] **Step 4: configure-full.sh 安装 wifi 控制器**

在 overlay 装配之后加（与 Lite 的安装模式一致）：

```sh
install -m 0755 "$SCRIPT_DIR/tr3000-full-wifi.sh" "$SOURCE_DIR/files/usr/sbin/tr3000-full-wifi"
install -m 0755 "$FULL_OVERLAY/etc/uci-defaults/91-tr3000-full-management-ap" \
	"$SOURCE_DIR/files/usr/sbin/tr3000-full-wifi-ap"
```

- [ ] **Step 5: 写 Full 行为测试（复用 Lite 测试模块）**

`tests/scripts/test_tr3000_full_wifi.py`：读取 `tests/scripts/test_tr3000_lite_wifi.py` 源码，应用与 Step 3 相同的三对 token 替换，再把被误替换的导入行 `from tests.scripts import test_tr3000_full_plant as plant_tests` 还原为 `…test_tr3000_lite_plant…`，然后 `exec(compile(source, …), module_globals)` 并从中取出 `ManagementAPTests` 子类化为 `FullManagementAPTests`。这样 Lite 的全部 AP 行为用例（开放 AP 禁用、psk2/lan 绑定、幂等、STA 保留、失败保留脚本、key 不落日志）自动以 Full 路径与 Full 期望值运行。文件末尾加一条哨兵断言防止变换失效：

```python
class FullTransformSentinel(unittest.TestCase):
    def test_transformed_module_targets_the_full_script(self):
        self.assertIn("tr3000-full", str(module_globals["SCRIPT"]))
        self.assertNotIn("tr3000-lite", str(module_globals["SCRIPT"]))
```

- [ ] **Step 6: 跑聚焦测试确认通过**

Run: `python3 -m unittest tests.scripts.test_tr3000_full_drift tests.scripts.test_tr3000_full_wifi -v 2>&1 | tail -10`
Expected: PASS（含 STA 保留用例 `test_management_identity_survives_station_add_disconnect_and_removal` 的 Full 变体）。

- [ ] **Step 7: 提交**

```bash
bash scripts/validate.sh
git add scripts/tr3000-full-wifi.sh scripts/configure-full.sh overlays/devices/tr3000-full tests/scripts/test_tr3000_full_drift.py tests/scripts/test_tr3000_full_wifi.py
git commit -m "feat(full): ship the managed mt_wifi access point with a drift guard"
```

---

### Task 3: 三上行故障切换与 USB 手机共享（改名 + 五处语义改写）

**Files:**
- Create: `scripts/tr3000-full-uplink-watch.sh`、`scripts/tr3000-full-uplink-lib.sh`、`scripts/tr3000-full-uplink-status.sh`、`scripts/tr3000-full-uplink-changed.sh`、`scripts/tr3000-full-usbwan-lib.sh`（← Lite 对应五件，RENAME + 下述语义改写）
- Create: `overlays/devices/tr3000-full/files/etc/config/tr3000-full-uplink-watch`（← Lite overlay 同名 config RENAME，含 `globals` 段 interval 15 / failures 3 / successes 2）
- Create: `overlays/devices/tr3000-full/files/etc/init.d/tr3000-full-uplink-watch`（← Lite overlay init.d RENAME；`service_triggers` 去掉 `tr3000-lite-remote`，保留 `network tr3000-full-uplink-watch firewall`）
- Create: `overlays/devices/tr3000-full/files/etc/uci-defaults/90-tr3000-full-uplink-watch`（enable+start 新服务）
- Create: `overlays/devices/tr3000-full/files/etc/hotplug.d/iface/95-tr3000-full-uplink-reconcile`（← Lite RENAME，调用 `/usr/sbin/tr3000-full-uplink-watch reconcile`）
- Create: `overlays/devices/tr3000-full/files/etc/hotplug.d/net/90-tr3000-full-usbwan`（← Lite RENAME + 锁改名）
- Modify: `scripts/configure-full.sh`
- 保留不动: `files/etc/config/lite-uplink-watch`、`files/etc/init.d/lite-uplink-watch`（**不得 git rm**：`configure-lite.sh:212` 显式安装后者；Full 侧在装配后从源树删除，见 Step 3）
- Test: `tests/scripts/test_tr3000_full_uplink.py`（新）

**Interfaces:**
- Produces: `/usr/sbin/tr3000-full-uplink-watch`（`reconcile|daemon`）、`/usr/sbin/tr3000-full-uplink-status`（`--json`，schema_version=1，字段同 Lite：`active/previous/interfaces[].{name,device,address,gateway,base_metric,effective_metric,health,failures,successes,available}`）、`/usr/lib/tr3000-full/{uplink-lib.sh,usbwan-lib.sh,uplink-changed}`。
- Produces: 状态目录 `/var/run/tr3000-full/uplink`；事件 `ubus send tr3000-full.uplink-changed`。
- Consumes: `lite-common.sh`（共享 helper，不改名）；Task 1 overlay 装配。

**五处语义改写（spec D2a + 锁改名 + 受保护集合，其余逐字 RENAME）：**

| 位置（Lite 源） | Full 写法 |
|---|---|
| `uplink-lib.sh:49` `for protected in plant mgmt` | `for protected in lan` |
| `uplink-status.sh:110` `ap:*' mgmt '*) network=mgmt` | `ap:*' lan '*) network=lan` |
| `uplink-changed.sh` 的 REMOTE 段（`tr3000-lite-remote sync` + `wg_direct/wg_vps` 循环） | 整段替换为：`if [ "$(uci -q get network.wg.proto)" = wireguard ] && [ "$(uci -q get network.wg.auto)" = 1 ]; then ifdown wg >/dev/null 2>&1 && ifup wg >/dev/null 2>&1 || result=1; fi` |
| `90-…-usbwan:25` `NETWORK_LOCK=/var/lock/tr3000-lite-plant` | `NETWORK_LOCK=/var/lock/tr3000-full-network`（:55 注释同步改为"网络文件写锁"） |
| `90-…-usbwan:90` `for protected in wan plant mgmt wwan` | `for protected in wan lan wwan` |

注：`uplink-watch.sh` 里 `REMOTE_GUARD=/usr/sbin/tr3000-lite-remote` 经 RENAME 变为 `tr3000-full-remote`——该路径在 Full 永不存在，`[ -x ]` 守卫使其成为无害 no-op，**保留纯改名**，不删分支。

- [ ] **Step 1: 写失败的 Full 上行测试**

创建 `tests/scripts/test_tr3000_full_uplink.py`。以 `tests/scripts/test_tr3000_lite_uplink.py` 为蓝本（fixture 模式照抄：fake ubus/ip/uci + 临时 root），顶部常量 `SCRIPT/LIB/STATUS/CHANGED/USB_HOOK/USBWAN_LIB` 指向 Full 对应路径，`rename` 从 `tests.scripts.test_tr3000_full_drift` 导入；先写七个用例：

```python
def test_protected_set_is_the_access_segment(self):
    # uplink-lib 拒绝把 uplink 绑到 lan 的设备
    text = LIB.read_text(encoding="utf-8")
    self.assertIn("for protected in lan", text)
    self.assertNotIn("plant", text)

def test_status_maps_managed_ap_to_lan(self):
    text = STATUS.read_text(encoding="utf-8")
    self.assertIn("ap:*' lan '*) network=lan", text)
    self.assertNotIn("mgmt", text)

def test_uplink_event_restarts_the_single_wg_interface(self):
    # fixture: network.wg.proto=wireguard, auto=1 → ifdown/ifup wg 各一次
    # fixture: auto=0 → 不重启；无 wg → 不重启
    ...

def test_usbwan_lock_is_the_full_network_lock(self):
    text = USB_HOOK.read_text(encoding="utf-8")
    self.assertIn("/var/lock/tr3000-full-network", text)
    self.assertIn("for protected in wan lan wwan", text)

def test_three_failures_demote_and_two_successes_recover(self):
    # 与 Lite 同名用例同断言：metric 10→1010→10，health 字段一致
    ...

def test_usbwan_lib_is_a_pure_rename_of_lite(self):
    expected = rename((ROOT / "scripts/tr3000-lite-usbwan-lib.sh").read_text())
    self.assertEqual(expected, USBWAN_LIB.read_text())

def test_multiple_usb_candidates_fail_closed_and_lan_is_never_stolen(self):
    # 移植 tests/scripts/test_tr3000_lite_usbwan.py 的
    # test_multiple_candidates_fail_closed_and_recover_after_removal 与
    # test_existing_manual_binding_and_protected_interfaces_are_not_stolen，
    # 受保护接口 fixture 用 network.lan.device=br-lan 替代 plant/mgmt
    ...
```

（`...` 处按蓝本同名用例的 fixture 与断言移植，token 按 RENAME；`test_uplink_event_restarts_the_single_wg_interface` 的 fixture 用 `network.wg.*` 替代 Lite 的 `wg_direct/wg_vps`。）

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m unittest tests.scripts.test_tr3000_full_uplink -v`
Expected: FAIL（Full 脚本不存在）。

- [ ] **Step 3: 生成五件套并做五处语义改写**

先按 RENAME（含 `lite-uplink-watch→tr3000-full-uplink-watch`）sed 生成五个脚本与 overlay 四个文件（config/init.d/uci-defaults/两个 hotplug），再按上表逐处编辑。`configure-full.sh`：

```sh
install -m 0755 "$SCRIPT_DIR/tr3000-full-uplink-watch.sh" "$SOURCE_DIR/files/usr/sbin/tr3000-full-uplink-watch"
install -m 0755 "$SCRIPT_DIR/tr3000-full-uplink-status.sh" "$SOURCE_DIR/files/usr/sbin/tr3000-full-uplink-status"
mkdir -p "$SOURCE_DIR/files/usr/lib/tr3000-full"
install -m 0644 "$SCRIPT_DIR/tr3000-full-uplink-lib.sh" "$SOURCE_DIR/files/usr/lib/tr3000-full/uplink-lib.sh"
install -m 0644 "$SCRIPT_DIR/tr3000-full-usbwan-lib.sh" "$SOURCE_DIR/files/usr/lib/tr3000-full/usbwan-lib.sh"
install -m 0755 "$SCRIPT_DIR/tr3000-full-uplink-changed.sh" "$SOURCE_DIR/files/usr/lib/tr3000-full/uplink-changed"
rm -f "$SOURCE_DIR/files/etc/uci-defaults/90-lite-uplink-watch" \
	"$SOURCE_DIR/files/etc/init.d/lite-uplink-watch" \
	"$SOURCE_DIR/files/etc/config/lite-uplink-watch" \
	"$SOURCE_DIR/files/usr/sbin/lite-uplink-watch"
```

同时删除 configure-full.sh 里旧的 `lite-uplink-watch.sh` 三行 install。`files/etc/{init.d,config}/lite-uplink-watch` 保留在仓库（Lite 依赖），仅由上面的 `rm -f` 从 Full 装配树移除。注意 uplink-status.sh 头部 source 路径经 RENAME 后应为 `/usr/lib/tr3000-full/uplink-lib.sh`，与安装路径一致。

- [ ] **Step 4: 跑聚焦测试确认通过**

Run: `python3 -m unittest tests.scripts.test_tr3000_full_uplink tests.scripts.test_scripts -v 2>&1 | tail -10`
Expected: PASS。另跑 `python3 -m unittest tests.scripts.test_tr3000_lite_uplink tests.scripts.test_tr3000_lite_usbwan -v` 确认 Lite 未回归。

- [ ] **Step 5: 提交**

```bash
bash scripts/validate.sh
git add -A scripts overlays/devices/tr3000-full files tests/scripts/test_tr3000_full_uplink.py
git commit -m "feat(full): adopt the verified multi-uplink failover and USB tethering"
```

---

### Task 4: 软件包组合（seed / configure 门禁 / workflow 默认值）

**Files:**
- Modify: `configs/full.seed`
- Modify: `scripts/configure-full.sh`（必选/排除断言、wpad provider 检查）
- Modify: `.github/workflows/build-full.yml`（`include_tailscale` 默认 false、`include_cloudflared` 默认 true）
- Test: `tests/scripts/test_scripts.py`、`tests/workflows/test_workflows.py`

**Interfaces:**
- Produces: `full_base_config()` fixture 扩展后的必选包集合（见 Step 1）；`run_full_configure(...)` 签名不变。
- Produces: seed 中 `# CONFIG_PACKAGE_tailscale is not set`（由动态段按开关覆盖）；cloudflared 同机制不变。

- [ ] **Step 1: 写失败的配置测试**

`tests/scripts/test_scripts.py`：`full_base_config()` 的 `required_packages` 追加 `"luci-app-homeproxy", "luci-i18n-homeproxy-zh-cn", "ucode-mod-digest", "luci-app-ddns", "ddns-scripts", "ddns-scripts-cloudflare", "luci-i18n-ddns-zh-cn", "luci-app-cloudflared", "luci-i18n-cloudflared-zh-cn", "luci-theme-argon", "luci-app-argon-config", "luci-i18n-argon-config-zh-cn", "wpad-openssl", "sing-box"`。新增用例：

```python
def test_full_config_selects_the_home_router_package_set(self):
    result, config, _ = run_full_configure(full_base_config())
    self.assertEqual(0, result.returncode, result.stderr)
    for package in ("luci-app-homeproxy", "ucode-mod-digest", "ddns-scripts-cloudflare",
                    "luci-theme-argon", "wpad-openssl", "sing-box"):
        self.assertIn(f"CONFIG_PACKAGE_{package}=y", config)
    self.assertNotIn("CONFIG_PACKAGE_luci-theme-aurora=y", config)

def test_full_tailscale_defaults_off_and_switch_overrides(self):
    result, config, _ = run_full_configure(full_base_config())
    self.assertNotIn("CONFIG_PACKAGE_tailscale=y", config)
    result, config, _ = run_full_configure(full_base_config(), include_tailscale="true")
    self.assertIn("CONFIG_PACKAGE_tailscale=y", config)

def test_full_cloudflared_defaults_on_and_false_removes_it(self):
    result, config, _ = run_full_configure(full_base_config())
    self.assertIn("CONFIG_PACKAGE_cloudflared=y", config)
    result, config, _ = run_full_configure(
        full_base_config().replace("CONFIG_PACKAGE_cloudflared=y\n", ""),
        include_cloudflared="false")
    self.assertNotIn("CONFIG_PACKAGE_cloudflared=y", config)
```

（第三个用例需 configure-full.sh 在 `include_cloudflared=true` 时把 cloudflared 列入必选断言——与现有 tailscale/singbox 动态断言同机制，已存在则仅确认。）`tests/workflows/test_workflows.py`：把 Full 输入默认值断言改为 `include_tailscale=false`、`include_cloudflared=true`。

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m unittest tests.scripts.test_scripts tests.workflows.test_workflows -v 2>&1 | tail -15`
Expected: 新用例 FAIL。

- [ ] **Step 3: 改 seed 与 configure 门禁**

seed 按 spec §6.10 追加 12 个 `=y`（homeproxy/i18n×3/ucode-mod-digest/ddns×3/cloudflared/argon×3/wpad-openssl），`CONFIG_PACKAGE_tailscale=y` 改为 `# CONFIG_PACKAGE_tailscale is not set`，追加排除 `# CONFIG_PACKAGE_kmod-usb-net-ipheth is not set`。configure-full.sh：必选包循环追加上述包（cloudflared 除外——它走动态断言）；排除列表追加 `luci-app-argon-config` 以外的 aurora 项已有则不动、追加 `kmod-usb-net-ipheth`；加 wpad provider 唯一性检查（照抄 configure-lite.sh:149-151 的写法）；加 `grep -Fq 'CONFIG_PACKAGE_luci-theme-argon=y'` 与 aurora 未选断言。workflow 两个默认值翻转。

- [ ] **Step 4: 跑聚焦测试确认通过**

Run: `python3 -m unittest tests.scripts.test_scripts tests.workflows.test_workflows -v 2>&1 | tail -10`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
bash scripts/validate.sh
git add configs/full.seed scripts/configure-full.sh .github/workflows/build-full.yml tests
git commit -m "feat(full): select the home-router package set with build-time tunnel switches"
```

---

### Task 5: 服务控制器、首启默认与 LuCI 状态页

**Files:**
- Modify: `scripts/service-toggle.sh`（`sing-box`→`homeproxy`；status JSON 增 `legacy_config_detected`）
- Modify: `overlays/devices/tr3000-full/files/etc/uci-defaults/95-tr3000-full-services`
- Modify: `packages/luci-app-tr3000-full/htdocs/luci-static/resources/view/tr3000-full/services.js`
- Create: `packages/luci-app-tr3000-full/htdocs/luci-static/resources/view/tr3000-full/uplinks.js`（← Lite `uplinks.js` RENAME，控制器路径 `/usr/sbin/tr3000-full-uplink-status`）
- Modify: `packages/luci-app-tr3000-full/root/usr/share/luci/menu.d/luci-app-tr3000-full.json`（firstchild + services/uplinks 两子页）
- Modify: `packages/luci-app-tr3000-full/root/usr/share/rpcd/acl.d/luci-app-tr3000-full.json`（write.file 增 `/usr/sbin/tr3000-full-uplink-status: ["exec"]`）
- Test: `tests/structure/test_repository_contract.py`（Full LuCI/首启用例改造）、`tests/scripts/test_scripts.py`（service-toggle 用例）

**Interfaces:**
- Produces: `tr3000-full-service status --json` 输出四服务 `wireguard/tailscale/homeproxy/cloudflared` 各 `{installed,enabled,running}` + 顶层 `legacy_config_detected: true|false`（`uci -q get network.plant` 或 `network.mgmt` 任一非空即 true）。
- Produces: `enable|disable homeproxy` 操作 `/etc/init.d/homeproxy`；`disable sing-box` 不再是 CLI 服务名（首启脚本直接调 `/etc/init.d/sing-box disable`，见 Step 3）。
- Consumes: Task 3 的 `tr3000-full-uplink-status --json`。

- [ ] **Step 1: 写失败的测试**

`tests/structure/test_repository_contract.py` 改造既有两个 Full 用例：`test_full_luci_package_is_admin_only_and_uses_fixed_controller` 的服务列表改为 `("wireguard", "tailscale", "homeproxy", "cloudflared")`，ACL write.file 断言含两个控制器；`test_full_first_boot_policy_disables_remote_services` 断言 95-services 含 `disable wireguard/tailscale/cloudflared/homeproxy` 四行与 `/etc/init.d/sing-box disable`。新增：

```python
def test_full_service_status_flags_legacy_industrial_config(self):
    # fixture root: etc/config/network 含 config interface 'plant' →
    # status --json 的 legacy_config_detected 为 true；干净 network → false
    ...
```

（fixture 模式照抄本文件既有 service-toggle 测试；若无则用临时 root + fake uci，参照 `tests/scripts/test_tr3000_lite_remote.py` 的 PATH fixture 手法。）

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m unittest tests.structure.test_repository_contract -v 2>&1 | tail -10`
Expected: FAIL。

- [ ] **Step 3: 实现控制器与首启默认**

`service-toggle.sh`：`known_service` 与 `print_json_status` 中 `sing-box` 全部换 `homeproxy`（init 名 `/etc/init.d/homeproxy`）；`print_json_status` 末尾追加 `"legacy_config_detected":%s`，值由 `[ -n "$(uci -q get network.plant 2>/dev/null)" ] || [ -n "$(uci -q get network.mgmt 2>/dev/null)" ]` 判定。95-services 内容：

```sh
#!/bin/sh
/usr/sbin/tr3000-full-service disable wireguard >/dev/null 2>&1 || :
/usr/sbin/tr3000-full-service disable tailscale >/dev/null 2>&1 || :
/usr/sbin/tr3000-full-service disable cloudflared >/dev/null 2>&1 || :
/usr/sbin/tr3000-full-service disable homeproxy >/dev/null 2>&1 || :
# The sing-box package ships its own init; HomeProxy owns the binary instead.
/etc/init.d/sing-box disable >/dev/null 2>&1 || :
exit 0
```

- [ ] **Step 4: LuCI 视图与菜单**

`services.js`：services 数组第三项 `{ id: 'homeproxy', title: _('HomeProxy (sing-box)'), note: _('Configure nodes and routing mode in Services → HomeProxy.') }`；render 顶部当 `status.legacy_config_detected` 为 true 时插入红色 `alert-message danger`：`_('Legacy industrial configuration detected. Reflash without keeping settings (sysupgrade -n).')`。`uplinks.js` 按 RENAME 复制。menu.d 改为 parent firstchild + `…/services`、`…/uplinks` 两个 view 子项（结构照抄 Lite menu.d 的 firstchild 模式，路径留在 `admin/services/tr3000-full`）。ACL 增 uplink-status exec。

- [ ] **Step 5: 跑聚焦测试确认通过**

Run: `python3 -m unittest tests.structure.test_repository_contract tests.scripts.test_scripts -v 2>&1 | tail -10`
Expected: PASS。

- [ ] **Step 6: 提交**

```bash
bash scripts/validate.sh
git add scripts/service-toggle.sh overlays/devices/tr3000-full packages/luci-app-tr3000-full tests
git commit -m "feat(full): control homeproxy and tunnels from LuCI with legacy-config detection"
```

---

### Task 6: build-full 门禁与产物证据

**Files:**
- Modify: `scripts/build-full.sh`
- Create: `tests/scripts/test_full_build_evidence.py`

**Interfaces:**
- Produces: Artifact 文件 `full-runtime-contract.txt`（`schema_version=1`、`evidence_kind=expected-defaults-not-live-state`、`lan_cidr=192.168.10.1/24`、`lan_dhcp_pool=192.168.10.100-192.168.10.249`、`uplink_order=wan,wwan,usbwan`、`uplink_metrics=10,20,30`、`wireless_stack=mt_wifi`、`management_ap_network=lan`、`management_ap_encryption=psk2`、`management_ap_default_open_ap=disabled`、`proxy_engine=sing-box`、`proxy_ui=homeproxy`、`proxy_default=disabled`、`tunnel_default=disabled`、`wg_listener_default=0`、`wg_to_lan_forwarding=present`、`ddns_provider_default=cloudflare.com-v4`、`ddns_default=disabled`、`luci_theme_default=argon`、`luci_theme_fallback=bootstrap`、`wan_management=off`、`plant_segment=absent`）。
- Produces: Artifact `image-packages.manifest`（照抄 build-lite.sh 的 profile manifest 提取逻辑）。
- Consumes: Task 1–4 的 overlay 与 seed；`verify-image.sh` 不改（`MAX_BYTES=104857600`）。

- [ ] **Step 1: 写失败的门禁测试**

`tests/scripts/test_full_build_evidence.py`（蓝本：`tests/scripts/test_lite_build_evidence.py`）：

```python
def test_build_full_asserts_the_overlay_before_compiling(self):
    text = (ROOT / "scripts/build-full.sh").read_text(encoding="utf-8")
    for token in ("config interface 'lan'", "option ipaddr '192.168.10.1'",
                  "config device 'br_lan'", "list ports 'eth1'", "config dhcp 'lan'"):
        self.assertIn(token, text)
    self.assertIn("must not ship a wireless configuration", text)
    # 断言发生在 make download 之前
    self.assertLess(text.index("config interface 'lan'"), text.index("make download"))

def test_full_runtime_contract_matches_the_overlay(self):
    # 解析 build-full.sh 内嵌 heredoc 的 contract 字段，与 overlay 实际值比对
    # （lan_cidr/dhcp 池/uplink metrics 来自 overlay 文件解析，非硬编码）
    ...

def test_image_size_gate_is_unchanged(self):
    text = (ROOT / "scripts/verify-image.sh").read_text(encoding="utf-8")
    self.assertIn("MAX_BYTES=104857600", text)
    self.assertIn("verify-image.sh", (ROOT / "scripts/build-full.sh").read_text(encoding="utf-8"))
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m unittest tests.scripts.test_full_build_evidence -v`
Expected: FAIL。

- [ ] **Step 3: 实现 build-full 门禁**

在 `configure-full.sh` 调用之后、`make download` 之前插入 overlay 断言块（照抄 build-lite.sh:108-122 的结构，路径换 `$SOURCE_DIR/files/etc/config/…`，另加 `grep -Fq plant` 反向断言与 wireless 缺失断言）。构建后：提取 `*cudy_tr3000-v1-ubootmod.manifest` 为 `image-packages.manifest`；必选包断言 `luci-app-tr3000-full luci-app-homeproxy sing-box wpad-openssl luci-theme-argon ddns-scripts-cloudflare`；排除断言 `ruby libruby luci-app-openclash luci-app-passwall luci-theme-aurora`；USB 三包集合相等断言（照抄 Lite）；cloudflared/tailscale 按开关断言存在/不存在；写 `full-runtime-contract.txt` heredoc（字段见 Interfaces）；禁止 secret 文件进 Artifact 的检查照抄 Lite。

- [ ] **Step 4: 跑聚焦测试确认通过**

Run: `python3 -m unittest tests.scripts.test_full_build_evidence tests.scripts.test_scripts -v 2>&1 | tail -10`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
bash scripts/validate.sh
git add scripts/build-full.sh tests/scripts/test_full_build_evidence.py
git commit -m "feat(full): gate the image on the home-router contract and package evidence"
```

---

### Task 7: 文档同步

**Files:**
- Modify: `docs/FULL-README.md`（重写为家用路由器）、`docs/TEST-PLAN.md`（F1–F14）、`docs/TAILSCALE.md`、`docs/CLOUDFLARED-ACCESS.md`（家用语义）、`README.md`（索引）、`configs/devices/TR3000/TR3000-Full-综合增强版-提示词.md`（顶部标注被取代）
- Create: `docs/HOMEPROXY-SPLIT-ROUTING.md`、`docs/TUNNEL-ACCESS.md`、`docs/DDNS-CLOUDFLARE.md`
- Delete: `docs/WIREGUARD-SNAT.md`、`docs/SINGBOX-SPLIT-ROUTING.md`
- Test: `tests/structure/test_repository_contract.py`

**Interfaces:**
- Consumes: Task 1–6 的最终行为（地址、服务名、开关默认值、contract 字段）。
- Produces: 三份新手册被 `docs/FULL-README.md` 链接；TEST-PLAN 含 F1–F14。

- [ ] **Step 1: 写失败的文档契约测试**

```python
def test_full_documents_describe_the_home_router(self) -> None:
    readme = (ROOT / "docs/FULL-README.md").read_text(encoding="utf-8")
    for doc in ("HOMEPROXY-SPLIT-ROUTING.md", "TUNNEL-ACCESS.md", "DDNS-CLOUDFLARE.md"):
        self.assertTrue((ROOT / "docs" / doc).is_file(), doc)
        self.assertIn(f"docs/{doc}", readme)
    for forbidden in ("192.168.77", "br-mgmt", "plant"):
        self.assertNotIn(forbidden, readme)
    plan = (ROOT / "docs/TEST-PLAN.md").read_text(encoding="utf-8")
    for case in range(1, 15):
        self.assertIn(f"F{case}", plan)
    self.assertFalse((ROOT / "docs/WIREGUARD-SNAT.md").exists())
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m unittest tests.structure.test_repository_contract -v 2>&1 | tail -8`
Expected: FAIL。

- [ ] **Step 3: 写文档**

内容按 spec §6.12：FULL-README 覆盖出厂网络（192.168.10.1、DHCP 池、管理 AP 读取方式）、HomeProxy 三模式、三穿透通道与默认关闭、DDNS Cloudflare（Bearer Token 填法：username=`Bearer`、password=Token；域名 `host@domain.tld`）、Argon/Bootstrap 切换、三上行切换、首次部署与 `sysupgrade -n`；TEST-PLAN 增 F1–F14（spec §6.11 表格照录）；TUNNEL-ACCESS 写 wg 三条规则默认关与启用顺序（先配接口→开 listener→开 mgmt/icmp）；删除两份工业文档并清理仓库内对它们的链接引用（`rg -l 'WIREGUARD-SNAT|SINGBOX-SPLIT-ROUTING' docs/ README.md`，Lite 专属文档中的引用改为指向历史 spec 或删除该链接行）。

- [ ] **Step 4: 跑测试确认通过并提交**

```bash
python3 -m unittest tests.structure.test_repository_contract -v 2>&1 | tail -5
bash scripts/validate.sh && python -m unittest discover -s tests
git add -A docs README.md configs/devices/TR3000 tests/structure
git commit -m "docs(full): document the home-router firmware and retire the industrial runbooks"
```

---

### Task 8: GitHub Actions 构建与产物核对（验证任务，无仓库改动）

**Files:** 无（验证步骤；结论写进最终汇报）。

**Interfaces:**
- Consumes: 本分支全部提交；`build-full.yml`。
- Produces: 一次成功构建的运行号 + 五项产物核对结论；失败则修复后重跑（修复属于新提交，回到对应任务的测试循环）。

- [ ] **Step 1: 推送分支（先向用户确认——远端写操作）**

Run: `git push -u origin feature/tr3000-full-factory-access`

- [ ] **Step 2: 触发并等待构建**

Run: `gh workflow run build-full.yml --ref feature/tr3000-full-factory-access` → `gh run list --workflow=build-full.yml --limit 1` 取运行号 → `gh run watch <run-id> --exit-status`
Expected: 退出码 0。若体积门禁失败：按 spec D4/D6 降级（sing-box tiny 或 cloudflared 默认关）需**回报用户批准**后再改，不得自行放宽 100 MiB。

- [ ] **Step 3: 下载并核对产物**

Run: `gh run download <run-id> -n TR3000-128M-112M-Full -D /tmp/full-art`
核对（解包 sysupgrade root 分区）：
1. `/etc/config/network` 含 lan/br_lan/eth1，无 plant/mgmt；
2. `/etc/config/dhcp` 含 `config dhcp 'lan'`、limit 150；
3. 镜像内**无** `/etc/config/wireless`；
4. `full-runtime-contract.txt` 字段与 Task 6 Interfaces 一致；
5. `image-packages.manifest` 含 homeproxy/sing-box/argon/ddns-cloudflare/cloudflared，不含 tailscale/ruby/openclash/passwall/aurora。

- [ ] **Step 4: 记录结论**

运行号、镜像大小（对照 100 MiB 余量）、五项核对结果写进最终汇报；未通过项显式列出。真机 F1–F14 由用户在设备旁执行。分支合并/PR 走 `superpowers:finishing-a-development-branch`。
