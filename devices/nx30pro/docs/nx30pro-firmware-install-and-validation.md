# NX30 Pro 固件安装与真机验证设计

状态：**设计文档，不授权刷写**。本文只规划备份、部署、部署值录入与真机验证步骤。
本文不提供未经核实的写入命令；所有写入动作都需要用户单独、明确的授权。

| 项 | 值 |
|---|---|
| 系统源码 | `https://github.com/hanwckf/immortalwrt-mt798x`，锁定 commit `740103d655bcee6da7bc3b49b1cfdfdee4cd5bb6`，Linux **5.4** |
| profile | `h3c_nx30pro_112M`，布局 `immortalwrt-112m`（**默认**，UBI 112 MiB）；备选 `default`（原厂，保留 `pdt_data`、`pdt_data_1`、`exp`、`plugin`） |
| 镜像角色 | `factory.bin`（112 MiB `ubi` 分区的原始 UBI 镜像）与 `sysupgrade.bin`（带元数据的 sysupgrade tar 包）；两者都**不是启动链镜像** |
| 配对启动链 | `https://github.com/Yuzhii0718/bl-mt798x-dhcpd`，commit `e4cf4dc72d451dc7a86c9508390ad5a2e50743c4`，版本 `SP1`；两边是**同一份分区合同** |
| 固件状态 | 候选、未编译、未真机验证（`firmware_lock.py check` 退出 3） |

- 配套事实来源：[`nx30pro-firmware-compatibility.md`](nx30pro-firmware-compatibility.md)、
  [`BUILD.md`](BUILD.md)、[`FLASH.md`](FLASH.md)、[`RECOVERY.md`](RECOVERY.md)、
  [`TEST-REPORT.md`](TEST-REPORT.md)、
  [`nx30pro-uboot-install-and-recovery.md`](nx30pro-uboot-install-and-recovery.md) 与
  [`../source-lock.json`](../source-lock.json)。
- 状态标记：候选、**未真机验证**。
- 地址约定：所有分区地址都是 **NMBM 逻辑地址**，不是物理 NAND 地址。

## 1. 前置识别（只读）

在原厂系统上先收集事实，结果只保留在本地，不进入 Git，也不作为公开 Actions 产物：

```sh
cat /etc/openwrt_release 2>/dev/null || cat /etc/os-release
dmesg | grep -i -E "nand|spi|mt7981|boot"
cat /proc/mtd
ls -l /dev/mtd* 2>/dev/null
ip addr show
```

必须落档：厂商与型号（确认是 NX30 Pro 而非 NX30）、硬件修订、NAND 型号与容量、
**`/proc/mtd` 中的 master 行（哪一行描述物理闪存）**、原厂分区名、启动介质、各接口 MAC。

**不得假设某个分区编号就是整片闪存**，必须先确认 master 行。

## 2. 读取并记录 WAN MAC（只读，部署前必做）

112M 布局没有 `pdt_data_1` 分区，系统需要从部署值里取 WAN MAC。
在**原厂布局**上读取它，并只保存在本地：

```sh
# 在原厂系统上查找带有 ethaddr 键的分区，先看有哪些分区
cat /proc/mtd
# 用上一步确认的分区设备读取（设备名与路径按实际观察填写）
dd if=<分区设备> bs=1 count=4096 2>/dev/null | grep -a -o 'ethaddr=[0-9a-fA-F:]*'
```

把读到的 MAC 写进本次部署记录，并保留原厂分区内容。
**不要**把 MAC 提交 Git，也不要放进公开 Actions artifact。

设备补丁 `../patches/0002-mediatek-nx30pro-wan-mac-source.patch` 的取值顺序是
`/etc/nx30pro/wan-mac` → `Factory` 的 ascii `ethaddr`（只读）→ 仍存在的 `pdt_data_1`
（只读）；三者都取不到时保留 bootloader 交下来的地址并记录日志。补丁同时移除了
底座把派生 Wi-Fi MAC 写回 `Factory` 偏移 4 的行为，出厂校准区在 112M 布局下只读。
真机上 `Factory` 是否仍被改写必须用备份比对确认，当前 UNRESOLVED。

## 3. 备份（只读，先做后动）

备份必须在任何写入之前完成，并且必须包含**整片闪存**与**每个关键分区**：

```sh
# 先确认本机工具的选项：输出文件参数、是否跳过坏块、是否带 OOB
nanddump --help

# 整片闪存镜像，参数与设备名按上一步确认的结果填写
nanddump <本机支持的参数> <master-device> <整片镜像输出文件>

# 关键分区逐个导出，设备名用 /proc/mtd 里观察到的真实分区名
dd if=<分区设备> of=<分区镜像输出文件> bs=1M

sha256sum <备份文件列表> > SHA256SUMS
```

备份验收条件：整片镜像长度与 master 行容量一致、每个分区镜像长度与分区容量一致、
坏块与 OOB 策略已记录、读取退出码为 0、校验和已生成并离线保存。
必须备份：`bl2`、`u-boot-env`、`Factory`、`fip`、`ubi`，以及存在的 `pdt_data`、`pdt_data_1`、
`exp`、`plugin`（112M 布局会把这些空间划进 UBI）。

**停止条件**：在独立恢复路径被证明、并且整片备份验收通过之前，不得进行任何写入。

## 4. 部署值（不进入镜像）

