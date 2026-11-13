# OpenWrt 固件配置项目 Skill 设计

## 意图

在本仓库内创建一个轻量项目级 Skill，让 AI 在新增或修改 OpenWrt、ImmortalWrt、TR3000、x86_64、Raspberry Pi 及后续设备配置时，始终遵守现有目录、配置分层和硬件核实规则。Skill 同时保存少量已经在本项目中真实出现过的调试问题，避免重复踩坑，但不承担完整发布和刷写流程。

## 目标

- 正确区分发行版、设备和固件变体。
- 固定使用 `common → distribution → device → local` 配置优先级。
- 说明 manifest、Kconfig、feeds、patches、overlay 和专用构建配置分别放在哪里。
- 把新增设备、修改软件包和调整专用固件的重复步骤写成清晰检查清单。
- 未核实的 `revision`、`target`、`subtarget`、`profile` 和产物规则保持 `UNRESOLVED`。
- 收录本项目已知、可由证据支持的配置及构建启动阶段问题。

## 非目标

- 不覆盖完整发布、自动刷写、远程设备维护或 release 管理。
- 不提供 bootloader 写入、分区擦除、`mtd write` 或 `dd` 命令。
- 不取代 GitHub Actions 的完整故障排查手册；未知故障仍需系统化读取日志。
- 不保存密码、密钥、Wi-Fi 凭据或现场网络参数。
- 不把 TR3000 Lite 的专用配置套用到通用 TR3000、x86_64 或 Raspberry Pi。

## 约束

- Skill 位于 `.agents/skills/openwrt-firmware-config/SKILL.md`，随项目版本控制。
- 采用单一 `SKILL.md`，中文正文，控制在约 300 行以内。
- 工作流只负责调用，稳定逻辑继续保留在 `scripts/` 中。
- 不编辑 `work/`、`output/`、`cache/` 生成内容。
- `local/` 除 README 外不进入 Git。
- GitHub Actions 是主要编译环境；Windows 原生环境只做编辑、校验和 Git 操作。

## 考虑过的方案

### 方案一：配置管理加已知问题（已选择）

集中管理目标识别、配置分层、设备扩展、软件包差异和少量已知调试问题。优点是短小、触发准确，适合当前仓库；新问题如果反复出现并已确认根因，再加入速查表。

### 方案二：完整固件生命周期

额外覆盖 Actions 编译、通用诊断、产物发布和刷写交接。覆盖面更广，但 Skill 体积和维护成本更高，简单配置任务也会加载大量无关内容。用户决定暂不采用。

### 方案三：完整生命周期并拆分参考文件

扩展性最好，但当前设备数量和成熟构建入口不足以支撑这套复杂度，暂不采用。

## 触发范围

当用户要求在本仓库中新增或修改 OpenWrt/ImmortalWrt 设备、固件变体、manifest、Kconfig、软件包、feeds、patches、overlay、Lite seed，或遇到已知的配置合并/ccache 问题时触发。纯粹查看日志、通用 Linux 问题、发布管理和与本仓库无关的 OpenWrt 咨询不触发。

## Skill 内容结构

1. **开始前读取顺序**：`AGENTS.md`、目标 manifest、`docs/configuration-layers.md`、目标专用文档及相关脚本。
2. **任务分类**：发行版、设备、固件变体、配置类型和影响范围。
3. **目录职责**：`manifests/`、`configs/`、`feeds/`、`patches/`、`overlays/`、`files/`、`local/`。
4. **配置层级**：公共、发行版、设备、本地层的放置条件和覆盖规则。
5. **设备差异重点**：
   - TR3000 通用入口仍有 `UNRESOLVED` 字段；
   - TR3000 Lite 是固定上游 commit、固定 feed、112 MiB UBI 的独立路径；
   - TR3000 U-Boot 与系统固件分离，不属于普通软件包配置；
   - x86_64 先确定镜像/文件系统策略；
   - Raspberry Pi 先确定精确型号，不能用“Raspberry Pi”猜 profile。
6. **重复流程**：读取事实、确认目标、选择配置层、最小修改、运行 `make defconfig` 或项目校验、检查最终配置、报告未验证项。
7. **常见任务清单**：新增设备、增加公共包、增加设备包、排除包、增加 feed、增加 overlay、升级源码 revision。
8. **已知调试问题**：用“症状 → 已确认根因 → 修复 → 验证”格式记录。
9. **完成报告**：修改了什么层、影响哪些目标、运行了哪些验证、还有哪些 `UNRESOLVED` 或真机未验证项。

