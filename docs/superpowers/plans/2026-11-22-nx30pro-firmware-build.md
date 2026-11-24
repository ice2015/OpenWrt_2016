# NX30 Pro 112M 自用固件编译计划

> **For agentic workers:** 执行时使用 superpowers:executing-plans，逐项完成复选框。本文件仅为计划，不执行配置修改、构建或刷机。

**Goal:** 基于用户指定 nx30pro-112m 分支，构建适合千兆宽带、10 台以内设备的家庭主路由固件。

**Architecture:** 固定上游源码和 feeds，在 NX30 Pro 专属层定制软件包与无秘密默认配置。按 common → distribution → device → local 合并，验证 make defconfig 后的实际配置；先验证启动和容量，再交付全功能固件。

**Tech Stack:** jerryhan77/immortalwrt-mt798x、nx30pro-112m、Linux 5.4 系列设备树、LuCI、PassWall/sing-box、Docker、GitHub Actions。

**Spec:** 本文需求表及配套 [U-Boot 计划](2026-11-22-nx30pro-uboot-build.md)，依据本次用户确认的需求编写。

## 已确认需求

| 模块 | 目标行为 |
|---|---|
| 硬件 | H3C NX30 Pro，原厂硬件，当前原厂系统 |
| 系统 | 指定仓库的 nx30pro-112m 分支，实施时锁定完整 commit |
| 启动 | 网页 U-Boot 与 NMBM 112M 布局配套，先完成兼容核实 |
| 基础网络 | PPPoE 主路由、双频 Wi-Fi、DHCP、IPv4/IPv6；用户确认双栈可从外网连入 |
| 使用规模 | 1000M 宽带，平时联网设备少于或等于 10 台 |
| 科学上网 | PassWall 管理 sing-box；订阅、节点及规则在部署后设置 |
| 分流 | 国内外分流、指定设备直连或代理；DNS 由统一方案管理 |
| 远程回家 | WireGuard 服务端供手机/电脑访问家庭网络；预装 Tailscale、ZeroTier |
| 服务访问 | Argo 按 Cloudflare Tunnel/cloudflared 规划，令牌部署后配置 |
| DDNS | 支持 IPv4/IPv6 更新；服务商及域名在部署时确定 |
| Docker | 预装引擎和适配的管理入口；无预装容器/镜像，使用机内剩余闪存 |
| 界面 | 中文，Argon 默认、Bootstrap 备用，简洁静态背景 |

用户选择“全功能预装、按需启用”。首次启动不自动启用代理、隧道、组网或 Docker；基础网络可配置。PPPoE、Wi-Fi、管理密码等真实值由用户部署时录入。

## 方案取舍

- **已选：在 jerryhan77 的 nx30pro-112m 分支直接定制。** 保留其设备适配，代价是要核实旧版底座与新软件的兼容性。
- 在较新 hanwckf 提交移植 112M：当前不选，避免增加移植范围。
- 换用较新 ImmortalWrt 官方 NMBM：当前不选，不把它的 profile、镜像格式与所选分支混用。
- 不预先承诺全部包能装下或代理跑满千兆；容量/性能不达标时先报告实际结果，再讨论删减，不静默取消用户要求。

## 全局约束

- 设备源码为 https://github.com/jerryhan77/immortalwrt-mt798x ，分支 nx30pro-112m；commit 和所有 feeds revision 暂为 `UNRESOLVED`。
- 源码已见 profile 为 h3c_nx30pro_112M；最终 target/subtarget 和完整 Kconfig 选择符仍需在锁定源码确认。
- UBI 起点 0x580000、长度 0x7000000（112 MiB）。当前镜像定义 IMAGE_SIZE=110592k（108 MiB），不擅自改大。
- 112 MiB 包含内核、只读系统和可写数据及 UBI 开销，不是 Docker 独享空间。
- 本仓库现有 sources.json 的 immortalwrt 源是官方仓库，不能为 NX30 Pro 全局改成此 fork。
- 设备功能只进入设备层；公共层及其他设备行为不变。
- 订阅、节点凭据、DDNS token、Argo token、VPN 私钥不提交、不烘焙进镜像。
- GitHub Actions 是主构建环境；本地编译只能在 Linux/WSL2。
- 不手工修改 work/、output/、cache/ 的生成内容。

## Review Focus

