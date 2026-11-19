# TR3000 Full 家用路由器改造设计（去工业段 / 科学上网 / 内网穿透）

- 日期：2026-11-19
- 目标：Cudy TR3000 v1（MT7981，128 MiB NAND，U-Boot Mod，112 MiB UBI）Full 固件
- 基线分支：`feature/tr3000-full-factory-access` @ `55f42c4`
- 状态：**待审批**。批准前不实现任何固件行为变更。

## 1. 背景与意图

Full 原本定位是"工业现场远程维护网关"：设备接入工业交换机，用 WireGuard 做工程师到 PLC/HMI 的精准 SNAT，用 Cloudflare Tunnel 暴露 HMI/NAS。

用户的新定位是**自用家用路由器**：

- **放弃工业属性**：不再有 plant 段、不再有 mgmt 段、不再有 PLC/HMI 精准 SNAT 授权模型。
- **科学上网**：集成 sing-box，支持 VLESS + WS + TLS、智能分流、直连与全局代理模式。
- **内网穿透**：集成 WireGuard、Cloudflare Tunnel（Argo），Tailscale 可选。
- **DDNS**：集成 LuCI DDNS，优先支持 Cloudflare。
- **主题**：Argon 默认，Bootstrap 备用。
- **网络接入**：WAN、Wi-Fi 中继、USB 手机共享，及三者之间的故障切换。

Full 因此从"工业网关"变为"家里的一台路由器"，但**固件基础不变**：ImmortalWrt MT798x 6.6、112 MiB U-Boot Mod 分区、DHCP U-Boot 网页恢复。

## 2. 已核实的事实（不是推测）

| # | 事实 | 依据 |
|---|---|---|
| E1 | Full 从未成功构建过一次：Actions 里 `build-full.yml` 运行次数为 **0** | `gh run list --workflow=build-full.yml` 返回 `[]` |
| E2 | Full 当前**出厂不可达**：`files/etc/config/network` 里没有 `lan`；eth1 被 `plant` 以 `proto none` 占住；`br-mgmt` 是没有端口的空桥，`mgmt`（192.168.77.1）无实体接口；镜像内也没有 `/etc/config/wireless` | 仓库 `files/etc/config/{network,dhcp,firewall}` |
| E3 | Full 与 Lite 用**同一份**上游基线 `config/128muboot.config`（`weekdaycare/immortalwrt-mt7981-cudy-tr3000` @ `cc777df`，源码 `padavanonly/immortalwrt-mt798x-6.6` @ `ec9ef10`） | `scripts/build-full.sh`、`scripts/build-lite.sh` |
| E4 | 该基线的无线栈是 **mt_wifi**（`kmod-mt_wifi`、`mtwifi-cfg`、`luci-app-mtwifi-cfg`），**没有** mac80211 / mt76 / mt7915e | `config/128muboot.config` 第 6300/6570/6727/6742 行等 |
| E4a | `luci-app-mtwifi-cfg` 与 `mtwifi-cfg` 位于**固定源码树** `package/mtk/applications/`，不在 luci/packages feed 里 —— 它们随源码树提供，不需要额外 feed | 源码树 `package/mtk/applications/luci-app-mtwifi-cfg`、`package/mtk/applications/mtwifi-cfg` |
| E5 | 上游基线已含 `kmod-nft-tproxy=y`、`dnsmasq-full`（含 `dnsmasq_full_nftset`）、`kmod-tun=y`、`ip-full=y`、`jsonfilter=y`、`wpad-openssl=y`、`luci-theme-bootstrap=y`、`luci-theme-aurora=y` | 同上 |
| E6 | 固定 feed 里有 `luci-app-homeproxy`（含 `po/zh_Hans`）、`luci-app-ddns`、`luci-app-cloudflared`、`luci-app-argon-config`、`luci-theme-argon`（2.4.3，依赖 `wget`+`jsonfilter`） | `immortalwrt/luci` @ `cc142cd` |
| E7 | 固定 feed 里有 `sing-box` 1.12.25（full 变体）、`cloudflared` 2025.5.0、`tailscale`、`ddns-scripts` 2.8.2（含 `ddns-scripts-cloudflare` 与 `cloudflare.com-v4` provider） | `immortalwrt/packages` @ `171d5f9` |
| E8 | `luci-app-homeproxy` 依赖 `+sing-box +firewall4 +kmod-nft-tproxy +ucode-mod-digest`；`ucode-mod-digest` 在基线里是 `not set`，但模块源码存在于固定源码树 `package/utils/ucode`（`UcodeModule(digest, ...)`） | `luci-app-homeproxy/Makefile`；源码树 `package/utils/ucode/Makefile` |
| E9 | homeproxy 的路由模式恰好覆盖需求：`gfwlist` / `bypass_mainland_china`（智能分流）/ `proxy_mainland_china` / `custom` / `global`（全局）；节点类型含 `vless` + `ws` transport + `tls`，另有 `direct` 节点类型（直连） | `homeproxy/client.js`、`homeproxy/node.js` |
| E10 | homeproxy 客户端模式走 `redirect`/`redirect_tproxy`/`tun`，自带 dnsmasq 分流与 `nftset` GFW 表；`/etc/init.d/homeproxy` 用 procd，配置文件在 `/etc/config/homeproxy` | `homeproxy/init.d/homeproxy`、`generate_client.uc` |
| E11 | 上游 DHCP U-Boot 已开启 `CONFIG_MTK_WEB_FAILSAFE=y` 与 `CONFIG_MTK_WEB_FAILSAFE_AFTER_BOOT_FAILURE=y`（网页恢复），且 `TR3000 DHCP U-Boot` 工作流已成功构建过一次（run `43368155899`） | `bl-mt798x-dhcpd` @ `f6b361e` 的 `mt7981_cudy_tr3000-v1_defconfig`；`gh run list --workflow=build-uboot.yml` |
| E12 | sing-box full 变体 arm64 二进制 **stripped 后 39.9 MiB**；cloudflared arm64 二进制 34.8 MiB；镜像门禁是 100 MiB（`verify-image.sh` 的 `MAX_BYTES=104857600`），UBI 只有 112 MiB | 实测下载上游 release 产物 + `scripts/verify-image.sh` |
| E13 | Lite 分支已有一整套**经过 CI 验证**的家用路由器底座：接入段（`lan` = br-lan，192.168.10.1/24）、mt_wifi 受管 WPA2 AP（禁用开放默认 AP）、三上行故障切换（wan/wwan/usbwan，metric 10/20/30）、USB RNDIS/CDC 热插拔、WireGuard + Cloudflare DDNS 授权 | `overlays/devices/tr3000-lite/`、`scripts/tr3000-lite-*.sh`、CI run `44449317194` |
| E14 | Full 今天装的是**旧版** `scripts/lite-uplink-watch.sh`（202 行），Lite 装的是新版 `scripts/tr3000-lite-uplink-watch.sh`（296 行）+ lib/status/changed 三件套；两者的 USB 热插拔、WG 重启、上行状态能力不同 | `scripts/configure-full.sh:120` vs `scripts/configure-lite.sh:171-178` |
| E15 | `files/etc/config/{network,dhcp,firewall}` 与 `files/etc/{config,init.d}/lite-uplink-watch` 这五份**实际只服务 Full**（Lite overlay 全部覆盖同名文件）；只有 `files/etc/uci-defaults/90-lite-uplink-watch` 是真正共享 | 逐文件对比 `files/` 与 `overlays/devices/tr3000-lite/files/` 同名文件 |
| E16 | `files/etc/config/lite-uplink-watch` 与 `files/etc/init.d/lite-uplink-watch` 与 Lite overlay 里的同名文件**内容不同**（overlay 版多 `globals` 段与 `service_triggers`/`reload_service`） | `diff` 结果 |

