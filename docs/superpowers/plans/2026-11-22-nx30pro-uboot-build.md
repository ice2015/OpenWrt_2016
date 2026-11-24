# NX30 Pro 网页 U-Boot 编译计划

> **For agentic workers:** 执行时使用 superpowers:executing-plans，逐项完成复选框。本文件仅为计划，不授权刷写设备。

**Goal:** 为原厂硬件 H3C NX30 Pro 构建可追溯、带网页恢复入口、与选定 112 MiB NMBM 固件布局一致的 U-Boot。

**Architecture:** U-Boot 独立于系统固件构建和发布。先锁定源码、核实设备配置及分区，再构建候选镜像；只有静态匹配和真机验证均完成后，才能标记为可用。

**Tech Stack:** hanwckf/bl-mt798x、MT7981、ATF、U-Boot、SPI-NAND、NMBM、GitHub Actions/Linux。

**Spec:** 本文“设计依据与边界”及配套 [固件计划](2026-11-22-nx30pro-firmware-build.md)，依据本次用户确认的需求编写。

## 设计依据与边界

- 用户设备当前为原厂系统、未改硬件；要求网页刷机/恢复及大分区。
- 系统选择 jerryhan77/immortalwrt-mt798x 的 nx30pro-112m 分支定制。
- 排除 FlyFish-go/H3C-NX30-Uboot：其支持列表中的 NX30 不能等同于 NX30 Pro。
- 候选启动源码为 https://github.com/hanwckf/bl-mt798x ，具体 commit、设备构建参数、工具链版本及产物名称均为 `UNRESOLVED`，须由源码确认。
- Issue #106 记录的 20241115 发布版及 mt7981_h3c_magic-nx30-pro-fip-fixed-parts.bin，只能作为调查线索，不能证明与本计划 112M 布局匹配。
- 不提供未经核实的 mtd 写入命令，不把系统 factory 镜像当成 bootloader 镜像。

## 全局约束

- 本轮只新增计划文档；不下载镜像到设备、不改分区、不刷写、不执行编译。
- 后续构建以 GitHub Actions 为主；本地只能 Linux/WSL2，不在原生 Windows 编译。
- 设备专用输入必须隔离；不更改 TR3000、x86 或其他目标。
- 不手改 work/、output/、cache/ 下的生成内容；只允许构建工具正常生成。
- 设备备份、MAC、序列号、校准数据不得提交 Git，也不上传公开 Actions artifact。

## 方案选择

1. **首选：从固定 commit 构建匹配的网页 U-Boot。** 可核实分区与 NMBM 行为，成本是必须完成源码检查和真机验证。
2. 使用历史预编译镜像：仅在来源、哈希和布局均能验证时考虑；issue 实测不能替代这些证据。
3. 官方 OpenWrt U-Boot layout：不作为当前默认方案，不能与选定的 NMBM 112M 固件直接混用。

## 配套分区合同

以下来自用户指定系统设备树，表示需要逐项核对的合同，并非已验证的 U-Boot 配置。地址属于 NMBM 暴露的逻辑分区空间，不能直接当物理 NAND 写入地址。

| 分区 | 起始 | 大小 |
|---|---|---|
| BL2 | 0x000000 | 0x100000（1 MiB） |
| u-boot-env | 0x100000 | 0x080000（512 KiB） |
| Factory | 0x180000 | 0x200000（2 MiB） |
| FIP | 0x380000 | 0x200000（2 MiB） |
| ubi | 0x580000 | 0x7000000（112 MiB） |

UBI 结束位置为 0x7580000。其后空间用途、NMBM 保留区、坏块处理及逻辑容量必须结合两端源码核实，不能按“128M 减分区”自行分配。

## Review Focus

1. NX30 与 NX30 Pro 混淆：设备构建检查应拒绝错误板型。
2. U-Boot 与内核分区不一致：合同校验应在构建/发布前失败。
3. NMBM 参数或 NAND 支持不一致：必须检查源码，并记录真机识别结果。
4. 镜像内容与刷写对象混淆：产物说明必须区分 BL2、FIP 和组合镜像。
5. 恢复依赖已损坏的启动链：网页恢复不能代替独立恢复路径及原厂备份。

## Task 1：锁定源码和板级配置

**拟建文件：** `configs/devices/nx30pro/uboot-source-lock.json`、`docs/nx30pro-uboot-compatibility.md`。这是实施期新增文件，本轮不创建。

