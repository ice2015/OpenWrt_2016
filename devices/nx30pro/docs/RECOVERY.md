# NX30 Pro 112M 固件恢复设计

状态：**设计文档，不授权刷写**。本文只规划恢复与回退的目标、入口和前置条件，
不提供任何可执行的写入或擦除命令，也不提供未经核实的裸偏移。整片闪存的只读
**备份**是每一次恢复的输入，永远排在任何写入之前；所有写入动作都需要用户单独、
**明确的授权**。

| 项 | 值 |
|---|---|
| 系统源码 | `https://github.com/hanwckf/immortalwrt-mt798x`，锁定 commit `740103d655bcee6da7bc3b49b1cfdfdee4cd5bb6`，Linux **5.4** |
| profile | `h3c_nx30pro_112M`，布局 `immortalwrt-112m`（**默认**，UBI 112 MiB） |
| 备选布局 | `default`（原厂，UBI 64 MiB，保留 `pdt_data`、`pdt_data_1`、`exp`、`plugin`） |
| 配对启动链 | `https://github.com/Yuzhii0718/bl-mt798x-dhcpd`，commit `e4cf4dc72d451dc7a86c9508390ad5a2e50743c4`，版本 `SP1` |
| 分区合同 | 与启动链是**同一份分区合同**，地址都是 **NMBM** 逻辑地址，不是物理 NAND 地址 |
| 固件状态 | 候选、未编译、未真机验证；当前**没有**可刷写的镜像 |

被拒绝的旧底座 `jerryhan77/immortalwrt-mt798x`（revision
`78cf22edddf07443d8f0506c9f361d3498475189`，与 Galaxian 112M 参考树同源）只作为
**被拒绝的证据**保留：它的恢复行为从未在本设备上被证明，不得当作恢复依据。

## 1. 三种场景必须分开

恢复能力完全取决于设备还能启动到哪一层。三种场景的入口、输入和风险都不同，
不得混用。

### 1.1 系统仍能启动

| 入口 | 输入 | 说明 |
|---|---|---|
| LuCI 升级页 | 本系统的 `sysupgrade.bin` | 带元数据的 sysupgrade tar 包，`append-metadata` 会让升级页校验设备与 profile |
| `sysupgrade` 命令 | 本系统的 `sysupgrade.bin` | 与 LuCI 升级页同一条路径；是否保留配置由操作者决定，结果需在真机记录 |

前提：设备当前运行的就是同一 profile（`h3c_nx30pro_112M`）的本系统。
sysupgrade 只替换系统，不改启动链，也不改分区表。

### 1.2 系统不能启动，但启动链能启动

| 入口 | 输入 | 写入目标 |
|---|---|---|
| 启动链网页恢复入口 `http://192.168.1.1/` 上传 `firmware` | `factory.bin`（112 MiB `ubi` 分区的原始 UBI 镜像） | `ubi` 分区 |
| 启动链网页恢复入口上传 `initramfs` | 本构建**不产出** initramfs 镜像 | 见下方说明 |
| 串口进入启动链恢复菜单 | 同上 | 由启动链文档单独约束 |

说明：

- 锁定的镜像规则只构建两个角色，`factory.bin` 与 `sysupgrade.bin`；
  `IMAGE/factory.bin := append-ubi | check-size $$(IMAGE_SIZE)`，
  `IMAGE/sysupgrade.bin := sysupgrade-tar | append-metadata`。
  两者**都不是启动链镜像**。需要 initramfs 时必须另行授权一次构建，
  不得假想一个不存在的产物。
- 网页恢复入口能上传 `firmware` 与 `initramfs` 两类系统镜像，这是启动链侧的事实，
  见 [`nx30pro-uboot-compatibility.md`](nx30pro-uboot-compatibility.md) 第 7 节。
- 串口只用于观察启动日志与进入启动链的恢复菜单；本文不给出任何串口写入命令。
- 该场景依赖候选启动链已经刷入并且能启动。启动链自身未真机验证时，
  这条路径同样未证明。

### 1.3 启动链不能启动

**状态：UNRESOLVED。** 网页恢复入口与串口菜单都要求设备能启动到 U-Boot；
BL2 或 FIP 损坏时这两条路径同时失效。可接受的**独立恢复路径**（原厂恢复流程、
外部编程器，或另一台可引导设备）在没有真机证据前不给出任何命令，
也不借用其他机型的恢复流程。此时唯一的输入是第 2 节的整片闪存备份，
而写回它同样需要一条已被证明的独立通道。

## 2. 回退输入（备份）

回退的输入只有备份，没有别的：

| 对象 | 用途 |
|---|---|
| 整片闪存镜像 | 唯一能还原原厂分区表、NAND 坏块映射与出厂数据的副本；分区级备份**不能**替代它 |
| `bl2`、`fip`、`u-boot-env` | 启动链回退，见启动链恢复文档 |
| `ubi` | 系统回退：原厂系统或上一次可用的候选系统 |
| `Factory` | 出厂校准数据，回退后必须与读数比对，确认没有被改写 |
| `pdt_data`、`pdt_data_1`、`exp`、`plugin` | 原厂布局下的 OEM 区域；`immortalwrt-112m` 会把这片空间划进 UBI，只有整片备份能还原 |

