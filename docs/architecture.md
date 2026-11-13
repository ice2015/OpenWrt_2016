# 架构与数据流

## 仓库边界

本仓库保存“如何构建”的事实：源码来源、目标设备、配置片段、feeds、补丁、rootfs 覆盖、编排脚本和复现报告规则。上游 OpenWrt/ImmortalWrt 源码是可丢弃的工作数据，下载到 `work/`；固件写入 `output/`；下载和工具链缓存写入 `cache/`。这三个目录都不进入 Git。

不使用 Git submodule 保存上游源码，也不在上游 checkout 中长期维护手工改动。需要保留的差异必须回到本仓库的配置、补丁或 overlay 层。

## 组件职责

```text
manifests/*.json
      │
      ├── tools/manifest.py：解析、校验、列出和解析目标
      │
      ├── scripts/*.sh：本地与 CI 的稳定命令入口
      │
      └── .github/workflows/*.yml：权限、触发器、runner 和产物编排
                            │
                            └── work/ → output/ + 构建报告
```

`tools/manifest.py` 只使用 Python 标准库，避免在校验阶段安装依赖。它允许清单结构有效但构建信息仍为 `UNRESOLVED`；只有请求 `--require-build-ready` 时才以状态码 `3` 拒绝目标。

## 清单解析

`manifests/sources.json` 定义：

- OpenWrt 与 ImmortalWrt 的 Git 仓库；
- 可复现的 revision；
- 公共层；
- 每个发行版自己的配置及 feed 层。

`manifests/devices/<id>.json` 定义：

- 稳定设备 ID 和显示名称；
- 支持的发行版；
- 原生 target、subtarget 和 profile；
- 设备配置、feeds、补丁、overlay 及产物匹配规则；
- 硬件注意事项。

解析结果按公共、发行版、设备的顺序返回。未来实现本地构建时，`local/` 只在最后追加，并且永不出现在 GitHub 的不可信 Pull Request 上下文中。

## GitHub Actions 数据流

1. `validate.yml` 在 Pull Request 和相关推送中运行结构校验与标准库测试。
2. 用户从 `build.yml` 选择发行版、设备和可选 revision。
3. `build.yml` 调用 `reusable-build.yml`，不复制构建逻辑。
4. 可复用任务先校验清单，再调用 `scripts/build.sh`。
5. 清单仍有未知字段时，任务在下载源码前失败并给出具体字段。
6. 真实构建阶段实现后，任务将上传固件、解析后的 `.config`、源码 revision、包列表、日志和校验和。

Actions 权限默认为 `contents: read`，不使用 `pull_request_target`。签名密钥等敏感值只能从受信任工作流的 GitHub Secrets 注入。

## 退出码

| 状态码 | 含义 |
| --- | --- |
| `0` | 校验或查询成功 |
| `2` | 清单、参数、路径或发行版/设备组合无效 |
| `3` | 结构有效，但构建所需字段仍为 `UNRESOLVED` |
| `4` | 目标已可解析，但当前脚手架尚未实现真实构建阶段 |

