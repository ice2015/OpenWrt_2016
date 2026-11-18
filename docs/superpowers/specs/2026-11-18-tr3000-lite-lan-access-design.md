# TR3000-Lite 出厂可达性改造设计（LAN 接入模式 + mt_wifi 兼容）

- 日期：2026-11-18
- 目标：Cudy TR3000 v1（MT7981，128 MiB NAND，U-Boot Mod，112 MiB UBI）Lite 固件
- 基线分支：`feature/tr3000-lite-managed-access` @ `53452e6`
- 本分支：`feature/tr3000-lite-lan-access`
- 状态：**待审批**。批准前不实现任何固件行为变更。

## 1. 背景

用户在 `feature/tr3000-lite-managed-access` 产出的固件（Actions run 43918523291，Artifact `tr3000-lite-128m-ubootmod-112m`）上实测：

1. PC 插 LAN 口拿不到 IP，ping 不通路由器；
2. WiFi 连上后没有 DHCP 分配，同样 ping 不通；
3. 要求：像普通路由器一样，**插上就有 IP、ping 通、浏览器进 LuCI**。

同时要求完整阅读 Lite 设计方案并给出方案与建议。

## 2. 证据（镜像级，来自 run 43918523291 的 sysupgrade 镜像）

镜像解包在 `/tmp/lite-artifact/img/rootfs`。关键事实：

| # | 事实 | 出处 |
|---|---|---|
| E1 | `/etc/config/network` 只有 `wan/wwan/usbwan/plant/mgmt`，**没有 `lan`** | `overlays/devices/tr3000-lite/files/etc/config/network` 覆盖了上游默认 |
| E2 | `/bin/config_generate` 仅在 `/etc/config/network` **为空**时才按 board.json 补默认 LAN；我们覆盖成非空 → 永远补不出 `lan` | 镜像 `bin/config_generate:9,530` |
| E3 | 上游 `board.d/02_network` 对 `cudy,tr3000-v1*` 是 `ucidef_set_interfaces_lan_wan "eth1" eth0`（LAN=eth1/WAN=eth0） | 镜像 `etc/board.d/02_network:117` |
| E4 | `/etc/config/dhcp` 被整体覆盖，只有 `mgmt/plant/wan` 三段，**没有 `config dhcp 'lan'`** | `overlays/devices/tr3000-lite/files/etc/config/dhcp` |
| E5 | WiFi 栈是 **mt_wifi**（`kmod-mt_wifi` + `mtwifi-cfg` + `wifi-scripts`），**没有** mac80211/mt76/mt7915e（`target-package-index.txt` 里也没有） | 镜像 `image-packages.manifest` |
| E6 | 镜像内**不存在** `/etc/config/wireless`；启动时由 `/sbin/wifi config` → `detect_mtwifi` 现场生成：`wireless.radio0/radio1`（`type=mtwifi`）+ `wireless.default_radio0/default_radio1`，属性为 **`network=lan`、`encryption=none`、SSID `ImmortalWrt-2.4G/5G`** | 镜像 `lib/wifi/mtwifi.sh:1-65` |
| E7 | mt_wifi 的 netifd 驱动 `drv_mtwifi_setup()` 第一行即 `ubus -t 120 wait_for network.interface.lan` → **没有 `lan` 就阻塞 120 秒**，且其自带默认 AP 绑定 `lan` → 建不起来 | 镜像 `lib/netifd/wireless/mtwifi.sh` |
| E8 | Lite 的 `91-tr3000-lite-management-ap` 按 mac80211 语义编写：要求 `/etc/config/wireless` 已存在、处理 `@wifi-device[*]` 匿名段、`encryption=psk2` | `overlays/devices/tr3000-lite/files/etc/uci-defaults/91-tr3000-lite-management-ap` |
| E9 | 仓库内 `mt_wifi/mtwifi/mac80211` **零引用**；`br-lan`/`network.lan` 在 Lite 层零引用 | `rg` 全仓 |
| E10 | `plant` = eth1 静态 `192.168.10.254/24`，DHCP 全关；`plant` zone `input REJECT`，只留一条默认 `enabled=0` 的 443 规则 → 插线既无 DHCP 也 ping 不通 | `overlays/devices/tr3000-lite/files/etc/config/firewall` |
| E11 | DTS 只有两个网口：`gmac0`=2.5G(WAN/eth0)、`gmac1`=1G(LAN/eth1) → **全机只有一个 LAN 口** | 上游 `mt7981b-cudy-tr3000-v1.dtsi` |
| E12 | plant HTTPS 门禁 = root 密码非空 **且** `/etc/tr3000-lite/management-ap.initialized`；该标记只由 AP 初始化成功写入 → AP 起不来 ⇒ LuCI 永远打不开 plant Web ⇒ 无法自救 | `scripts/tr3000-lite-plant.sh:143-150` |
| E13 | 218 个测试全为静态配置/脚本契约测试，无任何启动/冒烟测试；产物自述 `evidence_kind=expected-defaults-not-live-state` | `tests/`、`lite-runtime-contract.txt` |

