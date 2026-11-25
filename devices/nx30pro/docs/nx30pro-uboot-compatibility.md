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
- 真正的版本证据只能来自构建报告，由构建脚本在编译时记录编译器路径、编译器版本、
  **编译器二进制的 SHA-256（`compiler_sha256`）**、dpkg 包版本与 apt 候选版本；
- 换用不同工具链版本会改变产物字节，比较两次构建前必须先比对记录的编译器 SHA-256 与包版本；
- 工作流从发行版仓库安装该包，所以“逐字节可复现”只有在两次构建的工具链标识完全一致时才能主张；
  在此之前该验收项保持未决。

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
| DDR 类型 | 编译期选中 DDR3：`DRAM_USE_DDR4` 未开启，`AVAIL_DRAM_SIZE` 为 256/512 | `plat/mediatek/mt7981/drivers/dram/dram-configs.mk` |

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
所选系统的工厂镜像上限是 `IMAGE_SIZE := 110592k`（108 MiB，`append-ubi | check-size` 的上限），
**上游 64 MiB 的 ubi 分区装不下这个上限**；
因此上游原样构建的 U-Boot 与 112M 系统布局不匹配，不能直接作为配套启动链。

同一系统仓库里的非 112M 设备树 `mt7981-h3c-nx30pro.dts` 描述的正是上游这套分区表
（ubi 64 MiB + 四个 OEM 分区），即：**上游 U-Boot 与上游原厂系统彼此一致，两者同时与 112M 布局不一致**。

以下所有地址都是 **NMBM 逻辑地址**，即启动链与系统共同暴露的逻辑分区空间，
**不是物理 NAND 地址**，不能直接当作物理写入偏移使用。

112M 布局结束于 `0x7580000`（117.5 MiB）；上游原厂表结束于 `0x7800000`，
两张表合计分别为 120320 KiB 与 122880 KiB（120 MiB）。
两者之差 2560 KiB（2.5 MiB）**是由两张表推导出来的，不是实测值**：
NMBM 驱动按已加载映射的块数给出可用容量（`nmbm-core.c` 的 `data_block_count`），
真实容量可能更小。因此“逻辑末端 `0x7800000`”只能作为推导结论，
按计划要求，尾部空间用途与真实容量保持 `UNRESOLVED`；
必须保证的是**实测逻辑容量不小于 `0x7580000`**。

## 5. 最小设备补丁

不一致项只用一个设备级改动处理，不套用其他设备的参数：

```text
CONFIG_MTDPARTS_DEFAULT="nmbm0:1024k(bl2),512k(u-boot-env),2048k(Factory),2048k(fip),114688k(ubi)"
```

- 目标文件：`uboot-mtk-20230718-09eda825/configs/mt7981_h3c_magic-nx30-pro_defconfig`；
- 作用域：仅构建副本中的设备级输入，锁文件里的上游源码保持原样；
- 依据：BL2 / u-boot-env / Factory / FIP 的偏移与大小沿用合同；ubi 扩到 114688k（112 MiB）；
  尾部四个 OEM 分区在 112M 布局中不存在，故不保留；
- 该分区表总长 120320 KiB（117.5 MiB），小于上游原厂表的 122880 KiB（120 MiB）；
  它仍然要求设备的实测 NMBM 逻辑容量不小于 `0x7580000`。
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
| 复位键入口 | `common/main.c` 在 autoboot 之前执行 `glbtn`；`cmd/glbtn.c` 认领设备树中名为 `reset` 的按键，长按计数到 4 秒后执行 `httpd` | `common/main.c`、`cmd/glbtn.c`、板级 DTS 的 `button-reset` |
| 自动进入 | `CONFIG_MTK_WEB_FAILSAFE_AFTER_BOOT_FAILURE=y`，`mtkboardboot` 启动失败后自动执行 `httpd` | `board/mediatek/common/cmd_mtkboardboot.c` |
| 地址 | `http://192.168.1.1/`，端口 80 | `CONFIG_IPADDR="192.168.1.1"`，`include/env_default.h` |
| 启动链上传 | `bl2` → 写入 `bl2` 分区；`fip` → 写入 `fip` 分区 | `board/mediatek/common/bootmenu_mtd.c` 的 `write_bl2`/`write_fip` |
| 系统上传 | `firmware`、`initramfs` | `failsafe/failsafe.c` 的 `upload_handler` |
| 写入校验 | 写入后回读校验；BL2 上传前另做 BL2 校验，FIP 与系统镜像上传前**不**做结构校验 | `board/mediatek/common/failsafe.c`、`failsafe/failsafe.c` |

长按复位键进入网页入口的**机制**在源码中确定（`glbtn` → 计数 4 秒 → `httpd`），
但按键时序与实际进入效果仍需真机观察，保持 `UNRESOLVED`。

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
| `mt7981_h3c_magic-nx30-pro-bl2.bin` | ATF BL2 预加载镜像 | 写入 `bl2` 分区（NMBM 逻辑 `0x000000`，1 MiB） |
| `mt7981_h3c_magic-nx30-pro-fip-fixed-parts.bin` | ATF FIP（BL31 + BL33/U-Boot） | 写入 `fip` 分区（NMBM 逻辑 `0x380000`，2 MiB） |
| 系统 factory 镜像 | 内核 + rootfs（镜像上限 108 MiB） | 写入 `ubi` 分区，**不是** boot loader 镜像 |

