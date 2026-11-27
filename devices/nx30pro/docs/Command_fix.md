# H3C NX30 Pro 112M NMBM 固件与 U-Boot 重做要求

## 任务定位

在现有 OpenWrt 多设备工程中，从头重做 H3C Magic NX30 Pro 的 U-Boot 与固件构建。
旧 NX30PRO 实现、source lock 和两个 GitHub Actions 只作为调查证据与失败案例，不作为
新实现的默认输入。

第一版采用 21.02/Linux 5.4 兼容路线，优先保留已有 NX30PRO 板级支持、112 MiB NMBM
布局及指定软件栈。第一版通过真机验证后，再在独立 worktree 研究较新 ImmortalWrt
底座；本次不涉及 114M 非 NMBM 移植。

## 固件源码路线

- 候选底座：`https://github.com/hanwckf/immortalwrt-mt798x` 的
  `openwrt-21.02` 分支。
- 实施时重新调查并固定完整源码 commit；分支名只作说明，不能作为可复现输入。
- `https://github.com/Galaxian-Explosion/nx30pro-imm-112M-nmbm` 只作为
  112M DTS、profile 和镜像规则的移植证据，不直接沿用其 2023 年 commit 作为构建
  底座。
- packages、luci、routing、telephony 等 feeds 必须选择与源码处于同一 21.02 API
  代际的完整 commit。
- 软件包在 feed 中存在并不等于可构建；必须经过真实 feeds 安装和 `make defconfig`
  后检查最终 `.config`。
- 未核实的 source、feed、profile、镜像名称与规则保持 `UNRESOLVED`，不得猜值。

## U-Boot 路线

- 仓库：`https://github.com/Yuzhii0718/bl-mt798x-dhcpd`。
- Board：`h3c_magic-nx30-pro`。
- SoC：MT7981。
- 实施时固定完整 commit，不使用漂移的 master 作为构建输入。
- 使用当前 U-Boot 2025 树；第一版固件为 Linux 5.4，因此优先评估 SP1 ATF，最终
  SP1/2025/SP2 选择必须由配对证据决定。
- CPU 与 DDR 超频关闭。

### 分区布局

启用 `MULTI_LAYOUT=1` 与 `FIXED_MTDPARTS=1`，只允许：

1. `immortalwrt-112m`（默认）：
   - BL2：1 MiB
   - U-Boot 环境：512 KiB
   - Factory：2 MiB
   - FIP：2 MiB
   - UBI：112 MiB
2. `default`（备选）：原厂 64 MiB UBI，并保留 `pdt_data`、`pdt_data_1`、`exp`、
   `plugin`。

Web UI 提供设备专用的白名单布局选择器，只能选择上述两个标签。不得开放任意
`mtdparts`、通用环境变量或自定义分区编辑。切换至 112M 前必须明确提示 OEM 尾部
分区会被覆盖，并要求先完成备份。两种布局中的 BL2、环境、Factory、FIP 偏移与大小
必须一致。

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
- 通用环境变量写入页面。
- Web 终端与 Telnet。
- UBI 卷管理。
- CPU/DDR 超频配置。

如果上游配置无法把白名单布局选择与危险功能分离，使用只作用于 NX30PRO 的最小
补丁裁剪功能。

## 第一版固件软件包

### 发布硬门禁

以下任何一项在真实 `make defconfig` 后缺失，都必须拒绝该源码/feeds 组合，不生成
正式候选固件：

- LuCI、HTTPS、简体中文。
- Argon 主题与 Bootstrap 回退主题。
- PassWall **4.68**、Xray Core、Xray Plugin。
- DDNS。
- Tailscale。
- ZeroTier。
- Docker。
- Argo 隧道（`cloudflared`）。

不使用 HomeProxy、sing-box、OpenClash、PassWall2 或 AdGuard Home。

### 必须调查并报告、允许延期