## 3. 根因

**不是缺包，是两个前提同时错配：**

1. **管理面设计假设了 mac80211，实际硬件栈是 mt_wifi**（E5/E6/E8/E9）。设计里的"管理 AP"从未在真实驱动栈上成立过；mt_wifi 自带的默认 AP 又绑在 `lan` 上。
2. **`lan` 段被设计主动删除**（E1/E2/E4），而设备只有一个 LAN 口（E11）。于是"有线接入"被定义成工业段 plant：设计内**没有**任何"普通路由器式"的可达路径。
3. 两者叠加 → 上电即无可达网络：无线起不来（E7），有线被设计为无 DHCP、无 ICMP（E10），且 plant Web 被门禁锁死（E12）。

原设计文档其实已写明"首次启动无线设备发现、双频 AP 与 STA 共存、plant HTTPS 门禁…仍需真机验证"，但缺少任何可执行的启动冒烟验证，导致问题直到真机才暴露。

## 4. 目标 / 非目标 / 反目标

### 目标

- G1 **出厂可达**：插网线或连 WiFi → 拿到 DHCP 地址 → ping 通路由器 → 浏览器打开 LuCI。
- G2 **工业隔离降级为显式选择**：plant 段保留，但默认不接管唯一 LAN 口；由操作员在 LuCI 里显式切换，随时可切回。
- G3 **WiFi 栈假设修正**：全部无线逻辑按 mt_wifi 语义实现，并消除对 mac80211 专属行为的依赖。
- G4 **CI 可防回归**：新增静态契约测试，锁住"默认可达 + 无开放热点 + plant 默认不接管"三条不变量。
- G5 **既有远程访问能力不回归**：WireGuard/DDNS/上行健康/plant 地址事务保持可用，仅做段名迁移。

### 非目标

- 不换 WiFi 硬件栈（不引入 mac80211/mt76/mt7915e：当前 target 无此包，属 UNRESOLVED）。
- 不改硬件、不改 U-Boot/分区布局、不改 UBI 容量假设。
- 不在本次实现真机自动化测试（无 CI 设备）；真机项走 TEST-PLAN 清单。
- 不改 `wan/wwan/usbwan` 上行语义与指标。

### 反目标（即使技术上可行也不做）

- 不在工业段默认开启 DHCP（会给 PLC/HMI 误发地址，属安全回归）。
- 不把无线凭据、root 密码、任何现场参数写入固件或 Artifact。
- 不为了"能连上"而放开 `wan` 侧管理面。
- 不在正式产物里塞"万能调试固件"；调试手段只进 `local/`。

## 5. 关键决策

