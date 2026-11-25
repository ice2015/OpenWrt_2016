# NX30 Pro U-Boot 兼容性核实记录

状态：**候选、未真机验证**。本文只记录在锁定 commit 上核实到的源码事实与仍然未决的项。
本文不构成刷写许可，也不代表任何镜像可以在本机设备上工作。

- 设备：H3C Magic NX30 Pro（MT7981，SPI-NAND，128 MiB 级设备树分区）。
- 候选启动源码：<https://github.com/hanwckf/bl-mt798x>，锁定 commit
  `36916669d0874306638196c5327a20c2ef215bed`（master）。
- 配套系统源码：`jerryhan77/immortalwrt-mt798x`，锁定 commit
  `78cf22edddf07443d8f0506c9f361d3498475189`（`nx30pro-112m` 分支）。
- 机器可读锁文件：[`../uboot/uboot-source-lock.json`](../uboot/uboot-source-lock.json)。

## 1. 真实板名与构建入口

| 项 | 核实值 | 来源 |
|---|---|---|
| SoC | `mt7981` | `build.sh` 的 `SOC` 用法 |
| 板名 | `h3c_magic-nx30-pro` | 上游 ATF/U-Boot defconfig 文件名 |
| ATF 目录 | `atf-20240117-bacca82a8` | `build.sh` 中 `ATF_DIR` |
| U-Boot 目录 | `uboot-mtk-20230718-09eda825` | `build.sh` 中 `UBOOT_DIR` |
| ATF defconfig | `atf-20240117-bacca82a8/configs/mt7981_h3c_magic-nx30-pro_defconfig` | 内容仅 `_PLAT_MT7981=y`、`_MT7981_BOARD_BGA=y`、`_LOG_LEVEL_INFO=y` |
| U-Boot defconfig | `uboot-mtk-20230718-09eda825/configs/mt7981_h3c_magic-nx30-pro_defconfig` | 见第 3 节 |
| U-Boot DTS | `uboot-mtk-20230718-09eda825/arch/arm/dts/mt7981-h3c_magic-nx30-pro.dts` | `model = "mt7981-h3c_magic-nx30-pro"` |

构建命令固定为 `SOC=mt7981 BOARD=h3c_magic-nx30-pro FIXED_MTDPARTS=1 MULTI_LAYOUT=0 ./build.sh`。
`MULTI_LAYOUT=0` 是硬性限制：上游没有 `mt7981_h3c_magic-nx30-pro_multi_layout_defconfig`，
该板无法构建多布局变体。

上游仓库在锁定 commit 处没有 tag，`20241115` 是 release tag（commit
`15ad0ed949043bcbbcb5ef501ba156b1f25e676f`）。两者的 U-Boot 板级 defconfig **逐字节相同**；
release 只在 ATF 目录上更旧（`atf-20231013-0ea67d76a`）。因此 release 不能证明 112M 布局兼容，
只能作为调查线索（见第 8 节）。

## 2. 工具链

上游 `build.sh` 使用宿主机的 `aarch64-linux-gnu-` 交叉工具链（`CROSS_COMPILE=aarch64-linux-gnu-`），
**上游不提供工具链版本或校验和**。因此：

- 锁文件只记录来源（Ubuntu 24.04 的 `gcc-aarch64-linux-gnu`）与前缀，版本与校验和保持 `UNRESOLVED`；
- 真正的版本证据只能来自构建报告，由构建脚本在编译时记录 `gcc --version` 与 dpkg 包版本；
- 换用不同工具链版本会改变产物字节，比较两次构建前必须先比对记录的工具链版本。

宿主依赖来自上游 README 与 ATF 文档：`gcc-aarch64-linux-gnu`、`build-essential`、
`device-tree-compiler`、`flex`、`bison`、`libssl-dev`、`python3`。

## 3. 板级配置核实

来自 `mt7981_h3c_magic-nx30-pro_defconfig` 与板级 DTS 的已确认事实：

| 项 | 值 | 来源 |
|---|---|---|
| 内存 | 256 MiB（`0x40000000` + `0x10000000`） | U-Boot DTS `memory@40000000` |
| 启动介质 | SPI-NAND | DTS `spi_nand@0`；`bl2_verify` 节点 `compatible = "spim-nand"` |
| NAND 支持 | `CONFIG_MTD_SPI_NAND=y` | U-Boot defconfig |
| NMBM | `CONFIG_ENABLE_NAND_NMBM=y` | U-Boot defconfig |
| 环境分区 | `CONFIG_ENV_MTD_NAME="u-boot-env"`、`CONFIG_ENV_IS_IN_MTD=y`、`CONFIG_ENV_OFFSET=0x0` | U-Boot defconfig |
| UBI 支持 | `CONFIG_MTK_UBI_SUPPORT=y` | U-Boot defconfig |
| BL2 校验 | `CONFIG_MTK_UPGRADE_BL2_VERIFY=y` | U-Boot defconfig |
| FIP/系统镜像校验 | `CONFIG_MTK_UPGRADE_IMAGE_VERIFY` 未开启；`CONFIG_MTK_UPGRADE_FIP_VERIFY` 默认 `n` | U-Boot Kconfig |
| 固定分区表 | `CONFIG_MTK_FIXED_MTD_MTDPARTS`（由 `FIXED_MTDPARTS=1` 追加） | `board/mediatek/Kconfig`、`board/mediatek/common/mtd_helper.c` |
| DDR 类型 | 由 ATF 预编译 DRAM 初始化块运行时判定，编译期未开 `DRAM_USE_DDR4` | `plat/mediatek/mt7981/drivers/dram/emicfg.c` |

