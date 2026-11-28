# NX30 Pro 受限恢复 U-Boot 验证报告

本文件只记录**实际发生**的验证。计划中的步骤不写进结论，未运行的检查不写成通过。

| 层级 | 当前状态 |
|---|---|
| 静态实现 | 已完成（源码锁、布局白名单、功能门禁、构建编排、工作流定义、文档） |
| U-Boot 候选构建 | **已通过**（授权运行 run ID `46096386417`，2026-11-28）；报告状态为 `candidate-not-verified-on-device` |
| 真机验证 | **未授权**，未执行：没有刷写、没有擦除、没有启动测试 |

| 项 | 值 |
|---|---|
| 上游仓库 | `https://github.com/Yuzhii0718/bl-mt798x-dhcpd` |
| 锁定 commit | `e4cf4dc72d451dc7a86c9508390ad5a2e50743c4` |
| 版本 / 树 | `SP1`：`uboot-mtk-20250711` + `atf-20240117-bacca82a8` |
| 布局 | `immortalwrt-112m`（**默认**）、`default`（原厂备选） |

## 1. 已执行的静态验证

以下检查在本工作区实际运行并观察到结果。它们不编译 U-Boot，也不触发任何工作流。

| 命令 | 实际结果 |
|---|---|
| `python3 -m unittest tests.structure.test_nx30pro_uboot_contract tests.scripts.test_nx30pro_uboot_build tests.workflows.test_workflows` | `Ran 132 tests ... OK`（复审修复后） |
| `bash scripts/validate.sh` | 退出 0，输出 `Manifest catalog is valid.` |
| `python3 -m unittest discover -s tests -v` | `Ran 506 tests ... FAILED (failures=30, skipped=13)`（全量只在阶段末尾跑一次） |
| `uboot_lock.py preflight --source-dir <锁定 commit 的只读克隆>` | 退出 0；输出 `version: SP1`、`uboot_tree: uboot-mtk-20250711`、`atf_tree: atf-20240117-bacca82a8`、`default_layout: immortalwrt-112m` |
| `uboot_lock.py verify-layout-source --dts <锁定 commit 的真实设备树>` | 退出 0，只列出 `default` 与 `immortalwrt-112m` |
| `uboot_lock.py verify-patch --source-dir <锁定 commit 的纯净检出>` | 退出 0，`git apply --check` 通过 |

上述针对真实源码的三项检查使用的是 `e4cf4dc72d451dc7a86c9508390ad5a2e50743c4` 的
只读 blob-filtered 克隆（未编译、未触发任何工作流）。

全量测试的 30 项失败全部是既存的 TR3000/Lite 失败，与本次改动无关：实施前在基线
工作区（commit `2748192`）运行同一命令得到 `Ran 429 tests ... FAILED (failures=30,
skipped=13)`，两次的失败测试名集合逐项相同。按授权边界，这些失败只记录、不修复，
也不扩大改动范围。

工作流的静态前置检查是**设备限定**的（两个 NX30PRO U-Boot 测试模块 + workflow 合同
测试）：其他设备的测试状态不得决定本启动链能否构建，仓库全量套件由 `validate.yml` 承担。

## 2. 已执行的候选构建（授权运行）

| 项 | 值 |
|---|---|
| run ID | `46096386417` |
| URL | https://github.com/ice2015/OpenWrt_2016/actions/runs/46096386417 |
| 工作流 | `.github/workflows/build-nx30pro-uboot.yml`（`workflow_dispatch`，手动触发） |
| 分支 / commit | `codex/nx30pro-firmware-build` @ `dc12477` |
| 触发时间 | 2026-11-28T02:06:03Z |
| 结论 | `success`，8 个步骤全部 `success` |
| 产物 | `nx30pro-uboot-candidate-112m`、`nx30pro-uboot-candidate-logs` |

产物与门禁证据（取自下载的 artifact，逐项核对，不采信“绿色即通过”）：

