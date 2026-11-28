# NX30 Pro 112M 固件构建说明

状态：**配置合同已被真实 `make defconfig` 证明；固件候选尚未构建，未真机验证**。
源码锁当前是 `source-locked-defconfig-proven`：`firmware_lock.py check` 退出 **0**
并渲染构建计划。提升它的唯一依据是被授权的 `make defconfig` 探针（GitHub Actions run `46108752994`，artifact `nx30pro-firmware-defconfig-probe`，conclusion success），
其 `probe/final.config` 是打过两个设备补丁、装好四个锁定 feed 之后真实
`make defconfig` 的结果，`probe/config-audit.json` 的 `errors` 为 0：18 个硬门禁
与 11 个可选工具全部 `=y`。探针只跑配置阶段，**没有编译任何固件，也没有产出任何
candidate 镜像**。本文描述可复现的构建输入、门禁与产物角色，以及触发远程构建
所需的授权边界。

| 项 | 值 |
|---|---|
| 上游仓库 | `https://github.com/hanwckf/immortalwrt-mt798x` |
| 锁定 commit | `740103d655bcee6da7bc3b49b1cfdfdee4cd5bb6` |
| 分支（仅供追溯，构建从不解析分支） | `openwrt-21.02` |
| 内核 | Linux **5.4**（`target/linux/mediatek/Makefile`：`KERNEL_PATCHVER:=5.4`） |
| target / subtarget | `mediatek` / `mt7981` |
| profile | `h3c_nx30pro_112M`（`CONFIG_TARGET_mediatek_mt7981_DEVICE_h3c_nx30pro_112M=y`） |
| 设备树 | `mt7981-h3c-nx30pro-112M` |
| 布局 | `immortalwrt-112m`（**默认**）与 `default`（原厂备选），共两个，不可增删 |
| 源码锁 | `devices/nx30pro/source-lock.json` |
| 设备补丁 | `devices/nx30pro/patches/0001-mediatek-add-nx30pro-112m-profile.patch`、`devices/nx30pro/patches/0002-mediatek-nx30pro-wan-mac-source.patch` |
| 配对启动链 | `https://github.com/Yuzhii0718/bl-mt798x-dhcpd`，commit `e4cf4dc72d451dc7a86c9508390ad5a2e50743c4`，版本 `SP1` |

被拒绝的旧底座（只作**被拒绝的证据**与 112M 移植**参考**，不是构建输入）：
`jerryhan77/immortalwrt-mt798x`，被拒绝的 revision `78cf22edddf07443d8f0506c9f361d3498475189`，
与 `Galaxian-Explosion/nx30pro-imm-112M-nmbm` 同一棵树（该参考树同样只作移植证据）。
连续失败的旧固件 Action 就是在它上面跑的：`make defconfig` 删掉了 PassWall、Xray、
cloudflared、DDNS、ZeroTier、Docker、Argon 等硬门禁。

## 1. 构建入口

```sh
# 只校验源码锁并打印构建计划：不建目录、不获取源码与 feed、不编译。
# 当前它以状态码 3 停止，并且不打印任何计划。
sh devices/nx30pro/build/build.sh \
  --lock devices/nx30pro/source-lock.json --check-only

# 授权的 defconfig 探针：只跑阶段 1-4（取源码与 feed、打补丁、层合并、
# 真实 make defconfig、审计最终 .config），产出 probe/final.config 与
# probe/config-audit.json，然后停止：不下载完整源码树、不编译、不产出镜像、
# 不发布候选。这是把 build-blocked 锁提升为可构建的唯一证据来源。
sh devices/nx30pro/build/build.sh \
  --lock devices/nx30pro/source-lock.json --probe-defconfig \
  --source-dir <源码检出目录> \
  --feed-dir <四个 feed 的检出目录> \
  --artifact-dir <产物目录>

# 完整候选构建（只有在锁被授权探针提升为可构建之后才可能走到这里）
sh devices/nx30pro/build/build.sh \
  --lock devices/nx30pro/source-lock.json \
  --source-dir <源码检出目录> \
  --feed-dir <四个 feed 的检出目录> \
  --artifact-dir <产物目录> \
  [--jobs N] [--repo-root <本仓库根目录>]
```

