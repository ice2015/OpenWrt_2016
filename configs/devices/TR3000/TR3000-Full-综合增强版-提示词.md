# Cudy TR3000 128MB — Full 综合增强固件：独立开发提示词

> **已被取代（保留作历史）**：本文是 Full 的工业版规格。自 2026-11-19 起，Full 改为家用路由器定位（去工业段、sing-box/HomeProxy 科学上网、WireGuard/Cloudflare Tunnel/Tailscale 穿透、Cloudflare DDNS、Argon 主题），现行设计见 `docs/superpowers/specs/2026-11-19-tr3000-full-home-router-design.md`，操作说明见 `docs/FULL-README.md`。本文中的工业网段/精准 SNAT 要求不再适用于 Full。

> 将本文全文交给 Codex / Claude Code / 其他编程 Agent。本文为**独立完整任务**，无需依赖另一份 Lite 提示词。

## 1. 工程目标与硬件
你是 OpenWrt/ImmortalWrt、MT7981 NAND/U-Boot、GitHub Actions、WireGuard、Tailscale、sing-box、Cloudflare Tunnel（cloudflared）专家。基于 https://github.com/weekdaycare/immortalwrt-mt7981-cudy-tr3000 开发可复现 **TR3000-Full** GitHub Actions 自动构建仓库。

设备为 **Cudy TR3000 128MB NAND Flash、512MB RAM、MT7981**；当前已经安装其他第三方 U-Boot，用户计划**编译并重新安装上述仓库兼容的 DHCP U-Boot**。当前能用不代表可安全直接覆盖 BL2/FIP。用户希望系统使用 **128M-Ubootmod / 112MB UBI 分区**，之后可通过兼容的 U-Boot 恢复界面换刷自编译固件。固件不能与原厂 128M、256M 或 122MB 布局混用。

上游固件基础为 https://github.com/padavanonly/immortalwrt-mt798x-6.6 ，仓库目标分支见 GitHub Actions，`config/128muboot.config` 选择 `cudy_tr3000-v1-ubootmod`。务必核对最新仓库及固定构建 commit SHA、包名、ABI 和依赖。不得假设来自不同分支的二进制可互换。

## 2. 远程工业网络必须满足
现场是**独立二层工业交换机**，设备通常固定 IP、无默认网关，不能修改其 IP。TR3000 1G LAN (`eth1`，需实机核实) 连接交换机，2.5G WAN (`eth0`，需核实) / Wi-Fi STA / USB 手机共享为外部互联网。设计如下：
- `plant` 独立工业 LAN（现场安装时填写一个未占用 IP，如 `192.168.10.254/24`）；不得自动假设可用。
- `mgmt` 独立 Wi-Fi AP，如 `192.168.77.1/24`；与 `plant` 不桥接。
- `wg0` 连接 VPS（例 `10.77.0.2/32`；VPS `10.77.0.1`，工程师 `10.77.0.10`）。
- 远程 WireGuard 客户端 → 授权的指定 `plant` IP/端口做**精准 SNAT**，源转换为 TR3000 的现场 IP，使 PLC/HMI 无网关也能回程；必须使用 firewall4 / nftables 精确限制源、目标、接口和 conntrack。
- `plant` 永久**关闭 DHCPv4 Server、DHCPv6、RA、NDP 广告**，默认 `plant → WAN` 禁止、WAN 入站禁止、`mgmt → plant` 默认禁止、`wg0 → plant` 默认禁止且通过明确授权的维护开关启用。
- 管理 Wi-Fi 只给管理设备发 DHCP；外部 WAN / Wi-Fi STA / USB 只作为 DHCP Client。
- WAN 上行优先级：有线 10，Wi-Fi STA 20，USB tether 30；检测互联网健康状态，切换后重建 WireGuard。处理和报警同网段上行冲突，不得自动错误路由。酒店认证门户需人工确认。
- 同时支持多现场配置档，切换必须原子性应用/回滚，提示远端 VPS 静态路由/AllowedIPs 要配套更新；不同客户相同子网不能简单同时路由。
- TIA Portal S7-1200/1500 以固定 IP 方式访问；PROFINET DCP、LLDP 和二层搜索不保证跨 WireGuard。不要建议未经现场授权远程操作生产设备。
- 不把 WireGuard 私钥、Cloudflare token、Tailscale auth key、VLESS UUID 等生产密钥提交 GitHub 或放入公开固件。配置在首次启动后注入，限制权限为 0600。

