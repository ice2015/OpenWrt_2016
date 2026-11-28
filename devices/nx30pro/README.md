# NX30PRO

状态：固件与启动链都已锁定源码并具备构建入口，产物仍是候选、未真机验证。
本目录没有可构建的**其它**固件变体，也没有固件支持承诺。

## 目录内容

```text
nx30pro/
├─ README.md
├─ build/       # 设备构建、配置及镜像检查脚本
├─ files/       # 固件 rootfs 覆盖文件
├─ packages/    # 设备专属软件包
├─ patches/     # 设备专属补丁
├─ runtime/     # 设备运行脚本和库
├─ uboot/       # 配套 U-Boot 输入和说明
└─ docs/        # 初始化、运维和验证文档
```

尚未划分 Lite/Full 等变体。

## 系统固件（候选，未编译、未真机验证）

源码：`https://github.com/hanwckf/immortalwrt-mt798x`，锁定 commit
`740103d655bcee6da7bc3b49b1cfdfdee4cd5bb6`（分支 `openwrt-21.02` 仅供追溯），
Linux **5.4**；四个 feed（`packages`、`luci`、`routing`、`telephony`）同样固定到 commit。
被拒绝的旧底座 `jerryhan77/immortalwrt-mt798x`（revision
`78cf22edddf07443d8f0506c9f361d3498475189`，与 Galaxian 112M 参考树同源）只作为
**被拒绝的证据**与移植**参考**保留，不是构建输入。

源码锁状态是 `source-candidate-build-blocked`：`build/firmware_lock.py check` 以仓库统一的
构建未就绪状态码 **3** 拒绝它，`tools/manifest.py resolve --require-build-ready` 同样退出 3，
直到一次 `make defconfig` 探针被单独授权。

| 文件 | 职责 |
|---|---|
| `source-lock.json` | 锁定的系统源码 commit、四个 feed 的 revision、目标/profile、镜像规则、分区合同、软件包兼容表与未决项 |
| `config.config` | 设备层的原生 Kconfig 片段：唯一 profile、需求表中的软件包、刻意排除的软件包 |
| `feeds.conf` | 设备层 feed：四个 feed 固定到 commit |
| `patches/0001-mediatek-add-nx30pro-112m-profile.patch` | 移植 112M 设备树与 `h3c_nx30pro_112M` profile（锁定 commit 里没有） |
| `patches/0002-mediatek-nx30pro-wan-mac-source.patch` | 112M 布局没有 `pdt_data_1`，因此 WAN MAC 改从部署值/Factory/原厂分区依次取值，并且 `Factory` 只读 |
| `files/etc/uci-defaults/90-nx30pro-defaults` | 首次启动默认值：选中的服务全部默认关闭，WAN 区不开放路由器端口 |
| `files/etc/nx30pro/README` | 部署值目录说明（WAN MAC 不进入镜像） |
| `build/configure.sh` | 应用设备补丁、源码校验、按 `common -> distribution -> device` 合并配置层、`make defconfig`、审计最终 `.config`、扫描 overlay |
| `build/build.sh` | 锁门禁、拉取锁定源码与 feed、配置、下载、编译、镜像检查、产出 build-report；只构建，不刷写 |
| `build/firmware_lock.py` | 源码锁校验、设备树/镜像规则校验、配置层合并、最终配置审计、镜像检查与发布 |
| `docs/BUILD.md` | 可复现构建输入、逐阶段门禁、软件包合同、镜像角色与授权边界 |
| `docs/FLASH.md` | 刷写目标与前置条件（备份优先），不含任何写入命令 |
| `docs/RECOVERY.md` | 三种恢复场景、回退输入与停止条件 |
| `docs/TEST-REPORT.md` | 实际发生的验证记录；当前只有静态证据 |
| `docs/nx30pro-firmware-compatibility.md` | 已核实事实、软件包兼容表、源码级冲突与 UNRESOLVED 清单 |
| `docs/nx30pro-firmware-install-and-validation.md` | 备份、部署值录入、写入路径与真机验证顺序（未授权刷写） |

构建入口在 `.github/workflows/build-nx30pro.yml`（只有 `workflow_dispatch` 手动触发，
`permissions: contents: read`，不使用 Secrets，不含刷写命令）。
manifest `manifests/devices/nx30pro.json` 把设备登记到自带源码的分发 `immortalwrt-mt798x`。
**触发任何 Action、以及任何刷写，都需要用户单独、明确的授权。**

目标：MT7981 / `h3c_nx30pro_112M` profile，布局 `immortalwrt-112m`（**默认**，UBI 112 MiB），
镜像上限 108 MiB；备选布局 `default` 是原厂表，保留 `pdt_data`、`pdt_data_1`、`exp`、
`plugin`，切换到 112M 布局前必须先完成**整片闪存**与关键分区的只读**备份**。
分区合同与启动链是**同一份分区合同**，地址都是 NMBM 逻辑地址，不是物理 NAND 地址。

