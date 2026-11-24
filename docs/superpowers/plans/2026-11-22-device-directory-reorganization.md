# 按路由器硬件型号分类的目录重构执行计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将设备专属文件按硬件型号集中组织，使调整 TR3000、A6S 或 NX30Pro 专用目录里的固件配置时，不改变其他型号的构建输入、配置和产物；保留 TR3000 Lite / Full 的现有行为。

**Architecture:** 建议新增 `devices/<device-id>/`，集中保存该设备的配置、固件变体、overlay、feed 锁定、运行脚本、软件包及操作文档。公共构建工具、发行版配置、设备索引和 Actions 工作流仍集中维护；目录变化不改变配置优先级。

**Tech Stack:** Bash / POSIX sh、Python 标准库 unittest、JSON manifests、原生 OpenWrt Kconfig、GitHub Actions。

**Spec:** 用户在当前聊天提出按硬件型号分类，并计划加入 A6S、NX30Pro；约束依据 `AGENTS.md`、`docs/configuration-layers.md` 和 `docs/architecture.md`。本文件同时记录建议设计与执行步骤，尚未批准实施；只编写本计划，不执行迁移。

## 范围与方案选择

建议采用“设备目录集中、公共逻辑共享”。另一种方案是在 `configs/`、`feeds/`、`overlays/` 等每个目录内分别按设备细分，改动较小，但同一设备仍散落多处。整仓库按设备复制一套构建脚本会产生重复维护，不采用。

本轮实施范围建议是：TR3000 文件迁移、路径引用更新、回归验证，以及 A6S / NX30Pro 的说明入口。两款新硬件的实际上游适配、固件编译和刷机验证为后续独立工作，不默认继承 TR3000 的 Lite / Full 策略。

## Global Constraints

- 保持 `common → distribution → device → local`；TR3000 内部先应用 shared，再应用 lite/full，二者都属于 device 层。
- 保留稳定设备 ID `tr3000`、`x86-64`、`raspberry-pi`；新增目录使用 `a6s`、`nx30pro`，均为小写。
- 不改变 TR3000 的源码/feed SHA、包选择、112 MiB UBI 限制、profile、服务默认状态和固件产物名称。
- 不填写未经核实的新设备厂商、硬件修订、发行版支持、profile、revision、分区或产物规则。
- 不修改 `work/`、`output/`、`cache/`；不读取或迁移 `local/` 私有数据。
- 公共 `configs/common/`、`configs/distributions/` 和 `feeds/*.conf` 保持原位。
- `.github/workflows/` 保留在 GitHub 要求的位置，工作流继续调用脚本，不把构建逻辑搬进 YAML。
- 根目录 `scripts/` 的现有命令行入口和参数保持兼容；不在本次迁移中顺带重写通用构建系统。
- 固件只在 Linux / WSL2 或 GitHub Actions 编译，Windows 只执行编辑与校验。
- 不自动提交、推送、发布或触发远端固件构建；提交点仅为建议。
- 用户明确还有两个未合并 worktree。开始目录迁移前必须完成 Task 0，不能因当前 checkout 未列出它们就视为已处理。

## 建议目标结构

```text
devices/
  README.md                         # 型号索引与适配状态
  tr3000/
    README.md                       # Lite、Full、U-Boot 导航及硬件限制
    config.config                   # 原 configs/devices/tr3000.config
    build/                          # 型号专属构建、配置与镜像检查实现
    shared/
      files/                        # 当前 files/ 内容，保持首轮复制行为
      runtime/                      # 设备运行脚本
    lite/
      config.seed
      feeds.lock
      README.md
      requirements.md               # 原 Lite 提示词文档
    full/
      config.seed
      feeds.lock
      packages/luci-app-tr3000-full/
      README.md
      requirements.md
    uboot/
      README.md                     # 原 UBOOT-SAFETY.md
      flashing-record.md
    docs/                           # 设备运行及测试文档
  a6s/
    README.md                       # 待核实清单，不表示支持编译
  nx30pro/
    README.md                       # 待核实清单，不表示支持编译
configs/                            # 公共、发行版及暂未迁移设备
feeds/                              # 公共与发行版 feeds
manifests/devices/                   # 集中保留机器可读设备索引
scripts/                            # 公共工具及旧命令兼容入口
tests/
docs/                               # 全局架构、指南、历史设计与执行计划
.github/workflows/
```

shared 表示 TR3000 内部共享，不是全设备 common。首轮不拆分当前 `files/` 的 Lite / Full 内容：现有两条配置流程都整体复制它，拆分会改变固件行为，应另行审查。`devices/a6s` 与 `devices/nx30pro` 初期只提交有内容的 README，不建立空目录树或虚假可构建目标。

