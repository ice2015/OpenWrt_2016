# DHCP U-Boot 构建与刷写安全

> **警告：引导程序刷错可能使设备无法启动。** 当前设备已安装第三方 U-Boot，并不构成另一个 U-Boot 可无条件覆盖的依据。禁止远程无人值守刷写。

## 固定构建目标

独立工作流 **TR3000 DHCP U-Boot** 固定到 [`weekdaycare/bl-mt798x-dhcpd`](https://github.com/weekdaycare/bl-mt798x-dhcpd) commit `f6b361ed80012244b1ed33be1b5080b4d65e83fb`。该 commit 的配置文件包含 `mt7981_cudy_tr3000-v1_defconfig` 和 `mt7981_cudy_tr3000-v1_multi_layout_defconfig`。工作流实际运行：

```sh
SILENT=Y SOC=mt7981 BOARD=cudy_tr3000-v1 VERSION=2025 MULTI_LAYOUT=1 ./build.sh
```

只构建 Cudy TR3000 128 MiB 多布局目标；不构建 256 MiB U-Boot。产物中 `bl2-...` 与 `fip-...-multi-layout...` 分开保存并分别计算 SHA256。BL2 是预加载/BL2 镜像，FIP 包含 U-Boot/FIP；必须按照当前硬件分区映射和对应设备文档判定刷写对象。该版本的构建脚本不产生独立恢复镜像，不能把 BL2/FIP 改名为 recovery。

构建完成只表示编译/文件名和 SHA 检查通过，不证明镜像适配某台设备，也不会执行刷写。

## 刷写前强制核验

1. 在本地串口或可信本地控制台运行：

   ```sh
   sh /root/scripts/preflight.sh
   cat /proc/mtd
   ubinfo -a
   cat /etc/openwrt_release
   dmesg | grep -Ei 'NAND|spi-nand|bad block|bad-block|MTD|mt7981'
   ```

   收集 NAND 型号、容量、坏块、UBI 卷、系统构建信息及实际 BL2/FIP/Factory 分区。`preflight.sh` 为只读报告；`ubinfo` 不可用或失败时先用经确认的设备工具补充检查，不要猜。

2. 通过本机 UART/现用 U-Boot 受信任的只读信息页，记录 U-Boot 版本、当前活动布局/启动分区及恢复入口。DTS 提供的标签只能作为交叉比对，不能代替当前硬件分区表。
3. 使用适用于该板修订的已验证方法备份**全部**分区，包括 Factory/RF 校准、BL2、FIP/U-Boot、环境、bdinfo 和 UBI 数据。保留原始文件名/大小；异机保存所有备份并在异机计算 SHA256。不要只备份 UCI 配置。
4. 确认 UART 接线/驱动、可用恢复 UI 或经验证的串口恢复流程、已知可恢复的镜像和现场操作人员。先在可控实验台验证恢复流程。
5. 确认设备确实为 128 MiB NAND 的 TR3000 v1，确认当前第三方 U-Boot 的分区布局，并将目标 U-Boot 的 multi-layout 选择与 112 MiB UBI 固件布局逐项匹配。若任一信息不确定，停止。
6. 单独下载构建 Artifact，异机校验 SHA256；核实文件名中的芯片、板型、版本、multi-layout 标记和 Artifact 的固定源码 commit。

没有充分证据前，**不要执行任何 `mtd write`、`dd`、擦除、偏移写入或 bootloader 环境修改命令**。本仓库不提供这些写入命令，因为现用第三方布局、分区映射和设备修订尚未由现场只读检查确认。

## 固件刷入注意事项

- 先确认 DHCP U-Boot 已可靠安装且恢复界面可用，再选择明确匹配的 112 MiB U-Boot Mod 系统镜像。
- 升级前再次确认 U-Boot 当前布局选项与镜像一致；不要跨不兼容布局勾选“保存旧配置”。
- 系统编译工作流不会刷写 bootloader；U-Boot 与系统固件必须分别验证、分别授权。
- 不在远程无人值守现场更新 BL2/FIP；断电、网络断开或错误布局都可能造成不可恢复故障。
- 具体写入区域、按钮/网页名称和恢复步骤必须来自对应硬件版本及当前 U-Boot 的已验证文档。该信息未知时明确保持未解决。
