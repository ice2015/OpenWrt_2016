---
name: openwrt-firmware-config
description: Use when changing this repository's OpenWrt or ImmortalWrt devices, firmware variants, manifests, Kconfig packages, feeds, patches, overlays, Lite seed, or when diagnosing its known configuration merge, ccache, m4, ninja, and UNRESOLVED failures.
---

# OpenWrt 固件配置

## 核心原则

把仓库中的已核实事实作为唯一依据。配置优先级固定为：

```text
common → distribution → device → local
```

只修改能表达需求的最窄层。不要猜 `revision`、`target`、`subtarget`、`profile`、分区布局、产物规则或软件源 revision；未知值保持 `UNRESOLVED`。GitHub Actions 是主要编译环境，Windows 原生环境只负责编辑、校验和 Git 操作。

不要编辑 `work/`、`output/`、`cache/` 等生成目录。不要提交密码、密钥、Wi-Fi 凭据、现场网络参数或 `local/` 私有内容。不要提供未经验证的刷写命令和偏移量。

## 开始前读取顺序

1. 读取根目录 `AGENTS.md`。
2. 读取目标 `manifests/devices/<device-id>.json` 与 `manifests/sources.json`。
3. 读取 `docs/configuration-layers.md`。
4. 读取目标专用文档、配置片段与实际调用它们的脚本/工作流。
5. 用 `rg` 查找同一符号、软件包、profile 和文件引用，确认真实影响范围。

不要只看用户提供的文件名就开始写配置；manifest、脚本和最终 `.config` 共同定义构建行为。

## 任务分类与配置层选择

先明确五个维度：发行版、精确硬件型号/修订、固件变体、配置类型、影响目标。

| 层 | 放置条件 | 典型位置 |
|---|---|---|
| common | 所有设备和 OpenWrt/ImmortalWrt 都需要 | `configs/common/`、`feeds/common.conf`、`patches/common/`、`overlays/common/files/` |
| distribution | 只属于 OpenWrt 或 ImmortalWrt | 对应发行版 config/feed/patch 目录 |
| device | 只属于一个硬件或固件变体 | `configs/devices/`、`feeds/devices/`、`patches/devices/`、`overlays/devices/` |
| local | 个人实验、网络和秘密 | 被忽略的 `local/`；不能成为 CI 隐式依赖 |

公共层改动必须列出全部受影响目标。需求只提到一台设备时，默认从 device 层开始论证；“以后可能复用”不足以把它上移到 common。

按类型选择文件：

- 目标、源码版本、层引用、产物匹配：`manifests/`。
- 原生 Kconfig：`configs/`，保留 `CONFIG_...` 语法。
- 附加软件源：`feeds/`，固定可复现 revision。
- 源码差异：`patches/`，说明适用 revision。
- rootfs 文件：`overlays/` 或项目已有 `files/` 路径。
- 稳定构建逻辑：`scripts/`；工作流只传入数据和调用脚本。

## 设备与固件变体重点

- **TR3000 通用入口**：manifest 的目标字段仍可能是 `UNRESOLVED`。先核实制造商、硬件修订和上游 revision，不能复制 Lite 值。
- **TR3000 Lite**：独立的固定源码/feeds、`128muboot.config`、U-Boot Mod profile 与 112 MiB UBI 路径。以 `configs/lite.seed`、`scripts/configure-lite.sh`、`scripts/build-lite.sh` 和 Lite 工作流为准。
- **TR3000 U-Boot**：与系统固件分离；不要把 bootloader 构建当成普通软件包配置，也不要把系统固件产物当成通用刷机镜像。
- **x86_64**：先确定镜像类型、启动方式、分区和文件系统策略，再解析 target/profile 与产物规则。
- **Raspberry Pi**：先确定精确型号及修订。不能用笼统的 “Raspberry Pi” 猜 `subtarget` 或 `profile`。
- **OpenWrt 与 ImmortalWrt**：分别核实源码 revision、默认 feeds 和目标定义；相同设备名不保证配置可直接复用。

## 重复配置流程

1. 读取事实并写出当前已知/未知项。
2. 确认发行版、精确型号、固件变体及影响目标；缺少硬件事实时停在 `UNRESOLVED`。
3. 按 `common → distribution → device → local` 选择最窄配置层。
4. 核实 manifest、Kconfig、feed、patch、overlay 与脚本之间的引用关系。
5. 先添加能暴露缺口的测试或校验，再作最小修改。
6. 合并配置并运行 `make defconfig`；检查最终 `.config`，不能只检查 seed/fragment。
7. 检查唯一目标 profile、必需包、排除包、feed revision、分区和产物匹配。
8. 从仓库根目录运行：

   ```sh
   bash scripts/validate.sh
   python -m unittest discover -s tests -v
   ```

9. 对含 `UNRESOLVED` 的普通目标运行 `python tools/manifest.py resolve --require-build-ready ...`，确认状态码 `3` 的安全阻止仍有效。
10. 报告本地证据，并明确哪些项目仍需 GitHub Actions 或真机验证。

## 常见配置任务

### 新增设备或发行版组合

- 先创建/更新 manifest，不从相似设备复制未核实目标值。
- 添加 device 配置片段及所需 feed/patch/overlay 引用。
- 未知字段保留 `UNRESOLVED`，让通用构建在下载源码前停止。

### 增加或排除软件包

- 查找包符号在 seed、上游基线和验证脚本中的所有出现位置。
- 设备专用包放 device 层；只有所有当前目标都需要且容量/依赖已验证时才考虑 common。
- 用 `make defconfig` 后的最终 `.config` 验证 `=y` 或 `is not set`，并检查镜像容量。

### 增加 feed、patch 或 overlay

