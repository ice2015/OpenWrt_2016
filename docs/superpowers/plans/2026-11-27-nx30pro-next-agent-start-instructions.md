# NX30PRO 下一 Agent 启动与授权说明

> 更新日期：2026-11-27  
> 当前阶段：设计与实施计划已完成，源码实施尚待下一 Agent 执行  
> 使用方式：先发送“阶段一”提示；静态实现验收后，再由用户决定是否发送“阶段二”授权

## 目的

本文件用于启动下一个 Agent 完成 NX30PRO 固件与 U-Boot 重做工作，并把高消耗的源码实施、测试和候选构建分成两个独立授权阶段。

分阶段的原因：

- 防止 Agent 在尚未完成 source lock、配置门禁和静态测试时提前触发 GitHub Actions。
- 防止“设计完成”“源码实现完成”“候选构建通过”“真机验证通过”被混为同一状态。
- 先完成可以在工作区核验的实现，再决定是否消耗 Actions 时间进行远程构建。

## 阶段一：完成源码实施与静态验证

### 授权范围

阶段一允许：

- 读取需求、设计、实施计划和旧实现证据。
- 修改 NX30PRO 的源码锁、配置、脚本、测试、workflow 静态定义和相关文档。
- 运行 NX30PRO 聚焦测试及仓库静态校验。
- 在最后运行一次仓库要求的全量单元测试，并区分本任务失败与既存无关失败。
- 更新交接文件，保存实际完成状态和验证证据。

阶段一禁止：

- 触发任何 GitHub Actions。
- 执行固件或 U-Boot 编译。
- push、发布 Release、合并或刷写设备。
- 为了让测试通过而修改 TR3000 或其他无关设备。
- 猜测 commit、profile、ATF 版本、产物名称或分区事实。

### 发给下一 Agent 的提示词

复制并发送以下内容：

```text
请读取并严格执行：

1. AGENTS.md
2. .agents/skills/agent-handoff/SKILL.md
3. docs/superpowers/plans/2026-11-27-nx30pro-next-agent-handoff.md
4. docs/superpowers/plans/2026-11-27-nx30pro-next-agent-start-instructions.md

按照交接文件中的顺序，完成 NX30PRO U-Boot 和固件的源码实现、配置、测试及 workflow 静态改造。

要求：
- 原来的实现只作参考，以 devices/nx30pro/docs/Command_fix.md 和批准设计为准。
- 先执行 U-Boot 实施计划，再执行固件实施计划。
- 使用测试驱动方式逐项完成，不要只给方案。
- 只修改 NX30PRO 和必要的项目通用入口，不修复或改动 TR3000。
- 先运行 NX30PRO 聚焦测试；全仓测试只在最后运行一次。若出现既存 TR3000 失败，只记录，不修改 TR3000。
- 保护当前工作区已有改动，不删除、覆盖或归属来源不明的文件。
- 未核实的 commit、profile、ATF 版本和产物名称保持 UNRESOLVED，禁止猜测。
- 本阶段允许修改源码、配置、测试和 workflow 文件。
- 本阶段禁止触发 GitHub Actions、禁止固件或 U-Boot 编译、禁止 push、禁止刷机。
- 完成静态实现后，更新交接文件，报告已完成项、测试证据以及仍需 Actions 验证的项目。
- 不得把设计完成写成源码已实现，也不得把静态测试通过写成固件构建成功。
```

## 阶段一验收条件

进入阶段二前，至少应确认：

- U-Boot 与固件实施计划中获准执行的静态任务已经落地。
- U-Boot source lock、固件 source/feed lock 使用完整 commit，不使用漂移分支。
- NX30PRO 分区、布局、必需包、排除包和产物静态门禁已经实现。
- 两个 workflow 仍然只有安全的手动入口，没有被实际执行。
- NX30PRO 聚焦测试和 `scripts/validate.sh` 有明确的实际结果。
- 全仓测试若存在 TR3000 等无关失败，已经单独记录，没有为此扩大修改范围。
- 交接文件已经从“已设计未实施”更新为真实的当前状态。

