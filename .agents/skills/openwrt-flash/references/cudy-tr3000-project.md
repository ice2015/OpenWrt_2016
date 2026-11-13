# Cudy TR3000 项目产物

本页只解释**当前仓库已经实现并由 GitHub Actions 生成**的 Cudy TR3000 v1 产物。它不把构建成功当成某台设备可以刷写的证明，也不替代精确硬件、当前分区和恢复方法的现场核验。

## 当前实现范围

| 用途 | 工作流 | Artifact | 适用范围 | 主要内容 |
| --- | --- | --- | --- | --- |
| Lite 系统固件 | [`TR3000 Lite firmware`](../../../../.github/workflows/build-lite.yml) | `tr3000-lite-128m-ubootmod-112m` | Cudy TR3000 v1、128 MiB NAND、`cudy_tr3000-v1-ubootmod`、112 MiB UBI | `firmware/` 中匹配 profile 的非空 `sysupgrade.bin`、`SHA256SUMS`、构建配置、包清单、源码与 feed 记录、日志 |
| DHCP U-Boot | [`TR3000 DHCP U-Boot`](../../../../.github/workflows/build-uboot.yml) | `tr3000-dhcp-uboot-128m-multilayout` | Cudy TR3000 v1、MT7981、128 MiB multi-layout | `images/` 中各一个 BL2 与 multi-layout FIP、`SHA256SUMS`、`uboot-commit.txt`、`FLASH-TARGETS.txt`、许可证状态和日志 |

以仓库文件为事实源：[Lite 说明](../../../../docs/LITE-README.md)、[U-Boot 安全说明](../../../../docs/UBOOT-SAFETY.md)、[`build-lite.sh`](../../../../scripts/build-lite.sh) 和 [`build-uboot.sh`](../../../../scripts/build-uboot.sh)。工作流或脚本改变后重新读取，不能只依赖本页的旧副本。

以下目标当前**不可从上述产物推导**：

- 256 MiB NAND 的 TR3000：两个 Artifact 都只覆盖 128 MiB，不能下载其中任一文件试刷。
- TR3000 Full：仓库当前没有对应的已实现 GitHub Actions 工作流和发布 Artifact。
- 通用 OpenWrt/ImmortalWrt TR3000：[`manifests/devices/tr3000.json`](../../../../manifests/devices/tr3000.json) 的 target、subtarget、profile 仍是 `UNRESOLVED`；Lite 的固定 profile 不会自动解决通用 manifest。
- 原厂 128 MiB 布局、256 MiB 布局、122 MiB 或其他 UBI 布局：112 MiB UBI 的 U-Boot Mod sysupgrade 不能跨布局套用。
- 新 NAND 批次：Cudy 官方下载页警告 TR3000 1.0 自序列号批次 `2544` 起可能使用 `F50L1G41LC`，旧中间固件或旧 OpenWrt 可能无法启动。即使设备标为 128 MiB，也要重新核实本项目固定源码是否明确支持该 NAND；没有证据时停止。

## 先做硬件与布局门禁

在选择 Artifact 前同时满足以下条件：

1. 设备标签和系统信息确认是 Cudy TR3000 v1，而不是名称相近的 Cudy 型号。
2. 标签、`/proc/mtd`、启动日志或可信硬件资料共同确认 NAND 容量为 128 MiB；记录序列号批次和 NAND 芯片 ID。
3. 系统固件升级还要确认当前 U-Boot、profile 与 112 MiB UBI 布局匹配。仅“当前能启动”不能证明布局相同。
4. U-Boot 操作还要确认当前 BL2、FIP、Factory、环境和 UBI 的实际分区映射、大小、坏块及活动布局；DTS 标签不能替代现场分区表。
5. 备份位于路由器之外并校验可读；Factory/RF 校准、设备身份、BL2、FIP、环境与配置备份都只能回写同一台设备的正确区域。

可在可信本地控制台运行只读检查：

```sh
sh /root/scripts/preflight.sh
cat /proc/mtd
ubinfo -a
cat /etc/openwrt_release
dmesg | grep -Ei 'NAND|spi-nand|bad block|bad-block|MTD|mt7981'
```

