# NX30 Pro 固件兼容性核实记录

状态：**配置合同已被真实 `make defconfig` 证明；固件候选未构建、未真机验证**。
本文只记录在锁定 commit 上可复核的事实，以及仍然 UNRESOLVED 的项。本文不构成刷写许可，
也不代表任何镜像可以在本机设备上工作。源码锁当前是 `source-locked-defconfig-proven`，
`firmware_lock.py check` 退出 **0**；提升它的唯一依据是被授权的 `make defconfig` 探针（GitHub Actions run `46108752994`，artifact `nx30pro-firmware-defconfig-probe`，conclusion success）。
探针只跑配置阶段，没有编译固件，也没有产出任何 candidate 镜像。

| 项 | 值 |
|---|---|
| 设备 | H3C Magic NX30 Pro（MT7981，SPI-NAND，112 MiB UBI 布局） |
| 系统源码 | `https://github.com/hanwckf/immortalwrt-mt798x`，锁定 commit `740103d655bcee6da7bc3b49b1cfdfdee4cd5bb6` |
| 分支（仅供追溯） | `openwrt-21.02`（`git ls-remote` 只有这一个 ref，且等于 HEAD；构建从不解析分支） |
| 内核 | Linux **5.4**（`target/linux/mediatek/Makefile`：`KERNEL_PATCHVER:=5.4`、`KERNEL_TESTING_PATCHVER:=5.4`） |
| profile | `h3c_nx30pro_112M`，由设备补丁移植（上游锁定 commit 中不存在） |
| 布局 | `immortalwrt-112m`（**默认**）与 `default`（原厂备选），共两个 |
| 配对启动链 | `https://github.com/Yuzhii0718/bl-mt798x-dhcpd`，commit `e4cf4dc72d451dc7a86c9508390ad5a2e50743c4`，版本 `SP1` |
| 机器可读锁 | [`../source-lock.json`](../source-lock.json) |

## 1. 源码与 feed 锁定

| 输入 | 仓库 | 锁定 revision | 分支（仅供追溯） |
|---|---|---|---|
| 系统源码 | `https://github.com/hanwckf/immortalwrt-mt798x` | `740103d655bcee6da7bc3b49b1cfdfdee4cd5bb6` | `openwrt-21.02` |
| packages feed | `https://github.com/immortalwrt/packages.git` | `e09f3c7d1903cfe7f523e209ab3ec778013ba309` | `openwrt-21.02` |
| luci feed | `https://github.com/immortalwrt/luci.git` | `5829eabba50ec0afa17d2ee486bc90dc15180c34` | `openwrt-21.02` |
| routing feed | `https://github.com/openwrt/routing.git` | `a9e43101bb726070cbf81b6225fc0625f4a4a5e5` | `openwrt-21.02` |
| telephony feed | `https://github.com/openwrt/telephony.git` | `920fbc5c0a2e4badf51bceff42e9a1e3eb693462` | `openwrt-21.02` |

选择依据：锁定 commit 的 `feeds.conf.default` 只列 packages、luci、routing、telephony
这四个 feed，全部在 `openwrt-21.02` 分支上；四个分支都已冻结（分支头早于源码 commit
日期且未再变化），所以 pin 不会漂移，也不存在“更新一点的 21.02 feed”可选。
设备层不需要额外 feed：需求表里的软件包全部由主树或这四个 feed 提供。

被拒绝的旧底座：`jerryhan77/immortalwrt-mt798x`，被拒绝的 revision
`78cf22edddf07443d8f0506c9f361d3498475189`。`git ls-remote` 显示该 commit 是
`hanwckf/immortalwrt-mt798x` 的 `refs/pull/135/head`，即一个**未合并的 PR**，
与 `Galaxian-Explosion/nx30pro-imm-112M-nmbm`（同一 revision）是同一棵树。
它只作为**被拒绝的证据**保留：连续失败的旧固件 Action 就在它上面跑，
`make defconfig` 删掉了 PassWall、Xray、cloudflared、DDNS、ZeroTier、Docker、Argon。
该树的 112M profile 与设备树现在只作为**移植参考**（`source-lock.json` 的
`source.port_reference`），移植结果重放到上面锁定的 hanwckf commit 上。

## 2. 目标、profile 与镜像规则