| # | 决策 | 取舍与理由 |
|---|---|---|
| D1 | 新增 `lan` 段：`br-lan`（成员 eth1 + WiFi AP），`192.168.10.1/24`，DHCP `192.168.10.100-249`，zone `lan` `input ACCEPT`/`forward ACCEPT`，`lan→wan` 转发 | 192.168.10.0/24 避开 192.168.0/24、192.168.1/24 这类最常见的家用/办公网段（现场撞段概率最低）；`lan` 是 OpenWrt 惯用名，且 mt_wifi 驱动硬依赖 `network.interface.lan`（E7），用 `lan` 同时满足"普通路由器"与驱动约束 |
| D2 | 取消 `mgmt` 段（192.168.77.1/24），其角色合并进 `lan`；原 `mgmt→plant` 放行/SNAT 规则改为 `lan→plant`（源 192.168.10.0/24） | 只有一个管理面最不容易出错；`mgmt` 与 `lan` 并存会让操作员分不清该连哪个。代价：远程访问文档与源码中的 192.168.77 需迁移（24 处引用） |
| D3 | `plant` 改为**按需接管**：默认 `proto none` 且**不绑定 eth1**；切换到"工业模式"时 eth1 从 `br-lan` 摘出并由 plant 接管（默认 `192.168.20.254/24`、静态、DHCP 关、ICMP 关、LuCI 需 root 密码+显式开关）；可随时切回 | 一个物理口无法同时当"普通 LAN"和"工业段"。默认态可达、工业态隔离，两头都不牺牲。切换必须可逆，否则现场会被锁死 |
| D4 | 管理 AP 绑定 `lan`，WPA2（mt_wifi `encryption=psk2`），SSID `TR3000-Lite-<MAC 后 6 位大写十六进制>`，每机 16 随机字节 key（32 位小写 hex），只存 0600 的 `/etc/config/wireless` | 与既有实现一致；绑定 `lan` 后 PC 从 WiFi 拿到 192.168.10.x，与有线同段，符合"普通路由器"预期 |
| D5 | **关闭 mt_wifi 自带的开放默认 AP**（`default_radioX`，`encryption=none`） | 一旦 `lan` 有了 DHCP，这些默认开放热点会变成任何人都能连的开放网络——这是当前设计完全没考虑到的安全缺口 |
| D6 | AP 就绪标记 `/etc/tr3000-lite/management-ap.initialized` 保留，但**改为由 init.d 服务在验证通过后写入**，且**不再**作为 plant HTTPS 的唯一门禁；plant HTTPS 门禁改为"root 密码非空 + 操作员显式启用" | E12 的死锁来自"标记既是门禁又只有一条脆弱的写入路径"。恢复通道改为"有线 LAN（默认态）"后，plant Web 门禁不再需要依赖 AP 状态 |
| D7 | `enable-plant` 切换要求 AP 已就绪；否则必须显式 `--force-local-console`（只能从本地串口/控制台执行），LuCI 不提供该选项 | 防止"切到工业模式后管理路径断掉"导致失联；与仓库既有 fail-closed 风格一致 |
| D8 | 保留 `kmod-mt_wifi`，不引入 mac80211 | 当前 target 包索引无 mt76/mt7915e（E5），换栈需上游补包并核实硬件支持度，属 UNRESOLVED 且风险最高 |
| D9 | 无线配置改为"uci-defaults 首次配置 + init.d 服务常态校验/修复"双层 | mt_wifi 每次 `/sbin/wifi config` 都会重建 radio/default 段（E6），单一 uci-defaults 不足以长期维持；init.d 服务负责幂等修复并打标记 |

## 6. 详细设计

### 6.1 段与地址规划

| 段 | 设备 | 地址 | DHCP | 何时生效 |
|---|---|---|---|---|
| `lan`（接入/管理） | `br-lan` = eth1 + WiFi AP | `192.168.10.1/24` | `192.168.10.100-249` | 始终（出厂默认） |
| `plant`（工业段） | eth1（切出后） | 默认 `192.168.20.254/24`，可改 | 永久关闭 | 仅"工业模式" |
| `wan` | eth0 | DHCP | — | 始终 |

> `plant` 默认地址由原设计的 `192.168.10.254` 改为 `192.168.20.254`：接入段已占用 `192.168.10.0/24`，同一子网不能同时挂在 br-lan 与 plant 两个接口上（会造成直连路由二义与 ARP 混乱）。`192.168.20.0/24` 同样避开常见网段，且 `plant` 地址在 LuCI「工业 LAN」页可随时改。

**默认态（出厂，接入模式）**

桥接设备必须用**具名 section**（现 overlay 是匿名 section，UCI 无法按名寻址，事务里改不了成员）：