- [ ] 读取上游 README、build.sh 以及 NX30 Pro 的 defconfig、DTS、分区和网页升级处理代码，定位真实板名及 ATF/U-Boot 目录。
- [ ] 选择并记录完整 commit、工具链来源/版本/校验和、依赖 revision；不得只锁定分支名。
- [ ] 核实 DDR 类型、SPI-NAND、NMBM 启用状态、保留参数、网页升级支持的格式及恢复地址。
- [ ] 逐项对照上述分区合同；检查 NMBM 映射和 Factory 读取方式。若不一致，记录最小设备补丁或停止，不套用其他设备参数。
- [ ] 在兼容性文档列出可确认事实和 `UNRESOLVED` 项；不能在关键项未确认时生成可刷写发布包。

**验收：** 能从锁定 commit 定位每项配置来源；系统与启动链布局一致，有明确证据。

## Task 2：建立独立构建和静态校验

**拟建文件：** `scripts/build-nx30pro-uboot.sh`、`.github/workflows/build-nx30pro-uboot.yml`、`tests/test_nx30pro_uboot_contract.py`。

**接口：** 脚本读取设备源码锁，输出镜像及 build-report；不执行刷写。报告至少包含源码 commit、工具链版本、构建参数、分区表和 SHA-256。

- [ ] 添加测试：错误板型、布局不一致、缺少 commit、镜像类型未确认时必须拒绝构建就绪状态；运行并确认失败。
- [ ] 实现脚本，按核实后的上游参数调用 build.sh；保留构建日志，不猜 BOARD 值。
- [ ] 加入手动触发的 Actions，使用 contents: read；普通 PR 不获取 Secrets、不发布镜像。
- [ ] 校验镜像是否能装入对应分区；确认产物是 FIP、BL2 或组合包及其所含组件，不依文件名推断。
- [ ] 运行测试、检查脚本语法；执行构建，上传镜像、锁文件、日志、build-report 和 SHA256SUMS。
- [ ] 从干净环境按相同锁重建；比较哈希，若不同，调查时间戳/路径等因素并记录，不能直接宣称逐字节可复现。

**验收：** 干净环境构建成功；静态检查通过；仍标记“候选、未真机验证”。

## Task 3：备份和真机验证设计

**拟建文件：** `docs/nx30pro-uboot-install-and-recovery.md`。

- [ ] 识别本机固件版本、硬件修订、NAND 型号及当前 MTD/启动日志；敏感值只在本地保留。
- [ ] 制定完整闪存及关键分区的备份、哈希校验和恢复步骤，特别保留 Factory、MAC 所在数据及原厂布局证据。
- [ ] 确认原厂系统到候选 U-Boot 的安装入口及独立恢复手段；没有证据就保持未解决，不借用其他机型命令。
- [ ] 在实际刷写前列出准确文件、SHA-256、写入对象、回退路径和数据损失范围，单独供用户审阅。
- [ ] 获得实际刷写授权后，测试网页恢复入口、正常冷启动、复位按钮和配套最小系统启动；不以主动断电写入作为验收手段。
- [ ] 验证启动日志中的 NMBM、分区、MAC、无线校准与系统侧一致；再测试匹配 factory 镜像的网页安装。

**验收：** 本机测试记录包含硬件信息、镜像哈希、启动日志和结果；原厂恢复可行性单独报告，不未经验证承诺一键回原厂。

## 必要检查与交付

后续实现相关代码后，在仓库根目录执行：

```sh
bash scripts/validate.sh
python -m unittest discover -s tests -v
```

同时检查未知配置的构建阻止行为、设备隔离及新脚本语法。交付镜像与说明必须明确区分“编译通过”“静态布局匹配”“本机验证通过”三种状态。

## 参考资料

- [hanwckf/bl-mt798x](https://github.com/hanwckf/bl-mt798x)
- [Issue #39：NMBM 回复](https://github.com/hanwckf/bl-mt798x/issues/39)（历史用户讨论）
- [Issue #106：NX30 Pro 实测组合](https://github.com/hanwckf/bl-mt798x/issues/106)（历史用户实测，不等于 112M 兼容证明）
- [所选 112M 设备树](https://github.com/jerryhan77/immortalwrt-mt798x/blob/nx30pro-112m/target/linux/mediatek/files-5.4/arch/arm64/boot/dts/mediatek/mt7981-h3c-nx30pro-112M.dts)

资料核查日期：2026-11-22。链接分支会变化，实施时必须固定 commit。
