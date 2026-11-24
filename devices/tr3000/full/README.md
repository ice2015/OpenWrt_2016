# TR3000 Full 家用路由器

本构建只适用于已核实的 **Cudy TR3000 v1、128 MiB NAND、MT7981、`cudy_tr3000-v1-ubootmod`、112 MiB UBI**。它不是原厂 128M、256M、122 MiB UBI、factory、recovery、BL2 或 FIP 镜像。构建成功不等于某一台设备已经满足刷写条件。

Full 的定位是**自用家用路由器**：出厂插线即可管理，家里设备走科学上网，外面能穿透回家。工业远程维护语义（独立工业网段、精准 SNAT 授权）已整体移除；需要工业能力的设备请使用 Lite 变体。

## 出厂网络

| 段 | 设备 | 地址 | 说明 |
| --- | --- | --- | --- |
| `lan`（接入/管理） | `br-lan` = eth1 + 管理 AP | `192.168.10.1/24` | DHCP 池 `192.168.10.100–192.168.10.249`；插线或连 WiFi 即拿到地址 |
| `wan` | eth0（2.5G） | DHCP | 主上行，metric 10 |
| `wwan` | Wi-Fi 中继（STA） | DHCP | 备用上行，metric 20，默认不自动启用 |
| `usbwan` | USB 手机共享 | DHCP | 备用上行，metric 30，默认不自动启用 |

- 首次接入：插网线 → PC 拿到 `192.168.10.x` → `ping 192.168.10.1` → 浏览器 `https://192.168.10.1` 设置非空 root 密码。
- 管理 WiFi：SSID `TR3000-Full-<无线 MAC 后 6 位大写十六进制>`，WPA2，每机随机密钥。密钥只存在设备本机 `0600` 的 `/etc/config/wireless`，**不在仓库、构建日志或 Artifact 中**；用有线登录后在 LuCI 无线页查看。
- 无线栈是 **mt_wifi**（与上游基线一致）。首启脚本与常驻服务会禁用驱动自带的开放默认热点，并维持每射频一个受管加密 AP；用户自建的中继 STA 不受影响。
- 三上行自动故障切换：每 15 秒探测，连续 3 次失败降权（metric +1000）、连续 2 次恢复还原；默认出口变化时重启已启用的 `wg` 隧道。USB 共享支持 RNDIS/CDC-ETHERNET 热插拔，多候选时失败关闭。

## 科学上网（sing-box + HomeProxy）

默认编译 `sing-box` 与上游 `luci-app-homeproxy`（含中文）。配置入口：**服务 → HomeProxy**。

- 节点：支持 VLESS + WS + TLS（以及上游支持的其它协议），可手工添加或订阅导入。
- 路由模式：**智能分流**（Bypass mainland China / GFWList）、**全局代理**（Global）、**直连**（Custom routing 默认出口 direct，或 direct 节点）。
- 代理模式：Redirect TCP / Redirect TCP + TProxy UDP / Tun，LAN 客户端透明代理；可按 IP/MAC 过滤。
- 首次启动**不启用**：未配置节点时服务不会运行。节点凭据与订阅只存在首启后管理员写入的 `/etc/config/homeproxy`，权限受限，不入仓库/固件/Artifact。

详见 [HomeProxy 分流手册](../docs/HOMEPROXY-SPLIT-ROUTING.md)（`devices/tr3000/docs/HOMEPROXY-SPLIT-ROUTING.md`）。

## 内网穿透

三条通道全部**默认关闭**，凭据首启后本地注入：

| 通道 | 用途 | 配置入口 |
| --- | --- | --- |
| WireGuard | 从外面进家里的 LAN（入站） | 标准 LuCI WireGuard 协议页 + 防火墙规则 |
| Cloudflare Tunnel (Argo) | 经 Cloudflare Access 暴露家里 Web 服务 | 服务 → Cloudflared（`luci-app-cloudflared`） |
| Tailscale（可选） | 免打洞备用远程通道 | 构建开关 `include_tailscale`，默认不编译 |