| 项 | 值 | 来源 |
|---|---|---|
| target / subtarget | `mediatek` / `mt7981` | `target/linux/mediatek/Makefile`、`mt7981/target.mk` |
| profile | `h3c_nx30pro_112M` | 设备补丁移植，**不在**锁定 commit 中 |
| profile 符号 | `CONFIG_TARGET_mediatek_mt7981_DEVICE_h3c_nx30pro_112M=y` | 同上 |
| 设备树 | `mt7981-h3c-nx30pro-112M.dts` | `target/linux/mediatek/files-5.4/arch/arm64/boot/dts/mediatek/` |
| 支持的设备串 | `h3c,nx30pro`（沿用原厂 profile） | 移植的 profile 定义 |
| 内核 | Linux 5.4 | `target/linux/mediatek/Makefile` |
| 镜像上限 | `IMAGE_SIZE := 110592k`（108 MiB） | 移植的 profile 定义 |
| 块大小 / 页大小 | `BLOCKSIZE := 128k` / `PAGESIZE := 2048` | 同上 |
| UBI 参数 | `UBINIZE_OPTS := -E 5`、`KERNEL_IN_UBI := 1` | 同上 |
| 输出目录 | `bin/targets/mediatek/mt7981` | `include/image.mk` 的 `BIN_DIR` |

锁定 commit 里与 NX30 Pro 有关的只有五个原厂文件（`Device/h3c_nx30pro`、
`mt7981-h3c-nx30pro.dts`、`02_network`、`01_leds`、`platform.sh`），
**没有** 112M profile，也没有 112M 设备树；原厂 profile 的 `IMAGE_SIZE := 65536k`
对应 64 MiB UBI。所以 112M 支持是设备移植，由
`../patches/0001-mediatek-add-nx30pro-112m-profile.patch` 提供，锁里记为
`target.verification = ported-by-device-patch`，只有静态校验证据
（`verify-device-tree`、`verify-image-rules`），没有构建证据。

移植时保留原厂设备树的共享板级节点，只替换 NMBM 分区表；不引入参考树的
`mt7981-h3c-nx30pro-base.dtsi`，因为那会连带改写原厂 `mt7981-h3c-nx30pro.dts`。
`nmbm_spim_nand { compatible = "generic,nmbm"; forced-create; }` 与
`lower-mtd-device = <&spi_nand>` 的绑定必须保留，否则合同里的 `nmbm0` 逻辑偏移不存在。

### 2.1 两个镜像角色

- factory 角色，规则 `append-ubi | check-size $$(IMAGE_SIZE)`：112 MiB `ubi` 分区的
  原始 UBI 镜像，超过 `IMAGE_SIZE := 110592k` 时 `check-size` 拒绝构建。
- sysupgrade 角色，规则 `sysupgrade-tar | append-metadata`：带元数据的 sysupgrade tar 包，
  供 LuCI 升级页与 `sysupgrade` 命令使用。

子目标默认只构建 sysupgrade（`target/linux/mediatek/image/Makefile:19`，
`define Device/Default` 里的 `IMAGES := sysupgrade.bin`），所以 profile 显式
`IMAGES += factory.bin`。`factory.bin` 与 `sysupgrade.bin` 都**不是启动链镜像**，
也不能互相替代；启动链镜像是 BL2 与 FIP，由 `build-uboot.sh` 单独构建。

最终文件名保持 UNRESOLVED：`include/image.mk` 的名字是
`$(IMG_PREFIX)-$(PROFILE)-<role>`，`IMG_PREFIX` 以 `VERSION_DIST_SANITIZED` 与只在真实
构建里解析的版本变量开头。`manifests/devices/nx30pro.json` 因此记的是通配模式
`bin/targets/mediatek/mt7981/*h3c_nx30pro_112M-factory.bin` 与它的 sysupgrade 孪生，
产物门禁按角色后缀加 profile 段解析，从不按精确文件名。

## 3. 分区合同（与启动链一致）

分区合同来自启动链锁
`../uboot/uboot-source-lock.json` 的 `layouts.entries["immortalwrt-112m"]`，
两边是**同一份分区合同**；合同测试同时读取两个文件，任何一侧漂移都会失败。

| 布局标签 | mtdparts |
|---|---|
| `immortalwrt-112m`（**默认**） | `nmbm0:1024k(bl2),512k(u-boot-env),2048k(Factory),2048k(fip),112M(ubi)` |
| `default`（原厂备选） | `nmbm0:1024k(bl2),512k(u-boot-env),2048k(Factory),2048k(fip),65536k(ubi),6144k(pdt_data),6144k(pdt_data_1),1024k(exp),38400k(plugin)` |