```uci
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
	option proto 'none'          # 默认不接管任何设备
```

`wan/wwan/usbwan` 保持不变；`mgmt` 段删除。

**工业态（plant 模式，操作员显式切换后）**

```uci
config device 'br_lan'
	option name 'br-lan'
	option type 'bridge'
	# 无 ports 成员：eth1 被摘出；br-lan 仅剩 WiFi AP，管理仍可达

config interface 'plant'
	option device 'eth1'
	option proto 'static'
	option ipaddr '192.168.20.254'
	option netmask '255.255.255.0'
```

`lan` 段地址与 DHCP 不变（br-lan 仍存在，只是没有有线成员）→ 切到工业态后，WiFi 管理路径不受影响。

### 6.2 DHCP / dnsmasq

```uci
config dhcp 'lan'
	option interface 'lan'
	option start '100'
	option limit '150'          # 192.168.10.100-249
	option leasetime '12h'
	option dhcpv4 'server'
	option dhcpv6 'disabled'
	option ra 'disabled'
	option ndp 'disabled'
```

`plant`/`wan` 段维持 `ignore=1` + 全禁用（E10/D3 的安全姿态不变）。dnsmasq 全局 `local '/lan/'`、`domain 'lan'` 保持。

### 6.3 防火墙

- 新增 `lan` zone：`network 'lan'`，`input ACCEPT`，`output ACCEPT`，`forward ACCEPT`（LAN 段即"接入/管理"段，等同上游默认家用路由器语义）。
- 新增 `forwarding lan→wan`（PC 可正常上网）。
- 删除 `mgmt` zone 及其专属规则（DHCP/DNS/SSH/HTTPS 对 mgmt 的放行由 `lan` 的 `input ACCEPT` 覆盖）。
- `plant` zone 维持 `input REJECT`/`forward REJECT`；`tr3000_lite_plant_luci` 规则默认 `enabled=0`，由操作员显式启用。
- `mgmt→plant` 的 ICMP/TCP 放行与 SNAT 规则改名并改源网段：`tr3000_lite_lan_plant_icmp` / `_tcp` / `_snat_icmp` / `_snat_tcp`，`src_ip 192.168.10.0/24`、`dest_ip` 跟随 plant CIDR、`snat_ip` = plant 地址。**注**：这组规则的目的是让"没有默认网关的 PLC/HMI 能回程"，源网段变化不影响该语义。
- `wan` zone 与 `wan` 管理面关闭策略不变。

### 6.4 WiFi：mt_wifi 兼容（第二个根因）

**职责重新划分**

| 组件 | 职责 |
|---|---|
| `overlays/.../etc/uci-defaults/91-tr3000-lite-management-ap`（改造） | 首启生成 SSID/key、禁用开放默认 AP、创建受管 AP、提交 |
| `scripts/tr3000-lite-wifi.sh`（新增） | 幂等校验/修复：受管 AP 缺失、开放 AP 复活、radio 被关 → 修复 + `/sbin/wifi reload`；验证通过后写 marker |
| `overlays/.../etc/init.d/tr3000-lite-wifi`（新增） | procd 服务，`START=20`（`/etc/init.d/boot` 之后），调用上述脚本 |

**改造要点（相对现有实现）**

1. 去掉"必须有 mac80211 语义"的假设：
   - 保留对命名 radio 段（`radio0/radio1`，mt_wifi 形态）与匿名 `@wifi-device[*]`（mac80211 形态）的**双路兼容**，但以命名段为主路径；
   - **不再使用 `uci -d '<delim>' get` 解析设备列表**（该用法在 uci 上行为不稳），改为解析 `uci show wireless` 输出，兼容标量 `device` 与列表 `device` 两种写法。
2. 受管 AP 规格：`device=<radio>`、`mode=ap`、`network=lan`、`encryption=psk2`、`disabled=0`、`ssid`/`key` 持久化复用（不轮换）。
   mt_wifi 的 `encryption=psk2` 对应 WPA2PSK/AES（`mtwifi_defs.lua:120`），key 为 8–63 个可打印 ASCII，32 位 hex 合法。
   `mt_wifi` 读取 `key`（不是 `password`），字段名不得沿用 hostapd 的 `password` 习惯。
