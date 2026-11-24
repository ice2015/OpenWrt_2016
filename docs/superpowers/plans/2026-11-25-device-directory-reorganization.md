# 设备目录重构执行计划（当前基线版）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 按型号集中 TR3000 文件，保持 Lite/Full/U-Boot 的构建行为，并建立 A6S、NX30Pro 待适配入口。

**Architecture:** 真实设备实现和输入归入 devices/tr3000，公共工具共享；根脚本保留兼容入口。变体专属 runtime、overlay 和 LuCI 包分别归属 lite/full。

**Tech Stack:** POSIX sh、Bash、Python 标准库 unittest、JSON manifests、OpenWrt Kconfig、GitHub Actions。

**Spec:** `docs/superpowers/specs/2026-11-25-device-directory-reorganization-design.md`，用户于 2026-11-25 批准。本计划取代旧计划作为执行入口；旧计划保留历史内容。

## Global Constraints

- 保持 `common → distribution → device → local`，设备内部依次应用 shared 和选定变体。
- 保持当前源码/feed SHA、包策略、服务默认值、profile、分区限制、产物名及最新真机修复。
- 不引入新的调度框架，不重写脚本业务逻辑，不做新设备适配或刷机。
- 不修改生成目录及 local 私有数据；未知硬件和源码字段继续 UNRESOLVED。
- 不自动提交、推送、发布或触发远端构建。此次设计及后续计划先留在工作区供审阅。
- 两个旧 worktree 已由用户确认合并；以 master `9ecfdc3237c22d7be1dcd23bc4e33a48cfa83e69` 为已核实基线，执行前复查。
- Actions 名称、触发方式、已有构建参数和产物标识不变；目录引用必须同步。
- 每阶段留下可审阅差异，不自动 git commit。不得回退用户修改。

## 文件映射与职责

| 原文件或范围 | 新位置与职责 |
| --- | --- |
| configs/devices/tr3000.config | devices/tr3000/config.config：设备配置片段 |
| configs/{lite,full}.seed | devices/tr3000/{lite,full}/config.seed |
| feeds/devices/tr3000-{lite,full}.lock | devices/tr3000/{lite,full}/feeds.lock |
| files/ | devices/tr3000/shared/files/：保留整体复制行为 |
| overlays/devices/tr3000-{lite,full}/files/ | devices/tr3000/{lite,full}/files/ |
| packages/luci-app-tr3000-{lite,full}/ | devices/tr3000/{lite,full}/packages/ 下同名包 |
| scripts/{build-lite,build-full,configure-lite,configure-full,build-uboot,verify-image}.sh | devices/tr3000/build/ 下同名文件 |
| scripts/prepare-lite-ddns.py | devices/tr3000/build/prepare-lite-ddns.py |
| patches/devices/tr3000-lite/ddns/0001-reserve-managed-bulk-start.patch | devices/tr3000/lite/patches/ddns/0001-reserve-managed-bulk-start.patch |
| scripts/{plant-profile,plant-access,preflight,lite-common,lite-uplink-watch,service-toggle,singbox-rollback}.sh | devices/tr3000/shared/runtime/ 下同名文件，先核实实际读取关系 |
| scripts/tr3000-lite-*、scripts/tr3000-full-* | devices/tr3000/{lite,full}/runtime/ 下同名文件 |
| 两份 configs/devices/TR3000/ 提示词 | devices/tr3000/{lite,full}/requirements.md |
| docs/{LITE,FULL}-README.md | devices/tr3000/{lite,full}/README.md，旧位置留导航 |
| docs/UBOOT-SAFETY.md、cudy-tr3000-uboot-flashing-record.md | devices/tr3000/uboot/{README,flashing-record}.md，旧位置留导航 |
| docs/{WIREGUARD-VPS-ROUTING,WIREGUARD-SNAT,TAILSCALE,SINGBOX-SPLIT-ROUTING,CLOUDFLARED-ACCESS,TEST-PLAN}.md | devices/tr3000/docs/ 下同名文档，旧位置留导航 |

新增 devices/README.md、devices/tr3000/README.md、devices/{a6s,nx30pro}/README.md 和 tests/structure/test_device_isolation.py。tests、集中 manifests、公共 configs/feeds/patches/overlays、公共 scripts/lib 和 Actions 保持位置。现有测试继续使用 unittest，不引入 pytest。

## Review Focus

1. 从仓库外、带空格路径调用旧脚本：参数和退出状态保持一致（Task 3）。
2. 被 source 的库误用 exec 包装、宿主转发器装进固件：验证真实安装与库查找（Task 3）。
3. 新增 Lite/Full 文件遗漏、Windows 大小写掩盖旧路径：完整引用搜索与 Linux 校验（Task 1、5）。
4. cache hashFiles 空匹配或含另一变体输入：逐个验证路径存在和输入范围（Task 4）。
5. 迁移丢失真机修复或放宽 UNRESOLVED 门禁：保留现有完整回归及状态码检查（Task 2、5）。

## Task 1：记录基线和目录契约