`build.sh` 追加的 `CONFIG_MEDIATEK_UBI_FIXED_MTDPARTS=y` 在该 U-Boot 树中**没有对应 Kconfig 符号**，
`make olddefconfig` 会丢弃它；产物名里的 `-fixed-parts` 只来自 `CONFIG_MTK_FIXED_MTD_MTDPARTS`。
这一点记录在锁文件的 `build_env_notes` 中，避免以后误读产物名。

## 4. 分区合同逐项对照

合同来源是所选系统的 112M 设备树
`target/linux/mediatek/files-5.4/arch/arm64/boot/dts/mediatek/mt7981-h3c-nx30pro-112M.dts`。

| 分区 | 合同（112M） | 上游 U-Boot 固定分区表 | 一致？ |
|---|---|---|---|
| BL2 | `0x000000` / `0x100000` | `bl2` 1024k @ 0 | 是 |
| u-boot-env | `0x100000` / `0x080000` | `u-boot-env` 512k @ 0x100000 | 是 |
| Factory | `0x180000` / `0x200000` | `Factory` 2048k @ 0x180000 | 是 |
| FIP | `0x380000` / `0x200000` | `fip` 2048k @ 0x380000 | 是 |
| ubi | `0x580000` / `0x7000000`（112 MiB） | `ubi` 65536k（64 MiB） | **否** |
| pdt_data | 未定义 | 6144k @ 0x4580000（只读） | **否** |
| pdt_data_1 | 未定义 | 6144k @ 0x4b80000（只读） | **否** |
| exp | 未定义 | 1024k @ 0x5180000 | **否** |
| plugin | 未定义 | 38400k @ 0x5280000 | **否** |

上游固定分区表原文：

```text
nmbm0:1024k(bl2),512k(u-boot-env),2048k(Factory),2048k(fip),65536k(ubi),6144k(pdt_data),6144k(pdt_data_1),1024k(exp),38400k(plugin)
```

四个前置分区的偏移与大小完全一致，分歧只在 UBI 容量和尾部四个 OEM 分区。
所选系统的工厂镜像是 `IMAGE_SIZE := 110592k`（108 MiB），**装不进上游 64 MiB 的 ubi 分区**；
因此上游原样构建的 U-Boot 与 112M 系统布局不匹配，不能直接作为配套启动链。

同一系统仓库里的非 112M 设备树 `mt7981-h3c-nx30pro.dts` 描述的正是上游这套分区表
（ubi 64 MiB + 四个 OEM 分区），即：**上游 U-Boot 与上游原厂系统彼此一致，两者同时与 112M 布局不一致**。

112M 布局结束于 `0x7580000`（117.5 MiB），其后到 NMBM 逻辑末端 `0x7800000` 还有 2.5 MiB，
两端源码都没有给出用途，按计划要求保持未决，不做自行分配。

## 5. 最小设备补丁

不一致项只用一个设备级改动处理，不套用其他设备的参数：

```text
CONFIG_MTDPARTS_DEFAULT="nmbm0:1024k(bl2),512k(u-boot-env),2048k(Factory),2048k(fip),114688k(ubi)"
```

- 目标文件：`uboot-mtk-20230718-09eda825/configs/mt7981_h3c_magic-nx30-pro_defconfig`；
- 作用域：仅构建副本中的设备级输入，锁文件里的上游源码保持原样；
- 依据：BL2 / u-boot-env / Factory / FIP 的偏移与大小沿用合同；ubi 扩到 114688k（112 MiB）；
  尾部四个 OEM 分区在 112M 布局中不存在，故不保留；
- 该分区表总长 120320k（117.5 MiB），小于上游原厂表的 120832k（118 MiB），不会超出 NMBM 逻辑容量。
- 配置项本身可用：`CONFIG_MTDPARTS_DEFAULT` 是普通字符串符号，只依赖 `MTD || SPI_FLASH` 且要求
  `!SYS_MTDPARTS_RUNTIME`；本板 `MTD` 由 `MTK_BOOTMENU_MTD` 选中（`MEDIATEK_BOOTMENU=y` 下的默认 choice），
  `SYS_MTDPARTS_RUNTIME` 只由 `MEDIATEK_MULTI_MTD_LAYOUT` 打开（本板未开启），因此补丁值会被
  `make olddefconfig` 保留。