112M 布局逐项（NMBM 逻辑偏移）：

| 分区 | NMBM 逻辑地址 | 大小 |
|---|---|---|
| BL2 | `0x000000` | 1 MiB |
| u-boot-env | `0x100000` | 512 KiB |
| Factory | `0x180000` | 2 MiB |
| FIP | `0x380000` | 2 MiB |
| ubi | `0x580000` | 112 MiB |

系统侧设备树把 BL2、FIP 写成大写，启动链 mtdparts 写成 `bl2`、`fip`：只有大小写不同，
偏移与大小逐项相同。所有地址都是 **NMBM 逻辑地址**（逻辑设备 `nmbm0`），
不是物理 NAND 地址。

`default` 与 `immortalwrt-112m` 的 bl2、u-boot-env、Factory、fip 完全一致，差异只在
UBI 与其后的 OEM 区域：`ubi` 从 64 MiB 变成 112 MiB，`pdt_data`、`pdt_data_1`、
`exp`、`plugin` 被 UBI 回收。两张表推导出的逻辑末尾相差 2.5 MiB，这是**推导**值，
不是设备读数；真实 NMBM 可用容量取决于映射块数，可能更小。

因此**切换即数据损失**：切换到 `immortalwrt-112m` 之前必须完成**整片闪存**与每个
关键分区的只读**备份**并通过验收（见
[`nx30pro-firmware-install-and-validation.md`](nx30pro-firmware-install-and-validation.md)
与 [`FLASH.md`](FLASH.md)）。112M 布局本身无法还原这些区域。

## 4. 软件包兼容表

底座是 2021 年的 ImmortalWrt 21.02（Linux 5.4），近年的插件很多不在这一层。
下表逐项记录在锁定 commit 上**实际读到**的包、来源与状态，不按名称猜测。
状态与 `source-lock.json` 逐项一致：`available` 表示被授权的 `make defconfig` 探针（GitHub Actions run `46108752994`，artifact `nx30pro-firmware-defconfig-probe`，conclusion success）的
`probe/final.config` 里该包全部符号都是 `=y` 且审计无报错；`candidate` 表示
“只在锁定 feed 索引里读到了它”，没有 defconfig 证据就不得写成可用。

### 4.1 硬门禁（18 项）

| 需求 | 包 | 符号 | 来源 | 版本 | 状态 |
|---|---|---|---|---|---|
| LuCI 管理界面 | `luci` | `CONFIG_PACKAGE_luci` | luci feed | — | available |
| 界面 HTTPS | `luci-ssl-openssl` | `CONFIG_PACKAGE_luci-ssl-openssl` | luci feed | — | available |
| 简体中文界面 | `luci-i18n-base-zh-cn` | `CONFIG_PACKAGE_luci-i18n-base-zh-cn`、`CONFIG_LUCI_LANG_zh_Hans` | luci feed | — | available |
| Argon 主题 | `luci-theme-argon` | `CONFIG_PACKAGE_luci-theme-argon` | luci feed | 2.3.1 | available |
| Bootstrap 兜底主题 | `luci-theme-bootstrap` | `CONFIG_PACKAGE_luci-theme-bootstrap` | luci feed | — | available |
| 透明代理管理器（锁定 4.68） | `luci-app-passwall` | `CONFIG_PACKAGE_luci-app-passwall`、`..._INCLUDE_Xray`、`..._INCLUDE_Xray_Plugin` | luci feed | 4.68-1 | available |
| PassWall 代理内核 | `xray-core` | `CONFIG_PACKAGE_xray-core` | packages feed | 1.8.3 | available |
| PassWall 插件集 | `xray-plugin` | `CONFIG_PACKAGE_xray-plugin` | packages feed | 1.8.3 | available |
| DDNS 脚本 | `ddns-scripts` | `CONFIG_PACKAGE_ddns-scripts` | packages feed | 2.8.2 | available |
| DDNS 管理界面 | `luci-app-ddns` | `CONFIG_PACKAGE_luci-app-ddns` | luci feed | — | available |
| 异地组网 Tailscale | `tailscale` | `CONFIG_PACKAGE_tailscale` | packages feed | 1.32.3 | available |
| 异地组网 ZeroTier | `zerotier` | `CONFIG_PACKAGE_zerotier` | packages feed | 1.12.2 | available |
| ZeroTier 管理界面 | `luci-app-zerotier` | `CONFIG_PACKAGE_luci-app-zerotier` | luci feed | — | available |
| 容器引擎守护进程 | `dockerd` | `CONFIG_PACKAGE_dockerd` | packages feed | 20.10.26 | available |
| 容器命令行客户端 | `docker` | `CONFIG_PACKAGE_docker` | packages feed | 20.10.26 | available |
| 容器管理界面 | `luci-app-docker` | `CONFIG_PACKAGE_luci-app-docker` | luci feed | 1 | available |
| 容器存储驱动 | `fuse-overlayfs` | `CONFIG_PACKAGE_fuse-overlayfs` | packages feed | 1.7.1 | available |
| Argo 隧道 | `cloudflared` | `CONFIG_PACKAGE_cloudflared` | packages feed | 2023.8.1 | available |