## 已知调试问题

### TR3000 Lite 的 m4 `cannot compute suffix of object files`

- **症状**：`tools/m4` 配置阶段提示无法计算目标文件后缀；并行和 `-j1` 都失败。
- **已确认根因**：上游基础配置中的 `CONFIG_CCACHE_DIR="/workdir/.ccache"` 覆盖 GitHub Runner 实际创建的临时缓存目录。链接测试可以通过，真正的 `-c` 编译需要写缓存临时文件时失败。
- **项目修复**：`build-lite.sh` 将实际 `CCACHE_DIR` 传给 `configure-lite.sh`，配置合并时覆盖上游固定路径。
- **避免误判**：如果 Actions 明确显示 cache miss，就不要把“清理旧缓存”当作修复；先检查最终 `build.config` 中的路径和底层 `config.log`。

### 带连字符的软件包配置被错误保留

- **症状**：如 `luci-app-openclash`、`luci-i18n-base-zh-cn` 的启用/禁用项未按 Lite seed 覆盖。
- **已确认根因**：配置合并正则只接受字母、数字或下划线，没有接受 OpenWrt 包符号中的连字符。
- **项目修复**：解析 `CONFIG_...` key 时允许 `[A-Za-z0-9_-]`，并通过真实配置合并测试验证。

### 并行日志中的临时 `ninja: No such file or directory`

- **症状**：并行 host tools 构建早期可能出现 staging 中的 ninja 尚不存在，但随后 ninja 被正常构建并继续执行。
- **处理原则**：不要只凭这一行判定最终根因。检查它是否导致对应 make target 失败，并用串行重试结果定位第一处稳定复现的错误。

### 通用目标被 `UNRESOLVED` 主动阻止

- **症状**：通用 OpenWrt/ImmortalWrt 构建在下载源码前以状态码 `3` 停止。
- **根因**：设备或源码 manifest 仍有未核实字段，这是设计的安全边界，不是构建系统故障。
- **处理原则**：从对应上游 revision 和精确硬件型号核实字段；不得复制相似设备值或为了让 Actions 变绿而随意填写。

## 重复配置流程

1. 阅读 `AGENTS.md` 和目标设备 manifest。
2. 确认发行版、精确硬件型号/修订和固件变体。
3. 判断改动属于 common、distribution、device 还是 local。
4. 核实是否需要调整 manifest、Kconfig、feed、patch 或 overlay。
5. 只修改最窄的层；公共层改动必须列出全部受影响目标。
6. 对 OpenWrt 配置执行 `make defconfig` 后检查最终 `.config`，不能只检查 seed/fragment。
7. 从仓库根目录运行：

   ```sh
   bash scripts/validate.sh
   python -m unittest discover -s tests -v
   ```

8. 如果目标仍含 `UNRESOLVED`，用 `tools/manifest.py resolve --require-build-ready` 确认它继续安全失败。
9. 报告改动层、影响目标、验证证据和仍需 GitHub Actions/真机完成的项目。

## 测试设计

创建 Skill 前用没有 Skill 的新代理运行基线场景；创建后用相同场景复测：

1. 用户要求“给 Raspberry Pi 增加 ImmortalWrt 配置”，但不提供 Pi 型号，检查代理是否会猜 profile。
2. 用户要求“给 TR3000 Lite 加 OpenClash，同时顺手放进 common”，检查代理是否识别设备专用影响和 Lite 排除策略。
3. 用户看到 m4 错误并要求清缓存，检查代理是否能识别本项目的 ccache 路径问题并要求验证 `build.config/config.log`。

成功标准：读取正确项目文件、选择最窄配置层、不猜硬件值、能复述已知问题的证据链，并运行项目规定的验证。

## 验收标准

- 项目内存在 `.agents/skills/openwrt-firmware-config/SKILL.md`。
- frontmatter 合法，description 从 `Use when...` 开始，能匹配中英文 OpenWrt 配置任务。
- Skill 不超过约 300 行，且无需读取额外 references。
- 三个测试场景均比无 Skill 基线更符合项目规则。
- `bash scripts/validate.sh` 与完整 Python 测试通过。
- Skill 不包含秘密、未核实值或危险刷写命令。

## 实施者可自行决定

- 根据基线测试实际暴露的遗漏调整章节顺序和措辞。
- 已知问题只保留已确认根因；未确认问题写成诊断入口，不写成结论。
- 若项目校验尚不能发现非法 Skill frontmatter，可增加小型自动检查；机械约束优先自动化。