构建参数来自源码锁，不来自调用方环境。`--jobs` 缺省时取 `nproc` 且上限为 3：
runner 只有 4 核、约 7 GiB 内存，而本底座的 Go 与容器包比常规构建更吃内存。
`build.sh` 只构建，**从不刷写**，也从不写任何闪存设备。

## 1.1 锁定的 feed

四个 feed 全部固定到 commit，`devices/nx30pro/feeds.conf` 与源码锁逐项一致；
构建不使用分支引用。`feeds.conf.default`（锁定 commit 内）也只列这四个 feed，
设备层不需要额外 feed。

| feed | 仓库 | 锁定 commit |
|---|---|---|
| `packages` | `https://github.com/immortalwrt/packages.git` | `e09f3c7d1903cfe7f523e209ab3ec778013ba309` |
| `luci` | `https://github.com/immortalwrt/luci.git` | `5829eabba50ec0afa17d2ee486bc90dc15180c34` |
| `routing` | `https://github.com/openwrt/routing.git` | `a9e43101bb726070cbf81b6225fc0625f4a4a5e5` |
| `telephony` | `https://github.com/openwrt/telephony.git` | `920fbc5c0a2e4badf51bceff42e9a1e3eb693462` |

四条 `openwrt-21.02` feed 分支都已冻结（分支头早于源码 commit 日期且未再变化），
因此这些 pin 不会漂移。

## 1.2 锁定的分区布局

分区合同取自启动链锁
`devices/nx30pro/uboot/uboot-source-lock.json` 的 `layouts.entries["immortalwrt-112m"]`，
两边是**同一份分区合同**；`tests/structure/test_nx30pro_firmware_contract.py` 同时读取
两个文件，任何一侧漂移都会失败。地址均为 **NMBM 逻辑地址**（逻辑设备 `nmbm0`），
不是物理 NAND 地址。

| 布局标签 | mtdparts |
|---|---|
| `immortalwrt-112m`（**默认**） | `nmbm0:1024k(bl2),512k(u-boot-env),2048k(Factory),2048k(fip),112M(ubi)` |
| `default`（原厂备选） | `nmbm0:1024k(bl2),512k(u-boot-env),2048k(Factory),2048k(fip),65536k(ubi),6144k(pdt_data),6144k(pdt_data_1),1024k(exp),38400k(plugin)` |

112M 布局逐项（NMBM 逻辑偏移）：

| 分区 | 偏移 | 大小 |
|---|---|---|
| BL2 | `0x000000` | 1 MiB |
| u-boot-env | `0x100000` | 512 KiB |
| Factory | `0x180000` | 2 MiB |
| FIP | `0x380000` | 2 MiB |
| ubi | `0x580000` | 112 MiB |

系统侧设备树把 BL2、FIP 写成大写，启动链的 mtdparts 字符串写成 `bl2`、`fip`：
只有大小写不同，偏移与大小逐项相同。`default` 布局保留 `pdt_data`、`pdt_data_1`、
`exp`、`plugin`；`immortalwrt-112m` 把这片空间划进 UBI，所以**切换前必须先完成整片闪存的只读备份**（见 [`FLASH.md`](FLASH.md) 与
[`nx30pro-uboot-install-and-recovery.md`](nx30pro-uboot-install-and-recovery.md)）。

## 2. 构建前门禁（全部通过才会下载与编译）

`build.sh` 的阶段与证据文件：