PassWall 的后端只有 **Xray**（`INCLUDE_Xray` 与 `INCLUDE_Xray_Plugin` 两个开关），
版本正好是需求要求的 4.68（`PKG_VERSION:=4.68-1`）。`tailscale` 只有守护进程与命令行：
锁定的 luci feed 里没有 `luci-app-tailscale`，该缺口记在锁的 `unresolved`，
不用别的包冒充。

依赖闭包只对旧 Action 真正丢过的三个包做了完整静态枚举：`luci-app-passwall`（24 个
直接依赖）、`dockerd`（14 个）、`luci-ssl-openssl`（3 个），每一个都在
`dependency_index` 里有提供者、路径与锁定 commit（例如 `chinadns-ng` 2023.10.28、
`dns2socks` 2.1、`dns2tcp` 1.1.0、`microsocks` 1.0.3、`tcping` 0.3、`ipt2socks` 1.1.3、
`coreutils-base64`/`coreutils-nohup`、`libuci-lua`、`luci-compat`、`luci-lib-jsonc`、
`kmod-ipt-nat`、`iptables-mod-conntrack-extra`、`iptables-mod-tproxy`）。
其余条目 `dependencies` 为空，只校验 `provider_path`；这是 `dependency_closure_scope`
写明的范围，剩下的传递依赖由被授权的 `make defconfig` 探针兜住。

### 4.2 可选但必须尝试并上报（13 项）

| 需求 | 包 | 符号 | 来源 | 状态 |
|---|---|---|---|---|
| Cloudflare DDNS 提供者 | `ddns-scripts-cloudflare` | `CONFIG_PACKAGE_ddns-scripts-cloudflare` | packages feed | available |
| FRPC 内网穿透客户端 | `frpc` | `CONFIG_PACKAGE_frpc` | packages feed | available |
| 完整 dnsmasq 功能集 | `dnsmasq-full` | `CONFIG_PACKAGE_dnsmasq-full` | 主树 | available |
| SQM/QoS | `sqm-scripts` | `CONFIG_PACKAGE_sqm-scripts` | packages feed | available |
| 流量监控 | `nlbwmon` | `CONFIG_PACKAGE_nlbwmon` | packages feed | available |
| 网络唤醒 | `etherwake` | `CONFIG_PACKAGE_etherwake` | packages feed | available |
| 网页终端 | `ttyd` | `CONFIG_PACKAGE_ttyd` | packages feed | available |
| SFTP 服务 | `openssh-sftp-server` | `CONFIG_PACKAGE_openssh-sftp-server` | packages feed | available |
| 抓包（mini 变体） | `tcpdump-mini` | `CONFIG_PACKAGE_tcpdump-mini` | 主树 | available |
| 吞吐测量 | `iperf3` | `CONFIG_PACKAGE_iperf3` | packages feed | available |
| 路由诊断 | `mtr` | `CONFIG_PACKAGE_mtr` | packages feed | available |
| WireGuard 服务端 | `wireguard` | `CONFIG_PACKAGE_kmod-wireguard`、`CONFIG_PACKAGE_wireguard-tools` | — | UNRESOLVED |
| sing-box 后端 | `sing-box` | 无（锁定 feed 中不存在） | — | unavailable |

`nlbwmon` 没有 `PKG_VERSION`（只有 `PKG_RELEASE 3` 与 `PKG_SOURCE_VERSION`），
所以版本不可作为 semver 固定，锁里 `version` 为空。