## 3. 根因

Full 不是"功能不对"，是**出厂即不可达**（E2），并且整个科学上网/穿透故事都建立在 `plant` 这个工业前提上。改造的本质是两件事：

1. 把 Lite 已经证明可行的**家用路由器网络底座**（接入段 + 受管 AP + 多上行切换）搬到 Full；
2. 把 `plant` 相关的工业模型整个删掉，换成 sing-box + WireGuard + Cloudflare Tunnel 的家用模型。

## 4. 目标 / 非目标 / 反目标

### 目标

- G1 **出厂可达**：插网线或连 WiFi → 拿到 DHCP → ping 通 → 浏览器打开 LuCI。
- G2 **科学上网**：sing-box 支持 VLESS+WS+TLS；路由模式覆盖智能分流 / 直连 / 全局；LAN 客户端可走透明代理。
- G3 **内网穿透**：WireGuard、Cloudflare Tunnel（Argo）、Tailscale（可选）三者可用且默认关闭。
- G4 **DDNS**：LuCI DDNS 页面可用，Cloudflare provider 优先。
- G5 **主题**：Argon 为默认主题，Bootstrap 可随时切回。
- G6 **多接入与故障切换**：WAN / Wi-Fi 中继 / USB 手机共享，自动健康探测与切换。
- G7 **可防回归**：静态契约测试锁住"出厂可达 + 无 plant 段 + 代理/穿透默认关闭"三条不变量。
- G8 **不回归 Lite**：Lite 产物字节级行为不变。

### 非目标

- 不换无线栈（当前 target 无 mac80211/mt76/mt7915e，属 UNRESOLVED）。
- 不改硬件、U-Boot、分区布局、112 MiB UBI 假设。
- 不在本仓库实现真机自动化测试；真机项走 `docs/TEST-PLAN.md`。
- 不替换上游 sing-box / homeproxy / ddns-scripts / cloudflared / tailscale 的实现。
- 不实现 VPS 中继、frp、自建 DDNS 服务端。

### 反目标（即使技术上可行也不做）

- 不在工业段/管理段默认开 DHCP 之外的任何隐式行为。
- 不把 WireGuard 私钥、Cloudflare token、Tailscale auth key、sing-box 节点凭据、Wi-Fi 密钥写入固件、Artifact 或 CI 日志。
- 不在正式产物里塞"万能调试固件"；调试只进 `local/`。
- 不为了"能连上"而在 WAN 侧放开管理面。
- 不为了塞下更多包而放宽 100 MiB 镜像门禁。

## 5. 关键决策