| 顺序 | 阶段 | 命令 | 证据 |
|---|---|---|---|
| 1 | 源码锁门禁：源码与四个 feed 的完整 commit、目标与 profile、镜像规则、分区合同、软件包表全部齐备且可构建 | `firmware_lock.py check --lock` | `logs/build-plan.json` |
| 2 | 按锁定 commit 获取源码与四个 feed，并把 `^<commit>` 形式的 pin 写进 `feeds.conf` | `git clone --filter=blob:none` + `git checkout --detach` | `logs/source.json` |
| 3 | 构建前校验：检出就是锁定 commit、工作区干净、无上次构建残留、feed 未移动、设备补丁可应用 | `firmware_lock.py preflight` | `logs/preflight.json` |
| 4 | 配置阶段（见下表）：补丁 → 源码校验 → 层合并 → `make defconfig` → 最终配置审计 → overlay 扫描 | `devices/nx30pro/build/configure.sh` | `logs/configure.log` |
| 5 | 下载 | `make download -j N` | `logs/download.log` |
| 6 | 编译 | `make -j N` | `logs/build.log` |

阶段 4 的 `devices/nx30pro/build/configure.sh` 调用
`devices/nx30pro/build/firmware_lock.py` 的各个子命令，它**不编译任何固件**，
顺序是合同的一部分：

| 顺序 | 门禁 | 命令 | 证据 |
|---|---|---|---|
| 1 | 锁可构建；源码树就在锁定 commit；设备层只选 `mediatek` 与 112M profile | `firmware_lock.py check` | — |
| 2 | 应用设备补丁（四位前缀就是应用顺序：0001 profile、0002 WAN MAC） | `git apply --check` + `git apply` | `configure.log` |
| 3 | 打补丁后的设备树携带锁定的 112M 分区表与 NMBM 绑定 | `firmware_lock.py verify-device-tree` | `logs/device-tree.json` |
| 4 | 打补丁后的镜像规则携带锁定的 profile、显式镜像上限与两个镜像角色 | `firmware_lock.py verify-image-rules` | `logs/image-rules.json` |
| 5 | 按仓库文档化的优先级 `common -> distribution -> device` 合并配置层，层清单来自 `tools/manifest.py resolve` | `firmware_lock.py merge-config --out FILE` | `configure.log` |
| 6 | 安装 feed 并展开真实配置 | `./scripts/feeds update -a`、`./scripts/feeds install -a -f`、`make defconfig` | `configure.log` |
| 7 | 审计**最终** `.config`：硬门禁逐个 `=y` 且其枚举依赖齐备、可选包按锁状态上报、排除项保持关闭 | `firmware_lock.py verify-config --lock --config` | `logs/final-config.json` |
| 8 | overlay 密钥与部署值扫描，通过后才拷进 `files/` | `firmware_lock.py verify-overlay` | `logs/overlay.json` |

顺序 2 → 3/4 是必需的：112M 设备树与 profile 只存在于打完补丁的树里。
顺序 6 → 7 也是必需的：`make defconfig` 会删掉依赖不满足的包，只有它展开之后的
最终 `.config` 才是证据；被删掉的硬门禁必须在编译**之前**让构建失败。

## 3. 构建后门禁与产物

| 门禁 | 命令 | 证据 |
|---|---|---|
| 两个镜像角色按**角色模式 + profile 段**解析（从不按精确文件名），缺失/为空/重名/超过 `IMAGE_SIZE`/类型不符即失败 | `firmware_lock.py artifacts` | `logs/artifacts.json` |
| 软件包清单（构建产出的每个 `.ipk`）存在且非空 | `find bin -name '*.ipk'` | `logs/packages.txt` |
| 重新读取镜像、最终配置、包清单、feed 修订与日志后发布；只配置成功而未产出镜像的构建**永不**被发布 | `firmware_lock.py publish` | `build-report.json` |

产物目录结构（`publish` 写入 `<artifact-dir>`）：

```text
<artifact-dir>/
├─ images/                 # factory 与 sysupgrade 镜像、SHA256SUMS
├─ logs/                   # build-plan.json、preflight.json、configure.log、
│                          # download.log、build.log、artifacts.json 等逐阶段证据
├─ build-report.json       # 源码/feed 修订、目标、镜像规则、分区表、软件包表、
│                          # 配置审计、镜像 sha256、构建参数
├─ source-lock.json        # 本次构建使用的锁副本
├─ IMAGE-ROLES.txt         # 两个镜像角色是什么、不是什么
├─ final.config            # make defconfig 之后的最终配置
├─ packages.txt            # 构建产出的 .ipk 清单
└─ feeds-lock.json         # 实际检出的 feed 修订
```

