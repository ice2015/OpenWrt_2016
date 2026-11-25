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

## U-Boot 启动链（候选，未真机验证）

| 文件 | 职责 |
|---|---|
| `uboot/uboot-source-lock.json` | 锁定的上游 commit、板级配置、分区合同、NMBM 几何、网页恢复入口与未决项 |
| `build/build-uboot.sh` | 从锁定 commit 构建候选 BL2/FIP，输出 build-report 与 SHA256SUMS；只构建，不刷写 |
| `build/uboot_lock.py` | 源码锁校验、镜像内容识别（ATF FIP 表头、MediaTek BL2 启动头）与构建报告 |
| `docs/nx30pro-uboot-compatibility.md` | 已核实事实、分区合同逐项对照、最小设备补丁与 UNRESOLVED 清单 |
| `docs/nx30pro-uboot-install-and-recovery.md` | 备份、安装、回退与真机验证设计（未授权刷写） |

构建入口在 `.github/workflows/build-nx30pro-uboot.yml`（手动触发，`contents: read`，不使用 Secrets）。

关键结论：上游 U-Boot 的固定分区表是原厂布局（UBI 64 MiB），与所选 112M 系统布局不一致；
本目录用一条设备级 `CONFIG_MTDPARTS_DEFAULT` 补丁对齐，细节与证据见兼容性文档。

待核实：厂商、精确型号及硬件修订、闪存容量与启动方式、本机 WAN MAC、软件包策略及验收硬件。
未知项保持 UNRESOLVED；不得复制其他设备的配置作为已验证事实。

现有设计参考：[固件计划](../../docs/superpowers/plans/2026-11-22-nx30pro-firmware-build.md)、[U-Boot 计划](../../docs/superpowers/plans/2026-11-22-nx30pro-uboot-build.md)。
