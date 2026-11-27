# NX30 Pro 112M 固件与 U-Boot 重做设计

## 意图

重新设计 H3C Magic NX30 Pro 的固件与 U-Boot 配套构建。现有 NX30PRO
实现只作为调查证据，不继承其源码锁、feeds 锁和两个 Actions 的实现假设。

第一版继续以 Linux 5.4 / OpenWrt 21.02 系兼容性为边界，优先保留已经确认的
NX30PRO 设备支持、112 MiB NMBM 布局以及 PassWall 4.68 + Xray 软件栈，避免在
同一阶段同时承担设备移植和发行版大版本升级。

## 目标

- 固件源码以 `hanwckf/immortalwrt-mt798x` 的 `openwrt-21.02` 分支为候选，实施时
  从上游事实重新选择并固定完整 commit。
- 从 `Galaxian-Explosion/nx30pro-imm-112M-nmbm` 提取 112M DTS、profile 和镜像
  规则作为移植证据，不直接复用其 2023 年 commit 作为默认构建底座。
- U-Boot 使用 `Yuzhii0718/bl-mt798x-dhcpd`，实施时固定完整 commit；当前调查候选
  为 `e4cf4dc72d451dc7a86c9508390ad5a2e50743c4`。
- 固件和 U-Boot 共享同一份可机器校验的分区合同。
- 重做 NX30PRO 固件与 U-Boot 两个手动 GitHub Actions 工作流。
- 每个源码、feed 和第三方包都固定完整 commit，并在最终配置中验证，而不是只验证
  仓库中存在对应 Makefile。
- 输出固件、BL2、FIP、SHA256、最终配置、软件包清单、源码锁和构建报告。

## 非目标

- 本阶段不迁移到 ImmortalWrt 24.10/25.12，也不移植到新内核。
- 本阶段不开发 114M 非 NMBM 布局。
- 不自动刷写、不执行 NAND 擦除、不把候选产物描述为真机验证通过。
- 不允许 U-Boot Web UI 任意编辑分区表、Factory、原始闪存或环境变量。
- 不启用 CPU 或 DDR 超频。
- WireGuard 若在所选 Linux 5.4 底座没有可验证实现，则保持未实现和 `UNRESOLVED`，
  不以不兼容的包冒充支持。

## 约束

- 仓库配置优先级保持 `common → distribution → device → local`。
- 所有 NX30PRO 专用输入位于 `devices/nx30pro/`，不得影响其他设备。
- 不修改 `work/`、`output/`、`cache/` 等生成目录。
- 未核实的 commit、profile、分区或产物规则保持 `UNRESOLVED`。
- Windows 只用于编辑和静态校验；固件及 U-Boot 构建只在 GitHub Actions 或 Linux/
  WSL2 中运行。
- 本设计阶段不触发 Actions 或本地固件编译。

## 方案比较

### 方案 A：重建 21.02/5.4 配套栈（已选）

在 `hanwckf/immortalwrt-mt798x` 当前 21.02 系代码上重新锁定固件源码与 feeds，
移植已有 112M 设备定义，并配对 Yuzhii U-Boot。它最有可能保留 PassWall 4.68、
Xray 和 Docker，同时避免一次跨越设备、内核与包管理三层的迁移。

代价是底座较旧，WireGuard 和部分现代包继续受限。第一版真机通过后，可在独立
worktree 中规划 24.10 迁移。

### 方案 B：迁移 ImmortalWrt 24.10（未选）

安全维护和现代包更好，但官方代码没有 NX30PRO 设备定义，需要完整移植；同时不能
保证 PassWall 4.68 原样兼容。

### 方案 C：直接复用旧 Galaxian commit（未选）

112M profile 已存在，但该 commit 来自 2023 年，也是旧失败方案的底座。继续直接使用
会保留旧源码和 feeds 不兼容风险。

## 固件设计

### 源码与 feeds

实施时按以下顺序确定锁：

1. 核实 `hanwckf/immortalwrt-mt798x` 候选 commit 的 NX30PRO 板级支持、Linux 5.4、
   NMBM 参数和基础 profile。