- 上游 `build.sh` 的执行顺序保证了补丁生效：它先把 `configs/<board>_defconfig` 复制成 `.config`，
  再追加固定分区开关，最后执行 `olddefconfig`。因此补丁必须落在 defconfig 上，而不是 `.config` 上。

**风险**：被回收进 UBI 的区域在原厂布局中属于 `pdt_data`、`pdt_data_1`、`exp`、`plugin`，
其中 `pdt_data`/`pdt_data_1` 在原厂设备树里是只读分区，可能保存原厂分区/出厂数据。
首次启动 112M 系统会擦除该区域，因此**刷写前必须完整备份原厂闪存**（见安装与恢复文档）。

## 6. NMBM 几何

| 侧 | 配置 | 值 |
|---|---|---|
| U-Boot | `CONFIG_NMBM_MAX_RATIO` / `CONFIG_NMBM_MAX_BLOCKS` | 1 / 256 |
| 系统内核 | `NMBM_MAX_RATIO_DEFAULT` / `NMBM_MAX_BLOCKS_DEFAULT` | 1 / 256 |

两侧默认值一致，逻辑地址到物理块的映射规则相同；系统侧使用 `forced-create` 在缺失时建立结构。
`CONFIG_NMBM_LOWER_MTD` 默认为 `spi-nand0`，与板级 DTS 的 SPI-NAND 介质一致。

## 7. 网页恢复入口

| 项 | 值 | 来源 |
|---|---|---|
| 入口 | 启动菜单 `Start Web failsafe` → U-Boot `httpd` 命令 | `board/mediatek/common/bootmenu_mtd.c` |
| 自动进入 | `CONFIG_MTK_WEB_FAILSAFE_AFTER_BOOT_FAILURE=y`，`mtkboardboot` 启动失败后自动执行 `httpd` | `board/mediatek/common/cmd_mtkboardboot.c` |
| 地址 | `http://192.168.1.1/`，端口 80 | `CONFIG_IPADDR="192.168.1.1"`，`include/env_default.h` |
| 启动链上传 | `bl2` → 写入 `bl2` 分区；`fip` → 写入 `fip` 分区 | `board/mediatek/common/bootmenu_mtd.c` 的 `write_bl2`/`write_fip` |
| 系统上传 | `firmware`、`initramfs` | `failsafe/failsafe.c` 的 `upload_handler` |
| 写入校验 | 写入后回读校验；BL2 上传前另做 BL2 校验，FIP 与系统镜像上传前**不**做结构校验 | `board/mediatek/common/failsafe.c`、`failsafe/failsafe.c` |

`http://192.168.1.1/` 是**启动链的恢复入口**，只覆盖 BL2/FIP/系统镜像，
不能替代独立的恢复路径，也不能代替原厂备份（见第 8 节与安装恢复文档）。

## 8. 与上游 issue #106 的关系

上游 issue #106 记录的是 2024-11-22 的实测：boot loader 用 release `20241115` 的
`mt7981_h3c_magic-nx30-pro-fip-fixed-parts.bin`，系统用 ImmortalWrt 23.05.4 的
「H3C Magic NX30 Pro (NMBM layout)」工厂镜像。该组合是**原厂 64 MiB UBI 布局**，
与本计划选定的 112M 布局不是同一套分区，因此只能作为调查线索，不能证明 112M 兼容。

## 9. 产物区分

| 产物 | 内容 | 用途 |
|---|---|---|
| `mt7981_h3c_magic-nx30-pro-bl2.bin` | ATF BL2 预加载镜像 | 写入 `bl2` 分区（`0x000000`，1 MiB） |
| `mt7981_h3c_magic-nx30-pro-fip-fixed-parts.bin` | ATF FIP（BL31 + BL33/U-Boot） | 写入 `fip` 分区（`0x380000`，2 MiB） |
| 系统 factory 镜像 | 内核 + rootfs（108 MiB UBI 镜像） | 写入 `ubi` 分区，**不是** boot loader 镜像 |

三者不可互相替代；不得把系统 factory 镜像当作 bootloader 镜像，也不得把 BL2 或 FIP
当作“整机恢复镜像”。写入对象与回退步骤见安装与恢复文档。

## 10. 仍然未决的项（UNRESOLVED）

1. NAND 芯片型号、容量与物理块信息 —— 需真机启动日志与 flash id。
2. DDR 类型与容量 —— 需真机日志中的 `EMI: Using DDRx settings`。
3. 112M UBI 之后 2.5 MiB 的用途 —— 需原厂设备分区转储。
4. `pdt_data`、`pdt_data_1`、`exp`、`plugin` 的内容与重要性 —— 需原厂备份后检查。
5. 工具链包的确切版本与校验和 —— 由首次成功构建的构建报告给出。
6. 真机启动行为、网页恢复入口、MAC 与校准数据在候选镜像下的表现 —— 需真机测试。
7. 候选 U-Boot 能否启动所选系统的 108 MiB 工厂镜像 —— 分区布局确认后由真机测试给出。

在第 6、7 项完成前，本目录中的任何产物都只能标记为“候选、未真机验证”，不得作为可刷写发布包。
