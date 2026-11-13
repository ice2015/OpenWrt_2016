# Personal OpenWrt Builder

面向个人使用的多设备 OpenWrt/ImmortalWrt 构建仓库。项目以 GitHub Actions 为主要构建环境，首批设备入口包括 TR3000、x86_64 和 Raspberry Pi，并为后续硬件扩展保留稳定接口。

> 当前状态：项目结构、清单校验和 Actions 编排已经建立；源码版本、设备原生 profile 和个人软件包策略仍标记为 `UNRESOLVED`。在这些值经过核实前，构建脚本会主动停止，不会生成看似成功但不可信的固件。

## 快速开始

列出所有发行版/设备组合：

```sh
bash scripts/list-targets.sh
```

校验清单、路径和分层引用：

```sh
bash scripts/validate.sh
```

运行全部本地测试：

```sh
python -m unittest discover -s tests -v
```

本地脚本需要 Bash 和 Python 3。固件编译仅支持 Linux 或 WSL2；原生 Windows 用于编辑、校验和 Git 操作。日常完整构建从 GitHub 仓库的 **Actions → Build firmware → Run workflow** 手动选择发行版、设备和可选源码版本。

## 目录导航

| 目录 | 用途 |
| --- | --- |
| `manifests/` | 源码仓库、版本和设备构建元数据 |
| `configs/` | 原生 OpenWrt `.config` 片段 |
| `feeds/` | 公共及发行版专属 feed 片段 |
| `overlays/` | 写入固件 rootfs 的文件层 |
| `patches/` | 公共、发行版及设备补丁 |
| `scripts/` | 本地与 CI 共用的稳定命令接口 |
| `.github/workflows/` | GitHub Actions 校验和构建编排 |
| `local/` | 不提交的个人配置和私密覆盖 |
| `work/` | 不提交的上游源码及临时状态 |
| `output/` | 不提交的固件和构建报告 |
| `cache/` | 不提交的下载与编译缓存 |

## 设计原则

构建输入严格按以下顺序叠加，后层可以有意覆盖前层：

```text
common → distribution → device → local
```

公共策略只放真正适用于全部设备的内容；OpenWrt/ImmortalWrt 差异放在发行版层；硬件配置只放在对应设备层；密码、密钥和个人网络设置只能放入被 Git 忽略的本地层或 GitHub Secrets。

更多说明：

- [架构与数据流](docs/architecture.md)
- [配置分层规则](docs/configuration-layers.md)
- [新增设备指南](docs/adding-a-device.md)
- [本地私有配置说明](local/README.md)
- [AI 协作约定](AGENTS.md)

## 当前可选择目标

两个发行版均为首批设备保留入口：

- OpenWrt：TR3000、x86_64、Raspberry Pi
- ImmortalWrt：TR3000、x86_64、Raspberry Pi

“有入口”不等于“已经验证可刷写”。请先核实硬件修订、原生 target/subtarget/profile、上游源码 revision 和产物匹配规则，再启用实际编译。

## GitHub Actions

- `validate.yml`：Pull Request 和相关推送只读校验，不接触 Secrets，也不编译固件。
- `build.yml`：手动选择发行版、设备和可选源码版本。
- `reusable-build.yml`：单个发行版/设备组合的可复用 Linux 构建任务。

工作流仅负责编排，实际逻辑必须保留在 `scripts/` 中，以便本地和 CI 使用同一条路径。当前构建脚本在目标信息完整后仍会以状态码 `4` 提示“构建阶段尚未实现”；这是有意的安全边界。

## AI 修改项目时

编码代理应先阅读 `AGENTS.md`、目标设备清单和配置分层文档。不要直接编辑 `work/` 中的上游源码，也不要为了让工作流变绿而填入未经核实的硬件值。

