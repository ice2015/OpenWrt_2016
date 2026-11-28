# NX30 Pro 112M 固件验证报告

本文件只记录**实际发生**的验证。计划中的步骤不写进结论，未运行的检查不写成通过，
没有 run ID 与产物哈希的构建不写成一次成功的构建。

| 层级 | 当前状态 |
|---|---|
| 静态实现 | 已完成（源码锁、设备补丁、配置层、最终配置审计、构建编排、工作流定义、文档） |
| 固件候选构建 | **未触发**：没有运行任何 GitHub Action，本地也**未编译**任何固件或 U-Boot |
| `make defconfig` 探针 | **未运行**：真实的 `make defconfig` 从未在本仓库执行过。探针入口已实现（`build.sh --probe-defconfig` 与工作流输入 `probe_defconfig`，默认 false），运行它需要单独授权 |
| 真机验证 | **未授权**，未执行，没有任何设备被接触 |
| 配对启动链候选构建 | 已通过一次授权运行，产出 BL2 与 FIP，默认布局 `immortalwrt-112m`；运行编号、URL、哈希与门禁证据只记在 [`UBOOT-TEST-REPORT.md`](UBOOT-TEST-REPORT.md)。本文件在固件自己跑过之前不记任何运行编号。这不代表本固件已构建，也不代表两者成对可用 |

| 项 | 值 |
|---|---|
| 系统源码 | `https://github.com/hanwckf/immortalwrt-mt798x`，锁定 commit `740103d655bcee6da7bc3b49b1cfdfdee4cd5bb6`，Linux **5.4** |
| feed | `packages`、`luci`、`routing`、`telephony`，四个都固定到 commit（见 [`BUILD.md`](BUILD.md) 第 1.1 节） |
| profile | `h3c_nx30pro_112M`，布局 `immortalwrt-112m`（**默认**）；备选布局 `default`（原厂） |
| 镜像 | `factory.bin` 与 `sysupgrade.bin`，两者都**不是启动链镜像**；最终**文件名**仍是 UNRESOLVED |
| 配对启动链 | `https://github.com/Yuzhii0718/bl-mt798x-dhcpd`，commit `e4cf4dc72d451dc7a86c9508390ad5a2e50743c4`，版本 `SP1`；两边是**同一份分区合同**，地址是 **NMBM** 逻辑地址 |
| 源码锁状态 | `source-candidate-build-blocked`，`firmware_lock.py check` 退出 **3** |

被拒绝的旧底座 `jerryhan77/immortalwrt-mt798x`（revision
`78cf22edddf07443d8f0506c9f361d3498475189`）只作为**被拒绝的证据**保留。它上面的旧固件
Action 连续失败（需求文档记录的最新一次在配置阶段停止，未开始编译），这正是重新锁定
源码与 feed 的原因；本报告不把那些失败当作本次候选的任何证据。

## 1. 已执行的静态验证

以下命令在本次文档任务的工作区里**实际运行**并观察到结果。它们不编译固件，
不获取源码，不运行真实的 `make defconfig`，也不触发任何工作流。

| 命令 | 实际结果 |
|---|---|
| `python3 -m unittest tests.structure.test_nx30pro_firmware_contract tests.scripts.test_nx30pro_firmware_build tests.structure.test_nx30pro_uboot_contract tests.scripts.test_nx30pro_uboot_build tests.workflows.test_workflows` | `Ran 352 tests ... OK`（设备限定的五个模块） |
| `bash scripts/validate.sh` | 退出 0，输出 `Manifest catalog is valid.` |
| `python3 devices/nx30pro/build/firmware_lock.py check --lock devices/nx30pro/source-lock.json` | 退出 **3**，stdout 为空（不打印构建计划）；stderr 逐个列出 18 个硬门禁是 candidate，理由是没有任何被授权的 `make defconfig` 探针证明它们在最终 `.config` 里 |
| `sh devices/nx30pro/build/build.sh --lock devices/nx30pro/source-lock.json --check-only` | 退出 **3**，与上一条同一条错误；没有创建产物目录、没有克隆源码或 feed |
| `python3 tools/manifest.py resolve --distribution immortalwrt-mt798x --device nx30pro --require-build-ready` | 退出 **3**，输出 `source revision is UNRESOLVED` |

即：**构建被阻止**。`manifests/sources.json` 里 `immortalwrt-mt798x` 的 revision 保持
UNRESOLVED，只有被授权的探针通过之后才会写成锁定 commit；在那之前
`--require-build-ready` 与 `scripts/build.sh` 都停在状态码 3。

工作流的静态前置检查也是设备限定的：`bash scripts/validate.sh` 加上三个模块
（`tests.structure.test_nx30pro_firmware_contract`、`tests.scripts.test_nx30pro_firmware_build`、
`tests.workflows.test_workflows`），再跑 `build.sh --check-only` 锁门禁。别的设备的测试
状态不得决定本设备能否构建，仓库全量套件由 `validate.yml` 承担。仓库全量套件在本次
任务中**未运行**。

前序任务记录在案的静态证据（本次未重跑，出处是实施账本）：两个设备补丁在锁定 commit
的纯净检出上 `git apply --check` 通过，打完补丁的树 `verify-device-tree` 与
`verify-image-rules` 都退出 0；三层配置合并出的 seed 有 130 行，对它跑 `verify-config`
退出 1 并列出 39 处依赖缺失，证明 seed 不会被误当成最终配置。

## 2. 未执行的验证