详见 [穿透通道手册](../docs/TUNNEL-ACCESS.md)（`devices/tr3000/docs/TUNNEL-ACCESS.md`）。

## DDNS（Cloudflare 优先）

默认编译 `luci-app-ddns` + `ddns-scripts` + `ddns-scripts-cloudflare`，出厂预置一个**禁用**的 `cloudflare.com-v4` 模板。在 **服务 → DDNS** 填入域名与 Token 后启用。详见 [DDNS 手册](../docs/DDNS-CLOUDFLARE.md)（`devices/tr3000/docs/DDNS-CLOUDFLARE.md`）。

## LuCI 与主题

- 默认主题 **Argon**（首启自动设置），**Bootstrap** 保留备用，可在 系统 → 语言和风格 切回。Aurora 被显式排除。
  - 切换步骤：系统 → 系统 → “语言和风格” → “Design” 选 `bootstrap` → **Save**（此时仅暂存）→ 点击顶栏 **“Unsaved Changes: N”** → 下拉选 **Apply unchecked** → 刷新后生效。LuCI 24.10 的该页面只有 Save 按钮，不会自动提交。
- **服务 → TR3000 Full**：远程服务状态/启停页（WireGuard、Tailscale、HomeProxy、Cloudflare Tunnel）与多上行状态页。只控制固定控制器，未编译的服务不可启用。WireGuard 行在 `wg` 接口未配置前显示 “wg interface not configured (Network → Interfaces)”（包在镜像里，但按设计不自动建接口）；Tailscale 未编入时显示 “Not included in this build”。
- 检测到旧版工业配置结构时，服务页顶部显示红色提示并要求不保留配置重刷；固件不自动改写旧配置。

## GitHub Actions

进入 **Actions → TR3000 Full firmware → Run workflow**：

| 输入 | 默认值 | 作用 |
| --- | --- | --- |
| `include_tailscale` | `false` | 是否编译 Tailscale；不控制运行状态 |
| `include_singbox` | `true` | 是否编译 sing-box；不控制运行状态 |
| `include_cloudflared` | `true` | 是否编译 cloudflared 及其 LuCI 页；仍受镜像容量门禁 |
| `release` | `false` | 成功后是否发布带警告的 GitHub prerelease |

工作流固定 Actions 版本和源码提交。只有通过以下门禁的镜像才能进入 `firmware/`：

- 唯一 profile 是 `cudy_tr3000-v1-ubootmod`；DTS UBI 范围为 `0x7000000`，拒绝 `0x7a40000`；
- 编译前断言出厂 overlay 含接入段（`lan`/`br-lan`/eth1/DHCP）且不含工业段、不含无线配置；
- 文件名匹配目标 sysupgrade，文件非空且为包含目标 `CONTROL` 的 tar；默认不超过 100 MiB；
- 镜像包清单含 homeproxy/sing-box/Argon/Cloudflare DDNS 等必需包，排除项与可选开关一致；
- 生成同次构建的 `SHA256SUMS`、最终 `.config`、`image-packages.manifest`、`full-runtime-contract.txt`、feed/source 记录和日志。

Artifact 名为 `TR3000-128M-112M-Full`。`full-runtime-contract.txt` 记录的是**出厂预期默认值**，不是实机验证。失败运行或缺少完整门禁文件的 Artifact 不能视为可刷固件。

## 第一次部署

1. 在本地控制台记录设备标签、NAND 芯片、序列批次、`/proc/mtd`、`ubinfo -a`、坏块、当前 BL2/FIP/Factory、启动日志和恢复入口（`sh /root/scripts/preflight.sh` 为只读报告）。
2. 将 Factory/RF、bootloader、环境与配置备份到设备外并核验 SHA-256。
3. 实机逐个插拔网线，确认 `eth0`/`eth1` 与物理 WAN/LAN 的映射。
4. 刷入本固件：断电 → 按住 Reset 上电 5–8 s 至红灯 → U-Boot 网页（PC 用 DHCP，或静态 `192.168.1.2` 后访问 `http://192.168.1.1`）→ 分区布局选 **112M** → 上传 `…-ubootmod-squashfs-sysupgrade.bin` → 等待自动重启。**不要用 `sysupgrade` 刷本机**（见下节）。出厂 root 密码为空：插线进入 `https://192.168.10.1` 后按提示设置非空 root 密码。
5. 按需配置 HomeProxy 节点、穿透通道与 DDNS；凭据只写设备本机受限文件。
6. 按 [`TEST-PLAN.md`](../docs/TEST-PLAN.md) 的 F1–F14 区分 CI 与真机验收。