| 核验项 | 实际值 |
|---|---|
| BL2 | `bl2-mt7981_h3c_magic-nx30-pro_SP1_md5-d790ec64347cf25ace5ec867f0bbb113.img`，238432 字节（< 1 MiB 分区），`SPINAND!` 头 |
| BL2 SHA-256 | `6498a8e73fc331dd533d9466839453cc9ef66e2464b0a179c95d7950e4e7298e` |
| FIP | `fip-mt7981_h3c_magic-nx30-pro_SP1-Yuzhii-dhcpd-fixed-parts-multi-layout_md5-b89addb7e585fe8848948a3af85512b2.bin`，916865 字节（< 2 MiB 分区），ATF 目录头含 BL31（33065 字节）与 BL33（883664 字节，带 `U-Boot` 标记） |
| FIP SHA-256 | `c0ea269471d40a2431ba3dcf067123098b122dbe1000d8e1bc12f423d3b6bd43` |
| 构建参数 | `SOC=mt7981`、`BOARD=h3c_magic-nx30-pro`、`VERSION=SP1`、`VARIANT=default`、`FIXED_MTDPARTS=1`、`MULTI_LAYOUT=1`、`SIMG=0`、`UBIMNG=0`、`TELNETD=0`、`NAND_RAW=0`、`FSTHEME=bootstrap`、`SILENT=Y` |
| 分区表 | `BL2 0x000000/0x100000`、`u-boot-env 0x100000/0x80000`、`Factory 0x180000/0x200000`、`FIP 0x380000/0x200000`、`ubi 0x580000/0x7000000`（NMBM 逻辑） |
| 布局白名单 | `logs/layout-source.json`：只有 `default` 与 `immortalwrt-112m`，默认 `immortalwrt-112m` |
| 最终配置 | `logs/effective-config.json`：15 个必需符号全部启用；`CONFIG_WEBUI_FAILSAFE_FACTORY`、`_FLASH`、`_ENV`、`_CONSOLE`、`_UBI`、`_SIMG` 与 `CONFIG_MTK_TELNETD` 全部显式关闭；`mtdparts_default` 为 `null`（**没有**回退到单布局原厂表） |
| 设备补丁 | `logs/device-patch.json`：6 个上游文件全部 `Applied ... cleanly` |
| 工具链 | `aarch64-linux-gnu-gcc (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0`，包版本 `4:13.2.0-7ubuntu1`，编译器二进制 SHA-256 `cd90adc7801f4595267f61a5d25bd3a0c6beb2f9f1f107ab919a97a12972dc9a` |
| 报告状态 | `build-report.json` 的 `status` 为 `candidate-not-verified-on-device` |
| 构建日志 | 唯一警告是上游 `CONFIG_OF_EMBED is enabled` 提示（该 MediaTek 树的既有设定），非本次改动引入 |

**这次运行证明了什么**：锁定 commit 能编译；设备补丁能干净应用；最终配置携带锁定的
受限功能集与 112M 默认布局；两个产物结构正确且不超过各自分区。

**这次运行没有证明什么**：设备能否启动、恢复入口是否可用、布局切换是否安全、
BL2/FIP 与固件是否配对可用。这些都属于真机验证，目前**未授权**。

## 3. 仍未执行的验证

| 项 | 状态 | 需要什么 |
|---|---|---|
| 产物逐字节可复现性 | UNRESOLVED | 第二次授权运行后比较两份 `SHA256SUMS`；上游把时间戳与镜像 md5 写进产物与文件名 |
| 固件侧配对 | UNRESOLVED | 固件候选构建通过后，与本次 BL2/FIP 一起做配对启动测试 |
| 真机启动、恢复入口、布局切换 | 未授权 | 单独设计并授权的真机方案 |

## 4. 产物角色提醒

| 角色 | 说明 |
|---|---|
| BL2 | MediaTek SPI-NAND 预加载镜像，写入 `bl2` 分区（NMBM 逻辑 `0x000000`，1 MiB） |
| FIP | 含 BL31 与 BL33/U-Boot 的 ATF 包，写入 `fip` 分区（NMBM 逻辑 `0x380000`，2 MiB） |

两者都**不是系统镜像**，单独一个也不构成恢复路径。所有地址都是 **NMBM 逻辑地址**，
不是物理 NAND 地址。本文件不提供任何写入命令。

## 5. 真机验证前必须完成的事项

1. 整片闪存与 `bl2`、`u-boot-env`、`Factory`、`fip`、`ubi` 以及 OEM 区域
   `pdt_data`、`pdt_data_1`、`exp`、`plugin` 的只读**备份**并校验；
2. 证明存在一条不依赖候选启动链的独立恢复路径；
3. 确认配对固件在没有 `pdt_data_1` 的 112M 布局下能取得 WAN MAC，且不会改写 `Factory`；
4. 取得用户对写入动作的明确授权。

在上述任一项未完成前，不得执行任何写入，也不得把候选产物描述为可刷写发布包。

## 6. 变更记录

| 日期 | 变更 |
|---|---|
| 2026-11-27 | 建立本文件；记录静态实现完成、候选构建未触发、真机验证未授权 |
| 2026-11-28 | 用户授权阶段二；触发 run `46096386417` 并逐项核对产物与门禁证据，候选构建通过；真机验证仍未授权 |
