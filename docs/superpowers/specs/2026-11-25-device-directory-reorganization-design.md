# 按设备集中管理的目录重构设计

日期：2026-11-25。状态：用户已批准设计并完成迁移，Linux 完整回归通过；Actions/真机验证待手动安排。当前执行计划为 `docs/superpowers/plans/2026-11-25-device-directory-reorganization.md`。

## 意图与基线

将同一硬件型号的构建输入、专属实现和操作文档集中起来，方便维护单个型号并避免影响其他型号。以 `docs/superpowers/plans/2026-11-22-device-directory-reorganization.md` 为基础，按当前代码补齐迁移范围。

用户已确认原先两个 worktree 的工作均已合并，并选择“按型号集中管理、公共逻辑共享”。当前检查基线为 master `9ecfdc3237c22d7be1dcd23bc4e33a48cfa83e69`，工作区干净，本地只登记当前工作树，已知分支无未合入 master 的分支。实施前重新核实基线及用户修改。

## 目标、非目标与约束

- TR3000 的 Lite、Full、U-Boot 专属文件归入 `devices/tr3000/`；旧脚本命令、参数、退出码和设备内安装路径兼容。
- A6S、NX30Pro 本轮只建立待适配 README；保留已有历史计划，链接到它们，不新增可构建 manifest。
- 公共工具、发行版配置、集中 manifest、测试和 Actions 保持共享位置。x86-64、raspberry-pi 本轮不迁移。
- 保持 `common → distribution → device → local`，设备内部依次应用 shared 和选定变体。
- 保持当前源码/feed SHA、包策略、服务默认值、profile、分区限制、产物名及最新真机修复。
- 不引入新的调度框架，不重写脚本业务逻辑，不做新设备适配或刷机。
- 不修改生成目录及 local 私有数据；未知硬件和源码字段继续 UNRESOLVED。
- 不自动提交、推送、发布或触发远端构建。此次设计及后续计划先留在工作区供审阅。

## 方案选择

1. 按型号集中：设备文件进入 `devices/<id>/`，公共部分共享，旧脚本保留薄转发。维护单个型号所需文件集中，但迁移时需要同步全部消费者。用户已选择此方案。
2. 按文件类别继续细分：在 configs、scripts、packages 等目录分别按设备分组。迁移量较小，但单个型号仍散落多处，不采用。

## 目录与文件归属

```text
devices/
  README.md
  tr3000/
    README.md
    config.config
    build/                 # Lite/Full 配置、构建，U-Boot 构建，镜像检查
    shared/
      files/               # 当前根 files/，保留整体复制语义
      runtime/             # 两个变体共用的运行脚本
    lite/
      config.seed
      feeds.lock
      files/               # 原 overlays/devices/tr3000-lite/files
      packages/luci-app-tr3000-lite/
      runtime/             # Lite 专属运行脚本和库
      README.md
      requirements.md
    full/
      config.seed
      feeds.lock
      files/               # 原 overlays/devices/tr3000-full/files
      packages/luci-app-tr3000-full/
      runtime/             # Full 专属运行脚本和库
      README.md
      requirements.md
    uboot/
      README.md
      flashing-record.md
    docs/
  a6s/README.md
  nx30pro/README.md
```

以下为本设计提出的实现选择：将新增的变体专属 runtime 分开存放，以免 Lite 专属改动成为 Full 输入。原计划列出的七个通用运行脚本先按现有安装关系归入 shared/runtime；所有 `scripts/tr3000-lite-*`、`scripts/tr3000-full-*` 归入对应变体 runtime。实施者根据两个 configure 的实际读取清单核实归属，不按文件名推断共享关系。

六个真实构建脚本迁入 build：build-lite、build-full、configure-lite、configure-full、build-uboot、verify-image。设备专属宿主辅助工具 `prepare-lite-ddns.py` 同样迁入 build，更新调用关系。公共 scripts/lib、manifest 工具及通用构建入口保持原位。

配置片段、seed、feed lock、提示词及旧计划列出的操作文档沿用其迁移映射。额外纳入 Lite LuCI 包、两个变体 overlay、所有新增运行脚本及其测试引用。tests 保持现有分类位置，目标镜像命令清单保持测试夹具位置。

## 路径解析与兼容