| # | 决策 | 取舍与理由 |
|---|---|---|
| D1 | **Full 自建**：`overlays/devices/tr3000-full/` 承载 Full 专属 rootfs；需要复用的脚本按 `tr3000-full-*` 复制一份；Lite 完全不动 | 用户已选定。理由：Full 与 Lite 的网络模型已经分叉（Full 无 plant），共用一套 overlay 会让两个变体的差异互相污染；Lite 刚通过 CI（E13），不冒险改它。代价：约 1200 行 shell 需要"改名复制"同步，由 D2 的漂移守卫兜底 |
| D2 | **漂移守卫测试**：Full 的 `tr3000-full-*` 脚本必须与 Lite 对应脚本在"去 token 化"后逐字相等；不等即测试失败 | 复制粘贴的真正风险是日后 Lite 修了 mt_wifi 坑而 Full 没跟上。一个纯文本比对测试把"靠人记得同步"变成 CI 强制。**该守卫只适用于纯 token 改名的文件**（实测：`tr3000-lite-wifi.sh`、`91-tr3000-lite-management-ap`、`tr3000-lite-wifi` init.d 三者改名后归一化完全相等）。有语义差异的文件（见 D2a）不纳入守卫，改为逐条断言其差异点 |
| D3 | **科学上网用上游 `luci-app-homeproxy`**，不自己写 sing-box 配置界面 | homeproxy 的路由模式、节点类型、订阅、LAN 过滤、透明代理模式与需求逐条对应（E9/E10），且是上游维护、带中文、在固定 feed 里。自己写等于重造一个功能更差的 homeproxy。代价：引入 `ucode-mod-digest` 依赖（E8），需在 seed 里打开 |
| D4 | **sing-box 用 full 变体**（现有 seed 已是），先测体积再决定是否降级 | 需求只要 VLESS+WS+TLS+分流+直连+全局，tiny 变体可能够；但 homeproxy 依赖 `+sing-box`（tiny 靠 `PROVIDES` 满足，机制微妙）。先按 full 走并实测，撞体积再降级并单独立项 |
| D5 | **WireGuard 定位为"从外面进家里"**：路由侧跑 `wg` 接口，防火墙放行 `wg → lan` 转发与 `wg` 管理面入站 | 与"内网穿透"字面含义、以及 Cloudflare Tunnel / Tailscale 的方向一致（都是把家里的东西暴露给外面的自己）。不采用"路由器出站连 VPS 再回程"模型：那是科学上网的传输层，已由 sing-box 承担 |
| D6 | **Cloudflare Tunnel 与 Tailscale 保持构建期开关**：cloudflared 默认开（需求点名要），Tailscale 默认关（需求写"可选"） | E12 体积是硬约束，先把最刚性的能力放进默认产物；Tailscale 走 `include_tailscale` 开关按需开 |
| D7 | **Argon 默认靠主题自带 uci-default 实现**（首启把 `luci.main.mediaurlbase` 设为 `/luci-static/argon`），同时保留 Bootstrap 包 | 不改 `luci-base` 的 `/etc/config/luci`，避免与上游 conffile 打架；Bootstrap 在 LuCI 里可随时切回（"备用"）。依赖 `wget`+`jsonfilter` 已满足（E5/E6） |
| D8 | **DDNS 用上游 `luci-app-ddns` + `ddns-scripts` + `ddns-scripts-cloudflare`**，出厂预置一个 `cloudflare.com-v4` provider 模板（`enabled=0`、无凭据） | 三个包都在固定 feed 里（E7），Lite 已在用同一组。凭据只在首启后由管理员填，写入 root-only 文件 |
| D9 | **保留 Full 专属 LuCI 包**，但收窄为"状态 + 开关"页；代理/穿透/DDNS 的配置界面全部交给上游页面 | 上游页面已覆盖各自配置；Full 页只做一件事：一眼看清四个服务与当前上行的开/关状态，并提供统一的启停入口 |
| D10 | **删除** `plant-profile.sh`、`plant-access.sh` 的 Full 安装、`singbox-rollback.sh`、`files/etc/tr3000-full/examples/sing-box.json.example` | 前两个是 plant 专属；`singbox-rollback.sh` 清的是 `tr3000_full_singbox_*` 防火墙段，sing-box 改由 homeproxy 接管后该机制不复存在；sing-box 手工 JSON 由 homeproxy 的 `/etc/config/homeproxy` 取代 |
| D11 | **不动 `scripts/` 里 Lite 仍引用的脚本**，只停止 Full 安装它们 | `plant-profile.sh` / `plant-access.sh` 仍被 `configure-lite.sh` 安装（Lite 仍需），删掉会打破 Lite |
| D2a | **有语义差异的文件清单**（不纳入 D2 守卫，改为差异点断言） | 实测 Lite 脚本里有三处不能只改名：`uplink-lib.sh:49` 的 `for protected in plant mgmt`（Full 无 plant/mgmt，改为保护 `lan`）；`uplink-status.sh:110` 的 `ap:*' mgmt '*) network=mgmt`（Full 的 AP 绑 `lan`，改为 `lan`）；`uplink-watch.sh` 依赖的 `tr3000-lite-remote`（Full 无工业远程控制器，WG 重启改为直接 `ifdown/ifup wg`）。这三处必须在 Full 副本里按 Full 语义改写，不能机械改名 |
| D12 | **升级策略**：Full 从未发布过，不存在需要迁移的存量配置；出厂一律不保留配置刷机 | E1。旧 Full 产物从未存在，所以没有"旧版配置结构"要检测；文档写明首次部署用 `sysupgrade -n` |

## 6. 详细设计

### 6.1 目录与分层

```
overlays/devices/tr3000-full/files/etc/
├── config/
│   ├── network          # 家用路由网络：wan/wwan/usbwan/lan，无 plant、无 mgmt
│   ├── dhcp             # lan 的 DHCP 段
│   ├── firewall         # lan/wan/wg zone
│   ├── tr3000-full-uplink-watch   # 上行探测目标
│   └── tr3000-full      # Full 运行策略（服务默认关闭等）
├── init.d/
│   ├── tr3000-full-wifi
│   └── tr3000-full-uplink-watch
├── uci-defaults/
│   ├── 90-tr3000-full-uplink-watch
│   ├── 91-tr3000-full-management-ap
│   └── 95-tr3000-full-services
├── hotplug.d/
│   ├── iface/95-tr3000-full-uplink-reconcile
│   └── net/90-tr3000-full-usbwan
└── tr3000-full/examples/cloudflared.yml.example
```

`scripts/` 新增（均为 Lite 对应脚本的 token 改名副本，见 D2）：

```
scripts/tr3000-full-wifi.sh              ← scripts/tr3000-lite-wifi.sh（纯 token 改名）
scripts/tr3000-full-uplink-watch.sh       ← scripts/tr3000-lite-uplink-watch.sh（D2a 改写）
scripts/tr3000-full-uplink-lib.sh        ← scripts/tr3000-lite-uplink-lib.sh（D2a 改写）
scripts/tr3000-full-uplink-status.sh     ← scripts/tr3000-lite-uplink-status.sh（D2a 改写）
scripts/tr3000-full-uplink-changed.sh    ← scripts/tr3000-lite-uplink-changed.sh（D2a 改写）
scripts/tr3000-full-usbwan-lib.sh        ← scripts/tr3000-lite-usbwan-lib.sh
```

**共享层 `files/` 的清理**（只动 Full 专属内容，不改 Lite 行为）：