2. 以同一时间点和同一 21.02 API 代际选择 packages、luci、routing、telephony feeds。
3. 在写入锁文件前检查所有必需包的依赖闭包。
4. 安装 feeds、运行真实 `make defconfig`，保存并审查最终 `.config`。
5. 只有最终配置仍为 `=y` 的包才能在 source lock 中标记 `available`。

不得重复旧 Action 的错误：把不兼容 feeds 中可被索引的包误判为可构建包。

### 设备与镜像

- SoC：MediaTek MT7981。
- 设备：H3C Magic NX30 Pro。
- 启动介质：SPI-NAND + NMBM；具体 NAND 型号仍需真机读取。
- 默认布局：`immortalwrt-112m`。
- UBI 分区：112 MiB；镜像上限必须从最终 image rule 读取并与分区合同核对。
- 必须生成并区分 factory 与 sysupgrade 产物；具体文件名由最终 profile 决定，设计期
  不沿用旧名称作为无条件事实。
- WAN MAC、Factory 写入行为及无线校准数据来源必须在新源码中重新核实。

### 软件包

第一版核心包是发布硬门禁，缺少任何一项就停止，不生成正式候选固件：

- LuCI、HTTPS、简体中文、Argon 与 Bootstrap 回退主题。
- PassWall 4.68、Xray Core 与 Xray Plugin；不使用 HomeProxy、sing-box、OpenClash、
  PassWall2 或 AdGuard Home。
- DDNS、Tailscale、ZeroTier、Docker。
- Argo 隧道（`cloudflared`）。

以下附加工具必须尝试并在报告中记录，但允许因所选旧底座不兼容而延期：

- Cloudflare DDNS、FRPC、dnsmasq-full、SQM、NLBWMon、WOL、TTYD、SFTP、tcpdump、
  iperf3、MTR。

核心包必须在真实 `make defconfig` 后仍为 `=y`；否则判定该源码/feeds 组合不合格，
不得进入正式编译。附加工具的状态只能是 `available`、`partial`、`unavailable` 或
`UNRESOLVED`，且不能通过删除门禁或伪造配置隐藏差异。所有非必要网络服务（包括
PassWall、DDNS、Tailscale、ZeroTier、Docker、cloudflared 以及已纳入镜像的附加服务）
默认关闭，部署后显式启用。令牌、域名及其他秘密不得进入镜像。Docker 存储驱动和
镜像剩余空间需要构建产物与真机验证。

## U-Boot 设计

### 源码与版本

- 仓库：`https://github.com/Yuzhii0718/bl-mt798x-dhcpd`。
- 板级配置：`h3c_magic-nx30-pro`。
- SoC：`mt7981`。
- 使用当前 U-Boot 2025 树；因第一版固件为 Linux 5.4，优先评估 SP1 ATF，最终选择
  必须由启动兼容证据决定。
- 禁止用漂移的 master 作为构建输入；source lock 固定完整 commit。

### 分区

启用 `MULTI_LAYOUT=1` 与 `FIXED_MTDPARTS=1`，只提供上游 NX30PRO DTS 中已定义的：

1. `immortalwrt-112m`（默认）：1 MiB BL2、512 KiB U-Boot 环境、2 MiB Factory、
   2 MiB FIP、112 MiB UBI。
2. `default`（备选）：64 MiB UBI，并保留 `pdt_data`、`pdt_data_1`、`exp`、`plugin`。

禁止 Web UI 任意编辑 `mtdparts`。从原厂布局切换到 112M 前必须展示数据损失警告并
要求先完成只读备份。Factory 在两套布局中的偏移与大小必须保持一致。

Web UI 提供设备专用的白名单布局选择器，只能选择 `immortalwrt-112m` 或 `default`。
选择器可以保存对应的布局标签，但不得暴露通用环境变量编辑或自定义 `mtdparts` 输入。
默认选择为 `immortalwrt-112m`。如果上游 Web UI 无法通过 Kconfig 将该能力与通用环境
编辑分离，则使用只作用于 NX30PRO 的最小补丁实现。