## 型号隔离契约（用户明确要求）

目录分类必须同时落实为构建输入隔离，不能只是移动文件。

- 设备目录归该型号独占。A6S 的 manifest、构建适配和 overlay 不得读取 `devices/tr3000/`，TR3000 与 NX30Pro 同理。
- 每个型号只叠加公共层、发行版层和自身设备层；不能扫描整个 `devices/` 后统一复制 seed、软件包或 rootfs 文件。
- Lite / Full 是型号内部的变体。修改 `devices/tr3000/shared/` 可以影响 TR3000 的两个变体，但不能影响 A6S / NX30Pro；修改 lite 专属输入不能改变 Full 的有效输入。
- 型号专属构建规则同样放在自身目录下。根目录 `scripts/build-lite.sh`、`build-full.sh`、`configure-lite.sh`、`configure-full.sh`、`build-uboot.sh`、`verify-image.sh` 在迁移后只保留兼容转发入口；真实 TR3000 实现位于 `devices/tr3000/build/`，避免后续修改型号逻辑时改动公共工具。
- 将来新型号实现必须使用 `devices/<id>/build/`，公共 `scripts/` 只负责通用参数解析、调度和真正共享的工具；不把所有型号的分区/profile 判断堆在同一个脚本中。
- 构建工作目录、产物目录、ccache 目录与 Actions concurrency group 按型号和变体区分。源码 checkout 不在不同型号之间复用；建议路径为 `work/<id>/<variant>/`、`output/<id>/<variant>/`、`cache/ccache/<id>/<variant>/`。
- 缓存键包含型号、变体、源码 SHA 和该型号相关 seed/feed lock 的哈希。其他型号专用文件变化不能改变当前型号的缓存键；依赖真实变更时允许公共输入使多个型号缓存失效。
- 下载缓存只共享经上游校验的数据；不得通过共享缓存传递 `.config`、rootfs overlay、编译产物或设备私有参数。
- 公共/发行版层修改仍可能影响多个型号，必须单独列出影响范围并执行相关目标回归。隔离保证针对设备专属修改，不能承诺公共工具变化无影响。
- 验收以有效输入清单和哈希不变为依据；不把未验证的二进制逐字节可复现性当作已达成保证。

新增 `tests/structure/test_device_isolation.py`，覆盖跨型号路径引用拒绝、变体选择、输入哈希及生成目录隔离。新硬件尚无真实构建配置时使用临时测试夹具验证规则，不为测试捏造真实硬件 profile。

## 文件迁移清单

| 现有路径 | 目标路径 |
| --- | --- |
| `configs/devices/tr3000.config` | `devices/tr3000/config.config` |
| `configs/lite.seed`、`configs/full.seed` | `devices/tr3000/{lite,full}/config.seed` |
| `feeds/devices/tr3000-lite.lock`、`tr3000-full.lock` | `devices/tr3000/{lite,full}/feeds.lock` |
| `files/` 全部内容 | `devices/tr3000/shared/files/` |
| `packages/luci-app-tr3000-full/` | `devices/tr3000/full/packages/luci-app-tr3000-full/` |
| `configs/devices/TR3000/TR3000-Lite-工业远程维护版-提示词.md` | `devices/tr3000/lite/requirements.md` |
| `configs/devices/TR3000/TR3000-Full-综合增强版-提示词.md` | `devices/tr3000/full/requirements.md` |
| `docs/LITE-README.md`、`docs/FULL-README.md` | `devices/tr3000/{lite,full}/README.md` |
| `docs/UBOOT-SAFETY.md` | `devices/tr3000/uboot/README.md` |
| `docs/cudy-tr3000-uboot-flashing-record.md` | `devices/tr3000/uboot/flashing-record.md` |

运行脚本迁入 `devices/tr3000/shared/runtime/`，保留文件名：`plant-profile.sh`、`plant-access.sh`、`preflight.sh`、`lite-common.sh`、`lite-uplink-watch.sh`、`service-toggle.sh`、`singbox-rollback.sh`。原 `scripts/` 同名入口保留为薄转发脚本，安装进固件的仍为真实脚本，保持 `/root/scripts/`、`/usr/sbin/` 等设备端路径不变。

设备运行文档迁入 `devices/tr3000/docs/`，保留文件名：`WIREGUARD-VPS-ROUTING.md`、`WIREGUARD-SNAT.md`、`TAILSCALE.md`、`SINGBOX-SPLIT-ROUTING.md`、`CLOUDFLARED-ACCESS.md`、`TEST-PLAN.md`。`docs/package-build-and-install-guide.md` 保持原位，更新其中 TR3000 示例。旧操作文档位置保留简短迁移导航，防止已发布链接失效；历史 specs/plans 保留历史路径文字，不批量改写历史记录。