构建脚本从自身位置计算 DEVICE_ROOT、REPO_ROOT，只读取 shared 和当前变体输入；同目录调用真实 configure/verify，不回调根兼容入口。现有公共工具仍通过 REPO_ROOT 定位。

根 scripts 下被迁移的可执行入口保留薄转发，完整传递参数和退出状态，支持从仓库外及含空格路径执行。宿主兼容入口不得安装进固件；configure 直接安装真实 runtime，保留设备端库定位、调用名、权限及所有 /usr、/etc、/root 路径。

库文件的宿主兼容路径如存在 source 调用，则提供可 source 的兼容文件而非 exec 包装；本轮通过 Git 符号链接保留任意工作目录下 POSIX sh/Bash 的 source 行为，Windows 无链接权限时使用 Linux/WSL 检出执行。Python 辅助命令使用 Python 兼容入口。保留旧命令的原始 Git 可执行位。

原 files 的复制顺序与变体 overlay 覆盖顺序保持一致，不在本轮拆分其功能内容。旧操作文档保留迁移导航；全局文档、配置技能、刷机技能的活动路径同步更新。历史 specs/plans 不批量改写；后续可明确更新本轮执行计划状态及步骤。

## 隔离与构建状态

沿用 tools/manifest.py 的验证入口，拒绝设备层读取其他 devices/<id> 的 config/feed/patch/overlay，继续拒绝路径越界及符号链接逃逸。公共和发行版层保持现有语义，不为本轮迁移创建第二套解析器。

Actions 调用型号目录真实构建入口；hashFiles 更新为当前型号、当前变体的实际输入，避免空匹配和跨设备依赖。保持已有 workflow 文件名、产物标识、缓存前缀及互异的 concurrency group。型号和变体的 source/output/ccache 隔离需核实当前实现；必要时调整 workflow 显式路径，不静默改变用户传入的 CLI 路径。

隔离验收针对有效输入及内容哈希。shared 修改可影响 Lite/Full，变体专属修改只影响本变体；公共工具变化可能影响多个目标。不得以目录重命名或临时夹具测试宣称真实固件二进制不变。

## 迁移顺序与错误处理

先记录当前基线和测试结果，再建立索引与目录约定，然后迁移构建输入、runtime、构建实现，最后迁移文档和更新技能引用。每阶段同步全部消费者及测试，保留可审阅差异。

对被迁移输入保存旧路径至新路径的 SHA256 对照；除路径定位所需修改，文件内容应保持一致。新增真机修复的 loopback、工具依赖、SSH 配置、空 UCI delta 判断及自带软件仓库不能在迁移中退回旧版本。

阶段失败时先定位修复该阶段，不继续扩大迁移；若必须回退，仅撤销本轮对应变更，保护用户修改，不使用 reset --hard。Git rename 或等价可追踪移动方式由实施者选择。

## 验证与交付

- 基线与结束均运行 `bash scripts/validate.sh`、`python -m unittest discover -s tests -v`，结束另运行 `git diff --check`。
- 针对配置安装、旧入口、真实 runtime、脚本 POSIX 语法、manifest 越界和跨设备拒绝、workflow 缓存路径运行相关测试。
- 使用实际安装结果检查两个变体只装真实脚本，测试固件内库查找及新增工具清单审计继续通过。
- 三型号临时输入夹具用于验证隔离规则，变体输入哈希检查反映真实 configure 的选择关系，不能用与实现无关的哈希自测代替。
- list-targets 保持原六个组合状态；TR3000、x86-64、raspberry-pi 的未完成目标继续被 require-build-ready 以状态码 3 阻止。
- 搜索旧路径逐项分类；仅允许兼容入口、迁移导航和历史记录残留。Linux/WSL 可用时执行路径、脚本和大小写检查；如不可用明确记录限制。
- 本轮本地验证不代替 Actions 的 Lite、Full、U-Boot 编译及真机验证。交付列明修改范围、验证结果和未验证项，不自动触发构建。

## 留给实施者的决定

测试辅助函数、最小阶段划分、兼容库的具体写法、SHA256 记录格式及执行所用隔离分支由实施者决定。不得改变上述功能边界和兼容契约；发现无法兼容或新增业务改动时，先说明影响并重新确认设计。