实测（E15/E16）：`files/` 里下列文件**实际只服务 Full**，因为 Lite overlay 全部覆盖了同名文件：

| 现在在 `files/` | 去向 | 理由 |
|---|---|---|
| `etc/config/network`、`dhcp`、`firewall` | → `overlays/devices/tr3000-full/files/etc/config/` | Lite overlay 全部覆盖同名文件，故这三份只服务 Full；按仓库"设备专属改动放设备目录"的规则归位 |
| `etc/init.d/lite-uplink-watch`、`etc/config/lite-uplink-watch` | → Full overlay 的 `tr3000-full-uplink-watch` 同名新文件 | Lite overlay 已有**内容不同**的同名文件（E16），故 shared 版只服务 Full；名字带 lite 会误导 |
| `etc/uci-defaults/90-lite-uplink-watch` | **保留在 `files/`**（Lite 用），Full overlay 放 `90-tr3000-full-uplink-watch` | Lite overlay **没有**这份，是真共享。Full 侧由 `configure-full.sh` 删掉 shared 版并安装自己的 |
| `etc/uci-defaults/95-tr3000-full-services` | → Full overlay | Full 专属 |
| `etc/tr3000-full/examples/sing-box.json.example` | 删除 | 被 homeproxy 的 `/etc/config/homeproxy` 取代（D10） |
| `etc/tr3000-full/examples/cloudflared.yml.example` | → Full overlay | Full 专属，保留为无凭据参考 |
| `etc/config/ubihealthd` | 留在 `files/` | 真共享 |

**关键：Full 的上行控制器要从旧版升到新版**（E14）。Full 今天装的是 202 行的旧 `lite-uplink-watch.sh`，缺 USB 热插拔重扫、WG 重启、上行状态 JSON；Lite 用的 296 行新版才有。因此 Full 侧不是"改名旧版"，而是**改名 Lite 新版三件套**（`tr3000-lite-uplink-watch.sh` + `tr3000-lite-uplink-lib.sh` + `tr3000-lite-uplink-status.sh` + `tr3000-lite-uplink-changed.sh` + `tr3000-lite-usbwan-lib.sh`），并按 D2a 改写三处语义。

`configure-full.sh` 装配顺序：`files/` → Full overlay → 删除 Full 不需要的 `90-lite-uplink-watch`、`etc/init.d/lite-uplink-watch`、`etc/config/lite-uplink-watch`、`files/usr/sbin/lite-uplink-watch`。`configure-lite.sh` **完全不改**（Lite 仍从 `files/` + Lite overlay 取料）。

### 6.2 网络（Full 专属 overlay）

```uci
config interface 'wan'
	option device 'eth0'
	option proto 'dhcp'
	option metric '10'

config interface 'wwan'          # Wi-Fi 中继（STA，用户在 LuCI 里加）
	option proto 'dhcp'
	option metric '20'
	option auto '0'

config interface 'usbwan'        # USB 手机共享
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
```

- **没有 `plant`，没有 `mgmt`**。eth1 归 `lan`（唯一 LAN 口）。
- 选 `192.168.10.0/24` 而非上游默认 `192.168.1.0/24`：后者与大量家用/办公网段撞段（E9 之外的理由同 Lite D1），且与 Lite 变体保持一致，方便同一台设备换固件。
- `lan` 段 DHCP：`start 100`、`limit 150`（192.168.10.100–249）、`dhcpv4 server`、`dhcpv6/ra/ndp disabled`；`wan`/`wwan`/`usbwan` 一律 `ignore 1`。
- 防火墙：`lan` zone（input/forward ACCEPT）、`wan` zone（input REJECT、masq）、`wg` zone（见 D5）、forwarding `lan → wan`；**删除** plant zone、mgmt zone、以及全部 `tr3000_lite_*` SNAT/ICMP/TCP 规则。

### 6.3 无线：mt_wifi 受管 WPA2 AP

Full 与 Lite 同栈（E4），因此 Lite 已经踩过的坑 Full 必须继承解法：

- 镜像内**不含** `/etc/config/wireless`（凭据不入库、不入镜像）。
- `91-tr3000-full-management-ap`（uci-defaults）首启时：识别命名 radio 段 → 建/复用一个受管 AP（`device=<radio>`、`mode=ap`、`network=lan`、`encryption=psk2`、SSID `TR3000-Full-<MAC 后 6 位大写十六进制>`、32 位随机 hex key）→ **禁用 mt_wifi 自带的开放默认 AP** → 写 `/etc/tr3000-full/management-ap.initialized`（0600）。
- `tr3000-full-wifi`（init.d，START=20）每次开机幂等修复：AP 缺失 / 开放 AP 复活 / radio 被关 → 修复并 `/sbin/wifi reload`，校验通过才写就绪标记。
- **不触碰用户自建的 STA 接口**：用户在 LuCI 里加的、绑定到 `wwan` 的中继 STA 必须在 AP 修复后保持不变（这是 Lite 已有契约 `test_management_identity_survives_station_add_disconnect_and_removal` 的同款要求）。
- 纪律沿用 Lite：路径非符号链接、锁、临时目录、`umask 077`、`/etc/config/wireless` 权限 0600、日志与输出不含 SSID/key。

### 6.4 多上行与故障切换

Full 今天装的是**旧版** 202 行 `lite-uplink-watch.sh`（E14），缺 USB 热插拔重扫、WG 重启、上行状态 JSON。本设计把 Full 升到 Lite 的**新版**三件套（改名版），并按 D2a 改写三处语义：

| Lite 版语义点 | Full 改写 | 理由 |
|---|---|---|
| `uplink-lib.sh:49` `for protected in plant mgmt` | `for protected in lan` | Full 无 plant/mgmt；需要防的是 uplink 误选到接入段设备 |
| `uplink-status.sh:110` `ap:*' mgmt '*) network=mgmt` | `ap:*' lan '*) network=lan` | Full 的受管 AP 绑 `lan` |
| `uplink-changed.sh` 调 `tr3000-lite-remote sync` 并重启 `wg_direct`/`wg_vps` 两个角色 | 直接 `ifdown wg` / `ifup wg`（仅当 `network.wg.proto=wireguard` 且 `auto=1`） | Full 没有工业远程控制器，WireGuard 是单个标准 `wg` 接口（D5） |

