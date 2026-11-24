---
name: openwrt-firmware-config
description: Use when changing this repository's OpenWrt or ImmortalWrt devices, firmware variants, manifests, Kconfig packages, feeds, patches, overlays, Lite seed, or when diagnosing its known configuration merge, ccache, m4, ninja, disk space, and UNRESOLVED failures.
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
| device | 只属于一个硬件或固件变体 | `devices/<id>/`；TR3000 先 shared 再 lite/full；尚未迁移设备沿用旧 device 层目录 |
| local | 个人实验、网络和秘密 | 被忽略的 `local/`；不能成为 CI 隐式依赖 |

公共层改动必须列出全部受影响目标。需求只提到一台设备时，默认从 device 层开始论证；“以后可能复用”不足以把它上移到 common。

按类型选择文件：

- 目标、源码版本、层引用、产物匹配：`manifests/`。
- 原生 Kconfig：公共/发行版用 `configs/`，设备用 `devices/<id>/`，保留 `CONFIG_...` 语法。
- 附加软件源：`feeds/`，固定可复现 revision。
- 源码差异：`patches/`，说明适用 revision。
- rootfs 文件：公共层用 `overlays/`，TR3000 用 `devices/tr3000/shared/files/` 与选定变体的 `files/`。
- 稳定构建逻辑：公共工具用 `scripts/`，TR3000 真实实现用 `devices/tr3000/build/`；根 scripts 保留兼容入口，工作流调用真实实现。

## 设备与固件变体重点

- **TR3000 通用入口**：manifest 的目标字段仍可能是 `UNRESOLVED`。先核实制造商、硬件修订和上游 revision，不能复制 Lite 值。
- **TR3000 Lite**：独立的固定源码/feeds、`128muboot.config`、U-Boot Mod profile 与 112 MiB UBI 路径。以 `devices/tr3000/lite/config.seed`、`devices/tr3000/build/configure-lite.sh`、`devices/tr3000/build/build-lite.sh` 和 Lite 工作流为准。
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
- **修复**：`devices/tr3000/build/build-lite.sh` 把实际 `CCACHE_DIR` 传给 `devices/tr3000/build/configure-lite.sh`，合并配置时覆盖固定路径。
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

### GitHub Actions 构建中途报错 `No space left on device`

- **症状**：固件编译执行 2 小时以上时中断，Runner 抛出 `System.IO.IOException: No space left on device`（如 Worker 诊断日志写入失败），或 make 报告写入/解包错误。
- **已确认根因**：Ubuntu Runner 默认仅有 20~25 GB 可用空间，而 OpenWrt/ImmortalWrt 工具链、内核、多个软件包编译及 ccache 缓存全量构建峰值需要 35~45 GB 空间。若工作流未深度清理无用环境（如 Android SDK、.NET、Haskell、工具缓存、Docker 镜像），磁盘会在编译阶段被写满。
- **修复**：
  1. 工作流构建前执行深度清理，移除 `/usr/local/lib/android`、`/opt/hostedtoolcache`、`/opt/ghc`、`/usr/share/dotnet`、Docker 镜像等，释放 35GB+ 空间。
  2. 脚本中配置 `ccache -M 5G` 约束编译缓存上限，避免缓存无节制增长。
- **验证**：检查工作流 `Free runner disk space` 步骤中 `df -h` 输出的可用空间（应大于 55GB）；检查完整构建流程能够顺利完成打包与产物上传。

### Ruby 触发 Rust 工具链全量编译导致 Actions 6 小时超时