| 文件 | 内容 | 来源 |
|---|---|---|
| `/etc/nx30pro/wan-mac` | 本机 WAN MAC，一行一个地址 | 第 2 节读取 |
| PassWall 节点与订阅 | 部署后由 LuCI 或配置文件录入 | 用户 |
| DDNS 服务商与域名 | 部署后由 LuCI 录入 | 用户 |
| 云隧道令牌 | 部署后写入 cloudflared 配置 | 用户 |
| 组网账号 | 部署后由 Tailscale / ZeroTier 录入 | 用户 |

镜像里没有这些值，`/etc/nx30pro/` 在镜像中只有一份说明文件。

## 5. 写入路径（需授权）

写入目标、镜像角色与停止条件在 [`FLASH.md`](FLASH.md)，恢复与回退场景在
[`RECOVERY.md`](RECOVERY.md)。本节只给出目标分区与入口的对应关系：

| 目标 | 入口 | 写入对象 | 说明 |
|---|---|---|---|
| 启动链 | 网页恢复入口 `http://192.168.1.1/` 或串口 `mtkupgrade fip` | `fip` 分区（NMBM 逻辑 `0x380000`，2 MiB） | 见启动链恢复文档；这是升级候选启动链的路径 |
| 系统固件 | 网页恢复入口上传 `firmware` | `ubi` 分区（NMBM 逻辑 `0x580000`，112 MiB） | 写入 `factory.bin`（上限 110592k）；**这一步会按 112M 布局擦除 `pdt_data`、`pdt_data_1`、`exp`、`plugin`** |
| 系统固件 | LuCI 升级页 / `sysupgrade` 命令 | `ubi` 分区 | 只在已经运行同一 profile 的本系统时使用，输入是 `sysupgrade.bin`；它与 `factory.bin` 都**不是启动链镜像**，不能互换 |
| 启动链 | 网页恢复入口上传 `bl2` | `bl2` 分区（NMBM 逻辑 `0x000000`，1 MiB） | 只在确实需要更换 BL2 时使用 |

顺序建议：先备份 → 先写启动链（若需要）→ 确认能启动 → 再写系统固件 → 再做验证。
任何一步失败先回退，不要叠加写入。

## 6. 真机验证（授权后执行）

本节是**计划**，不是结果。执行需要用户对刷写与真机测试单独、明确的授权；
每一步的原始输出必须记进 [`TEST-REPORT.md`](TEST-REPORT.md)，没有 run ID、结论与
产物哈希的候选构建不得写进本表，没有设备读数的项不得写成已验证。

按顺序执行，每一步保留原始输出：

| 步骤 | 观察点 | 通过标准 |
|---|---|---|
| 冷启动 | 串口日志 | 设备启动到 U-Boot，分区表与合同一致（`ubi` 为 112 MiB） |
| NMBM | 启动日志 | 坏块映射正常，实测逻辑容量不小于 `0x7580000` |
| MAC | 各接口 MAC | 与原厂备份一致；`/etc/nx30pro/wan-mac` 生效，LAN MAC 由 WAN MAC 派生 |
| 出厂数据 | `Factory` 偏移 4 | 记录是否被系统改写，并与备份比对 |
| 无线校准 | 射频校准 | 与原厂备份一致，无校准缺失告警 |
| 基础网络 | PPPoE 拨号、DHCP、双频 Wi-Fi、IPv6 | 拨号成功、地址与前缀正常、无线正常 |
| 中文界面 | LuCI | 界面为中文，Argon 生效，Bootstrap 可切换 |
| 透明代理 | PassWall + xray | 配置节点后代理生效；确认**只有**一个代理管理器在运行 |
| 异地组网 | Tailscale / ZeroTier | 账号加入后连通；未配置时不自动启动、不外联 |
| 云隧道 | cloudflared | 令牌配置后隧道建立；未配置时不启动 |
| DDNS | luci-app-ddns | 域名更新正常 |
| 容器 | Docker | 引擎启动、镜像可拉取、容器可运行、日志按上限轮转 |
| 容量 | `df -h` 与镜像大小 | 剩余可写空间满足实际使用；不足时停止部署而不是删除用户数据 |
| 复位按钮 | 按 reset | 设备正常重启 |
| 回退 | 用备份的 `fip` / `bl2` 写回 | 能回到原状并冷启动正常 |

验收方式：不使用主动断电写入作为验证手段；所有写入走正常上电流程与官方入口。

## 7. 未决项（UNRESOLVED）

与 `../source-lock.json` 的 `unresolved` 对应：

1. 原厂分区名、master 行容量与整片备份的可获得性；
2. 原厂系统的独立恢复入口，以及任何独立于候选启动链的恢复途径；
3. 硬门禁的 `make defconfig` 证明与 112M profile 的构建证据（当前 `check` 退出 3）；
4. 本机 WAN MAC 的取值与读取方式（第 2 节给出的是方法，不是已验证结果），以及
   `Factory` 校准数据在 112M 布局下的真实位置与是否被改写；
5. factory 与 sysupgrade 的最终文件名；
6. WireGuard 服务端、sing-box 后端、`luci-app-tailscale`、Go 类包在 21.02 工具链上的
   可构建性（见兼容性文档）；
7. 容器存储驱动在最终可写空间上的表现（不假定 overlay2 可用）；
8. 镜像实际大小、剩余 overlay 空间与内存余量；
9. 每个服务的实际运行行为与性能（千兆 NAT 不等于千兆代理）；
10. NAND 型号、容量与坏块状态（112M 布局的逻辑容量是推导值，不是实测）。

在第 8、9 项完成前，本目录中的固件只能标记为“候选、未真机验证”。