其余机制（token 改名后逐字继承）：

- 三条上行 `wan` / `wwan` / `usbwan`，metric 10 / 20 / 30。
- 守护进程每 15 秒探测（默认 `1.1.1.1`、`9.9.9.9`）：连续 3 次失败判定不健康 → metric +1000 让位；连续 2 次恢复 → 回到原 metric。
- 切换时若默认出口变化且 `wg` 在跑，则重启 `wg`（连接会断，避免旧路径黑洞）。
- USB 手机共享：`90-tr3000-full-usbwan` 热插拔识别 RNDIS/CDC-ETHERNET，多候选时 fail-closed；掉线事件触发上行重扫（Lite 新版才有，Full 这次一并获得）。
- 上行状态 JSON（`tr3000-full-uplink-status --json`）供 Full LuCI 上行页使用。

### 6.4.1 Full 与 Lite 的上行差异对照

| 能力 | Full（今天） | Full（本次） | Lite |
|---|---|---|---|
| 三上行 metric 切换 | 有（旧版） | 有（新版） | 有（新版） |
| 健康探测阈值 3/2、间隔 15s | 有（旧版） | 有（新版） | 有 |
| USB 热插拔重扫 | **无** | 有 | 有 |
| 上行状态 JSON | **无** | 有 | 有 |
| 出口切换时重启 WG | **无** | 有（单个 `wg`） | 有（`wg_direct`/`wg_vps`） |

### 6.5 科学上网（sing-box）

- 包：`sing-box`（full 变体）、`luci-app-homeproxy`、`luci-i18n-homeproxy-zh-cn`、新增 `ucode-mod-digest`（E8）；`kmod-nft-tproxy`、`dnsmasq-full`、`ip-full`、`kmod-tun` 基线已满足。
- 配置入口：上游 LuCI `服务 → HomeProxy`（节点、订阅、路由模式、代理模式、LAN 过滤）。
- 模式映射（对照 E9）：
  - **智能分流** → `routing_mode=bypass_mainland_china`（或 `gfwlist`）；
  - **全局代理** → `routing_mode=global`；
  - **直连** → `routing_mode=custom` 且默认出口 `direct-out`，或直接选择 `direct` 节点。
- 节点类型 VLESS + WS + TLS 由上游节点页支持（D3）。
- 默认**不启动**：homeproxy 未配置节点时 `/etc/init.d/homeproxy` 自身返回失败，不产生半配置代理。
- 凭据只存在于首启后管理员写入的 `/etc/config/homeproxy`（及订阅缓存），不入仓库、不入 Artifact。

### 6.6 内网穿透

| 组件 | 形态 | 默认 | 说明 |
|---|---|---|---|
| WireGuard | 路由侧 `wg` 接口 + LuCI `luci-proto-wireguard` | 关闭（不自动建接口） | 防火墙：`wg` zone，`wg → lan` 转发 + `wg` 管理面入站（D5）。DDNS 主机名供对端定位 |
| Cloudflare Tunnel (Argo) | `cloudflared` 包 + `luci-app-cloudflared` | 关闭 | 出站隧道，把本机 Web 服务经 Cloudflare 暴露；token 写入 root-only 文件 |
| Tailscale | `tailscale` 包 | 关闭，且**编译期开关** `include_tailscale` 默认关（D6） | 作为免打洞的备用远程通道 |

三者都由 `tr3000-full-service`（改造自 `service-toggle.sh`）统一启停，Full 的 LuCI 页显示状态。

**WireGuard 防火墙细节**（出厂 overlay 预置，全部 `enabled 0`，管理员配好 `wg` 接口后手动启用或由文档指引启用）：

```uci
config zone
	option name 'wg'
	list network 'wg'
	option input 'REJECT'      # 默认拒绝，配合下面两条定向放行
	option output 'ACCEPT'
	option forward 'REJECT'

config forwarding
	option src 'wg'
	option dest 'lan'          # 穿透核心：外面的人进家里的 LAN

config rule 'tr3000_full_wg_mgmt'
	option name 'Allow-Full-wg-management'
	option enabled '0'
	option src 'wg'
	option proto 'tcp'
	option dest_port '22 443'
	option target 'ACCEPT'

config rule 'tr3000_full_wg_icmp'
	option name 'Allow-Full-wg-ping'
	option enabled '0'
	option src 'wg'
	option proto 'icmp'
	option icmp_type 'echo-request'
	option target 'ACCEPT'

# 既有的 wan 侧监听规则保留（默认关）：
config rule 'tr3000_full_wg_listener'
	option name 'Allow-WireGuard-listener-disabled-by-default'
	option enabled '0'
	option src 'wan'
	option proto 'udp'
	option dest_port '51820'
	option target 'ACCEPT'
```

没有监听放行，隧道握手根本到不了路由器；没有 `wg→lan` 转发，隧道通了也进不了家。三条默认全关，与"穿透默认关闭"的不变量一致；`lan` zone 的 `input ACCEPT` 不覆盖 `wg` zone，所以 wg 侧必须显式放行 22/443。`wg→wan` 不加转发：回家的人不该借家里的出口上网（要上网用科学上网那条路）。

**sing-box 自身服务的处置**：`sing-box` 包自带 `/etc/init.d/sing-box`（上游 `files/sing-box.init`）。Full 的代理入口是 homeproxy（它生成自己的配置并直接用 `/usr/bin/sing-box` 二进制），所以 `95-tr3000-full-services` 必须同时禁用 `sing-box` 本体服务与 `homeproxy`，避免两套 sing-box 实例抢端口/抢 nft 表。