**WireGuard 更正**：旧记录声称“5.4 内核没有 wireguard 模块”，这对 hanwckf 底座是
**错的**。锁定 commit 里有 `target/linux/generic/backport-5.4/080-wireguard-*`、
`package/kernel/linux/modules/netsupport.mk` 的 `KernelPackage/wireguard`
（`drivers/net/wireguard/wireguard.ko`）与 `wireguard-tools` 1.0.20210914。
但 `target/linux/generic/config-5.4` 出厂是 `# CONFIG_WIREGUARD is not set`，
能否为 mediatek/mt7981 构建出来没有证据，所以保持 UNRESOLVED，
未证明的包不得顺带进镜像。

### 4.3 刻意排除

| 包 | 理由 |
|---|---|
| `luci-app-homeproxy` | 设计未要求，锁定 luci feed 中不存在；PassWall 4.68 是唯一透明代理管理者 |
| `sing-box`、`luci-app-sing-box` | 设计未要求，锁定 feed 中不存在；记为 unavailable 而不是假装可用 |
| `luci-app-openclash` | **确实存在**于锁定 luci feed，必须显式关闭，否则会有第二个透明代理管理者 |
| `luci-app-passwall2` | 锁定 feed 中不存在；设计要求 PassWall 4.68，不是它的后继 |
| `luci-app-adguardhome` | 锁定 feed 中不存在，设计也未要求 |
| `luci-app-wireguard` | 存在于锁定 luci feed，`LUCI_DEPENDS:=+wireguard-tools +kmod-wireguard +luci-proto-wireguard`，选它会把两个未证明的 WireGuard 符号拉回来 |
| `tcpdump` | 完整版与 `tcpdump-mini` 安装同一个 `/usr/bin/tcpdump`，rootfs 组装时 `check_data_file_clashes` 失败；由 `CONFIG_PACKAGE_tcpdump-mini` 取代 |
| `dnsmasq` | `define Package/dnsmasq-full` 带 `PROVIDES:=dnsmasq`，两者安装同一个 `/usr/sbin/dnsmasq`；由 `CONFIG_PACKAGE_dnsmasq-full` 取代。`verify-config` 拒绝“关掉基线变体却丢了替代者”的最终配置，那会交付一台没有 DNS/DHCP 的路由器 |
| `luci-app-dockerman` | 与 `luci-app-docker` 并存的第二个容器管理入口；本底座的管理入口是 `luci-app-docker` |
| `ruby`、`libruby` | 拉起 host 端 Rust 自举编译，把构建推到 runner 时限之外；没有需求需要它 |

`tcpdump` 与 `dnsmasq` 两处 rootfs 冲突是仓库已记录的真实构建故障
（`.agents/skills/openwrt-firmware-config/SKILL.md`），设备层用显式
`# CONFIG_... is not set` 覆盖，`verify-config` 在最终 `.config` 上复查两个变体。

这一底座是 **firewall3**，不是 firewall4；`luci-app-firewall` 由主树与 luci feed 提供。

## 5. 所选系统对 OEM 分区的依赖（源码级冲突）

锁定 commit 的 `target/linux/mediatek/mt7981/base-files/etc/board.d/02_network`
在 `h3c,nx30pro` 分支（第 251 行）里：

```sh
wan_mac=$(mtd_get_mac_ascii pdt_data_1 ethaddr)
lan_mac=$(macaddr_add $wan_mac 1)
if [ "$(mtk_factory_get_byte "Factory" 4 2)" = "00-0c" ]; then
        local wifi_mac="$(macaddr_add $wan_mac 2)"
        mtk_facrory_write_mac "Factory" 4 $wifi_mac
fi
```

两个事实：底座的 WAN MAC 来源是 `pdt_data_1`，而 112M 布局**没有**这个分区；
底座还会在首启时把派生的 Wi-Fi MAC **写回** `Factory` 偏移 4。

设备补丁 `../patches/0002-mediatek-nx30pro-wan-mac-source.patch`（针对锁定 commit 重新
生成，旧的继承补丁因为行号变化无法应用）改变取值顺序：

1. `/etc/nx30pro/wan-mac`（部署时写入，**不进镜像**、不进 Git）；
2. `Factory` 分区的 ascii 键 `ethaddr`（**只读**）；
3. 仍存在的 `pdt_data_1`（只读，原厂布局的设备仍可读取）。

