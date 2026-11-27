# NX30 Pro 受限恢复 U-Boot 构建说明

状态：**静态实现完成，未编译、未真机验证**。本文描述可复现的构建输入、门禁与产物，
以及触发远程构建所需的授权边界。

| 项 | 值 |
|---|---|
| 上游仓库 | `https://github.com/Yuzhii0718/bl-mt798x-dhcpd` |
| 锁定 commit | `e4cf4dc72d451dc7a86c9508390ad5a2e50743c4` |
| 版本 / 树 | `SP1`：U-Boot `uboot-mtk-20250711` + ATF `atf-20240117-bacca82a8` |
| SoC / 板名 | `mt7981` / `h3c_magic-nx30-pro` |
| 布局 | `immortalwrt-112m`（**默认**）与 `default`（原厂备选），共两个，不可增删 |
| 源码锁 | `devices/nx30pro/uboot/uboot-source-lock.json` |
| 设备补丁 | `devices/nx30pro/uboot/patches/0001-nx30pro-restrict-recovery-ui.patch` |

## 1. 构建入口

```sh
# 只校验源码锁并打印构建计划，不获取源码、不编译、不产出镜像
sh devices/nx30pro/build/build-uboot.sh \
  --lock devices/nx30pro/uboot/uboot-source-lock.json --check-only

# 完整候选构建（需要已按锁定 commit 检出的源码树）
sh devices/nx30pro/build/build-uboot.sh \
  --lock devices/nx30pro/uboot/uboot-source-lock.json \
  --source-dir <锁定 commit 的检出目录> \
  --artifact-dir <产物目录> \
  --repo-root <本仓库根目录>
```

构建参数来自源码锁，不来自调用方环境：`SOC=mt7981`、`BOARD=h3c_magic-nx30-pro`、
`VERSION=SP1`、`VARIANT=default`、`MULTI_LAYOUT=1`、`FIXED_MTDPARTS=1`、`SILENT=Y`，
以及 `SIMG=0`、`UBIMNG=0`、`TELNETD=0`、`NAND_RAW=0`、`FIP_COMPRESS=0`。

主机依赖（源码锁 `host_packages`）：`build-essential`、`device-tree-compiler`、`flex`、
`bison`、`libssl-dev`、`python3`、`gcc-aarch64-linux-gnu`、`npm`。其中 `npm` 不可省略：
上游 `build.sh` 在编译前会对 `failsafe/embedded` 执行 `npm install` 与网页资源压缩。

## 1.1 锁定的分区布局

两套布局都来自锁定 commit 的
`uboot-mtk-20250711/arch/arm/dts/mt7981-h3c_magic-nx30-pro.dts`，地址均为 **NMBM 逻辑地址**：

| 标签 | mtdparts |
|---|---|
| `immortalwrt-112m`（**默认**） | `nmbm0:1024k(bl2),512k(u-boot-env),2048k(Factory),2048k(fip),112M(ubi)` |
| `default`（原厂备选） | `nmbm0:1024k(bl2),512k(u-boot-env),2048k(Factory),2048k(fip),65536k(ubi),6144k(pdt_data),6144k(pdt_data_1),1024k(exp),38400k(plugin)` |

两套表的 bl2、u-boot-env、Factory、fip 完全一致，差异只在 UBI 与其后的 OEM 区域。
切换到 `immortalwrt-112m` 会回收 `pdt_data`、`pdt_data_1`、`exp`、`plugin`，
因此必须先完成只读**备份**。

## 2. 构建前门禁（全部通过才会调用上游 build.sh）

| 顺序 | 门禁 | 命令 | 证据 |
|---|---|---|---|
| 1 | 源码锁可构建（完整 commit、树、版本、布局、功能、产物模式、主机依赖） | `uboot_lock.py check` | `logs/build-plan.json` |
| 2 | 检出就是锁定 commit；`build.sh` 对 `SP1` 真的编译锁定的两棵树；板级 defconfig、多布局 defconfig 与设备树存在；工作区干净；无上次构建残留 | `uboot_lock.py preflight` | `logs/preflight.json` |
| 3 | 设备树携带且只携带锁定的两套布局，地址空间是 NMBM 逻辑设备 | `uboot_lock.py verify-layout-source` | `logs/layout-source.json` |
| 4 | 设备补丁满足恢复合同（不新增布局、不暴露自由 `mtdparts`、不写任意环境变量、默认 `immortalwrt-112m`、切换前有警告），并且能应用到该检出 | `uboot_lock.py verify-patch` | `logs/device-patch-verify.json` |
| 5 | 应用设备补丁 | `uboot_lock.py patch` | `logs/device-patch.json` |
| 6 | 交叉编译器存在并记录身份 | `uboot_lock.py toolchain` | `logs/toolchain.json` |

第 2 项特别针对上游行为：多布局 defconfig 缺失时 `build.sh` 会静默降级到单布局
defconfig 并构建出原厂分区表，因此在获取源码之后、编译之前就必须断言该文件存在。