1. 旧底座与插件 API/依赖不匹配：逐包锁定并验证，不能无条件追踪最新版。
2. profile 与 bootloader 布局错配：联合分区合同检查失败时停止交付。
3. 全量包占满闪存：检查压缩镜像和实际 overlay 空间，禁止只看 112M 标签。
4. 代理、VPN 与 Docker 改写同一套网络规则：分别验证重启、停用和恢复。
5. 新设备源配置改变其他目标：隔离测试证明原有目标解析及构建输入不变。

## 拟建文件与职责

以下路径为实施期建议，未在本轮创建。若仓库已实施设备目录重组，应先更新本计划路径，不能同时制造两套入口。

| 文件 | 职责 |
|---|---|
| manifests/devices/nx30pro.json | 目标信息及设备层引用 |
| configs/devices/nx30pro/source-lock.json | 设备独享源码与依赖锁 |
| configs/devices/nx30pro/home.config | 原生 CONFIG_ 配置片段 |
| feeds/devices/nx30pro.conf | 设备额外 feeds，固定 revision |
| patches/devices/nx30pro/ | 必要且注明适用 commit 的补丁 |
| overlays/devices/nx30pro/files/ | 不含秘密的设备默认文件 |
| scripts/configure-nx30pro.sh | 合并配置、defconfig、必需/排除检查 |
| scripts/build-nx30pro.sh | 固定源码、调用配置和构建、生成报告 |
| .github/workflows/build-nx30pro.yml | 手动 CI 构建与产物上传 |
| tests/test_nx30pro_config.py | 有效配置、锁定和隔离测试 |
| docs/NX30PRO-README.md | 镜像用途、初始化、容量和验证结果 |

当前 manifest 模型尚无已确认的设备独享源码机制。先调查现有构建入口，再选择最小扩展；不能写入 schema 不支持的字段。首版可由专用脚本读取 source-lock，报告中明确与通用 manifest 入口的关系。

## Task 1：锁定构建事实和依赖

- [ ] 读取 AGENTS.md、固件配置技能、配置分层说明、现有 manifest/脚本/工作流及测试。
- [ ] 固定 nx30pro-112m 完整 commit，确认 target/subtarget、profile、默认 feeds、内核和 LuCI/防火墙版本。
- [ ] 确认 h3c_nx30pro_112M 同时引用正确 DTS、factory 与 sysupgrade 生成规则，记录两种镜像用途。
- [ ] 复核 108 MiB 镜像上限与 112 MiB UBI 的关系；核实 sysupgrade、MAC 和 Factory 数据读取方式。
- [ ] 与 U-Boot 计划的分区/NMBM 合同交叉检查；未匹配前只允许构建实验产物，不标记可刷写。
- [ ] 逐项建立包兼容表：PassWall、sing-box、cloudflared、WireGuard、DDNS、Tailscale、ZeroTier、dockerd/CLI/管理插件、Argon、Bootstrap 及中文包。
- [ ] 每项记录实际 Kconfig 符号、来源、完整 revision、依赖及内核要求；管理入口缺失或依赖冲突时明确报告，不凭名称猜包。

**验收：** 所有构建关键项可定位到固定源码；保留真实未知值并阻止不完整配置进入正式构建。

## Task 2：实现设备配置与隔离

- [ ] 添加测试：唯一设备选择；必需包在最终配置启用；未锁定输入被拒绝；NX30 Pro 配置不改变其他设备输入。
- [ ] 运行新测试确认失败，再实现上述设备层文件与最小源码选择机制。
- [ ] 按 common → distribution → device → local 合并；CI 不隐式读取 local。
- [ ] 启用表中所有功能的兼容包版本；PassWall 作为唯一透明代理管理者，不再启动独立 sing-box 服务接管同一流量。
- [ ] Docker、Argo、WireGuard、Tailscale、ZeroTier、PassWall 在未配置时不自动联网或启动业务；不内置测试账号、默认订阅或 token。
- [ ] DDNS 按服务商需要启用 provider；部署前确认服务商，不为“全支持”无条件塞入全部依赖。
- [ ] Argon 与所选 LuCI 匹配，Bootstrap 可切换；不使用面向新 LuCI 的不兼容主题版本。
- [ ] 运行 make defconfig 并验证最终 .config，检查依赖是否重新拉入被排除的大包；不直接复制 TR3000 seed。
- [ ] 测试网络默认值无家庭凭据、无默认开放的公网 LuCI/SSH；远程回家经 VPN 访问管理页面。

**验收：** 有效配置覆盖需求表；新增测试通过；其他设备输入不变；镜像中无个人秘密。

## Task 3：可追溯的 CI 编译与容量检查