3. **SSID 后缀来源**：优先取无线设备自身 MAC（`ra*`/`mtwifi*` 的 sysfs `address`、或 mt_wifi radio 段的 `phy` 对应接口），**不得**回退到 eth0/eth1 的 MAC（避免把 WAN/LAN MAC 派生成 SSID 后缀）；两者都不可用时才用持久化的 `/etc/tr3000-lite/ap-suffix` 随机值。
4. **禁用 mt_wifi 默认开放 AP**：识别 `encryption` 为空/`none`/`open` 且 `mode=ap`、且不是本模块受管段的 wifi-iface → 写 `disabled=1`（与既有脚本同逻辑，改为基于 `uci show` 解析）。
5. 首启时序：镜像内**不预置** `/etc/config/wireless`（保持"固件不含无线配置与凭据"），依赖启动序列 `kmodloader → /sbin/wifi config → uci_apply_defaults`（镜像 `etc/init.d/boot:49-57`）。若该时序未成立（`/etc/config/wireless` 不存在），脚本**失败退出但保留自身**（uci-defaults 仅在成功时删除），由 init.d 服务在稍后重试。
6. init.d 服务的修复动作结束后调用 `/sbin/wifi reload`（镜像 `sbin/wifi` 的 `wifi_reload` → `ubus call network reload` + 逐设备 disable/enable）以让 mt_wifi 重建 vif；随后用 `ubus call network.wireless status` 校验 radio/AP 状态，校验通过才写 `/etc/tr3000-lite/management-ap.initialized`（0600）。
7. init.d 服务每次运行都复核 `/etc/config/wireless` 权限为 0600（mt_wifi 的 `uci commit` 可能重写文件），并复核 radio `disabled=0`。
8. 保留既有安全纪律：路径非符号链接检查、锁、临时目录、`umask 077`、`/etc/config/wireless` 权限 0600、日志与输出不含 SSID/key。

### 6.5 plant 模式切换事务

复用现有 `scripts/tr3000-lite-plant.sh` 的候选目录 + UCI delta + `fw4 check` + 备份对 + 安装 + 核验 + 回滚框架，新增两个命令：

| 命令 | 语义 |
|---|---|
| `status --json` | 增加 `mode`（`lan`\|`plant`）、`lan_cidr`、`lan_dhcp_pool`、`plant_active`、`plant_device`、`ap_ready` 字段 |
| `validate --address IPV4/PREFIX` | 保持现有语义；管理网段重叠检查由 192.168.77.0/24 改为 192.168.10.0/24 |
| `apply --address … --allow-luci … --allow-lan …` | 保持：仅在 plant 模式下修改 plant 地址与放行策略。`--allow-mgmt` 保留为**兼容别名**（等价 `--allow-lan`），并在文档标注废弃 |
| `enable-plant --address IPV4/PREFIX [--force-local-console]` | **新**：eth1 从 `br-lan` 摘出 → plant 接管 eth1 并取该地址；写回防火墙 lan→plant 规则；AP 未就绪时要求 `--force-local-console` |
| `disable-plant` | **新**：plant 释放 eth1（`proto none`），eth1 回到 `br-lan` 成员，plant 地址清空 |
| `restore --backup-id ID` | 保持：恢复 network/firewall 备份对，仍受当前门禁约束 |

事务细节：

- 备份对扩展为 **network + firewall**（与现状一致）；`enable-plant`/`disable-plant` 同样先备份再改。
- 候选渲染新增：桥接成员的增删、`network.plant.device`/`proto`/`ipaddr`/`netmask`。
  **UCI 语义要点**：清空列表不能用 `option ports ''`（那是空字符串而非空列表），必须先 `delete network.br_lan.ports` 再按需 `add_list`；重新加入 eth1 时同理先 delete 再 add_list，避免出现重复成员。
- `verify_live` 增加模式断言：`lan` 接口存在且地址为 192.168.10.1/24；plant 模式下 eth1 属于 plant 而不属于 br-lan；非 plant 模式下 eth1 属于 br-lan 且 plant 无地址。
- 失败路径与现有实现一致：尽力恢复两个文件并上报 `rollback` 状态；**不允许**出现"切换成功但管理路径不可达"——`enable-plant` 前置校验 AP 就绪或要求强制参数。