`build-report.json` 的 `status` 固定是 `candidate-not-verified-on-device`。

### 3.1 两个镜像角色

镜像规则由 `devices/nx30pro/patches/0001-mediatek-add-nx30pro-112m-profile.patch`
加进 `target/linux/mediatek/image/mt7981.mk`：

- factory 角色，规则 `append-ubi | check-size $$(IMAGE_SIZE)`：112 MiB `ubi` 分区的
  原始 UBI 镜像，超过 `IMAGE_SIZE := 110592k` 时 `check-size` 直接拒绝构建。
- sysupgrade 角色，规则 `sysupgrade-tar | append-metadata`：带元数据的 sysupgrade tar 包，
  供 LuCI 升级页与 `sysupgrade` 命令使用。

`factory.bin` 与 `sysupgrade.bin` 两者**都不是启动链镜像**，也不能互相替代：
factory 镜像写的是 `ubi` 分区，sysupgrade 包只在已经运行本系统时有意义。
启动链镜像（BL2 与 FIP）由 `devices/nx30pro/build/build-uboot.sh` 构建，
不属于本构建。

其余 profile 事实：`BLOCKSIZE := 128k`、`PAGESIZE := 2048`、`UBINIZE_OPTS := -E 5`、
`KERNEL_IN_UBI := 1`、`SUPPORTED_DEVICES := h3c,nx30pro`、
`IMAGE_SIZE := 110592k`（**上限**，不是实测大小）。子目标默认只构建 sysupgrade
（`target/linux/mediatek/image/Makefile:19` 的 `IMAGES := sysupgrade.bin`），
所以 profile 显式 `IMAGES += factory.bin`；`verify-image-rules` 两边都校验。

输出目录是 `bin/targets/mediatek/mt7981`。**最终文件名保持 UNRESOLVED**：
`include/image.mk` 的名字是 `$(IMG_PREFIX)-$(PROFILE)-<role>`，而 `IMG_PREFIX`
以 `VERSION_DIST_SANITIZED` 与若干只在真实构建里才解析的版本变量开头。
因此 `manifests/devices/nx30pro.json` 记的是通配模式
`bin/targets/mediatek/mt7981/*h3c_nx30pro_112M-factory.bin` 与它的 sysupgrade 孪生，
`artifacts` 门禁按角色后缀加 profile 段解析，真正的名字要等第一次构建列出该目录。

## 4. 软件包合同（与源码锁逐项一致）

所有条目的状态都取自 `devices/nx30pro/source-lock.json`。`available` 只有一种含义：
被授权的 `make defconfig` 探针（GitHub Actions run `46108752994`，artifact `nx30pro-firmware-defconfig-probe`，conclusion success）的 `probe/final.config` 里该包的全部符号都是 `=y`，
并且 `probe/config-audit.json` 对它没有报错。提升之前的状态是 `candidate`
（“在锁定 feed 索引里读到了它”），那不足以写成可用；任何没有 defconfig 证据的包
仍必须留在 `candidate`、`unavailable` 或 `UNRESOLVED`。

### 4.1 硬门禁（18 项，缺一项就在编译前失败）

