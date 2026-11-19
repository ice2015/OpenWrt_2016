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

详见 [HomeProxy 分流手册](HOMEPROXY-SPLIT-ROUTING.md)（`docs/HOMEPROXY-SPLIT-ROUTING.md`）。

## 内网穿透

三条通道全部**默认关闭**，凭据首启后本地注入：

| 通道 | 用途 | 配置入口 |
| --- | --- | --- |
| WireGuard | 从外面进家里的 LAN（入站） | 标准 LuCI WireGuard 协议页 + 防火墙规则 |
| Cloudflare Tunnel (Argo) | 经 Cloudflare Access 暴露家里 Web 服务 | 服务 → Cloudflared（`luci-app-cloudflared`） |
| Tailscale（可选） | 免打洞备用远程通道 | 构建开关 `include_tailscale`，默认不编译 |

详见 [穿透通道手册](TUNNEL-ACCESS.md)（`docs/TUNNEL-ACCESS.md`）。

## DDNS（Cloudflare 优先）

默认编译 `luci-app-ddns` + `ddns-scripts` + `ddns-scripts-cloudflare`，出厂预置一个**禁用**的 `cloudflare.com-v4` 模板。在 **服务 → DDNS** 填入域名与 Token 后启用。详见 [DDNS 手册](DDNS-CLOUDFLARE.md)（`docs/DDNS-CLOUDFLARE.md`）。

## LuCI 与主题

- 默认主题 **Argon**（首启自动设置），**Bootstrap** 保留备用，可在 系统 → 语言和风格 切回。Aurora 被显式排除。
- **服务 → TR3000 Full**：远程服务状态/启停页（WireGuard、Tailscale、HomeProxy、Cloudflare Tunnel）与多上行状态页。只控制固定控制器，未编译的服务不可启用。
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
4. 刷入本固件（首次安装或 `sysupgrade -n`），插线进入 `https://192.168.10.1` 设置 root 密码。
5. 按需配置 HomeProxy 节点、穿透通道与 DDNS；凭据只写设备本机受限文件。
6. 按 [`TEST-PLAN.md`](TEST-PLAN.md) 的 F1–F14 区分 CI 与真机验收。

## 升级与回滚边界

- **升级本固件必须不保留配置刷机**（`sysupgrade -n`）。Full 没有发布过工业版正式固件；若设备上存在早期试验固件的工业配置结构，启动后服务页会明确提示，不自动迁移。
- 传输后重新核验镜像 SHA-256，并在目标设备上先运行 `sysupgrade -T <verified-image>`；失败时停止，不能用 `-F` 绕过。
- 本仓库不提供猜测的 `mtd write`、`dd`、`nandwrite`、擦除命令、MTD 编号或偏移。刷 U-Boot 前阅读 [`UBOOT-SAFETY.md`](UBOOT-SAFETY.md)。

## 本地校验

原生 Windows 不编译固件，只运行仓库校验：

```sh
bash scripts/validate.sh
python -m unittest discover -s tests -v
```

完整编译、包 ABI、镜像大小和上游下载必须由 GitHub Actions 或 Linux/WSL2 验证；启动、端口映射、NAND 兼容、恢复和穿透访问只能在已备份的实验设备验证。