- **症状**：GitHub Actions 构建执行满 6 小时后提示 `The job has exceeded the maximum execution time of 6h0m0s` 并被取消；查看 `build.log` 发现数万行在编译 `rustc-1.94.0-src`。
- **已确认根因**：上游基线配置默认开启 `CONFIG_PACKAGE_ruby=y`，新版 packages 源中的 `ruby` 依赖 host 端 Rust 自举编译。在 2 核 Runner 上从源码编译整个 `rustc` 需要数小时。
- **修复**：在设备 seed（如 `devices/tr3000/lite/config.seed` 与 `devices/tr3000/full/config.seed`）中显式加入 `# CONFIG_PACKAGE_ruby is not set` 与 `# CONFIG_PACKAGE_libruby is not set`，并在配置脚本中加入排除检查。
- **验证**：检查合并后的 `build.config` 中不含 `CONFIG_PACKAGE_ruby=y`；构建跳过 Rust 工具链编译，总耗时控制在 1 小时内。

### `tcpdump-mini` 与上游 `tcpdump` 在 rootfs 组装时文件冲突

- **症状**：固件编译接近尾声，执行 `package/install` 时报错 `check_data_file_clashes: Package tcpdump-mini wants to install file .../usr/bin/tcpdump But that file is already provided by package * tcpdump` 并返回 Error 255。
- **已确认根因**：上游基线中默认包含完整版 `CONFIG_PACKAGE_tcpdump=y`，而设备 seed 中额外声明了 `CONFIG_PACKAGE_tcpdump-mini=y`。两者向 rootfs 安装同名文件 `/usr/bin/tcpdump` 触发 opkg 冲突阻止。
- **修复**：在 seed 中显式添加 `# CONFIG_PACKAGE_tcpdump is not set` 排除完整版，并在配置脚本的排除列表中检查 `tcpdump`。
- **验证**：检查合并生成的 `build.config` 中不含 `CONFIG_PACKAGE_tcpdump=y`，仅保留 `CONFIG_PACKAGE_tcpdump-mini=y`。

### TR3000 Lite 真机：`opkg update` 全部失败（wget returned 4）——overlay 缺 loopback 接口

- **症状**：LuCI 软件包管理器对每个 feed 报 `Failed to download ... wget returned 4`；设备上 `ping 1.1.1.1` 通、`nslookup 域名 192.168.x.1`（显式指定服务器）也通，但 `wget`/`opkg`/`nslookup 域名`（走系统解析器）全部失败。
- **已确认根因（2026-11-24 真机）**：Lite overlay 的 `/etc/config/network` 整体覆盖上游默认时**丢掉了 `loopback` 接口段** → `lo` 处于 DOWN 且无地址 → dnsmasq 无法绑定 `127.0.0.1:53`，而 `/etc/resolv.conf` 指向 `nameserver 127.0.0.1` → 路由器自身解析全灭。连锁反应：NTP 无法解析服务器 → 时钟停在构建日期 → 即使手动修好 DNS，TLS 下载仍报 `Issued certificate not yet valid`。这不是网络/镜像站问题。
- **修复**：overlay `network` 补回 `config interface 'loopback'`（`device 'lo'`、`proto 'static'`、`ipaddr '127.0.0.1'`、`netmask '255.0.0.0'`）；`devices/tr3000/build/build-lite.sh` 在编译前断言该段存在。Full overlay 一直有这段，Lite 重写时遗漏。
- **验证**：真机 `ip addr show lo` 应有 `127.0.0.1/8` 且 UP；`netstat -lnp | grep 127.0.0.1:53` 有 dnsmasq；`nslookup mirrors.vsean.net`（不指定服务器）成功；NTP 同步后 `date` 为当前时间；`opkg update` 六个 feed 全部 `Signature check passed`。修复后实测可从 feed 安装 `coreutils-stat`。
- **教训**：整体覆盖上游 `/etc/config/network` 时，必须逐段核对上游默认（loopback 是最容易丢的一段）；静态契约测试只查 `lan` 段时看不见这个缺口。

### TR3000 Lite 真机：控制器调用的 `stat`/`od` 不在镜像里