| 需求 | 包 | 符号 | 来源 feed | 版本 | 状态 |
|---|---|---|---|---|---|
| LuCI 管理界面 | `luci` | `CONFIG_PACKAGE_luci` | luci | — | available |
| 界面 HTTPS | `luci-ssl-openssl` | `CONFIG_PACKAGE_luci-ssl-openssl` | luci | — | available |
| 简体中文界面 | `luci-i18n-base-zh-cn` | `CONFIG_PACKAGE_luci-i18n-base-zh-cn`、`CONFIG_LUCI_LANG_zh_Hans` | luci | — | available |
| Argon 主题 | `luci-theme-argon` | `CONFIG_PACKAGE_luci-theme-argon` | luci | 2.3.1 | available |
| Bootstrap 兜底主题 | `luci-theme-bootstrap` | `CONFIG_PACKAGE_luci-theme-bootstrap` | luci | — | available |
| 透明代理管理器（锁定 4.68） | `luci-app-passwall` | `CONFIG_PACKAGE_luci-app-passwall`、`..._INCLUDE_Xray`、`..._INCLUDE_Xray_Plugin` | luci | 4.68-1 | available |
| PassWall 代理内核 | `xray-core` | `CONFIG_PACKAGE_xray-core` | packages | 1.8.3 | available |
| PassWall 插件集 | `xray-plugin` | `CONFIG_PACKAGE_xray-plugin` | packages | 1.8.3 | available |
| DDNS 脚本 | `ddns-scripts` | `CONFIG_PACKAGE_ddns-scripts` | packages | 2.8.2 | available |
| DDNS 管理界面 | `luci-app-ddns` | `CONFIG_PACKAGE_luci-app-ddns` | luci | — | available |
| 异地组网 Tailscale | `tailscale` | `CONFIG_PACKAGE_tailscale` | packages | 1.32.3 | available |
| 异地组网 ZeroTier | `zerotier` | `CONFIG_PACKAGE_zerotier` | packages | 1.12.2 | available |
| ZeroTier 管理界面 | `luci-app-zerotier` | `CONFIG_PACKAGE_luci-app-zerotier` | luci | — | available |
| 容器引擎守护进程 | `dockerd` | `CONFIG_PACKAGE_dockerd` | packages | 20.10.26 | available |
| 容器命令行客户端 | `docker` | `CONFIG_PACKAGE_docker` | packages | 20.10.26 | available |
| 容器管理界面 | `luci-app-docker` | `CONFIG_PACKAGE_luci-app-docker` | luci | 1 | available |
| 本底座支持的容器存储驱动 | `fuse-overlayfs` | `CONFIG_PACKAGE_fuse-overlayfs` | packages | 1.7.1 | available |
| Argo 隧道 | `cloudflared` | `CONFIG_PACKAGE_cloudflared` | packages | 2023.8.1 | available |

`tailscale` 只有守护进程与命令行：锁定的 luci feed 里**没有** `luci-app-tailscale`，
该缺口记在锁的 `unresolved` 里，不用别的包冒充。

依赖闭包只对旧 Action 真正丢过的三个包做了完整静态枚举：`luci-app-passwall`（24 个
直接依赖）、`dockerd`（14 个）、`luci-ssl-openssl`（3 个），每一个都在锁的
`dependency_index` 里有提供者、路径与锁定 commit；其余条目只校验 `provider_path`。
这是 `dependency_closure_scope` 明确写下的范围，剩下的传递依赖由被授权的
`make defconfig` 探针兜住。

### 4.2 可选但必须尝试并上报（13 项）

| 需求 | 包 | 符号 | 来源 | 状态 |
|---|---|---|---|---|
| Cloudflare DDNS 提供者 | `ddns-scripts-cloudflare` | `CONFIG_PACKAGE_ddns-scripts-cloudflare` | packages | available |
| FRPC 内网穿透客户端 | `frpc` | `CONFIG_PACKAGE_frpc` | packages | available |
| 完整 dnsmasq 功能集 | `dnsmasq-full` | `CONFIG_PACKAGE_dnsmasq-full` | 主树 | available |
| SQM/QoS | `sqm-scripts` | `CONFIG_PACKAGE_sqm-scripts` | packages | available |
| 流量监控 | `nlbwmon` | `CONFIG_PACKAGE_nlbwmon` | packages | available |
| 网络唤醒 | `etherwake` | `CONFIG_PACKAGE_etherwake` | packages | available |
| 网页终端 | `ttyd` | `CONFIG_PACKAGE_ttyd` | packages | available |
| SFTP 服务 | `openssh-sftp-server` | `CONFIG_PACKAGE_openssh-sftp-server` | packages | available |
| 抓包（mini 变体） | `tcpdump-mini` | `CONFIG_PACKAGE_tcpdump-mini` | 主树 | available |
| 吞吐测量 | `iperf3` | `CONFIG_PACKAGE_iperf3` | packages | available |
| 路由诊断 | `mtr` | `CONFIG_PACKAGE_mtr` | packages | available |
| WireGuard 服务端 | `wireguard` | `CONFIG_PACKAGE_kmod-wireguard`、`CONFIG_PACKAGE_wireguard-tools` | — | UNRESOLVED |
| sing-box 后端 | `sing-box` | 无（锁定 feed 中不存在） | — | unavailable |

