# 设备目录重构验证记录

状态：迁移、独立审阅修复及最终 Linux 完整回归已完成。

## 交付位置

- 分支：`codex/device-directory-reorganization`。
- 工作区：`G:/My_code/AI_CODE/OpenWrt_2016/.worktrees/device-reorganization`。
- 基线：`9ecfdc3237c22d7be1dcd23bc4e33a48cfa83e69`。
- 交付方式：按用户本次明确授权，提交并推送独立分支 `codex/device-directory-reorganization`；不合并 master、不发布固件、不手动触发固件构建。推送后的自动校验遵循仓库现有配置。原 master checkout 保留。

## 文件与行为

TR3000 的配置、两个变体 seed/feed lock、overlay、LuCI 包、运行脚本、构建实现、DDNS 补丁及操作文档归入 `devices/tr3000/`。公共工具、发行版配置、集中 manifests 与 Actions 保持原位。A6S/NX30Pro/WR30U 仅增加待适配说明和 build/files/packages/patches/runtime/uboot/docs 目录骨架，以 .gitkeep 保留；没有注册构建目标。

旧可执行入口保留参数、退出码和原有 Git 可执行位；8 个被 source 的旧库入口使用 Git 符号链接，支持仓库外的 POSIX sh/Bash 调用。固件安装真实脚本，不安装宿主入口或库桥接器。Windows 无符号链接权限时应从 Linux/WSL 文件系统检出执行这些入口。

`2026-11-25-device-directory-reorganization-inputs.json` 记录 100 个源文件的旧路径、新路径、原 SHA256 和 Git mode；已逐项核对所有原 SHA256 与基线 Git blob 相同。除明确的路径引用变更，设备输入与 runtime 内容未改变。

Lite/Full 的配置夹具分别生成 42/32 个文件。迁移后配置及这些安装文件的哈希与基线相同；链接以链接目标字符串比较。三个工作流反向还原迁移路径后，其字节哈希与基线相同，因此触发器、runner、源码 SHA、参数、权限、并发组、缓存前缀和产物标识未改变。

这些证据验证仓库输入与安装流程，不替代实际 OpenWrt `make defconfig`、固件编译或真机测试。

## 验证结果

- 基线清单校验通过。基线完整回归运行 339 项、跳过 13 项；唯一失败来自初始 WSL Git 工作目录环境设置，使用正确工作目录重跑两个忽略规则测试均通过。固件行为测试没有基线失败。
- 输入迁移后针对性回归：91 项通过。
- Actions/manifest/隔离针对性回归：26 项通过。
- 原生 Linux 文件系统中的针对性回归：119 项通过，实际还原并检查 Git 符号链接。
- 独立审阅指出的 4 个重要问题，使用 5 项回归重现全部失败后修复，5 项全部通过：DDNS 新旧入口实际应用补丁、旧命令直接执行、POSIX source 兼容、设备层容器引用拒绝。
- `bash scripts/list-targets.sh`：原 6 个组合仍为 unresolved。
- immortalwrt 下 tr3000/x86-64/raspberry-pi 的 `--require-build-ready` 均返回状态码 3。
- 已对真实设备 shell 脚本运行 `sh -n`，并检查 README/设备文档相对链接及活动旧路径引用。
- 最终完整回归：`python3 -m unittest discover -s tests -v`，356 项，13 项跳过，0 失败，耗时 1392.406 秒。
- 最终 `bash scripts/validate.sh` 与 `git diff HEAD --check` 均通过。完整回归使用还原 Git 模式及符号链接的原生 Linux 文件系统快照；没有把 Windows 占位链接当成真正的 Linux 链接。

## 独立审阅与实施决定

独立审阅发现 4 个重要问题，无 Critical；全部纳入一次修复过程：

1. 移动 DDNS 辅助工具后，`__file__` 的相对补丁定位失效。将真实补丁归入 Lite 目录并修正定位；保留固定版本门禁及原 feed 源文件不变。
2. 9 个旧可执行入口需要显式保留 100755 Git mode。已恢复，并使用不经过解释器的直接执行检查。
3. 普通转发文件无法从 POSIX shell 获取被 source 文件的自身路径。改用 Git 符号链接；先前仅兼容 Bash/同目录调用的选择已被取代。代价是 Windows 无链接权限的占位检出需要转到 Linux/WSL 执行。
4. 设备层引用 `.`、`devices` 或其目录别名会包含其他型号。校验现在拒绝这些容器，保留普通公共层目录及当前设备目录的合法引用。

其余实施决定：

- 保留本轮被忽略的检查日志直到手工提交，避免没有提交历史时丢失证据；没有清理其他工作区。
- 在隔离工作区把 Windows CRLF 还原为 Git 中的 LF，随后核对原始 blob 哈希；没有因此修改历史文档或其他型号。
- 使用仓库专用 `lite/runtime/lite-common.sh` 桥接器供源脚本使用；固件始终安装共享库真实内容，安装哈希检查防止误装桥接器。
- 原计划中的部分文档已不存在，按当前真实文档迁移 HomeProxy、DDNS、TUNNEL 和 Lite 运维说明；历史 specs/plans 不重写。
- 基线运行期间先验证独立的 manifest 归属规则，没有提前移动固件输入；最后完整回归覆盖集成后的状态。
- 原先 Git 环境误设仅重跑受影响的忽略规则检查，最终回归使用具有独立 Git 元数据的 Linux 文件系统快照。
- `tools/tr3000_lite_provision.py` 保留已记录的稳定 CLI；它不在批准计划的具体迁移清单中。代价是这个离线设备工具仍位于 tools；不增加固件输入或跨设备依赖。

## 留待后续的小项

- 持久化语法测试主要检查旧入口；本轮已另外对全部真实设备脚本执行 `sh -n`，后续可把该覆盖收进测试。
- 跨设备测试中的符号链接夹具在原生 Windows 下仍要求链接权限，尚未拆成独立可跳过用例；本轮最终验证使用 Linux。

## Actions 与硬件交接

本轮没有手动触发 Lite、Full 或 U-Boot 编译，也没有刷机。后续应分别构建，检查最终 build.config、包清单、镜像布局、固件内路径、产物名称和 SHA256SUMS；二进制逐字节相同、启动成功和硬件行为均不作为本轮已验证结论。新设备未知项继续保持 UNRESOLVED。