**Files:** devices/README.md、devices/tr3000/README.md、AGENTS.md、docs/configuration-layers.md、tests/structure/test_repository_contract.py；新增 `docs/superpowers/plans/2026-11-25-device-directory-reorganization-inputs.json` 保存迁移源/目标/SHA256 对照。

**Interfaces:** 不改变 CLI 或 manifest schema；为后续任务提供完整迁移映射和原文件内容证据。

- [x] 按 using-git-worktrees 技能确定隔离 checkout；复查 git status、worktree、HEAD，保护已批准设计和本计划。
- [x] 读取两个 configure 的全部安装动作、相关构建脚本和测试，补充映射中的真实源文件；不要按通配符盲目搬移未核实文件。
- [x] 对映射中的全部源文件记录路径与 SHA256，不读取 local，不扫描生成目录。
- [x] 运行 `bash scripts/validate.sh`、`python -m unittest discover -s tests -v`，记录数量、失败或跳过原因；确认可用 Bash/Linux/WSL 环境。
- [x] 添加 RepositoryContractTests.test_device_index_documents_existing_variants，断言索引包含 tr3000/a6s/nx30pro，TR3000 包含 lite/full/uboot 导航；先运行 `python -m unittest tests.structure.test_repository_contract.RepositoryContractTests.test_device_index_documents_existing_variants -v` 确认因文件缺失失败。
- [x] 创建索引并更新目录规范：shared 仅 TR3000 内部共享，shared 和变体均为 device 层；新型号导航明确未适配。
- [x] 重跑该测试和 `git diff --check`，检查阶段差异，不提交。

## Task 2：迁移构建输入，保持安装结果

**Files:** 映射中的 config、seed、lock、files、overlay、两个 LuCI 包；manifests/devices/tr3000.json；scripts/configure-{lite,full}.sh、scripts/build-{lite,full}.sh；.github/workflows/build-{lite,full}.yml；tests/{scripts,structure,workflows}/ 下所有活动源路径消费者。

**Interfaces:** tr3000.config_layers 变为 `["devices/tr3000/config.config"]`；输入引用定位改变，复制次序和固件内路径不变。

- [x] 添加 test_tr3000_inputs_live_under_device_directory，断言新输入存在且实际 configure 使用新路径；先运行结构测试确认新路径缺失失败。
- [x] 移动映射中的输入文件并逐个核对 SHA256；保留原 files 全量复制后叠加变体 files 的顺序。
- [x] 更新两个 configure 的 seed/overlay/package/shared files 引用，更新 build 的 lock 引用和 workflow 的 seed/lock hashFiles 参数。
- [x] 同步 tests/scripts、tests/structure、tests/workflows 及 tests/device 中直接读取上述宿主路径的代码，保留行为断言，不批量改设备内路径。
- [x] 运行 `python -m unittest tests.scripts.test_scripts tests.scripts.test_lite_build_evidence tests.scripts.test_full_build_evidence tests.structure.test_repository_contract tests.structure.test_lite_device_readiness tests.workflows.test_workflows -v`，确认配置合并、必需/排除包、loopback、SSH 与工具依赖断言继续通过。
- [x] 检查差异与输入哈希，记录只有引用变更的文件，不提交。

## Task 3：迁移 runtime 与构建实现，保留旧入口

**Files:** 映射中的 scripts 文件及其兼容入口；两个真实 configure；tests/scripts/ 全部脚本消费者；tests/structure/test_lite_device_readiness.py；tests/device/ 中活动宿主路径。

**Interfaces:** build 脚本以自身目录上一级为 DEVICE_ROOT，上三级为 REPO_ROOT；shared 与选定变体 runtime 为安装来源。外部原命令行参数及退出状态不变。

- [x] 添加旧入口从仓库外和带空格路径运行 --help 的回归；对支持该参数的命令使用 --help，对其他命令使用已知只读查询或现有安全测试夹具，禁止实际变更网络。
- [x] 添加 test_installed_runtime_scripts_are_real_device_scripts：对两变体配置夹具比较安装文件与对应 runtime 字节，拒绝含宿主 devices 路径的包装器，验证库文件位于设备预期路径；先运行新增测试确认失败。
- [x] 迁移七个共享脚本和全部变体专属脚本，configure 从真实 runtime 安装；核实源库和脚本相对调用，保留设备内布局和权限。
- [x] 迁移六个构建实现及 prepare-lite-ddns.py，修正根目录定位和真实 configure/verify 调用；Python 辅助入口保持 main() 行为并完整转发参数。
- [x] 为旧可执行入口建立薄转发；被 source 的库用可 source 的兼容路径，不把库改成 exec 程序。更新测试直接读取实现时的源路径。
- [x] 运行 `python -m unittest discover -s tests/scripts -v` 及 `python -m unittest tests.structure.test_lite_device_readiness -v`；对迁移的 shell 用 `sh -n` 检查，验证原始拒绝参数时无副作用及退出码一致。
- [x] 用 SHA256 对照确认 runtime 业务内容未变化，单独审查必要的相对路径修改，不提交。