### 6.7 DDNS

- 包：`luci-app-ddns`、`ddns-scripts`、`ddns-scripts-cloudflare`。
- 出厂 `/etc/config/ddns` 预置一个 `service_name 'cloudflare.com-v4'`、`enabled 0`、域名/凭据留空的模板（**Cloudflare 优先**：模板就是 Cloudflare provider）。
- **凭据形式**（已核实 `update_cloudflare_com_v4.sh`）：`username` + `password` 两栏有两种填法——
  - `username` = 邮箱、`password` = Cloudflare **Global API Key**（走 `X-Auth-Email` + `X-Auth-Key` 头）；
  - `username` = 字面量 `Bearer`、`password` = **Scoped API Token**（走 `Authorization: Bearer` 头）。
  文档推荐后者（Token 可限定 zone 权限，比 Global API Key 权限小），两种都在文档里写清。
- 域名格式为 `hostname@yourdomain.tld`（脚本按 `@` 拆分主机与域）；脚本可读 `zone_id` 避免额外查询。
- 管理员在 LuCI `服务 → DDNS` 填 zone / token / 域名后启用；脚本需要 `curl`（基线已含）。
- 不把 token 写入仓库、固件、Artifact 或 CI 日志。

### 6.8 主题

- 包：`luci-theme-argon`、`luci-app-argon-config`、`luci-i18n-argon-config-zh-cn`；保留 `luci-theme-bootstrap`；继续排除 `luci-theme-aurora` / `luci-app-aurora-config`。
- Argon 默认：主题自带 `30_luci-theme-argon` uci-default 在首启设置 `luci.main.mediaurlbase=/luci-static/argon`（D7）。
- 备份：Bootstrap 包保留，LuCI `系统 → 语言和风格` 可切回。

### 6.9 LuCI

`packages/luci-app-tr3000-full` 保留（admin-only ACL，固定控制器 `/usr/sbin/tr3000-full-service`，不接受任意命令路径）：

- **服务页**（`services.js`）：wireguard / tailscale / cloudflared / homeproxy 四项的安装状态、启用状态、运行状态 + 启停按钮。
- **上行页**（`uplinks.js`，Lite 同款改名）：wan / wwan / usbwan 三条上行的当前设备、网关、metric、健康状态、切换事件。

代理节点、DDNS、Cloudflare Tunnel、WireGuard 各自的配置界面全部走上游页面（D9）。

`tr3000-full-service` 相对现有 `service-toggle.sh` 的改动：把 `sing-box` 这一项换成 `homeproxy`（服务名是 `/etc/init.d/homeproxy`），其余（wireguard / tailscale / cloudflared）保持。

### 6.10 构建与门禁

`configs/full.seed` 变更：

```
+ CONFIG_PACKAGE_luci-app-homeproxy=y
+ CONFIG_PACKAGE_luci-i18n-homeproxy-zh-cn=y
+ CONFIG_PACKAGE_ucode-mod-digest=y
+ CONFIG_PACKAGE_luci-app-ddns=y
+ CONFIG_PACKAGE_ddns-scripts=y
+ CONFIG_PACKAGE_ddns-scripts-cloudflare=y
+ CONFIG_PACKAGE_luci-app-cloudflared=y
+ CONFIG_PACKAGE_luci-i18n-ddns-zh-cn=y
+ CONFIG_PACKAGE_luci-i18n-cloudflared-zh-cn=y
+ CONFIG_PACKAGE_luci-theme-argon=y
+ CONFIG_PACKAGE_luci-app-argon-config=y
+ CONFIG_PACKAGE_luci-i18n-argon-config-zh-cn=y
+ CONFIG_PACKAGE_wpad-openssl=y
```

保持不变：`sing-box=y`、`kmod-tun`、`kmod-nft-tproxy`（基线已含，seed 显式声明便于断言）、`luci-theme-bootstrap=y`、`luci-proto-wireguard`、`kmod-wireguard`、`wireguard-tools`；继续排除 `openclash` / `passwall` / `aurora` / `docker` / `adguardhome` / `ruby` 等。

**tailscale 从 seed 移除**：现 seed 硬编码 `CONFIG_PACKAGE_tailscale=y`，与 `include_tailscale` 开关矛盾（开关只能追加、不能取消 seed 的硬选）。改为 seed 写 `# CONFIG_PACKAGE_tailscale is not set`，由 `configure-full.sh` 的动态段按开关追加 `=y` 或 `is not set`（与 cloudflared 同机制）。i18n 包名按 `luci.mk` 的 `zh_Hans→zh-cn` 别名规则生成（已核实）。

`scripts/configure-full.sh` 变更：

- 安装 Full overlay（在 `files/` 之后），并删除 `90-lite-uplink-watch`；
- 安装 `tr3000-full-*` 脚本到 `/usr/sbin/`、`/usr/lib/tr3000-full/`；
- 不再安装 `plant-profile.sh`、`plant-access.sh`、`singbox-rollback.sh`；
- 必选包断言扩展到上表全部；
- 断言 `ucode-mod-digest` 与 `wpad-openssl` 唯一 provider；
- 断言最终 `.config` 里 `luci-theme-argon=y` 且 `luci-theme-aurora` 未选。

`scripts/build-full.sh` 变更（对齐 build-lite.sh 的证据风格）：

- 断言 Full overlay 渲染出的 `/etc/config/network` 含 `config interface 'lan'`、`option ipaddr '192.168.10.1'`、`config device 'br_lan'`、`list ports 'eth1'`，且**不含** `plant` / `mgmt`；
- 断言 `/etc/config/dhcp` 含 `config dhcp 'lan'`；
- 断言 overlay **不含** `/etc/config/wireless`；
- 断言镜像内 `homeproxy`、`wpad-openssl`、`luci-app-homeproxy`、`luci-theme-argon` 存在，`cloudflared`/`tailscale` 与构建开关一致；
- 新增 `full-runtime-contract.txt`（`schema_version=1`，记录出厂 lan/wwan/usbwan、代理与穿透默认关闭、DDNS provider 优先 Cloudflare、主题 Argon），措辞与 Lite 的 `lite-runtime-contract.txt` 一致，明确 `evidence_kind=expected-defaults-not-live-state`；
- 体积门禁沿用 `verify-image.sh` 的 100 MiB 上限，不放宽。