## 3. 构建后门禁

| 门禁 | 命令 | 证据 |
|---|---|---|
| 最终 `.config` 携带锁定的功能集与默认布局，不含危险功能与超频符号 | `uboot_lock.py verify-config` | `logs/effective-config.json` |
| 产物按锁定模式解析，缺失/为空/重名/超分区大小/结构不符即失败 | `uboot_lock.py artifacts` | `logs/artifacts.json` |
| 发布镜像、SHA256SUMS、构建报告、锁副本与写入目标说明 | `uboot_lock.py publish` | `images/`、`build-report.json` |

`verify-config` 检查的是 `olddefconfig` 之后的最终配置，不是传给 `build.sh` 的环境变量。

启用的恢复功能：DHCP 服务器、Web failsafe、系统固件恢复、BL2 与 FIP 升级、TFTP、
UART、整机与分区的只读备份。关闭的功能：`CONFIG_WEBUI_FAILSAFE_FACTORY`（Factory 写入）、
`CONFIG_WEBUI_FAILSAFE_FLASH`（Flash Editor）、`CONFIG_WEBUI_FAILSAFE_ENV`（通用环境编辑）、
`CONFIG_WEBUI_FAILSAFE_CONSOLE`（Web 终端）、`CONFIG_MTK_TELNETD`（Telnet）、
`CONFIG_WEBUI_FAILSAFE_UBI`（UBI 卷管理）、`CONFIG_WEBUI_FAILSAFE_SIMG`、
`CONFIG_WEBUI_FAILSAFE_NAND_RAW`，以及任何 CPU/DDR 超频符号（锁定树中不存在该类符号，
校验仍会拒绝）。

## 4. 产物

| 角色 | 名字模式 | 写入目标（NMBM 逻辑地址） |
|---|---|---|
| ATF FIP（BL31 + BL33/U-Boot） | `fip-mt7981_h3c_magic-nx30-pro_SP1-Yuzhii-dhcpd-fixed-parts-multi-layout_md5-*.bin` | `fip`，`0x380000`，2 MiB |
| BL2 预加载镜像 | `bl2-mt7981_h3c_magic-nx30-pro_SP1_md5-*.img` | `bl2`，`0x000000`，1 MiB |

上游把镜像的 md5 写进文件名，因此文件名每次构建都不同；锁记录的是模式，构建时按
模式解析实际文件。两者都**不是系统镜像**，也不能单独充当恢复镜像。地址均为
**NMBM 逻辑地址**，不是物理 NAND 地址。

产物目录结构：

```text
<artifact-dir>/
├─ images/                 # BL2、FIP 与 SHA256SUMS
├─ logs/                   # 上表每一道门禁的 JSON 证据与 build.log
├─ build-report.json       # 源码 commit、树、工具链身份、构建参数、分区表、镜像 sha256
├─ uboot-source-lock.json  # 本次构建使用的锁副本
└─ FLASH-TARGETS.txt       # 写入目标说明与备份前置条件
```

## 5. 远程构建与授权

工作流 `.github/workflows/build-nx30pro-uboot.yml` 只有 `workflow_dispatch` 手动入口，
`permissions: contents: read`，不使用 Secrets，不含任何刷写、擦除或设备命令。它的步骤是：
安装锁中列出的主机依赖 → 运行仓库静态校验与锁门禁 → 克隆并检出锁定 commit →
调用上表的构建入口 → 仅在成功时上传候选产物，`if: always()` 上传日志。

**触发该工作流需要用户单独、明确的授权。** 静态测试通过不等于构建成功，
候选构建成功不等于真机可用。运行结果、run ID 与产物证据记录在
[`UBOOT-TEST-REPORT.md`](UBOOT-TEST-REPORT.md)。

## 6. 切换布局的前置条件

从 `default` 切换到 `immortalwrt-112m` 会把 `pdt_data`、`pdt_data_1`、`exp`、`plugin`
划入 UBI。切换前必须：

1. 完成整片闪存与关键分区的只读**备份**并校验（见
   [`nx30pro-uboot-install-and-recovery.md`](nx30pro-uboot-install-and-recovery.md)）；
2. 确认存在一条不依赖候选启动链的独立恢复路径；
3. 得到用户对写入动作的明确授权。

网页选择器只列出这两个标签，并在离开原厂布局前要求确认。

## 7. 未决项（UNRESOLVED）

NAND 型号与容量、DDR 类型、SP1 ATF 与 Linux 5.4 固件的真实启动兼容性、
112M 布局之后 2.5 MiB 空间的用途、OEM 区域内容、工具链确切版本与校验和、
产物逐字节可复现性、真机恢复时序与 MAC/校准数据处理，全部保持 UNRESOLVED。
详见 [`nx30pro-uboot-compatibility.md`](nx30pro-uboot-compatibility.md)。