- feed 固定完整 revision，并记录最终来源；不能使用漂移分支作为可复现输入。
- patch 说明上游适用范围，源码升级后重新验证。
- overlay 不含秘密；公共文件与设备文件分开放置。

### 升级源码 revision

- 将其视为跨目标变更：重新核实 profile、补丁、feeds、配置符号和 artifact patterns。
- 不因旧配置“看起来相似”就跳过 `make defconfig` 与 Actions 构建。

## 已知调试问题

### TR3000 Lite 的 m4 `cannot compute suffix of object files`

- **症状**：`tools/m4` configure 无法计算目标文件后缀，并行和串行重试都失败。
- **已确认根因**：上游基础配置中的 `CONFIG_CCACHE_DIR="/workdir/.ccache"` 覆盖 GitHub Runner 实际的临时 ccache 目录。链接探测可通过，而真正的 `-c` 编译需要写缓存临时文件时失败。
- **修复**：`scripts/build-lite.sh` 把实际 `CCACHE_DIR` 传给 `scripts/configure-lite.sh`，合并配置时覆盖固定路径。
- **验证**：先检查 artifact 中最终 `build.config` 的 `CONFIG_CCACHE_DIR`，再检查 `build_dir/host/m4*/config.log` 的底层编译错误。若 Actions 显示 cache miss，删除旧缓存不能修复路径不一致；不要把清缓存作为默认答案。

### 带连字符的软件包配置被错误保留

- **症状**：`luci-app-openclash`、`luci-i18n-base-zh-cn` 等启用/禁用项没有按 Lite seed 覆盖。
- **已确认根因**：旧合并正则只接受字母、数字和下划线，遗漏 OpenWrt 包符号中的连字符。
- **修复**：解析 `CONFIG_...` key 时允许 `[A-Za-z0-9_-]`。
- **验证**：运行真实 Lite 配置合并测试，并检查 `make defconfig` 后最终 `.config`，不能只匹配 seed 文本。

### 并行日志中的临时 `ninja: No such file or directory`

- **症状**：host tools 并行构建早期提示 staging 中的 ninja 不存在，随后 ninja 又可能正常构建。
- **已确认根因**：仅凭这一行不能确认最终根因；它可能是并行阶段的临时依赖状态。
- **修复**：先确认该行是否导致对应 make target 最终失败，不对非终止性日志作无依据修改。
- **验证**：查看第一处稳定失败和 `-j1 V=s` 串行重试；只有串行仍复现并指向同一依赖时才继续诊断。

### 通用目标被 `UNRESOLVED` 主动阻止

- **症状**：通用 OpenWrt/ImmortalWrt 构建在下载源码前以状态码 `3` 停止。
- **已确认根因**：设备或源码 manifest 仍含未核实字段；这是设计的安全边界，不是构建系统故障。
- **修复**：从精确硬件型号和指定上游 revision 核实字段；不得为让 Actions 变绿而随意填写。
- **验证**：解析未完成目标应继续返回状态码 `3`；完成后再用仓库校验和实际上游定义确认。

## 完整示例：TR3000 Lite 软件包变更

用户要求：“给 TR3000 Lite 加 OpenClash，并顺手放进 common。”

1. 读取 `configs/lite.seed`，确认 `luci-app-openclash` 当前被显式排除；读取 `scripts/configure-lite.sh`，确认它还在排除包验证中。
2. 拒绝直接放进 common：请求只针对 Lite，且 112 MiB UBI 的容量、feed 与运行依赖尚未验证。不要创建仓库不存在的新配置层来绕开规则。
3. 先核实 OpenClash feed 的兼容源码和完整 revision、依赖核心的获取方式、最终镜像大小及可写空间。缺失事实保持未实现，不猜 revision。
4. 若用户确认改变 Lite 定位，则只在 Lite 设备路径中同步更新 seed、排除/必需包验证、固定 feed、文档和测试。
5. 运行配置合并测试与仓库校验，再在 GitHub Actions 构建；检查最终 `build.config`、包清单、镜像大小和产物类型。

## 完成报告格式

按以下顺序交付：

- **目标**：发行版、精确设备、固件变体。
- **配置层**：修改了 common/distribution/device/local 中哪一层，为什么是最窄层。
- **文件与影响**：列出文件及所有受影响目标。
- **验证证据**：列出命令、结果、最终配置/产物检查。
- **未验证项**：仍为 `UNRESOLVED`、需要 Actions、容量检查或真机验证的内容。

## 快速参考

| 看到什么 | 先做什么 |
|---|---|
| 型号不明确 | 保留 `UNRESOLVED`，询问精确型号/修订 |
| “顺手放 common” | 列出全部目标，证明它们都需要且可承受 |
| seed 已改但结果不对 | 查看合并脚本和 `make defconfig` 后的最终 `.config` |
| m4 suffix 错误 | 对比 `CONFIG_CCACHE_DIR`、`build.config`、`config.log` |
| 单行 ninja 不存在 | 查对应 target 和串行稳定失败，不先下结论 |
| 通用构建状态码 3 | 核实 manifest；不要绕过 `UNRESOLVED` 门禁 |

## 常见错误

- 把 TR3000 Lite 的固定 profile、分区或包策略复制给通用 TR3000。
- 因“以后可能用”把设备专用包放进 common。
- 只修改 seed，不同步排除列表、feed、测试和最终配置检查。
- 看到 cache/m4 字样就删缓存，忽略配置路径与 `config.log`。
- 在 Windows 原生环境尝试完整固件编译并把环境失败误判为源码失败。
- 为通过 CI 猜 revision、profile 或 artifact pattern。
- 把未经真机验证的系统固件描述为通用刷写镜像。
