# NX30 Pro 112M 固件刷写边界

状态：**设计文档，不授权刷写**。本文只描述刷写目标、镜像角色与前置条件，
不提供任何可执行的写入命令，也不提供未经核实的裸偏移。整片闪存的只读**备份**
永远排在任何写入之前。所有写入动作都需要用户单独、**明确的授权**。

| 项 | 值 |
|---|---|
| 设备 | H3C Magic NX30 Pro（MT7981，SPI-NAND） |
| 系统源码 | `https://github.com/hanwckf/immortalwrt-mt798x`，锁定 commit `740103d655bcee6da7bc3b49b1cfdfdee4cd5bb6`，Linux **5.4** |
| profile | `h3c_nx30pro_112M`，布局 `immortalwrt-112m`（**默认**，UBI 112 MiB） |
| 备选布局 | `default`（原厂，UBI 64 MiB，保留 `pdt_data`、`pdt_data_1`、`exp`、`plugin`） |
| 配对启动链 | `https://github.com/Yuzhii0718/bl-mt798x-dhcpd`，commit `e4cf4dc72d451dc7a86c9508390ad5a2e50743c4`，版本 `SP1` |
| 分区合同 | 与启动链是**同一份分区合同**，地址都是 **NMBM** 逻辑地址，不是物理 NAND 地址 |
| 固件状态 | 候选、未编译、未真机验证（源码锁 `source-candidate-build-blocked`，`check` 退出 3） |

被拒绝的旧底座 `jerryhan77/immortalwrt-mt798x`（revision
`78cf22edddf07443d8f0506c9f361d3498475189`，与 Galaxian 112M 参考树同源）只作为
**被拒绝的证据**保留，不得作为刷写对象的来源。

本文不列偏移：本设备的偏移是从两张源码表**推导**出来的，不是设备读数。
需要偏移时看 [`BUILD.md`](BUILD.md) 第 1.2 节与
[`nx30pro-uboot-compatibility.md`](nx30pro-uboot-compatibility.md) 第 3 节，
并在真机上用 `/proc/mtd` 的实际输出核对之后才使用。

## 1. 刷什么：两个镜像角色

| 角色 | 名字后缀 | 用途 |
|---|---|---|
| factory 镜像 | `factory.bin` | 112 MiB `ubi` 分区的原始 UBI 镜像，上限 `IMAGE_SIZE := 110592k` |
| sysupgrade 镜像 | `sysupgrade.bin` | 带元数据的 sysupgrade tar 包，供 LuCI 升级页与 `sysupgrade` 命令使用 |

两个角色由镜像规则区分，规则写在移植补丁加进 `mt7981.mk` 的 profile 里：
factory 是 `append-ubi | check-size $$(IMAGE_SIZE)`，sysupgrade 是
`sysupgrade-tar | append-metadata`。

- 两者**都不是启动链镜像**，也不能互相替代。启动链镜像是 BL2 与 FIP，由
  `devices/nx30pro/build/build-uboot.sh` 单独构建，见
  [`nx30pro-uboot-install-and-recovery.md`](nx30pro-uboot-install-and-recovery.md)。
- 最终文件名**保持 UNRESOLVED**：名字前缀含只在真实构建里解析的版本变量，
  所以镜像按角色后缀加 profile 段 `h3c_nx30pro_112M` 识别，实际名字与 SHA-256
  只能取自构建产物的 `SHA256SUMS` 与 `build-report.json`。
- 当前**没有**可刷写的镜像：候选构建从未被触发，`firmware_lock.py check` 退出 3。

## 2. 前置条件（备份优先，缺一项就不进入第 3 节）

1. **整片闪存**与每个关键分区的只读**备份**已完成并通过验收：`bl2`、`u-boot-env`、
   `Factory`、`fip`、`ubi`，以及仍存在的 `pdt_data`、`pdt_data_1`、`exp`、`plugin`。
   备份命令与验收条件在
   [`nx30pro-firmware-install-and-validation.md`](nx30pro-firmware-install-and-validation.md)
   第 2、3 节；本文不重复任何写入或读取命令。分区级备份**不能**替代整片镜像。
2. 已证明存在一条**独立恢复路径**（不依赖候选启动链，也不依赖候选固件），
   见 [`RECOVERY.md`](RECOVERY.md) 第 3 节。当前该路径**未证明**，状态 UNRESOLVED。
3. 设备当前布局已确认。仍在 `default` 时，切换到 `immortalwrt-112m` 属于第 4 节的
   **数据损失**场景，必须先有整片备份。