若上述条件没有满足，不应授权阶段二。

## 阶段二：授权 GitHub Actions 候选构建

阶段二不是阶段一的默认延续。只有用户在查看阶段一结果后明确发送授权提示，下一 Agent 才可以触发手动 Actions。

### 授权范围

阶段二允许：

- 审查阶段一 diff、锁定文件、测试证据和 workflow 安全边界。
- 手动触发 NX30PRO U-Boot 候选构建。
- U-Boot 候选检查通过后，手动触发 NX30PRO 固件候选构建。
- 根据 Actions 日志修正 NX30PRO 范围内的问题并重新验证。
- 将 run ID、构建结果、产物证据和未验证项写回交接文件。

阶段二仍然禁止：

- 自动发布 Release 或自动合并。
- 刷写、擦除 NAND 或执行真机升级。
- 将构建成功描述为真机兼容或恢复功能验证成功。
- 为修复 NX30PRO 构建而改动 TR3000。
- 未经再次确认执行任何超出候选构建的外部操作。

### 用户确认后发送的授权提示词

```text
我现在明确授权执行 NX30PRO 的手动 GitHub Actions 候选构建。

请先审查当前 diff、source lock、feed lock、NX30PRO 聚焦测试和 workflow_dispatch 安全边界。确认无误后：

1. 先触发 U-Boot 候选构建；
2. 检查 BL2/FIP、锁定 commit、布局和构建报告；
3. U-Boot 候选通过后，再触发固件候选构建；
4. 检查最终 defconfig 必需包、排除包、112M 布局、产物和容量；
5. 失败时只诊断并修正 NX30PRO 范围，不改 TR3000；
6. 不允许发布 Release、不允许刷机、不允许自动合并；
7. 将 Actions run ID、实际结果和未验证事项写回交接文件；
8. 不得把候选构建成功描述为真机验证成功。
```

## 阶段二结果分类

下一 Agent 必须使用准确状态：

| 状态 | 含义 |
|---|---|
| 静态实现完成 | 源码、配置、测试和 workflow 定义已落地，但尚未编译 |
| U-Boot 候选构建通过 | Actions 成功生成并检查 BL2/FIP，不代表真机可用 |
| 固件候选构建通过 | Actions 成功生成并检查固件，不代表可安全刷写 |
| 构建失败 | 保留日志、run ID 和根因证据，不能写成部分完成 |
| 真机验证未授权 | 没有执行刷写、恢复、升级或硬件兼容测试 |

## 真机阶段

真机验证不包含在上述两个阶段。即使 U-Boot 和固件候选构建全部通过，以下事项仍需单独设计和明确授权：

- 备份现有 BL2、FIP、Factory 和关键分区。
- 确认恢复路径、串口、TFTP 和紧急回退条件。
- 验证 `default` 与 `immortalwrt-112m` 布局切换。
- 验证固件恢复、BL2/FIP 升级和只读备份功能。
- 验证 PassWall、Xray、DDNS、Tailscale、ZeroTier、Docker 和 Argo 隧道。

在真机方案获批前，不得提供或执行猜测的擦写偏移、`mtd write`、裸写 NAND 或不可恢复操作。

## 相关文件

1. `docs/superpowers/plans/2026-11-27-nx30pro-next-agent-handoff.md`
2. `docs/superpowers/specs/2026-11-27-nx30pro-firmware-uboot-redesign.md`
3. `docs/superpowers/plans/2026-11-27-nx30pro-uboot-redesign.md`
4. `docs/superpowers/plans/2026-11-27-nx30pro-firmware-redesign.md`
5. `devices/nx30pro/docs/Command_fix.md`

## 当前权限边界

创建本文件的当前对话只允许方案整理和文档保存：

- 未触发 GitHub Actions。
- 未执行固件或 U-Boot 编译。
- 未授权 push、发布、刷机或真机操作。
- 本文件中的阶段二提示只是未来可用的授权模板，不代表当前已经授权。
