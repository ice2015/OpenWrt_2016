# NX30 Pro U-Boot 兼容性核实记录

状态：**源码已锁定，未构建、未真机验证**。本文只记录在锁定源码中可复核的事实，
以及仍然 UNRESOLVED 的项。候选产物在通过 Actions 构建与真机验证前不得当作可刷写发布包。

| 项 | 值 |
|---|---|
| 上游仓库 | `https://github.com/Yuzhii0718/bl-mt798x-dhcpd` |
| 锁定 commit | `e4cf4dc72d451dc7a86c9508390ad5a2e50743c4` |
| 版本选择 | `SP1`（U-Boot 树 `uboot-mtk-20250711` + ATF 树 `atf-20240117-bacca82a8`） |
| SoC / 板名 | `mt7981` / `h3c_magic-nx30-pro` |
| 设备补丁 | `devices/nx30pro/uboot/patches/0001-nx30pro-restrict-recovery-ui.patch` |
| 机器可读合同 | `devices/nx30pro/uboot/uboot-source-lock.json` |

被拒绝的旧来源：`https://github.com/hanwckf/bl-mt798x`（commit
`36916669d0874306638196c5327a20c2ef215bed`）。它没有 DHCPD 网页恢复，也没有本板的
multi layout defconfig，无法提供锁定的布局白名单；它只作为失败证据保留。

## 1. 构建入口与版本选择

`build.sh` 把 `VERSION` 映射到实际编译的树：`2025` → `atf-20250711`，
`SP1` → `atf-20240117-bacca82a8`，`SP2` → `atf-20260123`；U-Boot 树始终是
`uboot-mtk-20250711`。

选择 `SP1` 的证据（上游 `README.md`，锁定 commit 内）：

> If you are using the 5.4 kernel or encounter issues such as `hwrng wrong`, try using
> the SP1 version or enable `_MT7986_TRNG_NS_ACCESS` in the ATF configuration.

本设备第一版固件是 Linux 5.4，因此优先采用 SP1 配对。这是上游文档证据，
**不是**本机启动日志；SP1 ATF 与 5.4 固件的真实启动兼容性保持 UNRESOLVED。

`build.sh` 还要求 `npm`：它在编译前先对 `failsafe/embedded` 的网页资源执行
`npm install` 与压缩，缺少 npm 会在环境检查阶段停止。

## 2. 板级配置核实

锁定 commit 中存在两份板级 defconfig：

| 文件 | 用途 |
|---|---|
| `uboot-mtk-20250711/configs/mt7981_h3c_magic-nx30-pro_defconfig` | 单布局，携带固定 `CONFIG_MTDPARTS_DEFAULT`（原厂表） |
| `uboot-mtk-20250711/configs/mt7981_h3c_magic-nx30-pro_multi_layout_defconfig` | 多布局，启用 `CONFIG_MEDIATEK_MULTI_MTD_LAYOUT`，不带 `CONFIG_MTDPARTS_DEFAULT`，分区表来自设备树 |

本构建锁定 `MULTI_LAYOUT=1` 与 `FIXED_MTDPARTS=1`，因此使用多布局 defconfig。
上游明确拒绝 `MULTI_LAYOUT=1` 与 `FIXED_MTDPARTS=0` 的组合。

需要注意的上游行为：当多布局 defconfig 缺失时，`build.sh` 会在 `SILENT=Y` 下**静默降级**
到单布局 defconfig，从而构建出原厂分区表。因此 `build-uboot.sh` 的 preflight 先断言
多布局 defconfig 与设备树存在，`verify-config` 再断言最终 `.config` 携带
`CONFIG_MEDIATEK_MULTI_MTD_LAYOUT=y` 且不携带原厂 `CONFIG_MTDPARTS_DEFAULT`。

按键入口：两份 defconfig 都启用 `CONFIG_CMD_GL_BTN=y` 与 `CONFIG_BUTTON_GPIO=y`，
设备树定义 `button-reset` 与 `button-mesh`。实际按键时序仍需真机记录（UNRESOLVED）。