## Review Focus

1. Linux 大小写敏感：消除对旧 `configs/devices/TR3000/` 的执行依赖。
2. 固件内路径：宿主文件迁移后，运行脚本仍能找到 `lite-common.sh` 和服务控制器。
3. 跨设备隔离：A6S / NX30Pro 不引用 TR3000 的网络配置、分区或 feed 锁。
4. Actions 缓存：hashFiles 随 seed / lock 路径更新，避免空匹配产生不正确缓存键。
5. 未适配目标：说明入口不使其出现在可构建列表；未来注册后未知字段仍以状态码 3 阻止。

## Task 0：盘点并处理两个未合并 worktree（迁移前置条件）

**Files:** 本计划的盘点记录；此阶段不迁移文件，不自动修改其他 worktree。

**Interfaces:** 向 Task 1 提供已核实的目标集成分支、基线 commit，以及两个 worktree 的处理结果。默认顺序为先完成并合并现有工作，再基于合并后的代码执行重构。

当前已知：用户报告两个 worktree 尚未合并；此前本地 `git worktree list` 只列出当前 checkout，当前聊天无额外挂载记录。两个 worktree 的位置、分支和修改范围仍未核实，不能将远端 feature 分支直接等同于它们。

| 待核实工作树 | 路径/所在主机 | 分支与 HEAD | 未提交修改 | 目标分支/PR | 涉及迁移文件 | 处理结果 |
| --- | --- | --- | --- | --- | --- | --- |
| worktree 1 | 待核实 | 待核实 | 待核实 | 待核实 | 待核实 | 未处理 |
| worktree 2 | 待核实 | 待核实 | 待核实 | 待核实 | 待核实 | 未处理 |

- [ ] 使用 `git worktree list --porcelain`、应用挂载记录及可访问的相关分支/PR 信息定位两个 worktree；如位于其他 clone 或主机，记录归属。信息不足时向用户索取路径或分支名，不自行猜测。
- [ ] 对每个可访问 worktree 只读执行 `git status --short --branch`、`git log -1`，核实目标分支后使用 `git log <目标分支>..HEAD --oneline` 和 `git diff --name-status <目标分支>...HEAD` 查看未合并提交及文件范围；另查未暂存、已暂存和未跟踪文件，三点 diff 不代表这些内容已被覆盖。
- [ ] 将改动与本计划迁移清单、构建脚本、workflow 和测试逐项比对，记录重命名冲突、旧路径引用及新增文件需要归属的型号。
- [ ] 先让原有功能在各自分支完成验证和审查；仅在已获得相应合并授权后执行合并，不因本计划存在而自动提交、合并、rebase 或清理其他 worktree。
- [ ] 推荐先将两个工作分支合入核实后的目标集成分支，再从该分支最新 commit 开始重构。若其中一个必须保留未合并，先记录保留原因、后续迁移/合并策略和负责人，并取得用户对例外顺序的明确确认；未确认前不开始目录迁移。
- [ ] 通过目标分支提交历史或 PR 合并状态验证处理结果；仅 worktree 干净不能证明已合并。更新上表和基线 commit，纳入新增文件后重新检查迁移清单。
- [ ] 处理完成后运行 `bash scripts/validate.sh` 和 `python -m unittest discover -s tests -v`；验证通过后才能进入 Task 1。保留已有 worktree，不自动删除或归档。

## Task 1：建立迁移基线和设备目录规范

**Files:** `devices/README.md`、`devices/tr3000/README.md`、`AGENTS.md`、`docs/configuration-layers.md`、`tests/structure/test_repository_contract.py`。

**Interfaces:** 原有命令不变；新增设备目录约定，不改变 manifest schema。

- [ ] 执行 `git status --short`、`git worktree list`；确认实施分支和用户改动，复用合适 checkout，需要新分支时使用 `codex/` 前缀。
- [ ] 确认 Task 0 已完成，并以其核实的合并后 commit 为基线；若存在经用户确认的未合并例外，复核对应兼容与后续合并策略。
- [ ] 运行基线 `bash scripts/validate.sh`、`python -m unittest discover -s tests -v`；记录当前测试数量和结果，不把本计划编写时的结果当作实施结果。
- [ ] 先添加 `test_device_index_documents_existing_variants`，断言设备索引包含 tr3000、a6s、nx30pro，TR3000 导航包含 lite/full/uboot；运行该测试应因文件尚不存在而失败。
- [ ] 添加两份索引，更新规范中设备专属文件路径示例，明确 shared 和 variants 属于 device 层；保持其他设备原路径有效。
- [ ] 重跑结构测试通过后检查 diff，形成第一个可审查提交点。

