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

## 系统固件（候选，未真机验证）

| 文件 | 职责 |
|---|---|
| `source-lock.json` | 锁定的系统源码 commit、四个 feed 的 revision、目标/profile、镜像规则、分区合同、软件包兼容表与未决项 |
| `config.config` | 设备层的原生 Kconfig 片段：唯一 profile、需求表中的软件包、刻意排除的软件包 |
| `feeds.conf` | 设备层 feed：四个 feed 固定到 commit |
| `patches/0001-mediatek-nx30pro-wan-mac-source.patch` | 112M 布局没有 `pdt_data_1`，因此 WAN MAC 改从部署值/Factory/原厂分区依次取值 |
| `files/etc/uci-defaults/90-nx30pro-defaults` | 首次启动默认值：所有服务默认关闭，WAN 区不开放路由器端口 |
| `files/etc/nx30pro/README` | 部署值目录说明（WAN MAC 不进入镜像） |
| `build/configure.sh` | 合并设备层、应用设备补丁、`make defconfig`、按最终 `.config` 校验 |
| `build/build.sh` | 拉取锁定源码与 feed、配置、编译、产出镜像与 build-report；只构建，不刷写 |
| `build/firmware_lock.py` | 源码锁校验、最终配置校验与构建报告 |
| `docs/nx30pro-firmware-compatibility.md` | 已核实事实、软件包兼容表、源码级冲突与 UNRESOLVED 清单 |
| `docs/nx30pro-firmware-install-and-validation.md` | 备份、部署值录入、写入路径与真机验证顺序（未授权刷写） |

构建入口在 `.github/workflows/build-nx30pro.yml`（手动触发，`contents: read`，不使用 Secrets）。
manifest `manifests/devices/nx30pro.json` 把设备登记到自带源码的分发 `immortalwrt-mt798x`。

目标：MT7981 / `h3c_nx30pro_112M` profile，112 MiB UBI 布局，镜像上限 108 MiB。
透明代理用 PassWall + xray（该底座没有 sing-box）；WireGuard 服务端在该底座不可用；
Tailscale 只有命令行界面。详情见兼容性文档。

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