- Cloudflare DDNS。
- FRPC。
- dnsmasq-full。
- SQM、NLBWMon。
- WOL、TTYD。
- SFTP。
- tcpdump、iperf3、MTR。

上述项目必须记录为 `available`、`partial`、`unavailable` 或 `UNRESOLVED`，不能删除
记录来隐藏不兼容。WireGuard 在 Linux 5.4 上若没有可验证实现，保持 `UNRESOLVED`。

所有非必要网络服务默认关闭，部署后显式启用。cloudflared 令牌、DDNS 域名、账号、
密码、密钥、Wi-Fi 凭据、现场 IP 和设备真实 MAC 不得进入镜像或仓库。

## GitHub Actions

从头重做：

- `.github/workflows/build-nx30pro-uboot.yml`
- `.github/workflows/build-nx30pro.yml`

要求：

- 只允许 `workflow_dispatch`，不得由 push、PR 或 schedule 自动触发。
- 固定源码、feeds、Actions 与工具链身份。
- 构建前运行仓库校验、source lock、分区合同和最终配置审计。
- 固件配置审计失败时必须在编译前停止。
- U-Boot 必须检查最终 `.config`，不能只检查传入环境变量。
- 分别上传成功候选产物和 `if: always()` 诊断日志。
- 输出 BL2、FIP、factory、sysupgrade、SHA256、最终配置、软件包清单、源码/feeds 锁、
  工具链信息和构建报告。
- workflow 不包含刷写、NAND 擦除或部署命令。
- 只有用户另行明确授权后才能触发；设计和静态实现阶段不得运行。

配套生成 `BUILD.md`、`FLASH.md`、`RECOVERY.md`、`TEST-REPORT.md`。文档必须区分
静态验证、Actions 候选构建和真机验证，不得把计划或绿色构建描述为真机兼容通过。

## 验收层级

### 静态验证

```sh
bash scripts/validate.sh
python -m unittest discover -s tests -v
```

静态检查不等于固件或 U-Boot 编译。

### 经授权的 Actions 候选构建

- 固件与 U-Boot 使用相同的 112M 分区合同。
- 核心软件包全部保留在最终 `.config`。
- 产物格式、大小、角色、哈希和来源完整。
- 使用 `gh` CLI 记录运行 ID、URL、结论与失败日志。

### 独立授权的真机验证

- 先完成原厂全闪存和全部分区备份与校验。
- 默认布局为 `immortalwrt-112m`，并能受控切换回 `default`。
- Web、DHCP、TFTP、UART 恢复路径正常。
- BL2、FIP 与固件配对启动。
- Factory、WAN/LAN/Wi-Fi MAC 与无线校准数据正确。
- WAN、LAN、Wi-Fi、LuCI 与全部核心硬门禁服务正常。
- 无异常 NMBM、NAND、ECC、UBI 错误。
- 完成多次重启、sysupgrade、回退及 72 小时稳定性测试。

本工程不自动执行真机刷写，不执行未经验证的 NAND 擦除命令。

## 当前已知旧方案问题

- 旧固件 Action 最近连续失败；最新 run `45579764579` 在配置阶段停止，未开始正式
  编译，也未产生固件。
- 旧 `make defconfig` 删除了 PassWall、Xray、cloudflared、DDNS、ZeroTier、Docker、
  Argon 等必需项，证明旧源码与 feeds 锁不兼容。
- 旧 U-Boot Action 只证明 BL2/FIP 可编译，未与成功固件配对、未真机验证；两次构建
  还因时间戳产生不同哈希。

## 未决硬件事实

- 实机 NAND 型号、容量、坏块状态和完整原厂分区转储。
- 112M UBI 之后空间的实测用途与容量。
- WAN MAC 与无线校准数据在新源码中的最终读取路径。
- 最终固件镜像大小、overlay 剩余空间及 Docker 存储驱动。
- U-Boot 与固件在真机上的配对行为。