`.github/workflows/build-full.yml`：保留现有输入，`include_tailscale` 默认由 `true` 改为 `false`（D6），`include_cloudflared` 默认 `true`（E12 体积由 CI 实测裁决，超限则构建失败——失败是正确结果，不绕过门禁）。

### 6.11 测试策略

**静态契约测试（CI 可跑）**

1. `tests/structure/test_repository_contract.py`
   - Full overlay 的 network/dhcp/firewall 满足出厂可达不变量（`lan` 段、`br_lan` 含 eth1、DHCP 池、`lan→wan` 转发、**无** plant/mgmt/无 `tr3000_lite_*` 规则）；
   - WireGuard 三条规则（listener/mgmt/icmp）与 `wg→lan` 转发存在且全部默认关；无 `wg→wan` 转发；
   - `95-tr3000-full-services` 同时禁用 `sing-box` 本体与 `homeproxy`（既有断言扩展）；
   - Full overlay 与 `files/` 均**不含** `/etc/config/wireless`；
   - 旧 `files/etc/config/network` 里的 `plant` / `br-mgmt` / `192.168.77` 全部消失（跨目录 grep 断言）。
2. `tests/scripts/test_tr3000_full_wifi.py`：按 mt_wifi 形态（命名 radio 段 + `default_radioX` 开放 AP）覆盖：开放 AP 被禁用、受管 AP 绑定 `lan` 且 `psk2`、重复执行幂等、缺 `/etc/config/wireless` 时失败且保留脚本、key 不落日志、**用户自建 STA 绑定 `wwan` 后不被破坏**。
3. `tests/scripts/test_tr3000_full_uplink.py`：三上行 metric、健康阈值切换、默认出口变化时重启单个 `wg`、USB 多候选 fail-closed、USB 热插拔重扫触发；并断言 D2a 的三处 Full 语义差异确实存在（避免守卫漏掉）。
4. `tests/scripts/test_tr3000_full_drift.py`（D2 漂移守卫）：仅对**纯 token 改名的文件**（`tr3000-full-wifi.sh`、`91-tr3000-full-management-ap`、`tr3000-full-wifi` init.d）把 Full 侧 token 归一化回 lite 后，与 Lite 对应文件逐字比对；不等即失败。有语义差异的上行五件套**不纳入**此守卫，改为在 `test_tr3000_full_uplink.py` 里逐条断言 D2a 的三处差异点（`protected` 集合含 `lan`、AP 网络映射为 `lan`、WG 重启针对单个 `wg`）。
5. `tests/scripts/test_scripts.py`：Full 配置合并与开关用例（homeproxy/argon/ddns/cloudflared/tailscale 的选中与未选中、ccache 覆盖、非法布尔在写 `.config` 前失败、112 MiB DTS 强制、唯一 profile）。
6. `tests/scripts/test_lite_build_evidence.py` 类似的 `test_full_build_evidence.py`：断言 `full-runtime-contract.txt` 与 overlay 实际内容一致。
7. `tests/workflows/test_workflows.py`：`include_tailscale` 默认 false、`include_cloudflared` 默认 true 的输入类型与默认值断言。

**真机验收清单**（`docs/TEST-PLAN.md` 增补，非 CI）

| # | 用例 | 期望 |
|---|---|---|
| F1 | 全新刷机（不保留配置）上电，插网线 | PC 拿到 192.168.10.x，网关 192.168.10.1 |
| F2 | `ping 192.168.10.1` | 通 |
| F3 | 浏览器 `https://192.168.10.1` | 进 LuCI（Argon 主题），可设 root 密码 |
| F4 | 连管理 WiFi | 拿到 192.168.10.x，可 ping，可进 LuCI |
| F5 | 扫描周围热点 | 看不到开放默认热点；只有 `TR3000-Full-XXXXXX` 且为 WPA2 |
| F6 | HomeProxy 配好 VLESS+WS+TLS 节点，路由模式切"智能分流" | 国内直连、指定站点走代理；LAN 客户端同样生效 |
| F7 | 路由模式切"全局" | 全部流量走代理；切"直连"后全部直连 |
| F8 | `logread \| grep -i mtwifi` | 无 `wait_for network.interface.lan` 超时错误 |
| F9 | 拔掉 WAN 网线，Wi-Fi 中继接入 | 默认路由切到 wwan，WAN 恢复后切回 |
| F10 | USB 手机共享接入 | usbwan 起，默认路由切到 usbwan |
| F11 | LuCI 启停 WireGuard / Cloudflare Tunnel / homeproxy | 状态与实际进程一致 |
| F12 | LuCI DDNS 用 Cloudflare provider | 域名解析到当前公网 IP |
| F13 | Argon 主题下切 Bootstrap | 可切换成功，重启后保持 |
| F14 | 升级本固件（保留旧配置） | 明确提示旧结构并要求 `sysupgrade -n`（若需要，见 D12） |

### 6.12 文档更新

- `docs/FULL-README.md`：重写为家用路由器定位（网络结构、科学上网、穿透、DDNS、主题、多接入与切换、首次部署、升级边界）。
- `docs/HOMEPROXY-SPLIT-ROUTING.md`（新）：VLESS+WS+TLS 节点配置、路由模式（分流/直连/全局）、LAN 透明代理、订阅、DNS 与 nftset 说明。
- `docs/TUNNEL-ACCESS.md`（新）：WireGuard / Cloudflare Tunnel / Tailscale 的用途边界与各自配置路径、凭据写入方式与权限、默认关闭的原因。
- `docs/DDNS-CLOUDFLARE.md`（新）：LuCI DDNS + Cloudflare provider 配置步骤。
- `docs/TEST-PLAN.md`：增补 F1–F14。
- `docs/WIREGUARD-SNAT.md`、`docs/SINGBOX-SPLIT-ROUTING.md`、`docs/TAILSCALE.md`、`docs/CLOUDFLARED-ACCESS.md`：删除或改写为家用语义（旧的 plant 精准 SNAT 文档整份删除）。
- `configs/devices/TR3000/TR3000-Full-综合增强版-提示词.md`：标注"工业版规格，已被本设计取代（保留作历史）"。