镜像两个角色：`factory.bin`（`ubi` 分区的原始 UBI 镜像，`append-ubi | check-size`）与
`sysupgrade.bin`（带元数据的 tar 包，供 LuCI 升级页与 `sysupgrade` 使用）。
两者都**不是启动链镜像**，也不能互换；启动链镜像是 BL2 与 FIP。最终文件名保持
UNRESOLVED（名字前缀含只在真实构建里解析的版本变量）。

首次启动默认值把所有选中的服务**默认关闭**：`passwall`、`passwall_server`、`ddns`、
`tailscale`、`zerotier`、`dockerd`、`cloudflared`、`frpc`、`nlbwmon`、`ttyd`、`sqm`、
`etherwake`；基线服务（`dnsmasq`、`network`、`firewall`、`system` 等）一个不碰，
overlay 也不附带 `/etc/config` 模板（避免丢掉 `loopback` 段），只用镜像里真有的
busybox 命令。镜像里没有账号、令牌、域名、密码或任何设备的 MAC。

透明代理用 PassWall 4.68 + xray（该底座没有 sing-box）；WireGuard 服务端保持
UNRESOLVED（backport 与 `KernelPackage/wireguard` 存在，但 5.4 出厂配置未开启，
可构建性未证）；Tailscale 只有命令行界面（锁定 luci feed 没有 `luci-app-tailscale`）。
详情见兼容性文档。

## U-Boot 启动链（源码已锁定，未构建、未真机验证）

来源：`https://github.com/Yuzhii0718/bl-mt798x-dhcpd`，锁定 commit
`e4cf4dc72d451dc7a86c9508390ad5a2e50743c4`，版本 `SP1`
（U-Boot 树 `uboot-mtk-20250711` + ATF 树 `atf-20240117-bacca82a8`，依据上游对
5.4 内核的配对说明）。旧来源 `hanwckf/bl-mt798x` 只作为被拒绝的证据保留。

| 文件 | 职责 |
|---|---|
| `uboot/uboot-source-lock.json` | 锁定的上游 commit、版本选择、板级配置、两套布局白名单、功能集、设备补丁、产物名字模式与未决项 |
| `uboot/patches/0001-nx30pro-restrict-recovery-ui.patch` | 使 `immortalwrt-112m` 成为默认布局，并关闭危险的网页恢复功能 |
| `build/build-uboot.sh` | 从锁定 commit 构建候选 BL2/FIP，输出 build-report 与 SHA256SUMS；只构建，不刷写 |
| `build/uboot_lock.py` | 源码锁校验、布局白名单校验、补丁合同校验、最终配置校验、镜像内容识别与发布 |
| `docs/UBOOT-BUILD.md` | 可复现构建输入、构建前后门禁、产物角色与授权边界 |
| `docs/UBOOT-TEST-REPORT.md` | 实际发生的验证记录；当前只有静态验证 |
| `docs/nx30pro-uboot-compatibility.md` | 已核实事实、两套分区表逐项对照、受限功能集与 UNRESOLVED 清单 |
| `docs/nx30pro-uboot-install-and-recovery.md` | 备份、安装、回退与真机验证设计（未授权刷写） |

构建入口在 `.github/workflows/build-nx30pro-uboot.yml`（只有 `workflow_dispatch`
手动触发，`contents: read`，不使用 Secrets，未授权前不得运行）。

关键结论：

- 锁定设备树已经携带两套布局：`immortalwrt-112m`（**默认**，UBI 112 MiB）与
  `default`（原厂，UBI 64 MiB，保留 `pdt_data`、`pdt_data_1`、`exp`、`plugin`）。
  分区表不需要补丁，`verify-layout-source` 直接对照源码校验，第三个标签会被拒绝。
- 启用的恢复功能：DHCP 服务器、Web failsafe、系统固件恢复、BL2 与 FIP 升级、TFTP、
  UART、整机与分区的只读备份。
- 关闭的功能：`CONFIG_WEBUI_FAILSAFE_FACTORY`、`CONFIG_WEBUI_FAILSAFE_FLASH`、
  `CONFIG_WEBUI_FAILSAFE_ENV`、`CONFIG_WEBUI_FAILSAFE_CONSOLE`、
  `CONFIG_WEBUI_FAILSAFE_UBI`、`CONFIG_WEBUI_FAILSAFE_SIMG`、`CONFIG_MTK_TELNETD`，
  以及任何 CPU/DDR 超频符号。网页选择器不提供自由 `mtdparts` 输入。
- 产物是 BL2 与 FIP，文件名含镜像 md5；两者都不是系统镜像。所有分区地址都是
  NMBM 逻辑地址，不是物理 NAND 地址。切换到 112M 布局前必须先完成只读备份。

待核实：厂商、精确型号及硬件修订、闪存容量与启动方式、本机 WAN MAC、软件包策略及验收硬件。
未知项保持 UNRESOLVED；不得复制其他设备的配置作为已验证事实。

现有设计参考：[固件计划](../../docs/superpowers/plans/2026-11-22-nx30pro-firmware-build.md)、[U-Boot 计划](../../docs/superpowers/plans/2026-11-22-nx30pro-uboot-build.md)。