## 3. Full 版软件组成
保留底层 NAND/UBI/Wi-Fi/网卡和 firewall4；预装 LuCI HTTPS + 中文、WireGuard 工具及 LuCI 协议、RNDIS/CDC USB 共享、可用时 iPhone USB 共享、`curl`、`ca-bundle`、`tcpdump-mini`、路由诊断和 SSH/SFTP。

在此基础增加：
1. **Tailscale + kmod-tun**：作为可选备用远程访问；默认禁用，不与 WireGuard 自动抢夺现场工业路由，启用时需要 ACL、路由批准和防火墙检查。
2. **sing-box**：用于 VLESS + WS + TLS 与按域名/IP 的出差上网分流。默认不启用透明全局代理，不捕获 WireGuard 端点、工业 `plant` 网段、管理网段、Tailscale 和 cloudflared 控制流量。合理处理 DNS 泄漏、路由环、UDP 与 nftables 规则顺序。智能分流策略为：国内访问直连、明确配置的目的地走 VPS，工业网段仅走指定 VPN，而非代理。附运行配置模板、无凭据示例和回滚脚本。
3. **Cloudflare Tunnel / cloudflared**：用于经过 Cloudflare Access 认证访问现场 HMI / NAS Web 应用及经私有网络路由访问授权 TCP 服务。默认禁用；不得直接暴露 PLC 管理或控制端口到公共域名。优先通过本地保存的 token 启动、procd 服务管理、崩溃重启与日志限制；出站网络检查包括 Cloudflare Tunnel 所需端口/协议。若 cloudflared 二进制体积对 112MB UBI 造成压力，提供构建期可选开关 `INCLUDE_CLOUDFLARED`，并做镜像容量检查，必要时改为后装而非强制硬塞。
4. **管理页面**：可通过 LuCI/脚本独立启动与关闭 WireGuard 远程维护授权、Tailscale、sing-box、cloudflared。默认只 WireGuard 可配置、业务应用不开机启动。生产级开机服务需用 procd，不要使用不受控后台 shell 循环。

明确移除非必要 OpenClash、PassWall、UPnP、AdGuard Home、Docker、额外 Aurora 主题、Bandix，避免同类组件叠加；`dnsmasq`/`dnsmasq-full` 按实际分流功能选一个，避免配置冲突。每项包需要检查上游 feeds 是否可用、编译依赖和容量余量。大型二进制优先使用**指定版本 + 固定 SHA256 + 与目标 libc/ABI 兼容性验证**的预编译方式；不要盲目下载 ARM64 glibc 程序或使用未验证的历史链接。使用预编译单文件时验证架构和运行依赖，不能假设静态链接。

## 4. GitHub Actions 完整要求
- Fork/衍生 weekdaycare 仓库，保留 LICENSE、引用来源、固定上游提交。
- 新增 `.github/workflows/build-full.yml`（独立于 Lite），提供输入 `include_tailscale`、`include_singbox`、`include_cloudflared`、`release`，默认启用构建但禁用运行服务；构建的包/二进制必须与开关一致。
- 基于 `config/128muboot.config` 生成 Full 的 seed config，不允许 `config/128m.config` 或 `256m.config` 混入；使用 `make defconfig` 校验，输出 config/package manifest。
- 另新增 `.github/workflows/build-uboot.yml`，按照 https://github.com/weekdaycare/bl-mt798x-dhcpd 的已核验指令构建 DHCP U-Boot，常见 128MB 多分区命令为 `SOC=mt7981 BOARD=cudy_tr3000-v1 VERSION=2025 MULTI_LAYOUT=1 ./build.sh`，需核对当前文档。仅发布 128MB 适配的 BL2/FIP/恢复镜像，分开标注。不能在 CI 中直接写入用户真实设备。
- Action 支持手动构建、缓存/磁盘清理、失败日志、SHA256、设备 Profile/布局一致性检查、工件归档、可选 Release；文件名明确 `TR3000-128M-112M-Full`。校验失败不能作为可刷固件发布。
- 控制构建机磁盘和网络超时；第三方下载固定版本/校验和，尽量锁定 Actions 完整版本，最小权限 `contents: read`（仅发布 Release 的作业显式升权）。
- 发布 Release 前对镜像大小、ubi 分区边界、镜像头和 device profile 做验证；不可把 U-Boot、factory、sysupgrade 混成一个无说明固件包。