DRAM 类型：SP1 ATF 的 DRAM 初始化是 MediaTek 预编译对象，本仓库没有该配对的
启动日志证据，因此 DDR 类型与容量保持 UNRESOLVED，不从旧候选抄写。

## 3. 分区合同（两套布局，同一来源）

来源：`uboot-mtk-20250711/arch/arm/dts/mt7981-h3c_magic-nx30-pro.dts` 的 `/mtd-layout`
节点。`uboot_lock.py verify-layout-source` 直接读取该文件并与锁比对；
上游没有的布局不会被合成，出现第三个标签会直接失败。

| 布局标签 | mtdparts |
|---|---|
| `immortalwrt-112m`（**默认**） | `nmbm0:1024k(bl2),512k(u-boot-env),2048k(Factory),2048k(fip),112M(ubi)` |
| `default`（备选，原厂） | `nmbm0:1024k(bl2),512k(u-boot-env),2048k(Factory),2048k(fip),65536k(ubi),6144k(pdt_data),6144k(pdt_data_1),1024k(exp),38400k(plugin)` |

所有地址都是 **NMBM 逻辑地址**，不是物理 NAND 地址。

112M 布局逐项（NMBM 逻辑偏移）：

| 分区 | 偏移 | 大小 |
|---|---|---|
| bl2 | `0x000000` | 1 MiB |
| u-boot-env | `0x100000` | 512 KiB |
| Factory | `0x180000` | 2 MiB |
| fip | `0x380000` | 2 MiB |
| ubi | `0x580000` | 112 MiB |

两套布局的 bl2、u-boot-env、Factory、fip 偏移与大小完全一致，差异只在 UBI 及其后
的 OEM 区域：

| 分区 | 原厂 `default` | `immortalwrt-112m` | 影响 |
|---|---|---|---|
| ubi | 64 MiB | 112 MiB | 原厂布局装不下 112M 系统的 factory 镜像 |
| pdt_data | 6 MiB | 不存在 | 被 UBI 回收 |
| pdt_data_1 | 6 MiB | 不存在 | 被 UBI 回收；配对固件必须在没有它的情况下取得 WAN MAC |
| exp | 1 MiB | 不存在 | 被 UBI 回收 |
| plugin | 37.5 MiB | 不存在 | 被 UBI 回收 |

布局表末尾空间：112M 布局止于 `0x7580000`，原厂布局止于 `0x7800000`（合计 122880 KiB）。
两者相差 2.5 MiB，这是从两张源码表**推导**出来的，不是设备读数；NMBM 报告的可用容量
取决于映射的块数，真实设备可能更小。要求是逻辑末尾至少达到 `0x7580000`，
在读取设备前保持 UNRESOLVED。

**切换即数据损失**：从 `default` 切到 `immortalwrt-112m` 会把 `pdt_data`、`pdt_data_1`、
`exp`、`plugin` 划入 UBI。切换前必须完成整片闪存的只读**备份**；112M 布局本身无法还原
这些区域。设备补丁因此在网页选择器上加入了确认与数据损失警告。

## 4. 设备补丁的作用范围

补丁 `0001-nx30pro-restrict-recovery-ui.patch` 只做三件事：

1. `board/mediatek/Kconfig` 新增 `CONFIG_MTK_DEFAULT_MTD_LAYOUT`（字符串，依赖
   `MEDIATEK_MULTI_MTD_LAYOUT`，默认 `default`），`board/mediatek/common/mtd_layout.c`
   用它替换四处硬编码的 `default` 回退标签。上游没有任何开关能让非 `default`
   标签成为默认布局，而两个布局标签必须原样保留，所以只能新增这个最小开关。
2. 两份板级 defconfig 关闭危险功能（见第 5 节），其中多布局 defconfig 另外设置
   `CONFIG_MTK_DEFAULT_MTD_LAYOUT="immortalwrt-112m"`。单布局 defconfig 一起加固，
   因为上游会静默降级到它。
3. bootstrap 网页 UI 记录当前布局，并在离开 `default` 前弹出确认，明确列出会被回收的
   `pdt_data`、`pdt_data_1`、`exp`、`plugin`。