## 7. 兼容与升级路径

- Full 从未发布（E1），**无存量配置需要迁移**。
- 首次部署与后续升级一律 `sysupgrade -n`（不保留配置），与 Lite 的清洁刷机策略一致。
- 若设备上已刷过本分支之前的 Full 试验固件，其 `/etc/config/network` 含 `plant`/`mgmt`，属旧结构：启动时检测到 `network.plant` 或 `network.mgmt` 存在即写一条明确 `logread` 提示，并在 Full LuCI 页顶部显示"检测到旧版配置结构，请用 `sysupgrade -n` 重刷"；**不自动改写配置**。

## 8. 未验证项（UNRESOLVED）

| 项 | 状态 | 说明 |
|---|---|---|
| Full 首次构建能否通过 | UNRESOLVED（从未构建过，E1） | 本设计的第一件事就是在 Actions 上跑通一次完整构建；门禁失败要修，不得放宽 |
| 最终镜像体积 | UNRESOLVED | sing-box 39.9 MiB + cloudflared 34.8 MiB 是大头（E12）。需实测；若超 100 MiB，按 D4 降级 sing-box 变体或把 cloudflared 改回默认关，并记录取舍 |
| homeproxy 与固定 sing-box 1.12.25 的实际行为 | UNRESOLVED | 需真机验证节点生成、订阅更新、路由模式切换、TProxy 生效 |
| mt_wifi 受管 AP 在 `network=lan` 下的真实行为 | UNRESOLVED | 沿用 Lite 的未验证项；Full 需独立复验 |
| Wi-Fi 中继（STA）与受管 AP 同 radio 并存 | UNRESOLVED | 需真机验证同时 AP+STA |
| `ucode-mod-digest` 能否在固定源码树里编译出包 | UNRESOLVED | 模块源码在树内（E8），但需 `make defconfig` 后确认包存在 |
| Argon 主题首启 uci-default 是否生效 | UNRESOLVED | 需真机确认 `mediaurlbase` 变为 argon |
| WireGuard `wg → lan` 转发与 DDNS 主机名组合 | UNRESOLVED | 需真机 + 外部对端验证 |
| 真机端口角色（eth0=2.5G WAN / eth1=1G LAN） | 沿用既有未验证项 | DTS 已确认，物理插孔仍需现场核对 |

## 9. 风险与回退

| 风险 | 影响 | 缓解 |
|---|---|---|
| 镜像超 100 MiB | 构建失败 | 实测优先；必要时降级 sing-box 变体或 cloudflared 改默认关（D4/D6）；不放宽门禁 |
| Full 首次构建暴露上游基线问题 | 无法出固件 | 逐项修复并在 `docs/TEST-PLAN.md` 记录；保留 Lite 不受影响 |
| homeproxy 与 sing-box 版本行为不一致 | 科学上网不工作 | 固定 feed SHA；真机验证后再放行文档结论 |
| 复制脚本日后与 Lite 漂移 | 两变体行为分叉 | D2 漂移守卫测试在 CI 强制 |
| 误把 Full 专属内容留在 `files/` | 污染 Lite 镜像 | 结构测试断言 Full 专属文件不在 `files/` |
| 凭据误入仓库/Artifact | 安全事故 | 契约测试禁止 `files/` 与 overlay 出现凭据；CI 日志不打印 SSID/key |
| `wwan` 中继与 `lan` 网段冲突 | 路由异常 | 段选择避开常见家用网段；管理员可改 |
| 上行切换导致 WireGuard 断连 | 短暂失联 | 切换时显式重启 `wg`（D5 附属行为） |

## 10. 范围外但需记录的后续项

- Full 与 Lite 后续是否收敛到共享 overlay（当前按 D1 分开）。
- `lan` 段地址可配置化（当前固定 192.168.10.1/24）。
- 真机冒烟自动化（需要设备农场）。
- sing-box 订阅的定时更新与失败回退策略。

## 11. 实施者裁量记录（非用户决定，可否掉）

以下是写作/审阅过程中由我定下的具体选择，列出供审批时核对：

1. **LAN 网段 192.168.10.1/24**（§6.2）：用户未指定；选与 Lite 一致且避开常见家用网段。
2. **cloudflared 默认编译开**（D6）：用户点名要 Argo；体积风险由 CI 100 MiB 门禁裁决，超限则降为默认关并回报，不放宽门禁。
3. **Tailscale 默认编译关**（D6）：用户写"可选"；理解为构建开关默认 false，需要时 Actions 里打开。
4. **WireGuard 方向定为入站穿透**（D5）：从需求"内网穿透"与 DDNS 的搭配推出；出站代理传输由 sing-box 承担，不另做 WG 出站模型。
5. **wg 侧管理面只放 22/443 + ICMP，不加 wg→wan 转发**（§6.6）：回家不等于借家里出口上网。
6. **DDNS 推荐 Scoped API Token（Bearer）而非 Global API Key**（§6.7）：权限更小；两种都支持并写进文档。
7. **sing-box 用 full 变体先实测**（D4）：需求面 tiny 可能够，但 homeproxy 的 `+sing-box` 依赖在 tiny 上靠 PROVIDES 机制满足，未经实测不先降级。
8. **旧版 Full 试验配置的检测只提示不迁移**（§7）：与 Lite 的清洁刷机策略一致；Full 无正式发布存量，检测仅为防御本分支早期试验件。