WireGuard 的旧说法“5.4 内核没有 wireguard 模块”是**错的**：锁定 commit 里有
`target/linux/generic/backport-5.4/080-wireguard-*`、`KernelPackage/wireguard` 与
`wireguard-tools` 1.0.20210914。但 `target/linux/generic/config-5.4` 出厂就是
`# CONFIG_WIREGUARD is not set`，能否为 mediatek/mt7981 构建出来没有证据，
因此保持 UNRESOLVED，未证明的包不得顺带进镜像。

### 4.3 刻意排除

| 包 | 理由 |
|---|---|
| `luci-app-homeproxy` | 设计未要求，锁定 luci feed 中不存在；PassWall 4.68 是唯一透明代理管理者 |
| `sing-box`、`luci-app-sing-box` | 设计未要求，锁定 feed 中不存在；记为 unavailable 而不是假装可用 |
| `luci-app-openclash` | **确实存在**于锁定 luci feed，所以必须显式关闭，否则会有第二个代理管理者 |
| `luci-app-passwall2` | 锁定 feed 中不存在；设计要求的是 PassWall 4.68，不是它的后继 |
| `luci-app-adguardhome` | 锁定 feed 中不存在，设计也未要求 |
| `luci-app-wireguard` | 存在于锁定 luci feed，`LUCI_DEPENDS` 是 `+wireguard-tools +kmod-wireguard +luci-proto-wireguard`，选它就会把两个未证明的 WireGuard 符号拉回来 |
| `tcpdump` | 完整版与 `tcpdump-mini` 安装同一个 `/usr/bin/tcpdump`，rootfs 组装时 `check_data_file_clashes` 直接失败；由 `CONFIG_PACKAGE_tcpdump-mini` 取代 |
| `dnsmasq` | `define Package/dnsmasq-full` 带 `PROVIDES:=dnsmasq`，两者安装同一个 `/usr/sbin/dnsmasq`；由 `CONFIG_PACKAGE_dnsmasq-full` 取代。`verify-config` 拒绝“关掉基线变体却丢了替代者”的最终配置，那会交付一台没有 DNS/DHCP 的路由器 |
| `luci-app-dockerman` | 与 `luci-app-docker` 并存的第二个容器管理入口；本底座的管理入口是 `luci-app-docker` |
| `ruby`、`libruby` | 会拉起 host 端 Rust 自举编译，把构建推到 runner 时限之外；没有任何需求需要它 |

这两处 rootfs 冲突（`tcpdump` 与 `dnsmasq`）是仓库已经记录过的真机/构建教训，
设备层 `config.config` 用显式的 `# CONFIG_... is not set` 覆盖处理，
`verify-config` 在最终 `.config` 上复查。

## 5. 首次启动默认值：所有非必要服务默认关闭

`devices/nx30pro/files/etc/uci-defaults/90-nx30pro-defaults` 由 `configure.sh`
拷进 rootfs。镜像组装时 `include/rootfs.mk` 的 `prepare_rootfs` 会给每个
`/etc/init.d` 脚本执行 `rc.common enable`，所以这个文件的工作就是把它们
**默认关闭**：