补丁**不改**任何分区表：两套布局已经存在于锁定的设备树中，由
`verify-layout-source` 对照源码校验。`verify-patch` 会拒绝任何新增第三个布局标签、
暴露自由 `mtdparts` 输入、写任意环境变量或重新启用危险功能的补丁。

## 5. 受限恢复功能集

启用（最终 `.config` 必须为 `=y`）：

| 功能 | 符号 |
|---|---|
| DHCP 服务器 | `CONFIG_MTK_DHCPD` |
| Web failsafe 入口 | `CONFIG_MTK_WEB_FAILSAFE`、`CONFIG_MTK_WEB_FAILSAFE_AFTER_BOOT_FAILURE`、`CONFIG_WEBUI_FAILSAFE` |
| 只读备份下载 | `CONFIG_WEBUI_FAILSAFE_ADVANCED`、`CONFIG_WEBUI_FAILSAFE_BACKUP` |
| 系统固件恢复 | `CONFIG_MTK_UBI_SUPPORT` |
| BL2/FIP 升级 | `CONFIG_MTK_UPGRADE_BL2_VERIFY` |
| TFTP | `CONFIG_CMD_TFTPPUT`、`CONFIG_CMD_PING` |
| UART | `CONFIG_DEBUG_UART`、`CONFIG_MTK_SERIAL` |
| 布局白名单 | `CONFIG_MEDIATEK_MULTI_MTD_LAYOUT`、`CONFIG_MTK_FIXED_MTD_MTDPARTS`、`CONFIG_MTK_DEFAULT_MTD_LAYOUT="immortalwrt-112m"` |
| NMBM | `CONFIG_ENABLE_NAND_NMBM` |

关闭（出现即为构建失败）：

| 功能 | 符号 | 原因 |
|---|---|---|
| Factory 写入 | `CONFIG_WEBUI_FAILSAFE_FACTORY` | 出厂校准区不得从浏览器改写 |
| Flash Editor | `CONFIG_WEBUI_FAILSAFE_FLASH` | 任意范围读写是不可恢复的变砖路径 |
| NAND 原始/OOB 写入 | `CONFIG_WEBUI_FAILSAFE_NAND_RAW` | 依附于 Flash Editor |
| 环境变量管理 | `CONFIG_WEBUI_FAILSAFE_ENV`、`CONFIG_WEBUI_FAILSAFE_ENV_CUSTOM_ENV` | 通用环境编辑等于任意 `mtdparts` 与任意启动命令 |
| Web 终端 | `CONFIG_WEBUI_FAILSAFE_CONSOLE` | 网络远程代码执行 |
| Telnet | `CONFIG_MTK_TELNETD` | 第二条未认证远程 shell |
| UBI 卷管理 | `CONFIG_WEBUI_FAILSAFE_UBI` | 可破坏所选布局的系统卷 |
| 单镜像（ROM dump）升级 | `CONFIG_WEBUI_FAILSAFE_SIMG` | 整片写入不是恢复路径 |
| GPT 改写 | `CONFIG_WEBUI_FAILSAFE_GPT` | 不适用于本 SPI-NAND 板 |
| CPU/DDR 超频 | 无对应符号 | 锁定树中没有 MediaTek 超频 Kconfig；`verify-config` 仍会拒绝任何名字含 OVERCLOCK 或 CPU/DDR/DRAM 频率的已启用符号 |

依据：`failsafe/Kconfig` 为每个危险页面提供独立开关，`failsafe/failsafe_core.c` 只在
符号打开时注册对应 handler，因此关闭符号同时移除了路由。`verify-config` 检查的是
`olddefconfig` 之后的最终 `.config`，不是传给 `build.sh` 的环境变量。

网页选择器只提供设备树中的两个标签；上游的 `custom` 项只有在存在
`mtd_layout_custom` 环境变量时才出现，而该变量只能由被关闭的环境管理器或 UART 写入。

## 6. NMBM 几何

