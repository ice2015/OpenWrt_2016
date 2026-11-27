# NX30 Pro 受限恢复 U-Boot 验证报告

本文件只记录**实际发生**的验证。计划中的步骤不写进结论，未运行的检查不写成通过。

| 层级 | 当前状态 |
|---|---|
| 静态实现 | 已完成（源码锁、布局白名单、功能门禁、构建编排、工作流定义、文档） |
| U-Boot 候选构建 | 未执行：**未触发** GitHub Actions，本地也**未编译** |
| 真机验证 | 未授权，未执行 |

| 项 | 值 |
|---|---|
| 上游仓库 | `https://github.com/Yuzhii0718/bl-mt798x-dhcpd` |
| 锁定 commit | `e4cf4dc72d451dc7a86c9508390ad5a2e50743c4` |
| 版本 / 树 | `SP1`：`uboot-mtk-20250711` + `atf-20240117-bacca82a8` |
| 布局 | `immortalwrt-112m`（**默认**）、`default`（原厂备选） |

## 1. 已执行的静态验证

以下检查在本工作区实际运行并观察到结果。它们不编译 U-Boot，也不触发任何工作流。

| 命令 | 结果 |
|---|---|
| `python3 -m unittest tests.structure.test_nx30pro_uboot_contract tests.scripts.test_nx30pro_uboot_build` | 见下方“静态验证记录” |
| `bash scripts/validate.sh` | 见下方“静态验证记录” |
| `uboot_lock.py verify-layout-source`（对锁定 commit 的真实设备树） | 通过：设备树只携带 `default` 与 `immortalwrt-112m` 两套布局 |
| `uboot_lock.py verify-patch --source-dir <锁定 commit 的纯净检出>` | 通过：设备补丁可应用，且不含第三个布局、自由 `mtdparts` 或环境写入 |

静态验证记录（2026-11-27，本工作区实际输出）：

| 命令 | 实际结果 |
|---|---|
| `python3 -m unittest tests.structure.test_nx30pro_uboot_contract tests.scripts.test_nx30pro_uboot_build tests.workflows.test_workflows` | `Ran 132 tests ... OK`（复审修复后） |
| `bash scripts/validate.sh` | 退出 0，输出 `Manifest catalog is valid.` |
| `python3 -m unittest discover -s tests -v` | `Ran 506 tests ... FAILED (failures=30, skipped=13)`（全量只在阶段末尾跑一次） |
| `uboot_lock.py preflight --source-dir <锁定 commit 的只读克隆>` | 退出 0；输出 `version: SP1`、`uboot_tree: uboot-mtk-20250711`、`atf_tree: atf-20240117-bacca82a8`、`default_layout: immortalwrt-112m`，证明 `upstream_build_trees` 对**真实** `build.sh` 的 VERSION→树映射解析正确 |
| `uboot_lock.py verify-layout-source --dts <锁定 commit 的真实设备树>` | 退出 0，只列出 `default` 与 `immortalwrt-112m` |
| `uboot_lock.py verify-patch --source-dir <锁定 commit 的纯净检出>` | 退出 0，`git apply --check` 通过 |

上述针对真实源码的三项检查使用的是 `e4cf4dc72d451dc7a86c9508390ad5a2e50743c4` 的
只读 blob-filtered 克隆（未编译、未触发任何工作流）。

注意：工作流的静态前置检查已改为**设备限定**（两个 NX30PRO U-Boot 测试模块 +
workflow 合同测试），不再跑 `discover -s tests`：其他设备的测试状态不得决定本启动链
能否构建，仓库全量套件由 `validate.yml` 负责。固件计划实施期间该目录里存在故意
未通过的 RED 测试，这也是设备限定的原因之一。

全量测试的 30 项失败全部是既存的 TR3000/Lite 失败，与本次改动无关：实施前在基线
工作区（commit `2748192`）运行同一命令得到 `Ran 429 tests ... FAILED (failures=30,
skipped=13)`，两次的失败测试名集合逐项相同。失败集中在
`scripts.test_tr3000_lite_remote_controller`（27 项）、`scripts.test_scripts`
（`test_every_script_supports_help`、`test_lite_network_input_validation`）与
`structure.test_device_isolation`（`test_legacy_libraries_can_be_sourced_from_posix_callers`）。
按授权边界，这些失败只记录、不修复，也不扩大改动范围。

本次实施新增 77 项测试（429 → 506），未引入新的失败。

## 2. 未执行的验证

| 项 | 状态 | 需要什么 |
|---|---|---|
| GitHub Actions 候选构建 | 未触发 | 用户明确**授权**后手动运行 `.github/workflows/build-nx30pro-uboot.yml` |
| BL2 / FIP 产物与哈希 | 不存在 | 授权后的构建产物；文件名含镜像 md5，需从 `build-report.json` 与 `SHA256SUMS` 记录 |
| 工具链身份与可复现性 | UNRESOLVED | 首次成功构建的 `logs/toolchain.json` 与两次构建的哈希比较 |
| 最终 `.config` 证据 | UNRESOLVED | 构建产生的 `logs/effective-config.json` |
| 真机启动、恢复入口、布局切换 | 未授权 | 单独设计并授权的真机方案 |

授权构建后，本文件必须补记：run ID 与 URL、结论、产物名字与 SHA-256、
工具链身份、`effective-config.json` 中的默认布局与危险功能检查结果。
构建成功只能写成“候选构建通过”，**不得**写成真机可用。

## 3. 产物角色提醒

| 角色 | 说明 |
|---|---|
| BL2 | MediaTek SPI-NAND 预加载镜像，写入 `bl2` 分区（NMBM 逻辑 `0x000000`，1 MiB） |
| FIP | 含 BL31 与 BL33/U-Boot 的 ATF 包，写入 `fip` 分区（NMBM 逻辑 `0x380000`，2 MiB） |

两者都**不是系统镜像**，单独一个也不构成恢复路径。所有地址都是 **NMBM 逻辑地址**，
不是物理 NAND 地址。本文件不提供任何写入命令。

## 4. 真机验证前必须完成的事项

1. 整片闪存与 `bl2`、`u-boot-env`、`Factory`、`fip`、`ubi` 以及 OEM 区域
   `pdt_data`、`pdt_data_1`、`exp`、`plugin` 的只读**备份**并校验；
2. 证明存在一条不依赖候选启动链的独立恢复路径；
3. 确认配对固件在没有 `pdt_data_1` 的 112M 布局下能取得 WAN MAC，且不会改写 `Factory`；
4. 取得用户对写入动作的明确授权。

在上述任一项未完成前，不得执行任何写入，也不得把候选产物描述为可刷写发布包。

## 5. 变更记录

| 日期 | 变更 |
|---|---|
| 2026-11-27 | 建立本文件；记录静态实现完成、候选构建未触发、真机验证未授权 |