备份的采集命令、验收条件与保密要求（MAC 与整片镜像不进 Git、不进公开 artifact）在
[`nx30pro-firmware-install-and-validation.md`](nx30pro-firmware-install-and-validation.md)
第 2、3 节与
[`nx30pro-uboot-install-and-recovery.md`](nx30pro-uboot-install-and-recovery.md) 第 2 节。
本文不重复这些命令。

回退之后必须重新做一次冷启动与启动日志检查，并核对各接口 MAC 与 `Factory` 读数。
原厂系统的完整恢复（原厂云端或本地流程）在没有真机证据前保持 UNRESOLVED，
**不得**宣称可以一键回到原厂。

## 3. 恢复入口的限制（来自启动链源码，必须写进操作说明）

- 候选启动链已关闭 Factory 写入、Flash Editor、通用环境变量编辑、Web 终端、Telnet、
  UBI 卷管理与单镜像（ROM dump）写入，因此**不存在**从浏览器直接改写 `Factory`
  或任意范围读写闪存的路径。
- 网页布局选择器只列 `immortalwrt-112m` 与 `default` 两个标签，没有自由 `mtdparts`
  输入；离开原厂布局前会要求确认，并列出会被回收的 `pdt_data`、`pdt_data_1`、
  `exp`、`plugin`。
- FIP 上传不做结构校验，只有写入后回读校验；回读校验只能证明写入的字节与上传的一致，
  **不能**证明镜像本身正确。镜像正确性只能靠 `build-report.json`、`SHA256SUMS`
  与内容识别保证。
- 网页恢复入口地址固定为 `http://192.168.1.1/`（启动链侧 `CONFIG_IPADDR`），端口 80；
  复位键长按进入的时序保持 UNRESOLVED。
- 这些入口**不能替代**独立恢复路径，也不能代替整片备份。

## 4. 写入目标一览

| 层 | 写入目标 | 由谁约束 |
|---|---|---|
| 系统固件 | `ubi` 分区（112 MiB） | 本文与 [`FLASH.md`](FLASH.md) |
| 启动链 FIP | `fip` 分区 | [`nx30pro-uboot-install-and-recovery.md`](nx30pro-uboot-install-and-recovery.md) |
| 启动链 BL2 | `bl2` 分区 | 同上 |
| 出厂校准 | `Factory` 分区 | **任何入口都不得写入**；只备份与比对 |

顺序：先确认场景（第 1 节）→ 先取备份（第 2 节）→ 需要时先恢复启动链 →
确认能启动 → 再恢复系统 → 再做验证。任何一步失败先回退，不叠加写入。

## 5. 授权门与停止条件

恢复写入与首次刷写受同一道授权门约束：目标文件与其 SHA-256、当前布局、
写入分区、独立恢复路径、数据损失范围必须成表交给用户确认，用户明确授权后才执行。
表格模板见 [`FLASH.md`](FLASH.md) 第 5 节。

**停止条件**：只要下面任一项成立，就不得写入。

- 整片闪存备份未完成或未通过验收；
- 独立恢复路径未证明（第 1.3 节仍是 UNRESOLVED 时，启动链不可启动的设备**没有**软件恢复手段）；
- 恢复用的镜像没有可追溯来源：run ID、结论、产物名与 SHA-256 必须记在
  [`TEST-REPORT.md`](TEST-REPORT.md)，当前它只有静态证据；
- 分区标签与 `/proc/mtd` 的实际输出未核对；
- 用户没有对这一次写入给出单独、明确的授权。

不使用主动断电写入作为验证手段；任何一步失败先回退，再分析。

## 6. 未决项（UNRESOLVED）

1. 独立于候选启动链的恢复途径；
2. 原厂分区名、master 行容量与整片备份的可获得性；
3. NAND 型号、容量与坏块状态（112M 布局的逻辑容量是从两张源码表推导的，不是实测）；
4. 本机 WAN MAC 取值与 112M 布局下的读取路径（没有 `pdt_data_1`）；
5. `Factory` 校准数据的真实位置，以及系统在真机上是否改写它；
6. sysupgrade 保留配置时部署值（`/etc/nx30pro/wan-mac` 与服务凭据）的实际去留；
7. 候选启动链与 112M 固件在真机上的配对启动行为；
8. 每个服务的运行行为，以及镜像实际大小与剩余 overlay 空间；
9. 最终镜像文件名与 WireGuard、`luci-app-tailscale`、Go 类包、容器存储驱动等
   构建侧未决项（见 [`BUILD.md`](BUILD.md) 第 8 节，硬门禁的 `make defconfig`
   证明尚未取得，profile 也只有静态补丁证据）。

在第 1、7 项完成前，本目录中的固件与启动链都只能标记为“候选、未真机验证”。
