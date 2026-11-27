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

静态验证记录（由实施 Agent 填写实际输出摘要，不得写“应该通过”）：

- 聚焦测试：UNRESOLVED（待本轮实施结束时补记实际结果）
- `scripts/validate.sh`：UNRESOLVED（同上）
- 仓库全量测试：UNRESOLVED（同上；其中 TR3000/Lite 的既存失败只记录、不修复）

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