| 项 | 状态 | 需要什么 |
|---|---|---|
| `make defconfig` 硬门禁探针 | 未运行 | 用户单独授权后，以 `probe_defconfig=true` 手动运行 `.github/workflows/build-nx30pro.yml`（或等价的 `build.sh --probe-defconfig`）：装齐四个锁定 feed，对 mediatek/mt7981 跑真实 `make defconfig`，并用 `verify-config --probe` 证明 18 个硬门禁仍是 `=y`。探针只产出 `probe/final.config` 与 `probe/config-audit.json`，不编译、不产出镜像 |
| GitHub Actions 候选构建 | **未触发** | 用户明确授权后手动运行 `.github/workflows/build-nx30pro.yml`（只有 `workflow_dispatch`，`permissions: contents: read`，不使用 Secrets） |
| 镜像产物与 SHA-256 | 不存在 | 授权构建产出的 `images/SHA256SUMS`、`build-report.json`、`final.config`、`packages.txt`、`feeds-lock.json`、`IMAGE-ROLES.txt` 与 `logs/` |
| 最终镜像文件名 | UNRESOLVED | 第一次真实构建列出的 `bin/targets/mediatek/mt7981` 目录内容 |
| 镜像实际大小与剩余 overlay 空间 | UNRESOLVED | 构建报告加真机 `df -h` |
| 主机工具链身份与可复现性 | 不存在 | 授权构建写入的 `logs/host-toolchain.txt` 与两次构建的哈希比较 |
| 真机启动、MAC、`Factory`、服务运行行为 | 未授权 | 单独设计并授权的真机方案，见 [`nx30pro-firmware-install-and-validation.md`](nx30pro-firmware-install-and-validation.md) |

授权构建之后，本文件必须补记：run ID 与 URL、结论、失败步骤与日志位置、产物名字与
SHA-256、最终 `.config` 的审计结果、`packages.txt` 与 `feeds-lock.json` 的实际修订。
即使构建全绿，也只能写成“候选构建完成，未真机验证”，**不得**写成真机可用。

## 3. 产物角色提醒

| 角色 | 规则 | 说明 |
|---|---|---|
| `factory.bin` | 见下 | 112 MiB `ubi` 分区的原始 UBI 镜像，上限 `IMAGE_SIZE := 110592k` |
| `sysupgrade.bin` | 见下 | 带元数据的 sysupgrade tar 包，供 LuCI 升级页与 `sysupgrade` 命令使用 |

两个角色由移植进 `mt7981.mk` 的镜像规则区分：factory 是
`append-ubi | check-size $$(IMAGE_SIZE)`，sysupgrade 是
`sysupgrade-tar | append-metadata`。两者都**不是启动链镜像**，也不能互换；
启动链镜像是 BL2 与 FIP，由 `devices/nx30pro/build/build-uboot.sh` 单独构建，
同样未编译、未真机验证。本文件不提供任何写入命令，刷写边界见
[`FLASH.md`](FLASH.md)，恢复设计见 [`RECOVERY.md`](RECOVERY.md)。

## 4. 真机验证前必须完成的事项

1. 硬门禁探针通过，源码锁从 `source-candidate-build-blocked` 提升为可构建；
2. 经授权触发一次候选构建，并把 run ID、结论、产物名与 SHA-256 记进本文件；
3. **整片闪存**与 `bl2`、`u-boot-env`、`Factory`、`fip`、`ubi` 以及仍存在的
   `pdt_data`、`pdt_data_1`、`exp`、`plugin` 的只读**备份**完成并通过验收；
4. 证明存在一条不依赖候选启动链与候选固件的独立恢复路径；
5. 在原厂布局上读出本机 WAN MAC 并准备好部署值 `/etc/nx30pro/wan-mac`；
6. 确认配对启动链（`SP1` 的 BL2 与 FIP）能启动，且两边是同一份分区合同；
7. 确认镜像里所有非必要服务默认关闭（`90-nx30pro-defaults` 关掉 `passwall`、
   `passwall_server`、`ddns`、`tailscale`、`zerotier`、`dockerd`、`cloudflared`、
   `frpc`、`nlbwmon`、`ttyd`、`sqm`、`etherwake`），且镜像里没有账号、令牌、域名、
   密码或任何设备的 MAC；
8. 取得用户对写入动作单独、**明确的授权**。

在上述任一项未完成前不得写入，也不得把候选产物描述为可刷写发布包。

## 5. 未决项（UNRESOLVED）

与 `source-lock.json` 的 `unresolved` 一一对应，全部尚无证据：

1. 硬门禁的 `make defconfig` 证明；
2. 112M `profile` 与设备树的构建证据（当前只有静态补丁校验）；
3. 设备的 WAN MAC 取值；
4. 112M 布局下的 WAN MAC 读取路径与 `Factory` 校准数据；
5. factory 与 sysupgrade 的最终文件名；
6. Linux 5.4 上的 WireGuard 服务端可构建性；
7. `luci-app-tailscale`（锁定 luci feed 中不存在）；
8. Go 类包（xray-core、xray-plugin、cloudflared、tailscale、docker、dockerd）在 21.02 工具链上的可构建性；
9. 容器存储驱动（`fuse-overlayfs` 在最终可写空间上的表现，不假定 overlay2 可用）；
10. 镜像实际大小与剩余 overlay 空间；
11. 每个服务的运行行为；
12. 设备的 NAND 型号、容量与坏块状态（112M 布局的逻辑容量是推导值，不是实测）。

## 6. 变更记录

| 日期 | 变更 |
|---|---|
| 2026-11-27 | 建立本文件；记录静态实现完成、锁门禁退出 3、候选构建未触发、真实 `make defconfig` 未运行、真机验证未授权 |