- **症状**：`tr3000-lite-plant` 报 `stat: not found` 后返回 `backup_owner`；管理 AP 首启脚本报 `od: not found` 后 `fail entropy`，AP 永远建不起来。
- **已确认根因（2026-11-24 真机）**：OpenWrt 的 busybox 默认**不含 `stat` 和 `od` applet**；Lite 镜像只装了 `coreutils`/`coreutils-base64`/`coreutils-nohup`。而 27 处控制器代码用 `stat -c` 做属主/权限门禁，AP 脚本与 DDNS 用 `od` 取随机数。开发机（完整 coreutils）上测试全绿，真机全灭。
- **修复**：`devices/tr3000/lite/config.seed` 增加 `CONFIG_PACKAGE_coreutils-stat=y`（feed 中存在该子包）；`od` 无对应子包，改用 busybox 自带的 `head -c N /dev/urandom | sha256sum | cut -c1-2N` 取随机 hex。新增 `tests/structure/test_lite_device_readiness.py` + `lite-image-commands.txt`（从已验证镜像导出的命令清单）审计所有随镜像脚本的工具调用。
- **验证**：真机 `command -v stat od`；`opkg install coreutils-stat` 后 `stat -c %u` 正常；修补后的 AP 脚本退出 0 并生成受管 AP。审计测试对旧脚本红（检出 od/stat）、对新脚本绿。
- **教训**：shell 脚本的工具依赖必须对照**目标镜像**的命令清单验证，不能以开发机 PATH 为准；`tests/structure/lite-image-commands.txt` 是唯一事实源，换 busybox 配置或增删包后要重新导出。

### TR3000 Lite 真机：空 libuci delta 被误判为“待提交修改”

- **症状**：首启 AP 脚本 `fail pending_wireless`；plant 控制器任何事务返回 `pending_firewall_state`。但 `uci changes` 为空。
- **已确认根因（2026-11-24 真机）**：`uci commit` 之后 libuci 会留下 **0 字节**的 `/tmp/.uci/<package>` 文件（dhcp/fstab/luci/system/wireless 等每次启动都有）。旧代码用 `[ ! -e ... ]` 判断“存在即拒绝”，把空文件当成待提交修改，导致管理 AP 与工业模式切换在真机上**从未成功过**。
- **修复**：改用 `[ ! -s ... ]`（只有非空 delta 才拒绝）；`/var/run/uci/<package>`（conf2dir 运行时覆盖）仍按存在即拒绝，因为空文件也会遮蔽配置。
- **验证**：真机分别放置空/非空 `/tmp/.uci/network` 后跑 `enable-plant`：空文件应走到地址校验（如 `management_overlap`），非空文件仍返回 `pending_firewall_state`，且配置不被改动。

### TR3000 Lite 真机：openssh-server 拒绝 root 密码登录，LuCI SSH 页面被隐藏

- **症状**：LuCI 里设置了 root 密码，SSH 密码登录仍 `Permission denied`；LuCI「系统 → 管理权」里看不到 SSH-Keys/SSH Access 页面。
- **已确认根因（2026-11-24 真机）**：Lite 排除 dropbear、装的是 `openssh-server`。OpenSSH 默认 `PermitRootLogin prohibit-password`，镜像未覆盖 → root 密码登录被拒。LuCI 的 SSH 页面依赖 `/usr/sbin/dropbear` 可执行（menu depends fs 检查），dropbear 不存在时页面 `satisfied:false` 直接隐藏；其 ACL 写的也是 `/etc/dropbear/authorized_keys`，与 OpenSSH 的 `/root/.ssh/authorized_keys` 无关。
- **修复**：overlay 增加 `/etc/ssh/sshd_config.d/99-tr3000-lite.conf`（`PermitRootLogin yes` + `PasswordAuthentication yes`；sshd_config 已 Include 该目录）；`configure-lite.sh` 断言该文件存在。root 密码本就是 Lite 的强制门禁（plant HTTPS/远程访问都要求非空），允许密码登录不引入新的弱口令面。
- **验证**：真机放置 drop-in 并 `/etc/init.d/sshd restart` 后，密码 SSH 登录成功。LuCI 的 dropbear 专属页面仍隐藏属上游行为，OpenSSH 密钥管理需另行设计（记录为后续项，不要假装修好）。