| 项 | 值 | 依据 |
|---|---|---|
| NMBM | 启用 | 多布局 defconfig 的 `CONFIG_ENABLE_NAND_NMBM=y` |
| 管理块比例 | 1（1/16） | `board/mediatek/Kconfig` 的 `NMBM_MAX_RATIO` 默认值，板级 defconfig 未覆盖 |
| 最大保留块 | 256 | 同上，`NMBM_MAX_BLOCKS` 默认值 |
| 与系统侧几何是否一致 | UNRESOLVED | 系统侧取决于尚未锁定的固件源码 |

## 7. 网页恢复入口

| 项 | 值 |
|---|---|
| 地址 | `http://192.168.1.1/`，端口 80 |
| 来源 | 板级 defconfig 的 `CONFIG_IPADDR="192.168.1.1"`、`CONFIG_NETMASK="255.255.255.0"` |
| 自动进入 | `CONFIG_MTK_WEB_FAILSAFE_AFTER_BOOT_FAILURE=y`，`mtkboardboot` 启动失败时自动开启 |
| 可上传的启动链镜像 | `bl2`、`fip` |
| 可上传的系统镜像 | `firmware`、`initramfs` |
| 目标分区名 | `bl2`、`fip`（`board/mediatek/common/bootmenu_common.h` 的 `PART_BL2_NAME`、`PART_FIP_NAME`） |
| BL2 校验 | 开启（`CONFIG_MTK_UPGRADE_BL2_VERIFY=y`，设备树带 `bl2_verify` 节点，`bl2_compatible = "spim-nand"`） |
| FIP/系统镜像校验 | 未开启（板级 defconfig 显式关闭 `CONFIG_MTK_UPGRADE_IMAGE_VERIFY`，未设置 `CONFIG_MTK_UPGRADE_FIP_VERIFY`），只有写入后回读校验 |

回读校验只能证明写入的字节与上传的一致，**不能**证明镜像本身正确；镜像正确性由构建
报告与内容识别保证。这些入口也**不能替代**独立恢复路径。

## 8. 产物区分

`build.sh` 把镜像的 md5 写进文件名，因此每次构建名字都不同；锁里记录的是名字模式：

| 角色 | 名字模式 | 写入目标 |
|---|---|---|
| ATF FIP（含 BL31 与 BL33/U-Boot） | `output/fip-mt7981_h3c_magic-nx30-pro_SP1-Yuzhii-dhcpd-fixed-parts-multi-layout_md5-*.bin` | `fip` 分区 |
| MediaTek BL2 预加载镜像 | `output/bl2-mt7981_h3c_magic-nx30-pro_SP1_md5-*.img` | `bl2` 分区 |

两者都**不是系统镜像**，单独一个也不构成恢复镜像。构建产物按内容识别（FIP 目录头与
BL31/BL33 条目、BL2 的 `SPINAND!` 启动头），并按分区大小校验；系统镜像不匹配任何
启动链模式，因此不可能被当作 BL2/FIP 发布。SHA-256 与工具链身份写入 `build-report.json`。

## 9. 与配对固件的源码级依赖

| 议题 | 状态 |
|---|---|
| WAN MAC 来源 | UNRESOLVED：新固件源码尚未锁定；112M 布局没有 `pdt_data_1`，配对固件必须在没有它的情况下取得 WAN MAC |
| Wi-Fi MAC 与校准数据 | UNRESOLVED：旧候选在首次启动时可能改写 `Factory` 偏移 4，新固件必须证明不会，否则先备份 `Factory` |

## 10. 仍然未决的项（UNRESOLVED）

1. NAND 芯片型号、容量与坏块布局；
2. DDR 类型与容量（SP1 ATF 配对）；
3. SP1 ATF 与 Linux 5.4 固件的真实启动兼容性；
4. 112M 布局之后 2.5 MiB 空间的用途；
5. `pdt_data`、`pdt_data_1`、`exp`、`plugin` 的内容与重要性；
6. 工具链确切版本与校验和；
7. 产物逐字节可复现性（上游把时间戳与 md5 写进产物/文件名）；
8. 真机启动行为、恢复入口时序、MAC 与校准数据处理。

在第 3、7、8 项完成前，本目录的 U-Boot 产物只能标记为“候选、未真机验证”。