三者不可互相替代；不得把系统 factory 镜像当作 bootloader 镜像，也不得把 BL2 或 FIP
当作“整机恢复镜像”。写入对象与回退步骤见安装与恢复文档。

## 10. 所选系统对 OEM 分区的依赖（源码级冲突）

所选系统（`jerryhan77/immortalwrt-mt798x`，`nx30pro-112m`）在
`target/linux/mediatek/mt7981/base-files/etc/board.d/02_network` 的 `h3c,nx30pro` 分支中：

```sh
wan_mac=$(mtd_get_mac_ascii pdt_data_1 ethaddr)
lan_mac=$(macaddr_add $wan_mac 1)
if [ "$(mtk_factory_get_byte "Factory" 4 2)" = "00-0c" ]; then
        local wifi_mac="$(macaddr_add $wan_mac 2)"
        mtk_facrory_write_mac "Factory" 4 $wifi_mac
fi
```

由此得到两条**已核实**的依赖：

1. 系统从 `pdt_data_1` 读取 WAN MAC（ASCII 键 `ethaddr`）并派生 LAN MAC；
   **112M 分区合同没有 `pdt_data_1`**，所以在这套布局上系统读不到 WAN MAC。
   MAC 的具体值仍然未知，但这个源码级冲突是确定的。
2. 当 `Factory` 偏移 4 的前两个字节是 `00-0c` 时，系统会把派生出的 Wi-Fi MAC
   **写回** `Factory` 偏移 4；也就是说系统首次启动可能修改出厂数据区。

结论：配套固件的 MAC 供给方式必须先解决（保留 `pdt_data_1`、改从 `Factory` 读取，
或显式写入），在这之前不能把 112M 布局与所选系统成对投入测试。
本轮不改固件，只把该冲突记录在源码锁的 `system_dependencies` 与安装恢复清单中。

## 12. 两次干净环境构建的哈希比较（2026-11-25）

按计划要求，用同一份锁在两个干净的 runner 上各构建一次：

| 项 | 第一次 | 第二次 |
|---|---|---|
| Actions 运行 | `45562479770` | `45562763520` |
| 源码 commit | `36916669d0874306638196c5327a20c2ef215bed` | 同左 |
| 工具链 | gcc 13.3.0，包 `4:13.2.0-7ubuntu1`，编译器 SHA-256 `cd90adc7…72dc9a` | 完全相同 |
| BL2 SHA-256 | `e6c8f96525519cadd9425c5b49a6e6335c82ceee49ee9a1f665a6b8218af11b8` | `de46862a82322c84bb708995730b0a963a1b38ec1cea491bf9a6d865b943639e` |
| FIP SHA-256 | `127f0648c2e018d7ae1e12f3ad9d0a26360329c06f98b999ba2789c8da03eefd` | `9b2490e6dfae1dcc43014fa1530f89d6a612e499c58c7177fd3322c2c5c6bbf6` |

哈希不同，但差异被精确定位：

- BL2 相差 **33 字节**：其中一段是嵌入的编译时间戳字符串
  （`: 06:43:01, Nov 25 2026` 对 `: 06:45:01, Nov 25 2026`），末尾若干字节是随内容变化的校验尾部；
- FIP 相差 **3 字节**：BL31 内的时间戳字符 1 字节，以及 BL33（U-Boot）版本串里的时间
  （`U-Boot 2023.07 (Nov 25 2026 - 06:42:34 +0000)` 对 `… 06:44:37 +0000`）。

结论：**差异来源是嵌入的编译时间戳**，源码、工具链、配置与补丁完全一致。
因此本构建**不能**宣称逐字节可复现；该验收项按计划保持未决，
若将来需要逐字节一致，必须先处理时间戳（例如固定 `SOURCE_DATE_EPOCH` 并核对上游是否支持）。

## 13. 仍然未决的项（UNRESOLVED）

1. NAND 芯片型号、容量与物理块信息 —— 需真机启动日志与 flash id。
2. 物理 DDR 型号与容量 —— 编译期选中的是 DDR3 配置，实际芯片需真机日志确认。
3. 112M UBI 之后 2.5 MiB 的用途，以及实测 NMBM 逻辑容量 —— 需原厂设备分区转储。
4. `pdt_data`、`pdt_data_1`、`exp`、`plugin` 的内容与重要性 —— 需原厂备份后检查。
5. 工具链包的确切版本与校验和 —— 由首次成功构建的构建报告给出（编译器 SHA-256、包版本、apt 候选版本）。
6. 真机启动行为、网页恢复入口的按键时序、MAC 与校准数据在候选镜像下的表现 —— 需真机测试。
7. 候选 U-Boot 能否启动所选系统的工厂镜像（上限 108 MiB） —— 分区布局确认后由真机测试给出。
8. 所选系统的 WAN MAC 供给方式在 112M 布局下的解决方案 —— 需固件侧决定。
9. 产物逐字节可复现性 —— 已定位为嵌入的编译时间戳（见第 12 节），固定时间戳前保持未决。

在第 6、7、8 项完成前，本目录中的任何产物都只能标记为“候选、未真机验证”，不得作为可刷写发布包。