### 6.6 LuCI

`packages/luci-app-tr3000-lite` 的「工业 LAN」页增加：

- 顶部显示当前模式（接入模式 / 工业模式）、`lan` 地址、AP 就绪状态；
- 接入模式下显示主按钮「启用 plant 模式（把 LAN 口交给工业网）」，带风险说明（有线将失去 DHCP/管理、切回需经 WiFi 或本地控制台）；
- 工业模式下保留既有地址/掩码校验与「应用 / 恢复」，并提供「退回接入模式」；
- 远程访问页、上行状态页中出现的 `mgmt` 字样改为 `lan`（`uplinks.js` 等）。

ACL 与菜单结构不变（仍是 admin-only、固定控制器调用）。

### 6.7 产物证据与构建校验

`scripts/build-lite.sh` 生成的 `lite-runtime-contract.txt` 字段调整：

```
schema_version=2
lan_interface=lan
lan_device=br-lan
lan_cidr=192.168.10.1/24
lan_dhcp_pool=192.168.10.100-192.168.10.249
plant_interface=plant
plant_device=eth1
plant_default_mode=inactive
plant_cidr=192.168.20.254/24
plant_dhcpv4_dhcpv6_ra_ndp=off
lan_to_plant_protocols=icmp-echo,tcp
lan_to_plant_snat=plant-address
lan_plant_bridged=0
wireless_stack=mt_wifi
management_ap_network=lan
management_ap_encryption=psk2
management_ap_default_open_ap=disabled
plant_https_gate=root-password-and-explicit-enable
...
```

移除 `mgmt_*` 字段；`schema_version` 递增（消费者需同步）。构建脚本另加断言：最终 overlay 的 `/etc/config/network` 含 `lan` 段且 `plant` 默认不绑定 `eth1`；`/etc/config/dhcp` 含 `config dhcp 'lan'`；overlay **不含** `/etc/config/wireless`。

### 6.8 测试策略

**静态契约测试（CI 可跑）** — 新增/改造 `tests/`：

1. `tests/structure/test_repository_contract.py`：
   - Lite overlay 的 network/dhcp/firewall 满足默认可达不变量（`lan` 段、`br-lan` 含 eth1、DHCP 池、ICMP 可达、`plant` 默认不绑定 eth1）；
   - overlay 不含 `/etc/config/wireless`（固件不含凭据）；
   - 无线脚本不依赖 mac80211 专属行为（不得出现 `uci -d` 列表解析、必须显式禁用开放 AP、必须绑定 `lan`）。
2. `tests/scripts/test_tr3000_lite_wifi.py`：按 mt_wifi 配置形态（命名 radio 段 + `default_radioX` 开放 AP）重写用例，覆盖：开放 AP 被禁用、受管 AP 绑定 `lan` 且 `psk2`、重复执行幂等、缺 `/etc/config/wireless` 时失败且保留脚本、key 不落日志。
3. `tests/scripts/test_tr3000_lite_plant.py`：新增模式切换用例——`enable-plant` 后 eth1 属于 plant、br-lan 不含 eth1；`disable-plant` 反向；备份/回滚；AP 未就绪且无 `--force-local-console` 时拒绝。
4. `tests/scripts/test_lite_build_evidence.py`：断言 `lite-runtime-contract.txt` 新字段与 overlay 实际内容一致。

**真机验收清单**（`docs/TEST-PLAN.md` 增补，非 CI）：

