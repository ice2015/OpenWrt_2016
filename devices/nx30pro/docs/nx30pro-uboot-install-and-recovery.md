# NX30 Pro U-Boot 安装与恢复设计

状态：**设计文档，不授权刷写**。本文只规划备份、安装、回退与真机验证步骤。
本文不提供未经核实的写入命令；所有写入动作都需要用户单独、明确的授权。

- 配套事实来源：[`nx30pro-uboot-compatibility.md`](nx30pro-uboot-compatibility.md) 与
  [`../uboot/uboot-source-lock.json`](../uboot/uboot-source-lock.json)。
- 候选产物：`mt7981_h3c_magic-nx30-pro-bl2.bin`（BL2 预加载镜像）与
  `mt7981_h3c_magic-nx30-pro-fip-fixed-parts.bin`（含 BL31 与 BL33/U-Boot 的 ATF FIP 包）。
- 状态标记：候选、**未真机验证**。写入前不得把它当作可刷写发布包。

## 1. 前置识别（只读）

在原厂系统上先收集事实，全部结果只保留在本地，不进入 Git，也不作为公开 Actions 产物：

```sh
# 固件与硬件版本
cat /etc/openwrt_release 2>/dev/null || cat /etc/os-release
uname -a
cat /proc/cpuinfo | head -20

# 闪存型号、分区与启动日志
dmesg | grep -i -E "nand|spi|mt7981|boot"
cat /proc/mtd
ls -l /dev/mtd* 2>/dev/null

# MAC 与校准数据的位置（只读打印，不记录到公开渠道）
ip addr show
```

需要落档的字段：

| 项 | 记录内容 | 备注 |
|---|---|---|
| 厂商与型号 | 原厂系统显示的型号字符串 | 用于确认是 NX30 Pro 而不是 NX30 |
| 硬件修订 | 原厂标签或系统信息中的版本号 | 未知时保持 UNRESOLVED |
| NAND 型号与容量 | 启动日志中的 NAND id 与容量 | 与上游 128 MiB 假设比对 |
| 当前分区表 | `/proc/mtd` 全部输出 | 原厂分区名目前未核实 |
| 启动介质 | 启动日志中的 boot medium | 应为 SPI-NAND |
| MAC 地址 | 每个接口的 MAC | 敏感值，只本地保存 |

原厂系统的分区名与上表并不一致之前，任何按名字定位的备份或写入步骤都不能执行。
上游 U-Boot 与所选系统使用的是 `bl2`、`u-boot-env`、`Factory`、`fip`、`ubi`、`pdt_data`、
`pdt_data_1`、`exp`、`plugin` 这一套逻辑名；原厂系统的命名仍待第 1 节确认。

## 2. 备份（只读，先做后动）

备份必须在任何写入之前完成，并且必须包含**整片闪存**与**每个关键分区**两部分：

```sh
# 整片闪存原始镜像（含坏块信息，工具选项以本机 --help 为准）
nanddump --help            # 先确认本机工具支持的选项
nanddump -o /mnt/backup/nx30pro-full.bin /dev/mtd0

# 关键分区逐个导出，分区名用 /proc/mtd 里观察到的真实名字
dd if=/dev/mtd<N> of=/mnt/backup/<observed-name>.bin bs=1M
sha256sum /mnt/backup/*.bin > /mnt/backup/SHA256SUMS
```

必须备份的对象：

| 对象 | 理由 |
|---|---|
| 整片闪存镜像 | 唯一能还原原厂分区表、NAND 坏块映射与出厂数据的副本 |
| `bl2` | 原厂启动链第一阶段，回退时需要原样写回 |
| `u-boot-env` | 原厂环境变量，可能含 MAC 派生信息与启动参数 |
| `Factory` | 出厂数据区（2 MiB），MAC 与校准数据可能在此 |
| `fip` | 原厂 FIP 包，回退目标 |
| `ubi` | 原厂系统分区，回退目标 |
| `pdt_data`、`pdt_data_1`、`exp`、`plugin` | 若存在则必须备份；112M 布局会把这片空间划进 UBI |

备份完成后：

1. 把整片镜像与各分区镜像的 SHA-256 写进本地记录；
2. 把记录与镜像分开保存（离线介质或本地加密存储）；
3. **不要**把整片镜像或含 MAC 的分区上传到公开 Actions artifact，也不要提交 Git；
4. 回退演练：在另一块同型号设备或同一台设备的可恢复状态下验证备份可读。

若整片镜像无法生成（例如原厂系统缺少 nanddump），记录该事实并保持 UNRESOLVED，
不要用分区级备份冒充完整备份。

## 3. 安装入口（需用户授权）

两个入口都来自锁定源码中的实际实现，只有在第 2 节备份完成后才允许使用：