4. 配对启动链（`SP1` 的 BL2 与 FIP）已按启动链文档刷入并能启动，且使用
   **同一份分区合同**。启动链未验证时不得成对刷写固件。
5. 本机 WAN MAC 已在**原厂布局**上读出并写入部署值 `/etc/nx30pro/wan-mac`
   （只在设备上写入，不进镜像、不进 Git、不进公开 artifact）。112M 布局没有
   `pdt_data_1`，这是底座原本的 MAC 来源；真实取值路径仍是 UNRESOLVED。
6. 镜像与 `Factory` 分区的 SHA-256 已记录，`Factory` 备份与刷写后读数可比对。
7. 用户已对**这一次**写入给出单独、明确的授权，并收到第 5 节的审阅表。

## 3. 写入目标与入口

| 目标 | 分区 | 入口 | 前提 |
|---|---|---|---|
| 系统固件（factory 镜像） | `ubi`（112 MiB） | 启动链的网页恢复入口 `http://192.168.1.1/` 上传 `firmware` | 设备能启动到候选 U-Boot |
| 系统固件（sysupgrade 镜像） | `ubi` | 已运行本系统时的 LuCI 升级页或 `sysupgrade` 命令 | 设备已在运行同一 profile 的本系统 |
| 启动链 FIP | `fip` | 见启动链恢复文档（网页入口或串口 `mtkupgrade fip`） | 由启动链文档单独约束 |
| 启动链 BL2 | `bl2` | 见启动链恢复文档 | 由启动链文档单独约束 |

写入顺序：先备份 → 需要时先写启动链 → 确认能启动 → 再写系统固件 → 再做验证。
任何一步失败先回退，不叠加写入。

## 4. 数据损失范围

首次以 `immortalwrt-112m` 布局启动 112M 系统，会把原厂 `default` 布局里 UBI 之后的
`pdt_data`、`pdt_data_1`、`exp`、`plugin` 划进 UBI，这片空间上的原厂数据**不可恢复**，
只能靠第 2 节的整片备份还原。此外：

- `Factory`（出厂校准区）不由本固件写入：设备补丁已移除底座把派生 Wi-Fi MAC 写回
  `Factory` 的行为，该区在 112M 布局下只读。真机上是否真的没有被改写，
  必须用备份比对确认，当前 UNRESOLVED。
- sysupgrade 只替换系统，不改启动链，也不改分区表。
- 使用 sysupgrade 保留配置时，部署值（`/etc/nx30pro/wan-mac` 与服务凭据）的去留
  取决于它们是否在 conffile 里；本文不假定结果，需在真机记录。

## 5. 授权门与停止条件

写入前必须把下表连同镜像 SHA-256 一起交给用户确认，用户明确授权后才执行：

| 项 | 内容 |
|---|---|
| 目标文件 | factory 或 sysupgrade 镜像；实际文件名取自构建产物，不猜 |
| 文件 SHA-256 | 取自 `images/SHA256SUMS` 与 `build-report.json` |
| 写入分区 | `ubi`（启动链镜像另见启动链文档） |
| 当前布局 | 应为 `immortalwrt-112m`（默认）；仍在 `default` 时先完成整片备份 |
| 独立恢复路径 | 必须已证明可用，否则不写入 |
| 回退路径 | 见 [`RECOVERY.md`](RECOVERY.md)；回退同样依赖可启动的启动链 |
| 数据损失 | 第 4 节列出的 OEM 区域 |
| 风险 | factory 镜像超限会被 `check-size` 拒绝；写错分区不可恢复 |

**停止条件**：只要下面任一项成立，就不得写入。

- 整片闪存备份未完成或未通过验收；
- 独立恢复路径未证明；
- 候选构建没有 run ID、结论、产物名与 SHA-256（即 [`TEST-REPORT.md`](TEST-REPORT.md)
  还停在静态证据阶段）；
- 配对启动链未在真机上启动过；
- 用户没有对这一次写入给出单独、明确的授权。

本文不提供写入命令，也不借用其他机型的刷写命令。不使用主动断电作为验证手段；
所有写入都走正常上电流程与官方入口。

## 6. 未决项（UNRESOLVED）

刷写相关的未决事实：本机 WAN MAC 取值与读取路径、`Factory` 校准数据的真实位置与
是否被改写、NAND 型号/容量/坏块状态、独立恢复路径、镜像实际大小与剩余 overlay 空间、
每个服务的运行行为、最终文件名、以及候选构建本身（尚未触发）。完整清单见
[`BUILD.md`](BUILD.md) 第 8 节与
[`nx30pro-firmware-compatibility.md`](nx30pro-firmware-compatibility.md)。