三者都取不到时，接口保留 bootloader 交下来的地址并记录日志，不从无到有派生 MAC。
补丁同时**移除**了上面那段对 `Factory` 的写入：出厂校准区在 112M 布局下只读。
代价是——如果某台设备的 `Factory` Wi-Fi MAC 字段真的是空（`00-0c`），它将保留空值
而不是原厂派生值，这只能靠真机比对确定，因此记为 UNRESOLVED。

`platform.sh` 的 `h3c,nx30pro` 走 `nand_do_upgrade`，与 112M 布局的 `ubi` 分区一致。

## 6. 首次启动默认值：所有非必要服务默认关闭

`../files/etc/uci-defaults/90-nx30pro-defaults` 保证设备层选中的每个服务都
**默认关闭**（`/etc/init.d/<name> disable` 加上各自的 enable 开关）：
`passwall` 与 `passwall_server`、`ddns`、`tailscale`、`zerotier`、`dockerd`、
`cloudflared`、`frpc`、`nlbwmon`、`ttyd`（上游默认开，必须显式关）、`sqm`、
`etherwake`。基线服务（`dnsmasq`、`network`、`firewall`、`system`、`dropbear`、
`uhttpd`、`luci`、`ucitrack`）一个都不碰。

边界：包不存在时 helper 返回 0；只 commit 自己改过的 UCI 包；值已正确时不写闪存；
脚本不删除自己（`/etc/init.d/boot` 只在返回 0 时删除它）；overlay 不附带任何
`/etc/config` 模板，因此仓库记录过的“整体替换 `/etc/config/network` 丢掉 `loopback`”
故障不会重现；只用镜像里真有的命令（`uci`、`mkdir`、`sed`、`echo`、`test`），
本底座 busybox 没有 `stat` 与 `od`。镜像里没有账号、节点、订阅、令牌、域名、
密码、密钥或任何设备的 MAC；部署值只在设备上写入。
运行行为全部 UNRESOLVED——这些是静态合同，不是设备观察结果。

## 7. 三种状态

| 状态 | 含义 | 当前 |
|---|---|---|
| 静态布局匹配 | 镜像分区合同与启动链合同逐项一致；补丁、镜像规则、配置层、overlay 有静态证据 | 已由源码、补丁与合同测试核实 |
| 候选构建完成 | 被授权的 Actions 用锁定源码与 feed 完成构建，产出两个镜像角色与完整证据 | **未触发**：`firmware_lock.py check` 退出 3 |
| 真机验证 | 启动、容量、MAC、`Factory`、服务行为都在设备上验证过 | **未授权、未执行** |

触发 `.github/workflows/build-nx30pro.yml`（只有 `workflow_dispatch`，
`permissions: contents: read`，不使用 Secrets）需要用户单独、明确的授权；
刷写同样需要单独授权。实际发生的验证只记录在
[`TEST-REPORT.md`](TEST-REPORT.md)，构建输入与门禁在 [`BUILD.md`](BUILD.md)，
刷写边界在 [`FLASH.md`](FLASH.md)，恢复设计在 [`RECOVERY.md`](RECOVERY.md)。

## 8. 仍然未决的项（UNRESOLVED）

与 `source-lock.json` 的 `unresolved` 一一对应：

1. 硬门禁的 `make defconfig` 证明（当前 `check` 退出 3，构建被阻止）；
2. 112M `profile` 与设备树的**构建**证据（只有静态补丁校验）；
3. 设备的 WAN MAC 取值；
4. 112M 布局下的 WAN MAC 读取路径与 `Factory` 校准数据（`pdt_data_1` 不存在）；
5. factory 与 sysupgrade 的最终**文件名**；
6. Linux 5.4 上的 WireGuard 服务端可构建性；
7. `luci-app-tailscale`（锁定 luci feed 中不存在）；
8. Go 类包（xray-core、xray-plugin、cloudflared、tailscale、docker、dockerd）在 21.02 工具链上的可构建性；
9. 容器**存储驱动**：`fuse-overlayfs` 在最终可写空间上的表现，不假定 overlay2 可用；
10. 镜像实际大小与剩余 **overlay** 空间；
11. 每个服务的**运行行为**（需带部署配置的真机测试）；
12. 设备的 **NAND** 型号、容量与坏块状态（112M 布局的逻辑容量是推导值，不是实测）。

在第 1、2、5 项完成前，本目录中的固件只能是“候选、未真机验证”；
在第 11、12 项完成前不得成对刷写。