## Task 2：迁移 TR3000 构建输入并同步全部消费者

**Files:** 迁移清单中的配置、feeds、files、packages；修改 `manifests/devices/tr3000.json`、`scripts/configure-lite.sh`、`scripts/configure-full.sh`、`scripts/build-lite.sh`、`scripts/build-full.sh`、`.github/workflows/build-lite.yml`、`.github/workflows/build-full.yml`；同步 `tests/scripts/test_scripts.py`、`tests/structure/test_repository_contract.py`、`tests/workflows/test_workflows.py`。

**Interfaces:** CLI、设备 ID、上游输入和固件安装路径不变；manifest 中 tr3000.config_layers 改为 `["devices/tr3000/config.config"]`。

- [ ] 在测试中先声明新 seed/lock/overlay/package 路径，添加 `test_tr3000_inputs_live_under_device_directory`；断言新路径存在，旧输入路径不再作为构建来源。先运行并确认预期失败。
- [ ] 保存本任务将迁移文件的相对路径和 SHA256 对照，使用 `git mv` 按表迁移，确认输入文件内容一致。
- [ ] 更新两个 configure 脚本的 seed、overlay 和 Full LuCI 包来源；明确每次均使用 TR3000 设备根目录。
- [ ] 更新两个 build 脚本 feed lock 位置，以及两个 workflow 的 hashFiles 参数；保留上游 SHA、缓存前缀、CLI 与产物名。
- [ ] 更新结构与工作流路径断言；保留现有配置合并、必需/排除包、可选包、ccache 和布局拒绝测试。
- [ ] 执行 `python -m unittest tests.scripts.test_scripts tests.structure.test_repository_contract tests.workflows.test_workflows -v`；全部通过后形成提交点。

## Task 3：归拢设备运行脚本，保持旧入口兼容

**Files:** 上述七个 runtime 脚本、原 `scripts/` 同名入口、两个 configure 脚本、`tests/scripts/test_scripts.py`。

**Interfaces:** 旧入口通过 `exec sh "$REPO_ROOT/devices/tr3000/shared/runtime/<原文件名>" "$@"` 转发；configure 从 runtime 安装真实文件，禁止安装转发入口到固件。

- [ ] 添加旧入口从仓库外运行 `--help`、非法参数拒绝且无副作用的测试；补充 `test_installed_runtime_scripts_are_real_device_scripts`，断言安装内容不是宿主转发器，并保留设备端库查找关系。
- [ ] 先运行新增测试确认失败，然后迁移真实脚本，创建转发入口并更新 configure 的安装来源。
- [ ] 不改变设备端文件名；检查 `singbox-rollback.sh` 的控制器回退路径和 `lite-uplink-watch.sh` 同目录库引用。
- [ ] 运行脚本测试和 POSIX 语法检查，确认从仓库外执行及带空格目录场景均通过，再形成提交点。

## Task 3A：隔离型号构建逻辑与构建状态

**Files:** `devices/tr3000/build/{build-lite,build-full,configure-lite,configure-full,build-uboot,verify-image}.sh`；根目录对应兼容入口；三个 TR3000 workflow；`tests/scripts/test_scripts.py`、`tests/workflows/test_workflows.py`、`tests/structure/test_device_isolation.py`。

**Interfaces:** 对外 CLI 与固件内路径不变；设备构建脚本的 `DEVICE_ROOT` 为其所在 build 目录的上一级，`REPO_ROOT` 为设备目录上两级；运行资源读取 `DEVICE_ROOT/shared/runtime/`。同目录调用 configure/verify，禁止回调宿主兼容入口。任务按 3 → 3A → 4 顺序执行。