`ubinfo` 缺失或失败时补充经确认的只读工具，不根据预期布局伪造结果。还要从本机 UART 或当前 U-Boot 的可信只读页面记录版本、活动布局、启动分区和恢复入口。

## Lite 系统固件选择与验证

运行 **TR3000 Lite firmware**，只从成功完成的运行下载 `tr3000-lite-128m-ubootmod-112m`。解压后：

1. 阅读 `README.txt`、源码提交、最终配置、包清单、feed 锁定记录和日志；失败运行留下的文件不算可用固件。
2. 只接受 `firmware/` 中名称同时包含 `cudy_tr3000-v1-ubootmod` 和 `sysupgrade.bin` 的非空镜像。
3. 用 `firmware/SHA256SUMS` 在另一台主机核验镜像，传到路由器后再次核验；清单与文件必须来自同一次 Artifact。
4. 在设备上运行 `sysupgrade -T` 检查。失败时停止，不能使用 `-F` 绕过。
5. 根据当前系统来源、版本、分区和配置兼容性决定保留或清空配置。跨 fork、跨不兼容布局或证据不足时，不默认保留旧配置。

该 Artifact 是系统 `sysupgrade`，不是 factory、BL2、FIP、原厂 Web 中间固件或通用 recovery 镜像。它不授权修改 bootloader。

## DHCP U-Boot 产物边界

运行 **TR3000 DHCP U-Boot** 只会构建 128 MiB multi-layout 的 BL2/FIP，不产生独立 recovery 镜像。不得把 BL2 或 FIP 改名当作 recovery，也不得与系统 `sysupgrade` 互换。

构建成功只证明固定源码在 CI 中生成了符合脚本文件名、非空和 SHA256 门禁的产物；Actions 变绿不能证明单机兼容、分区对象正确、刷写安全或恢复路径可用。下载后核对：

- Artifact 名、`uboot-commit.txt` 的固定源码提交、`FLASH-TARGETS.txt` 和 `images/SHA256SUMS`；
- BL2 与 FIP 文件名中的 MT7981、Cudy TR3000 v1、2025 和 multi-layout 标记；
- 现场 128 MiB NAND、现有第三方 U-Boot 布局、112 MiB UBI 选择与目标产物逐项一致。

U-Boot 与系统固件必须分别验证、分别授权。只有在本地有现场人员、UART、已验证恢复入口、可恢复镜像和异机备份时，才按**当前硬件与现用 U-Boot 的已验证文档**确定写入方法。仓库刻意不提供猜测的 `mtd write`、`dd`、擦除、偏移写入或环境修改命令；不在远程无人值守设备上更新 BL2/FIP。

## 执行摘要与验收

在任何写入前向用户提交两份彼此独立的摘要（只涉及其已授权的那一份）：

- 系统固件摘要：设备/NAND/序列批次、当前 profile 与布局、工作流运行、Artifact、镜像文件、SHA256、配置保留策略、恢复入口和断网影响。
- U-Boot 摘要：设备/NAND/批次、当前与目标布局、BL2/FIP 来源及 SHA256、实际分区证据、备份、UART/恢复方案、现场人员和停机风险。

系统升级后核对实际板型、版本、UBI/overlay、管理入口、LAN/WAN、DNS 与客户端流量。U-Boot 变更还要先验证恢复入口和布局选择，再加载对应的 112 MiB UBI 系统镜像。CI 编译、散列校验、设备启动、恢复演练和真实联网测试分别报告，不能互相替代。

## 每次重新核实的外部入口

- [OpenWrt Cudy TR3000 设备页](https://openwrt.org/toh/cudy/tr3000)
- [OpenWrt Firmware Selector](https://firmware-selector.openwrt.org/)
- [Cudy TR3000 1.0 下载页](https://www.cudy.com/pages/download-center/tr3000-1-0)
- [Cudy TR3000 256MB 1.0 下载页](https://www.cudy.com/pages/download-center/tr3000-256mb-1-0)

页面内容、稳定版和 NAND 支持会变化。实际操作时记录访问日期和精确页面；不能把本页写入时观察到的版本号称为“最新”。