| 入口 | 证据 | 写入对象 | 前置条件 |
|---|---|---|---|
| 网页恢复入口 `http://192.168.1.1/` 上传 `fip` | `failsafe/failsafe.c` 的 `upload_handler` 接受 `fip`；`board/mediatek/common/bootmenu_mtd.c` 的 `write_fip` 写入 `fip` 分区并回读校验 | `fip` 分区（`0x380000`，2 MiB） | 设备已进入 U-Boot 的 web failsafe 模式 |
| 串口 U-Boot 命令 `mtkupgrade fip` | 启动菜单项 "Upgrade ATF FIP" → `cmd_mtkupgrade.c` | `fip` 分区（`0x380000`，2 MiB） | 设备停在 U-Boot 提示符 |
| 网页恢复入口上传 `bl2` | 同上，`write_bl2` 写入 `bl2` 分区；上传前会做 BL2 校验 | `bl2` 分区（`0x000000`，1 MiB） | 同上 |

关键限制（来自源码，必须写进操作说明）：

- FIP 上传**不做**结构校验（`CONFIG_MTK_UPGRADE_FIP_VERIFY` 未开启），只做写入后回读校验；
  BL2 上传**会**做 BL2 校验，且要求启动介质匹配 `SPINAND!` 头（本板为 SPI-NAND）。
- 网页恢复入口的地址是 `192.168.1.1`（U-Boot 侧固定 `CONFIG_IPADDR`），端口 80；
  进入方式（启动菜单按键、失败自动进入）在真机观察前保持 UNRESOLVED。
- 网页恢复入口只覆盖启动链与系统镜像，**不能**代替独立恢复路径，也不能代替原厂备份。

## 4. 刷写前审阅清单（单独交付给用户）

实际写入前，必须把下面这张表连同镜像的 SHA-256 一起交给用户确认，用户明确授权后才执行：

| 项 | 内容 |
|---|---|
| 目标文件 | `mt7981_h3c_magic-nx30-pro-fip-fixed-parts.bin`（FIP）、`mt7981_h3c_magic-nx30-pro-bl2.bin`（BL2） |
| 文件 SHA-256 | 取自构建产物的 `SHA256SUMS` 与 `build-report.json` |
| 写入对象 | `fip` 分区（`0x380000`，2 MiB）/ `bl2` 分区（`0x000000`，1 MiB） |
| 写入方式 | 网页恢复入口上传，或串口 `mtkupgrade fip` |
| 回退路径 | 用第 2 节的 `bl2`、`fip`、`u-boot-env` 备份原样写回；原厂系统恢复路径保持 UNRESOLVED |
| 数据损失范围 | 写入 FIP/BL2 本身不改写 `Factory` 与 `ubi`；但随后首次启动 112M 系统会按 112M 布局擦除原厂的 `pdt_data`、`pdt_data_1`、`exp`、`plugin` 区域 |
| 风险 | FIP 校验关闭，写入错误镜像只能靠回读校验发现；BL2 错误会导致设备无法启动 |

## 5. 回退

1. 回退输入：第 2 节备份的 `bl2`、`fip`、`u-boot-env` 原始镜像及其 SHA-256；
2. 回退写入方式：与安装相同的两条入口（网页恢复入口或串口 `mtkupgrade`）；
3. 回退后必须重新做一次冷启动与启动日志检查；
4. 原厂系统的完整恢复（例如原厂云端或本地恢复流程）在没有真机证据前保持 UNRESOLVED，
   **不得**借用其他机型的恢复命令或宣称可以一键回到原厂。

## 6. 真机验证（授权后执行）

写入并重启后，按顺序验证，每一步都留下原始输出：

| 步骤 | 观察点 | 通过标准 |
|---|---|---|
| 冷启动 | 串口启动日志 | U-Boot 起来后识别出 `bl2`、`u-boot-env`、`Factory`、`fip`、`ubi`，且 `ubi` 为 112 MiB |
| NMBM | 启动日志中的 NMBM 段 | 坏块映射正常，无重复块告警 |
| MAC | 各接口 MAC | 与原厂备份一致 |
| 无线校准 | 射频校准读取 | 与原厂备份一致，无校准缺失告警 |
| 复位按钮 | 按下 reset | 设备正常重启，不进入异常模式 |
| 网页恢复入口 | 进入 failsafe 后访问 `http://192.168.1.1/` | 页面可打开，能列出可上传的启动链镜像 |
| 最小系统启动 | 启动最小可启动系统 | 内核与 rootfs 正常挂载 |
| 匹配工厂镜像 | 网页安装与所选系统匹配的 factory 镜像 | 写入成功并能启动 |

验收方式：**不使用**主动断电写入作为验证手段。所有写入都走正常上电流程与官方入口。
任何一步失败都先回退，再分析，不得继续叠加写入。

## 7. 未决项（UNRESOLVED）

1. 原厂系统的真实分区名与整片备份的可获得性；
2. 原厂系统自身的恢复入口（云端或本地）——没有证据前不给出任何命令；
3. NAND 芯片型号、容量与坏块布局；
4. MAC 与无线校准数据的确切存放位置（`Factory` 分区的偏移）；
5. 进入 web failsafe 的按键与时序；
6. 候选 U-Boot 在真机上的启动行为与 112M 系统的兼容性；
7. 工具链确切版本与产物逐字节可复现性。

在第 6、7 项完成前，本设备目录内的 U-Boot 产物只能标记为“候选、未真机验证”。
