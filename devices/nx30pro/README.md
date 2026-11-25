# NX30PRO

状态：固件待适配；U-Boot 启动链已锁定源码并具备构建入口，产物仍是候选、未真机验证。
本目录没有可构建的固件 manifest，也没有固件支持承诺。

## 目录内容

```text
nx30pro/
├─ README.md
├─ build/       # 设备构建、配置及镜像检查脚本
├─ files/       # 固件 rootfs 覆盖文件
├─ packages/    # 设备专属软件包
├─ patches/     # 设备专属补丁
├─ runtime/     # 设备运行脚本和库
├─ uboot/       # 配套 U-Boot 输入和说明
└─ docs/        # 初始化、运维和验证文档
```

尚未划分 Lite/Full 等变体；固件层的实际配置、源码锁和构建入口在后续适配时添加。
本轮不创建固件 manifest、固件配置，也不进行固件编译或刷写。

## U-Boot 启动链（候选，未真机验证）

| 文件 | 职责 |
|---|---|
| `uboot/uboot-source-lock.json` | 锁定的上游 commit、板级配置、分区合同、NMBM 几何、网页恢复入口与未决项 |
| `build/build-uboot.sh` | 从锁定 commit 构建候选 BL2/FIP，输出 build-report 与 SHA256SUMS；只构建，不刷写 |
| `build/uboot_lock.py` | 源码锁校验、镜像内容识别（ATF FIP 表头、MediaTek BL2 启动头）与构建报告 |
| `docs/nx30pro-uboot-compatibility.md` | 已核实事实、分区合同逐项对照、最小设备补丁与 UNRESOLVED 清单 |
| `docs/nx30pro-uboot-install-and-recovery.md` | 备份、安装、回退与真机验证设计（未授权刷写） |

构建入口在 `.github/workflows/build-nx30pro-uboot.yml`（手动触发，`contents: read`，不使用 Secrets）。
构建脚本读取源码锁；缺少完整 commit、板型不符、分区布局不符或镜像类型未确认时一律拒绝开始构建。

关键结论：上游 U-Boot 的固定分区表是原厂布局（UBI 64 MiB），与所选 112M 系统布局不一致；
本目录用一条设备级 `CONFIG_MTDPARTS_DEFAULT` 补丁对齐，细节与证据见兼容性文档。

待核实：厂商、精确型号及硬件修订、闪存容量与启动方式、发行版与源码 revision、上游 profile、镜像类型、
软件包策略及验收硬件。未知项保持 UNRESOLVED；不得复制其他设备的配置作为已验证事实。

现有设计参考：[固件计划](../../docs/superpowers/plans/2026-11-22-nx30pro-firmware-build.md)、[U-Boot 计划](../../docs/superpowers/plans/2026-11-22-nx30pro-uboot-build.md)。这些历史计划不表示适配已完成。