| 包 | 关掉的 init 脚本 | 关掉的开关 |
|---|---|---|
| `luci-app-passwall` | `passwall`、`passwall_server` | `passwall.global.enabled`、`passwall_server.global.enable` |
| `ddns-scripts` | `ddns` | `ddns.service.enabled` |
| `tailscale` | `tailscale` | 无 enable 选项，init 脚本就是唯一门禁 |
| `zerotier` | `zerotier` | `zerotier.zerotier.enabled` |
| `dockerd` | `dockerd` | 无 enable 选项；存储驱动与数据目录未证明，所以守护进程保持关闭 |
| `cloudflared` | `cloudflared` | `cloudflared.cloudflared.enabled` |
| `frpc` | `frpc` | 无 enable 选项 |
| `nlbwmon` | `nlbwmon` | 无 enable 选项 |
| `ttyd` | `ttyd` | `ttyd.ttyd.enable`（上游默认是 1，必须显式关） |
| `sqm-scripts` | `sqm` | `sqm.queue.enabled` |
| `etherwake` | `etherwake` | 只唤醒 `wakeonboot` 打开的目标，启动路径保持关闭 |

边界与事实：

- `/etc/init.d/boot`（START=10）在上述作品服务的 START 号（60/80/90/95/99）之前
  应用 uci-defaults，因此删掉 `rc.d` 软链就够了，不需要先 stop。
- 包不存在时两个 helper 都返回 0；只 commit 自己改过的 UCI 包；值已经正确时不写闪存。
- 脚本**不删除自己**：`boot` 只在脚本返回 0 时删除它，失败时留在下一次启动重试。
- 基线服务（`dnsmasq`、`network`、`firewall`、`system`、`dropbear`、`uhttpd`、
  `luci`、`ucitrack`）一个都不碰。overlay 也**不**附带任何 `/etc/config` 模板：
  仓库记录过的 Lite 真机故障就是整体替换 `/etc/config/network` 丢掉 `loopback` 段，
  连带打死本机解析器、NTP 与所有 TLS 下载；合同测试要求未来的 network 模板必须保留
  `loopback`。
- 只用镜像里真有的命令：`uci`、`mkdir`、`sed`、`echo` 与 `test` 内建。本底座 busybox
  的 `Config-defaults.in` 没有启用 `stat` 与 `od`，这是仓库记录过的另一条真机教训。
- 镜像里没有账号、节点、订阅、令牌、域名、密码、密钥或任何设备的 MAC。
  部署值只在设备上写入，见第 7 节与
  [`nx30pro-firmware-install-and-validation.md`](nx30pro-firmware-install-and-validation.md)。

## 6. 与启动链的配对

本固件与 `https://github.com/Yuzhii0718/bl-mt798x-dhcpd`（commit
`e4cf4dc72d451dc7a86c9508390ad5a2e50743c4`，版本 `SP1`：`uboot-mtk-20250711` +
`atf-20240117-bacca82a8`）配对，两边使用**同一份分区合同**。选 `SP1` 的依据是上游
README 对 5.4 内核的配对说明，不是本机启动日志；`SP1` ATF 与 Linux 5.4 固件的真实
启动兼容性保持 UNRESOLVED。

- 启动链产物是 BL2 与 FIP，文件名含镜像 md5；两者都**不是系统镜像**，本构建不产出它们。
- 系统镜像（factory / sysupgrade）都不是启动链镜像，写错分区不可恢复。
- 启动链侧已关闭 Factory 写入、Flash Editor、环境变量编辑、Web 终端、Telnet、
  UBI 卷管理与任何 CPU/DDR 超频符号；网页布局选择器只列 `immortalwrt-112m` 与
  `default` 两个标签。
- 112M 布局没有 `pdt_data_1`，而底座的 `02_network` 原本从它读 WAN MAC。
  `devices/nx30pro/patches/0002-mediatek-nx30pro-wan-mac-source.patch` 把取值顺序改成
  `/etc/nx30pro/wan-mac`（部署时写入，不进镜像）→ `Factory` 的 ascii `ethaddr`（只读）
  → 仍存在的 `pdt_data_1`（只读）；三者都取不到时保留 bootloader 交下来的地址并记录日志。
  该补丁同时**移除**了底座把派生 Wi-Fi MAC 写回 `Factory` 偏移 4 的行为，
  出厂校准区从此只读。

## 7. 远程构建与授权