### TR3000 Lite：公共 snapshot feed 不可依赖，产物必须自带软件仓库

- **症状**：`opkg update` 时好时坏；镜像站对 `24.10-SNAPSHOT` 路径 404/302，或 feed 里的包版本与固定 revision 构建的镜像不匹配（内核模块 ABI 风险）。
- **已确认根因**：snapshot 是移动目标，会被镜像站定期清理；固定 commit 的固件不能以活的 snapshot 源为包事实源（与 Full 分支 `devices/tr3000/full/README.md` 的结论一致）。
- **修复**：`devices/tr3000/build/build-lite.sh` 把本次构建的 `bin/packages/<arch>/{base,packages,luci,routing,telephony}` 与 `bin/targets/.../packages` 连同 `key-build.pub` 一起放进 artifact 的 `package-repo/`；架构名从最终 `.config` 的 `CONFIG_TARGET_ARCH_PACKAGES` 读取，不硬编码。
- **验证**：artifact 含 `package-repo/arch/*/Packages.gz` 与 `key-build.pub`；启用方式与 Full 相同：内网 HTTP 提供仓库 → 改写 `/etc/opkg/distfeeds.conf` → 公钥按 usign 约定（base64 解码后 bytes[2:10] 的 hex）放入 `/etc/opkg/keys/<keyid>` → `opkg update`，`check_signature` 保持开启。

## 完整示例：TR3000 Lite 软件包变更

用户要求：“给 TR3000 Lite 加 OpenClash，并顺手放进 common。”

1. 读取 `devices/tr3000/lite/config.seed`，确认 `luci-app-openclash` 当前被显式排除；读取 `devices/tr3000/build/configure-lite.sh`，确认它还在排除包验证中。
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
| No space left on device | 深度清理 Runner 磁盘（Android/hostedtoolcache 等），并限制 ccache 大小 |
| Rust 编译或 Actions 6h 超时 | 检查上游是否残留 `ruby`，在 seed 中显式排除 `ruby` / `libruby` |
| opkg update 全失败但 ping 通 | 先查 `lo` 是否 UP、dnsmasq 是否绑 127.0.0.1:53，再查时钟/NTP |
| 控制器报 stat/od not found | 对照 `tests/structure/lite-image-commands.txt`；补 `coreutils-stat` 或改用 busybox 工具 |
| pending_wireless/pending_firewall_state 但 uci changes 为空 | 检查 `/tmp/.uci/<pkg>` 是否为 0 字节；用 `-s` 不用 `-e` |
| root 密码 SSH 被拒 | 查 openssh `PermitRootLogin` 默认值与 sshd_config.d drop-in |

## 常见错误

- 把 TR3000 Lite 的固定 profile、分区或包策略复制给通用 TR3000。
- 因“以后可能用”把设备专用包放进 common。
- 只修改 seed，不同步排除列表、feed、测试和最终配置检查。
- 看到 cache/m4 字样就删缓存，忽略配置路径与 `config.log`。
- 在 GitHub Actions 仅清理 dotnet/powershell，未删除 Android SDK 和 hostedtoolcache 导致空间不足。
- 遗漏排除上游基线中的 `ruby`，导致触发整个 Rust 工具链从源码编译而超时。
- 在 Windows 原生环境尝试完整固件编译并把环境失败误判为源码失败。
- 为通过 CI 猜 revision、profile 或 artifact pattern。
- 把未经真机验证的系统固件描述为通用刷写镜像。
- 整体覆盖上游 `/etc/config/network` 时丢掉 `loopback` 段，导致设备自身 DNS/NTP/TLS 全灭。
- 以开发机 PATH 为准假设 `stat`/`od` 等工具存在，不对照目标镜像命令清单。
- 用 `[ -e /tmp/.uci/<pkg> ]` 判断待提交修改，把 commit 后留下的 0 字节 delta 当成冲突。
- 排除 dropbear 换 openssh-server 后不配置 `PermitRootLogin`，也不检查 LuCI SSH 页面的 dropbear 依赖。