- [ ] 先添加失败测试，断言真实构建脚本位于型号目录、旧入口从仓库外仍可执行，真实脚本没有其他型号目录依赖。
- [ ] 迁移六个脚本，修正 REPO_ROOT、seed、feed、package、overlay 及 runtime 来源，保留旧入口薄转发；保持原参数与退出码。
- [ ] 更新 workflow 使其直接调用设备目录真实入口；保持原工作流文件名和已发布产物标识不变。
- [ ] 在隔离测试中构造 tr3000、a6s、nx30pro 三个临时设备输入树，分别收集 common、distribution、当前设备和当前变体的路径/内容哈希；修改任一设备输入，断言其他两者哈希不变；修改 tr3000/lite 输入，断言 tr3000/full 哈希不变。
- [ ] 对实际 manifest 的 layer 路径增加校验：允许共享目录和本设备目录，拒绝其他 `devices/<id>/`；测试拒绝跨设备 overlay/config/feed/patch 路径，同时保留现有路径越界拒绝测试。涉及文件为 `tools/manifest.py` 与 `tests/manifest/test_manifest.py`，函数沿用现有校验入口，不创建第二套解析器。
- [ ] 为未来新型号工作流约定型号/变体独立的状态目录及缓存键；测试现有 Lite/Full 的目录、缓存和 concurrency group 不相同，且 hashFiles 不包含其他型号设备树。
- [ ] 运行 manifest、脚本、workflow 与隔离测试，确认旧入口兼容且没有跨型号读取后形成提交点。

## Task 4：迁移设备文档并加入新型号待适配说明

**Files:** 文档迁移清单、`devices/a6s/README.md`、`devices/nx30pro/README.md`、`README.md`、`docs/architecture.md`、`docs/adding-a-device.md`、`.agents/skills/openwrt-firmware-config/SKILL.md`、`tests/skills/`、`tests/structure/test_repository_contract.py`。

**Interfaces:** 新型号此时只有文档入口，没有 build-ready manifest；全局导航指向设备目录，旧操作文档链接保留迁移导航。

- [ ] 添加文档导航和状态测试，断言两款新设备说明明确未适配、没有 TR3000 profile/112 MiB 布局作为默认配置；先确认预期失败。
- [ ] 迁移操作文档与提示词，修复相对链接，原操作文档保留指向新位置的导航；不重写历史 specs/plans。
- [ ] A6S、NX30Pro README 各记录待核实项：厂商、精确型号/修订、闪存与启动方式、发行版/源码版本、profile、镜像类型、包策略及验收硬件。
- [ ] 更新仓库配置 Skill 与相关测试中的当前路径；检查项目刷机 Skill 的活动引用，只修正受迁移影响的路径，不改变刷机指令或硬件结论。
- [ ] 更新新增设备指南：硬件事实核实后再注册 manifest；不得靠猜测 supported_distributions 让校验通过。
- [ ] 运行结构和 Skill 测试；使用 `rg` 搜索旧路径，逐项确认只剩兼容入口、迁移说明或历史文档引用，再形成提交点。

## Task 5：总体验收及后续固件验证交接

**Files:** 全部本轮差异；必要时只修正迁移遗漏。

- [ ] 运行 `git diff --check`、`bash scripts/validate.sh`、`python -m unittest discover -s tests -v`，要求全部通过。
- [ ] 运行 `bash scripts/list-targets.sh`，原六个通用发行版/设备组合保持原状态，不新增虚假可构建目标。
- [ ] 运行 `python tools/manifest.py resolve --distribution immortalwrt --device tr3000 --require-build-ready`，预期状态码 3；分别验证 x86-64、raspberry-pi 的未知字段门禁不变。
- [ ] 比较迁移前后 seed、feed lock、overlay、LuCI 包和真实 runtime 内容；除明确的路径引用更新外不应改变功能内容。
- [ ] 验证型号隔离测试：修改单个型号专用输入后，其余型号有效输入哈希不变；有实际适配的新型号还须在独立 source/output 目录构建，不能仅凭目录命名验收。
- [ ] 在 Linux 环境完成脚本验证，避免 Windows 不区分大小写掩盖问题；检查没有文件只因 TR3000/tr3000 大小写而重复。
- [ ] 汇总影响路径、未验证项和建议提交，不自动推送或触发构建。用户安排 Actions 后，分别验证 Lite、Full、U-Boot：最终 build.config、固件内脚本路径、包清单、布局、产物名及 SHA256SUMS。
- [ ] 如任一阶段失败，停止后续迁移；对该阶段审查差异并恢复相应路径与引用。已提交阶段可通过独立 revert 撤销；禁止 reset --hard 或清理用户文件。

## 后续独立计划：A6S / NX30Pro 实际适配

先取得精确硬件和用户希望的发行版、用途，再核实指定上游 revision 中的设备定义。随后分别制定设备 manifest、seed、feeds、overlay、patch、构建入口、容量检查与真机验证计划。是否为两款设备提供 Lite / Full，应按容量与需求确定，不能复制 TR3000 目录即宣称支持。

## 本计划交付验收

- 本次只新增这一份 Markdown 计划；复选框未勾选，代表尚未执行。
- 目标结构、迁移路径、兼容策略、任务依赖、检查命令及新硬件边界均已明确。
- 实施前以用户对计划的修改意见为准；目录建议尚不是已实施事实。