## Task 4：落实 manifest 与 Actions 隔离

**Files:** tools/manifest.py、tests/manifest/test_manifest.py、tests/structure/test_device_isolation.py、tests/workflows/test_workflows.py、三个 TR3000 workflow。

**Interfaces:** 复用 validate_catalog(catalog, root) -> list[str] 与 _validate_layer 校验流程；不新增解析器。现有 require-build-ready 的退出语义不变。

- [x] 添加 manifest 测试：config/feed/patch/overlay 引用其他 devices/<id> 时拒绝；自身路径和公共路径通过；路径越界与符号链接逃逸继续拒绝。先确认跨设备测试在修改前失败。
- [x] 在现有校验入口加入设备归属校验，覆盖词法路径和实际解析后的归属，不放松现有边界。
- [x] 更新三个 workflow 调用 devices/tr3000/build 下的真实实现，保留触发器、权限、参数、产物名、缓存前缀和并发分组。
- [x] 添加 workflow 测试：每个 hashFiles 路径存在且匹配非空；Lite 与 Full 不引用对方专属输入；source/output/ccache/concurrency 按变体隔离。需要调整时仅修改 workflow 的显式目录参数。
- [x] 添加临时三设备夹具隔离测试，读取实际 manifest 层解析结果生成输入清单；单设备变动不改变其他设备清单哈希。
- [x] 使用实际 configure 安装夹具记录 Lite/Full 的真实读取输入：变体修改只影响自身；shared 修改可以影响两者。不得以自建无关哈希算法替代实际消费者验证。
- [x] 运行 `python -m unittest tests.manifest.test_manifest tests.structure.test_device_isolation tests.workflows.test_workflows -v`；审查状态与缓存差异，不提交。

## Task 5：迁移文档、更新技能并总体验收

**Files:** 映射中的设备文档；devices/{a6s,nx30pro}/README.md；README.md、docs/{architecture,configuration-layers,adding-a-device,package-build-and-install-guide}.md；.agents/skills/openwrt-firmware-config/SKILL.md；项目刷机技能的活动路径；tests/skills/、tests/structure/test_repository_contract.py；设计和迁移证据记录。

**Interfaces:** 旧操作文档保留新位置导航，历史 specs/plans 不批量改写；A6S/NX30Pro 不新增可构建目标。

- [x] 添加导航测试：两新设备明确未适配，列出精确型号/修订、闪存/启动、源码、profile、镜像、包策略和验收硬件待核实项；不继承 TR3000 的 112 MiB/profile。
- [x] 按映射迁移文档和提示词，修复相对链接，旧操作文档保留导航；NX30Pro README 链接已有 firmware/uboot 历史计划。
- [x] 更新全局文档、配置技能及刷机技能的活动引用；只调整迁移相关路径，不改变刷写命令或硬件结论。技能编辑遵循 writing-skills 的相关要求。
- [x] 用 rg 搜索全部旧输入路径和 scripts 直接读取关系，逐项归类为兼容入口、迁移导航、历史记录，修复其余活动引用。
- [x] 运行 `git diff --check`、`bash scripts/validate.sh`、`python -m unittest discover -s tests -v`，确认全部通过或明确环境跳过。
- [x] 运行 `bash scripts/list-targets.sh`，核对六个组合状态；分别运行 `python tools/manifest.py resolve --distribution immortalwrt --device <id> --require-build-ready`，id 依次为 tr3000、x86-64、raspberry-pi，预期均为状态码 3。
- [x] 在 Linux/WSL 环境复查脚本调用、文件权限和大小写敏感路径；不可用时记录未验证，不将 Windows 检查等同于 Linux 通过。
- [x] 更新 SHA256 对照中的目标哈希及必要引用修改说明；汇总 Actions Lite/Full/U-Boot 待验证项，不触发构建。
- [x] 完整差异审查后交付：修改范围、本地检查结果、兼容证据和未验证项。实施者调用 verification-before-completion 后才报告完成。

## 自审结果

覆盖已批准设计的文件归属、CLI/库兼容、变体隔离、旧 worktree 处理结果、真机修复保护、文档/技能更新、UNRESOLVED 门禁和 Actions 交接。五项 Review Focus 均有对应任务验证。历史计划的自动提交建议及尚未合并描述不再作为当前执行要求。

## 执行结果（2026-11-25）

已执行，详情见 [验证记录](2026-11-25-device-directory-reorganization-verification.md)。最终 Linux 完整回归 356 项、13 项跳过、0 失败；100 个迁移源文件原 SHA256 均与基线 Git blob 一致。阶段测试与最终完整回归共同覆盖计划中的脚本、结构、manifest、技能和工作流检查，避免重复运行同一套耗时回归。

旧库兼容使用 Git 符号链接，旧可执行命令保留原 mode；这取代最初的库转发实现。Actions/真实镜像/真机验证留待后续手动执行，本轮未触发。目录骨架后续补齐 A6S/NX30Pro/WR30U；现按用户新授权提交并推送独立分支，不合并 master。