**接口：** build-nx30pro.sh 消费固定源码锁和设备配置，输出固件、有效 .config、包清单、feeds 锁、日志、版本报告及 SHA256SUMS；不负责刷写。

- [ ] 专用 Actions 手动触发，contents: read，依赖和构建逻辑放脚本，workflow 只编排。
- [ ] 检查并按实际 Runner 环境清理无关预装组件，构建前记录 df -h；设置 ccache 上限和实际可写目录，避免继承其他项目的固定路径。
- [ ] 完成 defconfig、下载依赖和工具链构建；先构建最小启动验证配置，再构建目标全量配置，最小配置不能当作全量需求交付。
- [ ] 使用可调并行数运行 make；失败后保留首个稳定错误及串行详细日志，避免无依据换源码或删包。
- [ ] 校验 factory 镜像不超过源码定义上限，核实 sysupgrade 元数据、设备标识及包清单。
- [ ] 报告内核/rootfs/镜像大小；真机启动后补充 overlay 可用空间和空闲内存，不把估算写成实测。
- [ ] 输出配套 U-Boot commit/哈希或明确“尚未匹配”，禁止自动发布为通用 NX30 Pro 刷机包。

**验收：** CI 构建成功、需求包齐全、镜像容量通过、日志可追溯；Docker 可用空间需 Task 4 真机确认。

## Task 4：网络、远程访问与 Docker 验证

- [ ] 按配套 U-Boot 计划完成备份与刷写审阅后，再开展真机测试。
- [ ] 验证 PPPoE 重拨、DHCP、双频 Wi-Fi、IPv6 前缀更新及断电后正常启动。
- [ ] 分开测有线直连与 PassWall 代理吞吐、延迟、CPU/内存；记录协议和测试条件，不把千兆 NAT 等同于千兆代理。
- [ ] 测国内外域名、指定设备策略及 IPv6 流量路径，避免 IPv6 绕过预期代理规则。
- [ ] 方案默认：代理故障时国内直连继续工作；指定代理流量不自动切成直连。验证停止/重启代理后 DNS 和规则能恢复。
- [ ] 在外部网络分别验证 WireGuard 双栈入口及 DDNS 更新；默认只路由家庭网段，全流量回家另行配置。
- [ ] 分别验证 Tailscale、ZeroTier、Argo 的启停；Argo 默认不经 PassWall 重复绕行；不默认开放出口节点或整个家庭子网转发。
- [ ] Docker 使用最终可写空间中的专属数据目录，确认存储驱动/底层文件系统兼容后再启用；不能假定 overlay2 一定可用。
- [ ] Docker 日志采用轮转，例如每容器 max-size=1m、max-file=2；具体按锁定版本支持项落实，无自动拉取镜像和自动升级。
- [ ] 首次拉取前评估镜像压缩、解包、可写层和更新峰值空间；不足时停止部署，不自动删除现有数据、不用闪存 swap 硬撑。
- [ ] 容器启停后验证 DNS、防火墙转发、VPN 和 PassWall；以实际资源余量决定能否运行容器，记录限制。

**验收：** 网络基础功能稳定；远程访问逐项可用；Docker 引擎及存储验证有证据；未验证或无法容纳的功能明确列出。

## 必要检查与交付

实施相关修改后执行：

```sh
bash scripts/validate.sh
python -m unittest discover -s tests -v
```

补充设备配置合并、make defconfig、唯一 profile、必需包、feeds revision、镜像元数据和容量检查；未知目标仍应被构建就绪门禁阻止。文档交付只说明本地/CI/真机各自已验证范围。

最终交付：factory、sysupgrade（名称以实际产物为准）、校验和、构建报告、包/依赖锁、有效配置和初始化说明。敏感部署配置单独保存在用户本地。

## 参考资料

- [指定源码分支](https://github.com/jerryhan77/immortalwrt-mt798x/tree/nx30pro-112m)
- [112M 设备树](https://github.com/jerryhan77/immortalwrt-mt798x/blob/nx30pro-112m/target/linux/mediatek/files-5.4/arch/arm64/boot/dts/mediatek/mt7981-h3c-nx30pro-112M.dts)
- [设备与镜像定义](https://github.com/jerryhan77/immortalwrt-mt798x/blob/nx30pro-112m/target/linux/mediatek/image/mt7981.mk)
- [hanwckf 原项目说明](https://cmi.hanwckf.top/p/immortalwrt-mt798x/)
- 仓库约束：AGENTS.md、docs/configuration-layers.md、docs/architecture.md。

资料核查日期：2026-11-22。源码事实以实施时锁定的 commit 重新核实。