### 首启自检（有线登录后）

```sh
/usr/sbin/tr3000-full-wifi status --json     # 期望 ready=true、managed_aps=2、open_aps=0
/usr/sbin/tr3000-full-service status --json  # 期望远程服务全部 enabled=false、running=false
/usr/sbin/tr3000-full-uplink-status --json  # 期望三条上行 base_metric 10/20/30
```

- `ready=false` 时管理 AP 尚未建立：确认无线页里 mt_wifi 默认热点显示为 “Wireless is disabled”，受管 AP 为 `TR3000-Full-XXXXXX`（WPA2 PSK）。不要手工改写 `/etc/config/wireless`，控制器会在下次启动自愈。
- 受管 AP 的密钥只在本机 `/etc/config/wireless`（`0600`）。本仓库不提供任何默认密钥。

## 升级与回滚边界

- **本机的刷写与升级路径是 U-Boot 网页恢复，不是 `sysupgrade`。** 2026-11-22 实机证明：上游 `/lib/upgrade/nand.sh` 在运行中的系统里无法交换 UBI 卷（`ubimkvol` 报 `ENOSPC`、`ubirmvol/ubiupdatevol` 报 `EBUSY`，因 `rootfs_data` 占满剩余 LEB 且卷被运行根持有）；`sysupgrade -n` 会“成功”交接并重启，但**实际不写入**，设备回到旧固件。`sysupgrade -T` 仍可作为只读镜像体检使用；失败时停止，不能用 `-F` 绕过。
- 每次刷入都是全新配置（U-Boot 恢复天然不保留配置）。Full 没有发布过工业版正式固件；若设备上存在早期试验固件的工业配置结构，启动后服务页会明确提示，不自动迁移。
- 刷写前备份 Factory/RF、BL2、FIP、u-boot-env 与配置并异机核验 SHA-256；回滚用同一 U-Boot 恢复入口重刷已验证镜像。
- 本仓库不提供猜测的 `mtd write`、`dd`、`nandwrite`、擦除命令、MTD 编号或偏移。刷 U-Boot 前阅读 [`UBOOT-SAFETY.md`](../uboot/README.md)。

## 软件包来源（opkg）

- 镜像预置的 `24.10-SNAPSHOT` 公共镜像源**不可依赖**：snapshot 会被镜像站定期清理（2026-11-24 实测官方路径 404、第三方镜像 302）。固定修订版本的固件应以**本次构建自身生成的仓库**为准：构建产物目录下的 `bin/packages/<arch>/…` 与 `bin/targets/<target>/<subtarget>/packages`（含 `Packages.gz` 与 `Packages.sig`）。
- 启用步骤：把上述仓库以 HTTP 提供给设备（内网镜像或设备自服务均可）→ 改写 `/etc/opkg/distfeeds.conf` 指向它 → 将本次构建的公钥 `key-build.pub` 放入 `/etc/opkg/keys/<keyid>`，其中 keyid 为公钥 base64 解码后 **bytes[2:10] 的十六进制**（usign 约定）→ `opkg update`。`/etc/opkg.conf` 的 `check_signature` 保持开启。
- 从活的 snapshot 源安装内核模块存在 ABI 不匹配风险；本固件的包集合以 `image-packages.manifest` 为唯一事实源。

## 本地校验

原生 Windows 不编译固件，只运行仓库校验：

```sh
bash scripts/validate.sh
python -m unittest discover -s tests -v
```

完整编译、包 ABI、镜像大小和上游下载必须由 GitHub Actions 或 Linux/WSL2 验证；启动、端口映射、NAND 兼容、恢复和穿透访问只能在已备份的实验设备验证。