工作流 `.github/workflows/build-nx30pro.yml` 只有 `workflow_dispatch` 手动入口，
`permissions: contents: read`，不使用 Secrets，不含任何刷写、擦除或部署命令。步骤是：
深度清理 runner 磁盘并断言剩余空间（仓库记录过的 `No space left on device` 教训，
构建峰值约 40 GiB）→ 安装 `include/prereq-build.mk` 检查的主机依赖（含
`python3-distutils`）→ 记录主机工具链身份 → 运行 `bash scripts/validate.sh`、
**设备限定**的三个测试模块与 `build.sh --check-only` 锁门禁 → 调用第 1 节的完整构建
入口 → 仅在 `success()` 时上传候选产物（`if-no-files-found: error`），`if: always()`
上传日志。`ccache -M 5G` 限制编译缓存上限，`CCACHE_DIR` 由工作流自己给出，
避免仓库记录过的“固定缓存路径与 runner 实际路径不一致”故障。

静态前置检查刻意不跑仓库全量套件：别的设备的测试状态不得决定本设备能否构建，
仓库全量检查由 `validate.yml` 承担。

工作流带一个 `workflow_dispatch` 输入 `probe_defconfig`（boolean，**默认 false**）：
置为 true 时该次运行只执行上面的探针，证据以 `nx30pro-firmware-defconfig-probe`
（`if: always()`）上传，而候选产物上传步骤的条件是
`if: success() && inputs.probe_defconfig == false`，所以探针**不可能**发布镜像。
该输入是唯一的操作员开关：源码、feed、profile 与软件包全部由锁决定，
没有任何输入可以指定它们。

**触发该工作流需要用户单独、明确的授权。** 静态测试通过不等于候选构建完成，
候选构建完成不等于真机可用。任何运行结果都必须带 run ID、URL、结论与产物哈希
记进 [`TEST-REPORT.md`](TEST-REPORT.md)；没有这些证据就不得写成一次成功的构建。

设备侧的部署值（不进镜像、不进仓库）：

| 文件 / 位置 | 内容 | 何时写入 |
|---|---|---|
| `/etc/nx30pro/wan-mac` | 本机 WAN MAC | 部署时在设备上写入 |
| PassWall 节点与订阅 | 用户 | 部署时 |
| DDNS 服务商、域名与账号 | 用户 | 部署时 |
| cloudflared 隧道令牌与凭据文件 | 用户 | 部署时 |
| Tailscale / ZeroTier 账号 | 用户 | 部署时 |

软件仓库：仓库记录过“公共 snapshot feed 不可依赖，产物必须自带软件仓库”的教训。
本设备的候选产物目前只带 `packages.txt`（构建产出的 `.ipk` 清单），
**没有**打包 `bin/packages/` 与构建公钥，所以离线安装能力仍是待补项，
不得写成已经具备。

## 8. 未决项（UNRESOLVED）

与源码锁 `unresolved` 一一对应，逐项都还没有证据：

1. 硬门禁的 `make defconfig` 证明；
2. 112M `profile` 与设备树的**构建**证据（当前只有静态补丁校验）；
3. 设备的 WAN MAC 取值；
4. 112M 布局下的 WAN MAC 读取路径与 `Factory` 校准数据；
5. factory 与 sysupgrade 的最终**文件名**；
6. Linux 5.4 上的 WireGuard 服务端；
7. `luci-app-tailscale`；
8. Go 类包（xray-core、xray-plugin、cloudflared、tailscale、docker、dockerd）在 21.02 工具链上的可构建性；
9. 容器**存储驱动**（`fuse-overlayfs` 在最终可写空间上的表现，不假定 overlay2 可用）；
10. 镜像实际大小与剩余 **overlay** 空间；
11. 每个服务的**运行行为**；
12. 设备的 **NAND** 型号、容量与坏块状态（112M 布局的逻辑容量是从两张源码表推导的，不是实测）。

在第 1、2、5 项完成前，本目录里的固件只能是“候选、未真机验证”；
在第 11、12 项完成前不得成对刷写。详见
[`nx30pro-firmware-compatibility.md`](nx30pro-firmware-compatibility.md) 与
[`TEST-REPORT.md`](TEST-REPORT.md)。