| # | 用例 | 期望 |
|---|---|---|
| T1 | 全新刷机（不保留配置）上电，插网线 | PC 获得 192.168.10.x，网关 192.168.10.1 |
| T2 | `ping 192.168.10.1` | 通 |
| T3 | 浏览器 `https://192.168.10.1` | 进 LuCI，可设置 root 密码 |
| T4 | 连管理 WiFi | 拿到 192.168.10.x，可 ping，可进 LuCI |
| T5 | 扫描周围热点 | 看不到 `ImmortalWrt-2.4G/5G` 开放热点；只有 `TR3000-Lite-XXXXXX` 且为 WPA2 |
| T6 | `logread \| grep -i mtwifi` | 无 `wait_for network.interface.lan` 超时错误 |
| T7 | LuCI 切「启用 plant 模式」 | 成功；插线 PC 不再获得地址；WiFi 管理仍可达；plant 地址 192.168.20.254 无 DHCP、ping 不通 |
| T8 | LuCI 切「退回接入模式」 | 成功；插线重新获得 192.168.10.x |
| T9 | 断电重启（保留配置） | 模式与地址保持；AP 仍受管且加密 |
| T10 | 用**旧版 Lite 固件的配置**升级本固件（保留设置） | 启动日志出现"旧版配置结构"提示；LuCI「工业 LAN」页顶部红色提示；不自动改写配置 |

### 6.9 文档更新

- `docs/LITE-README.md`：网络默认值、首次部署流程（改为"插线即用"）、plant 模式说明、无线栈说明（mt_wifi）、真机验证清单更新。
- `docs/TEST-PLAN.md`：新增 §6.8 的 T1–T10。
- `docs/TR3000-LITE-PROVISIONING.md`、`docs/TR3000-LITE-REMOTE-ACCESS.md`：`mgmt`/192.168.77 → `lan`/192.168.10，管理路径描述改为"有线接入或管理 WiFi"。
- `docs/WIREGUARD-VPS-ROUTING.md`、`docs/SINGBOX-SPLIT-ROUTING.md`：涉及管理段的描述同步。
- 新增 `docs/TR3000-LITE-LAN-ACCESS.md`：出厂接入与工业模式切换的操作手册（替代散落在 README 的段落）。
- 旧设计文档 `2026-11-14-tr3000-lite-industrial-lan-management-design.md` 标注为"已被本设计取代（管理段与 WiFi 栈部分）"，保留历史。

## 7. 兼容与升级路径

**决策：现场一律重刷（不保留配置），本次不实现配置迁移脚本。**

- 刷机方式：首次安装，或 `sysupgrade -n`（不保留设置），让设备回到出厂默认结构。
- 风险控制：不做迁移意味着**保留配置升级会得到一台"半旧半新"的设备**（旧 `network/dhcp/firewall` 仍在，`lan` 不存在，行为与当前故障完全一致）。因此固件必须能**识别并明确告知**，而不是默默地坏掉：
  - 启动时检查 `network.lan` 是否存在、`network.plant` 是否仍绑定 `eth1`、是否存在 `network.mgmt`；任一命中即判定为"旧版配置结构"；
  - 命中时：写一条明确系统日志（`logread` 可见），并在 LuCI「工业 LAN」页顶部显示红色提示"检测到旧版配置结构，请用不保留配置的方式重新刷机（sysupgrade -n）"；
  - **不自动改写配置**——半吊子迁移会把设备留在更难排查的状态；
  - 退出码与状态字段需能被 `tr3000-lite-plant status --json` 读出（`legacy_config_detected=1`）。
- 文档：`docs/LITE-README.md`、新增的 `docs/TR3000-LITE-LAN-ACCESS.md`、`docs/cudy-tr3000-uboot-flashing-record.md` 均写明"升级本固件必须不保留配置刷机"，并给出 `sysupgrade -n` 命令。

**源码中 192.168.77.0/24 → 192.168.10.0/24 的改动点**（全仓 24 处引用；这是代码常量替换，不是运行时配置迁移）：

