# Cudy TR3000 128MB — Lite 工业远程维护固件：独立开发提示词

> **状态（2026-11-18 更新）**：本文是**原始需求提示词**，保留为决策输入记录。其中的管理段方案（`mgmt` `192.168.77.0/24`、`br-mgmt`、有线 LAN 口固定作 `plant`、`192.168.10.254` 作 plant 默认地址）已被 [TR3000-Lite 出厂可达性改造设计](../../../docs/superpowers/specs/2026-11-18-tr3000-lite-lan-access-design.md) 取代：出厂改为接入段 `lan` `192.168.10.1/24`（常驻、有 DHCP），`plant` 默认 `proto none` 且由操作员显式接管唯一 LAN 口，默认地址 `192.168.20.254/24`，无线按真实驱动栈 mt_wifi 实现。**按本文实施会重现“上电即无可达网络”的故障**，请以现行设计为准。

> 将本文全文交给 Codex / Claude Code / 其他编程 Agent。任务是交付**可复现的 GitHub Actions 工程**及实施文档，而非仅给操作建议。

## 1. 角色与目标
你是 OpenWrt/ImmortalWrt、MediaTek MT7981 NAND 引导链、GitHub Actions 和工业以太网/防火墙工程师。基于以下上游项目，开发 **TR3000-Lite** 固件自动构建工程：
- https://github.com/weekdaycare/immortalwrt-mt7981-cudy-tr3000
- 该仓库使用 `config/128muboot.config` 和 `128M-Ubootmod` 设备选项，设备目标为 `cudy_tr3000-v1-ubootmod`。
- 仓库默认 ubootmod DTS 是 **112MB UBI** 布局。不要误用 128M 原厂布局、256MB 设备布局，或把 122MB DTS 改动混入本项目。
- 上游代码、依赖和下载地址需要在实施时再次核验，固定上游 Git commit SHA，不能假定旧包名在新分支一直可用。

硬件：Cudy TR3000 **128MB NAND Flash、512MB RAM、MT7981**。用户**已经装有第三方 U-Boot**，但计划使用上述仓库编译并**重新刷入其 DHCP U-Boot**，然后运行自行编译的 Lite 固件。不得把当前存在第三方 U-Boot 当作新 U-Boot 可以无条件覆盖的证据。

目标场景：工业现场是独立二层交换机，PLC/HMI/伺服驱动固定 IP（例如 `192.168.10.0/24`），常常**没有默认网关**。TR3000 的 LAN 口连接现场交换机，另由 WAN、Wi-Fi STA 或 USB 手机共享提供联网。外地工程师经 VPS 上的 WireGuard 访问现场设备；无需改变 PLC 原 IP 或网关。

## 2. 网络架构与强制安全要求
1. 物理 LAN `eth1` 作为独立 `plant` 接口；WAN `eth0` 为 DHCP Client。实际设备端口映射应由设备 DTS 与运行时 `ip link` 核对，不能盲目写死。
2. 另建不桥接工业 LAN 的管理 Wi-Fi 网络 `mgmt`，示例 `192.168.77.1/24`；**管理 Wi-Fi 可启用 DHCP，但工业 plant 永久禁用 DHCPv4 Server、DHCPv6、IPv6 RA/NDP 服务**。禁止默认工业 LAN 与 Wi-Fi AP 桥接。
3. 现场地址由安装人员输入，例如 `192.168.10.254/24`；固件不能预设该地址并立即启用以免 IP 冲突。首次部署应先隔离连接和检测冲突，必要时回滚。
4. WireGuard 作为 `wg0`，示例 VPN `10.77.0.2/32`，远程工程师 `10.77.0.10`、VPS `10.77.0.1`。仅作为占位示例，禁止编进真实 WireGuard 私钥、PreSharedKey、VPS 地址和用户凭据。
5. 使用 firewall4 / nftables 做**仅限已授权 WireGuard 源地址 → 指定工业网段**的 SNAT，让无默认网关的 PLC 看到源地址为 TR3000 的现场 LAN IP。SNAT 需配置具体方向、源子网、目标子网和出口，且必须有 conntrack 回程。不应对 `plant` 所有流量全局 NAT。
6. 默认禁止 `plant → wan`、`wan → plant`、`plant → wg0` 主动新建连接及 `wan → router management`；仅明确允许 `wg0 → plant` 的授权目标/端口（默认远程访问开关关闭）。不允许 VPN 任意客户端横向访问所有工业设备。
7. 网络管理与工业网络相互隔离：管理 Wi-Fi 可以访问 LuCI/SSH，但默认不可访问工业 LAN，需显式临时授权。
8. 允许上网优先级 WAN（metric 10）＞ Wi-Fi STA（20）＞ USB tethering（30）；区分“链路存在”和“互联网可用”，实现故障恢复及 WireGuard 重新握手。不得通过上游 WAN DHCP 向工业 LAN 透传任何配置。
9. 为现场网段与酒店/手机上行网段重叠提供检测与警告；重叠时避免自动写入冲突路由。多个客户现场相同网段不能简单向同一 WireGuard 网络同时发布路由。
10. 注明 TIA Portal 对固定 IP 的常规三层通信支持，以及 PROFINET DCP/LLDP/广播发现不能直接跨越三层 WireGuard。远程下载程序属于高风险作业，需授权、现场安全联锁和断线应对流程。