## 5. 成品目录与必需文档
```
.github/workflows/build-full.yml
.github/workflows/build-uboot.yml
configs/full.seed
scripts/configure-full.sh
scripts/verify-image.sh
scripts/plant-profile.sh
scripts/plant-access.sh
scripts/service-toggle.sh
files/etc/config/          # 只包含安全默认项
docs/FULL-README.md
docs/UBOOT-SAFETY.md
docs/WIREGUARD-SNAT.md
docs/TAILSCALE.md
docs/SINGBOX-SPLIT-ROUTING.md
docs/CLOUDFLARED-ACCESS.md
docs/TEST-PLAN.md
```
此外输出完整的 WireGuard VPS/工程师端示例，说明 `AllowedIPs`、VPS Linux `ip_forward`、VPS 防火墙和路由分发；不能将 VPS 或客户设备的敏感信息写入仓库。

## 6. 重刷 DHCP U-Boot 及安全刷机
用户目前已经有**第三方 U-Boot，但准备重刷**。刷前必须用只读命令采集 `/proc/mtd`、`ubinfo -a`、NAND 芯片 ID、BL2/FIP/Factory 当前布局、U-Boot 恢复页、启动日志、bad block；备份所有可安全读取的重要 MTD 分区，尤其 Factory 校准数据，备份异机保存并核对 SHA256。当前 U-Boot 的具体类型未知，绝不凭空给出 `mtd write`/`dd` 目标分区编号、地址或偏移，也不要直接向 NAND 设备块做原始写入。

依据仓库**对应硬件批次的正式刷机教程**，确认 BL2/FIP 是否需要成对升级、恢复界面支持何种镜像、所用 112MB UBI 布局选择方法、UART 回退步骤，并给出停机、现场接线与断电风险说明。新 U-Boot 可成功进入恢复页后，才上传正确的 128M-Ubootmod 112MB 固件。跨布局刷写不保留旧配置。不要在远程无人值守现场刷 U-Boot。

## 7. 测试与验收
提交实际可执行的测试清单：
- 编译 profile、分区和镜像大小；U-Boot 独立生成、校验文件匹配。
- 首次启动时 `plant` 无 DHCP/RA 包，管理 Wi-Fi 可用且独立，WAN 流量不泄漏工业 LAN。
- WireGuard 握手、SNAT 访问静态 IP 的 PLC/HMI（用测试设备先验证）、回程、断网重连与停止授权后即时断开。
- Tailscale 与 WireGuard 共存不抢路由；sing-box 不代理工业和 WireGuard；Cloudflare Access 保护 HMI Web，不暴露 PLC 公网端口。
- 同网段 WAN 冲突、配置原子回滚、断电恢复、升级后配置迁移和剩余 NAND 空间。
- 区分 CI 编译通过、QEMU/模拟验证、真实 TR3000 上测试，不得伪称现场测试完成。

## 8. 结果交付
实际生成所有 YAML、seed 配置、shell 脚本和中文 MD，并说明如何 Fork、如何在 Actions 手动运行、如何下载镜像、如何升级/回滚。输出带校验和的 Release 构件。遇到包名/版本/镜像体积问题时优先保证 WireGuard + 工业 SNAT + 网络隔离，再降级 Tailscale/cloudflared/sing-box 的预装级别，而不是牺牲安全默认值。