| 位置 | 现状 | 目标 |
|---|---|---|
| `scripts/tr3000-lite-plant.sh:133` | 管理网段重叠检查用 192.168.77.0/24 | 改为 192.168.10.0/24 |
| `scripts/tr3000-lite-remote.sh:110` | 拒绝 Peer 源落在 192.168.77.0/24 | 改为 192.168.10.0/24 |
| `scripts/build-lite.sh:209-210` | 契约 `mgmt_cidr`/`mgmt_dhcp_pool` | 改为 `lan_cidr`/`lan_dhcp_pool`（§6.7） |
| `overlays/.../etc/config/{network,dhcp,firewall}` | `mgmt` 段与 `tr3000_lite_mgmt_plant_*` 规则 | 按 §6.1/§6.3 重写 |
| `packages/luci-app-tr3000-lite/.../industrial-lan.js`、`uplinks.js` | 展示 mgmt 地址 | 展示 lan 地址 |
| `tests/scripts/test_{scripts,tr3000_lite_plant}.py`、`tests/structure/*` | 断言 mgmt 契约 | 断言 lan 契约 |
| `docs/{LITE-README,TEST-PLAN,TR3000-LITE-PROVISIONING,TR3000-LITE-REMOTE-ACCESS,WIREGUARD-VPS-ROUTING,SINGBOX-SPLIT-ROUTING}.md` | 描述 192.168.77 管理网 | 改为 192.168.10 接入网 |

## 8. 未验证项（UNRESOLVED）

| 项 | 状态 | 说明 |
|---|---|---|
| mt_wifi 受管 AP 是否真能在 `network=lan` 下正常起 AP 并发 DHCP | UNRESOLVED（需真机） | mt_wifi 支持 `encryption=psk2`（`mtwifi_defs.lua:120`），但 `mtwifi_cfg` 对自定义 vif 的行为未验证 |
| `mt_wifi` 是否在 `network=lan` 之外还需要其它前置（如 `phy`/`dbdc_main`） | UNRESOLVED | 需真机 `logread` |
| eth1 从 `br-lan` 摘出后 br-lan 是否仍能承载 WiFi AP 并保持 192.168.10.1 | UNRESOLVED | 需真机 |
| `fw4 check` 对"lan zone ACCEPT + plant zone REJECT + lan→plant SNAT"的组合是否通过 | UNRESOLVED（可用 CI 内的 native nft 测试近似） | 已有 `tests/scripts/native_remote_nft.py` 可扩展 |
| mt_wifi 驱动 `wait_for network.interface.lan` 的 120s 超时是否在新结构下消失 | UNRESOLVED | 预期消失（`lan` 存在），需真机确认 |
| 真机端口角色（eth0=2.5G WAN / eth1=1G LAN） | 沿用既有未验证项 | DTS 已确认，物理插孔仍需现场核对 |
| `plant` 默认地址由 `192.168.10.254` 改为 `192.168.20.254` | 已定，需现场同步 | 旧文档/现场笔记中的 `192.168.10.254` 需一并更新；`plant` 地址可改，冲突时可手动选段 |

## 9. 风险与回退

| 风险 | 影响 | 缓解 |
|---|---|---|
| 受管 AP 在 mt_wifi 上起不来 | 无线不可用 | 有线接入路径独立可用（G1 的一半由网线保证）；init.d 服务持续重试并在 LuCI 显示"AP 未就绪" |
| 切到工业模式后无法回到接入模式 | 现场失联 | 切换前强制校验 AP 就绪或要求 `--force-local-console`；`restore --backup-id` 可回滚；备份保留 5 对 |
| 迁移脚本错误导致升级后失联 | 现场批量失联 | 本次不做迁移；改为强制"不保留配置刷机"+ 启动检测旧结构并明确提示（§7） |
| 开放默认 AP 未被禁用 | 开放热点泄露 | 首启脚本 + init.d 服务双层禁用；CI 契约测试锁死；真机 T5 验收 |
| `lan` 段 192.168.10.0/24 与现场已有网段冲突 | 路由异常 | 默认态可切回/改址（既有 plant 地址事务机制可复用为"lan 地址事务"，本期不做，记为后续项） |
| `lan` 接口被上游 `12_network-generate-ula` 自动加上 ULA IPv6 | 路由器多一个 IPv6 地址（客户端仍不发 IPv6，因 RA 已禁用） | 保留上游默认行为；如需完全关闭，另加 `option ip6assign ''`，本期不做 |

## 10. 范围外但需记录的后续项

- `lan` 地址段可配置（当前固定 192.168.10.1/24）——现场网段冲突时的补救手段；
- 真机冒烟测试自动化（需要设备农场或 QEMU + mt_wifi 模拟，暂不具备）；
- `mgmt` 段的"第二管理网段"能力（当前已合并进 `lan`）。