## 3. Lite 版软件范围
保留芯片、以太网、Wi-Fi、NAND/UBI、基础 firewall4 等构建必需组件。首选：LuCI/中文、HTTPS（`luci-ssl-openssl` 等）、`wireguard-tools`、`kmod-wireguard`、`luci-proto-wireguard`、`kmod-tun`（仅依赖需要时）、`kmod-usb-net`、`kmod-usb-net-rndis`、`kmod-usb-net-cdc-ether`、按实际兼容性加入 `kmod-usb-net-ipheth`、`curl`、`ca-bundle`、`tcpdump-mini`、`ip-full`、SSH/SFTP、DNS/路由诊断工具。检查目标源码包名和依赖，避免与上游已有包重复或失效；对于 iPhone USB 分享，说明额外用户态依赖与实际兼容限制。

明确**不预装**：OpenClash、PassWall、sing-box、Tailscale、cloudflared、AdGuard Home、Docker、UPnP、非必要 Aurora 主题和 Bandix。保留有限剩余存储与恢复余量。

## 4. GitHub Actions 必须实现
- 基于仓库 Fork 方案，保留原上游代码引用和 LICENSE；新增独立 `build-lite.yml`，不能覆盖其它固件工作流。
- 手动 `workflow_dispatch`；构建时钉住源码 SHA，使用 `config/128muboot.config` 为基线，通过清晰的 `configs/lite.seed` / 脚本进行包选择差异化，并用 `make defconfig` 校验。
- 优先选 `ubuntu-22.04` 或已验证兼容的 Runner，合理设置磁盘清理、缓存、重试、编译并发与日志。
- 对 SDK/feeds/额外依赖使用版本固定及校验；不从不受控 URL 静默拉取可执行文件；不在构建日志泄露 secrets。
- 输出仅 128MB U-Boot Mod **112MB 布局**固件，确保输出文件 device/profile 与构建配置匹配；提供镜像 SHA256、Git commit 信息、包清单、构建日志和 GitHub Artifact。不能误标记 `sysupgrade.bin` 为所有刷机方式都兼容。
- 为 DHCP U-Boot 增加**独立构建工作流** `build-uboot.yml`，基于 https://github.com/weekdaycare/bl-mt798x-dhcpd ，并核验上游所用命令 `SOC=mt7981 BOARD=cudy_tr3000-v1 VERSION=2025 MULTI_LAYOUT=1 ./build.sh`；不要把 256M U-Boot 混入 128M 发布物。U-Boot 的 BL2/FIP/恢复镜像分开命名、列清刷写对象与用途。系统编译过程不自动刷 bootloader。
- 构建完成对 `bin/targets` 做设备名、文件格式与 SHA 检查；任一检查不通过禁止发布为可刷机镜像。

## 5. 交付目录结构
```
.github/workflows/build-lite.yml
.github/workflows/build-uboot.yml
configs/lite.seed
scripts/configure-lite.sh
files/etc/config/  # 仅可安全默认启用的配置
scripts/plant-profile.sh
scripts/plant-access.sh
scripts/preflight.sh
docs/LITE-README.md
docs/UBOOT-SAFETY.md
docs/WIREGUARD-VPS-ROUTING.md
docs/TEST-PLAN.md
```
脚本要求幂等，遵循 `/bin/sh`/BusyBox 兼容，`set -eu`，错误恢复，不可触碰 Factory 校准数据，不生成/硬编码生产私钥。

## 6. 安全刷机与验证（强制先核验）
提供**只读检查命令**，采集 `cat /proc/mtd`、`ubinfo -a`、`cat /etc/openwrt_release`、`dmesg` 中 NAND 型号及 bad block、U-Boot 版本、当前 BL2/FIP/Factory 分区。要求用户做分区备份并**异机保存、计算 SHA256**。在不知道现用第三方 U-Boot 分区布局、芯片型号与目标镜像类型时，不准编造 `mtd write`/`dd` 的分区名或偏移；必须给出阻止写入的前置检查和可回退 UART/恢复方案。

确定 U-Boot 刷写与恢复界面可用之后，再选择对应 112MB 布局的 U-Boot Mod 固件并刷入；刷写前确认 U-Boot 的当前选择分区与固件布局一致。不要启用“保存旧配置”跨不兼容布局升级。避免在远程无人值守现场刷引导程序。

验收用例必须至少包括：工业 DHCP/RA 嗅探无广告、Wi-Fi/LAN 不桥接、WAN 上网、WireGuard 丢包和重连、SNAT 返回路径、拒绝未授权端口、PLC 固定 IP 联通、TIA Portal 固定 IP 在线（仅安全模拟环境）、断电/恢复机制、IP 冲突回滚。

## 7. 输出方式
真正生成仓库完整文件，不只输出示例片段；所有关键步骤有中文 README、命令与验收预期。标注哪些是已执行测试、哪些仍需真机验证。先提交安全默认配置与 CI，不要声称构建或刷机成功，除非实际有结果证明。