### 恢复功能

启用：

- DHCP Server。
- Web failsafe。
- 系统固件恢复。
- BL2 与 FIP 升级。
- TFTP 恢复。
- UART。
- 整机及分区的只读备份下载。

关闭：

- Factory 写入。
- 原始 Flash Editor。
- 环境变量写入页面。
- Web 终端与 Telnet。
- UBI 卷管理。
- CPU/DDR 超频配置。

构建检查必须检查最终 U-Boot `.config` 和产物内容，不能只检查传给脚本的环境变量。

## Actions 与构建边界

重做：

- `.github/workflows/build-nx30pro.yml`
- `.github/workflows/build-nx30pro-uboot.yml`

两者保持 `workflow_dispatch`，不得由 push 自动触发。工作流分为：

1. 仓库静态校验。
2. source lock 与分区合同 preflight。
3. 固定源码和 feeds 获取。
4. 配置生成及最终配置审计。
5. 构建。
6. 镜像格式、大小、哈希与来源报告。
7. 成功产物和 `always()` 诊断日志分别上传。
8. 在用户授权触发后，以 `gh` CLI 读取运行状态和失败日志，形成可追溯验证记录。

固件 Action 在配置审计失败时必须停止，不进入编译。U-Boot Action 必须输出 BL2 与
FIP，并记录工具链身份与时间戳导致的可重复性差异。两个工作流都不包含刷写命令。

配套文档交付包括 `BUILD.md`、`FLASH.md`、`RECOVERY.md` 与 `TEST-REPORT.md`，分别记录
可复现构建输入、经授权的刷写边界、恢复步骤和实际验证状态。文档不得把计划中的步骤
或候选产物写成已经完成的真机验证。

## 验证层级

### 本地静态验证

- `bash scripts/validate.sh`
- `python -m unittest discover -s tests -v`
- manifest、source lock、分区合同、设备隔离和 workflow 契约测试。

这些检查不等于固件编译。

### Actions 候选构建

- 最终 `.config` 必需包和排除包检查。
- 固件 factory/sysupgrade 格式与大小检查。
- U-Boot BL2/FIP 格式、大小、最终配置和分区检查。
- SHA256、源码/feeds/toolchain、包清单和日志归档。
- 经用户授权后使用 `gh` CLI 检查运行结论、失败步骤和日志，并把运行 URL/ID 写入
  `TEST-REPORT.md`。

只有用户另行授权时才触发 Actions。

### 真机验收

- 原厂全闪存和分区备份可下载、可校验。
- 两个布局可识别，默认是 `immortalwrt-112m`。
- Web、DHCP、TFTP 与 UART 恢复路径。
- BL2/FIP 与系统固件配对启动。
- Factory、WAN/LAN/Wi-Fi MAC 与无线校准数据保持正确。
- WAN、LAN、Wi-Fi、LuCI、PassWall/Xray、DDNS、Tailscale、ZeroTier、Docker、
  cloudflared 及其他已标记可用的软件。
- 无异常 NMBM、NAND、ECC、UBI 错误。
- 多次重启、sysupgrade、回退和 72 小时稳定性测试。

真机步骤必须独立授权；设计和 Actions 均不自动执行。

## 未决事项

- NX30PRO 实机 NAND 型号、容量、坏块状态和原厂分区转储。
- 固件候选 commit 与配套 feeds 的完整 commit。
- PassWall 4.68 及所有必需包在最终依赖闭包中的实际状态。
- Yuzhii U-Boot 最终 commit，以及 SP1/2025/SP2 的配对选择。
- 受限 Web UI 是否能仅通过配置关闭危险功能，还是需要设备专用最小补丁。
- 固件 profile、factory/sysupgrade 最终文件名和镜像上限。
- WAN MAC 与无线校准数据在新源码中的读取路径。
- 构建产物大小、overlay 剩余空间和 Docker 存储驱动。

