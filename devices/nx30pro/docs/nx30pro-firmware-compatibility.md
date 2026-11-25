# NX30 Pro 固件兼容性核实记录

状态：**候选、未真机验证**。本文记录在锁定 commit 上核实到的构建事实与仍然未决的项。
本文不构成刷写许可，也不代表任何镜像可以在本机设备上工作。

- 设备：H3C Magic NX30 Pro（MT7981，SPI-NAND，112 MiB UBI 布局）。
- 系统源码：`jerryhan77/immortalwrt-mt798x`，锁定 commit
  `78cf22edddf07443d8f0506c9f361d3498475189`（`nx30pro-112m` 分支）。
- 机器可读锁文件：[`../source-lock.json`](../source-lock.json)。
- 配套启动链：[`nx30pro-uboot-compatibility.md`](nx30pro-uboot-compatibility.md)。

## 1. 源码与 feed 锁定

| 输入 | 仓库 | 锁定 revision | 分支（仅供追溯） |
|---|---|---|---|
| 系统源码 | `https://github.com/jerryhan77/immortalwrt-mt798x.git` | `78cf22edddf07443d8f0506c9f361d3498475189` | `nx30pro-112m` |
| packages feed | `https://github.com/immortalwrt/packages.git` | `c494d5269421c94090b56a971b9796c21f808a55` | `openwrt-21.02` |
| luci feed | `https://github.com/immortalwrt/luci.git` | `97b019be0a676c48ec2d804f0aace49cefcbb365` | `openwrt-21.02` |
| routing feed | `https://github.com/openwrt/routing.git` | `d79f2b57ebeddabe72f0a099e12aa81e9598adc5` | `openwrt-21.02` |
| telephony feed | `https://github.com/openwrt/telephony.git` | `920fbc5c0a2e4badf51bceff42e9a1e3eb693462` | `openwrt-21.02` |

feed revision 取的是**源码 commit 当日**的分支头，因此构建输入不会随分支漂移。
设备层不需要额外 feed：需求表里的软件包全部存在于这四个基础 feed 中。

## 2. 目标、profile 与镜像规则

| 项 | 值 | 来源 |
|---|---|---|
| target / subtarget | `mediatek` / `mt7981` | `target/linux/mediatek/Makefile` 的 `SUBTARGETS` |
| profile | `h3c_nx30pro_112M` | `target/linux/mediatek/image/mt7981.mk` |
| profile 符号 | `CONFIG_TARGET_mediatek_mt7981_DEVICE_h3c_nx30pro_112M=y` | 同上 |
| 设备树 | `mt7981-h3c-nx30pro-112M` | 同上 |
| 内核 | 5.4（`KERNEL_PATCHVER:=5.4`） | `target/linux/mediatek/Makefile` |
| 镜像上限 | `IMAGE_SIZE := 110592k`（108 MiB） | `mt7981.mk` |
| 块大小 / 页大小 | `BLOCKSIZE := 128k` / `PAGESIZE := 2048` | `mt7981.mk` |
| UBI 参数 | `UBINIZE_OPTS := -E 5`、`KERNEL_IN_UBI := 1` | `mt7981.mk` |
| 产物 | `factory.bin`（`append-ubi \| check-size`）、`sysupgrade.bin`（`sysupgrade-tar \| append-metadata`） | `mt7981.mk` |

`IMAGE_SIZE` 是**上限**而不是实测大小；112 MiB 的 UBI 分区为 108 MiB 的镜像上限留出约 4 MiB 余量。

## 3. 分区合同（与启动链一致）

| 分区 | NMBM 逻辑地址 | 大小 |
|---|---|---|
| BL2 | `0x000000` | 1 MiB |
| u-boot-env | `0x100000` | 512 KiB |
| Factory | `0x180000` | 2 MiB |
| FIP | `0x380000` | 2 MiB |
| ubi | `0x580000` | 112 MiB |

这份合同与启动链使用的合同**逐项相同**（见启动链文档第 4 节），
两边的偏移与大小都由 `mt7981-h3c-nx30pro-112M.dts` 决定。
所有地址都是 NMBM 逻辑地址，不是物理 NAND 地址。

## 4. 软件包兼容表

底座是 2021 年的 ImmortalWrt 21.02（内核 5.4），很多近几年的插件并不存在于这一层。
下表逐项记录**实际存在**的包、来源与 revision，不按名称猜测。

| 需求 | 包 / 符号 | 来源 | 状态 | 说明 |
|---|---|---|---|---|
| 透明代理 | `luci-app-passwall` 4.68-1（`CONFIG_PACKAGE_luci-app-passwall=y`） | luci feed | 可用 | 后端只有 **xray**；PassWall 4.68 的依赖（`chinadns-ng`、`dns2socks`、`dns2tcp`、`microsocks`、`tcping`、`ip-full`、`ipset`、`ipt2socks` 等）在本层都存在 |
| 代理内核 | `xray-core`、`xray-plugin` | packages feed | 可用 | `CONFIG_PACKAGE_luci-app-passwall_INCLUDE_Xray=y` |
| sing-box | 无 | — | **不可用** | 21.02 的 packages feed 没有 sing-box，且新版本需要 21.02 底座没有的 Go 工具链。需求以 xray 满足并记录差异，不再引入第二个代理管理器 |
| 云隧道 | `cloudflared` | packages feed | 可用 | 该层没有 LuCI 界面，令牌与隧道在部署时配置，服务默认不启动 |
| DDNS | `ddns-scripts` + `luci-app-ddns` | packages + luci feed | 可用 | 该层的 provider 脚本在 `ddns-scripts` 内部；服务商与域名部署时录入 |
| 异地组网 | `tailscale` | packages feed | **部分** | 有守护进程与命令行，21.02 的 luci feed 没有 `luci-app-tailscale` |
| 异地组网 | `zerotier` + `luci-app-zerotier` | packages + luci feed | 可用 | |
| VPN 服务端 | `luci-app-wireguard` + `wireguard-tools` | luci feed + 主树 | **不可用** | 用户态工具在，但 5.4 内核没有 wireguard 模块，feed 也没有 `wireguard-go`，因此内核模式服务端无法实现；该需求保持未决 |
| 容器引擎 | `docker`、`dockerd`、`containerd`、`runc`、`fuse-overlayfs`、`luci-app-docker`、`luci-lib-docker` | packages + luci feed | 可用 | 存储驱动使用 `fuse-overlayfs`，**不假定 overlay2 可用** |
| 界面主题 | `luci-theme-argon`、`luci-theme-bootstrap` | luci feed | 可用 | |
| 中文界面 | `luci-i18n-*-zh-cn` | luci feed（各应用 `po/zh_Hans`） | 可用 | 覆盖 base、ddns、docker、firewall、passwall、zerotier |
| 防火墙 | firewall3 + `luci-app-firewall` | 主树 + luci feed | 可用 | 这一底座是 **firewall3**，不是 firewall4 |

**刻意排除**（理由记在源码锁的 `excluded_packages`）：`sing-box`、`luci-app-openclash`
（PassWall 是唯一透明代理管理者）、`luci-app-wireguard`、`wireguard-tools`（无内核支持）、
`ruby`/`libruby`（会拉起 Rust 工具链并把构建拖到 runner 上限）、
`luci-app-dockerman`（本层的容器管理入口是 `luci-app-docker`）。

## 5. 所选系统对 OEM 分区的依赖（源码级冲突）

底座的 `target/linux/mediatek/mt7981/base-files/etc/board.d/02_network` 在 `h3c,nx30pro` 分支里：

```sh
wan_mac=$(mtd_get_mac_ascii pdt_data_1 ethaddr)
lan_mac=$(macaddr_add $wan_mac 1)
if [ "$(mtk_factory_get_byte "Factory" 4 2)" = "00-0c" ]; then
        local wifi_mac="$(macaddr_add $wan_mac 2)"
        mtk_facrory_write_mac "Factory" 4 $wifi_mac
fi
```

112M 布局没有 `pdt_data_1` 分区（那块空间划进了 112 MiB 的 UBI），所以底座在这里读不到 WAN MAC。
设备补丁 `devices/nx30pro/patches/0001-mediatek-nx30pro-wan-mac-source.patch` 改变取值顺序：

1. `/etc/nx30pro/wan-mac`（部署时写入，**不进入镜像**）；
2. `Factory` 分区的 ASCII 键 `ethaddr`；
3. 仍存在时的 `pdt_data_1`（原厂布局的设备仍可读取）。

三者都取不到时，接口保留 bootloader 交给的地址，不再写入错误的 MAC，
也不改写 `Factory`；只有拿到真实 WAN MAC 时才保留底座原有的 `Factory` 派生写入行为。

## 6. 首次启动默认值

`devices/nx30pro/files/etc/uci-defaults/90-nx30pro-defaults` 保证：
PassWall、DDNS、Tailscale、ZeroTier、Docker 全部处于关闭状态；
云隧道没有配置文件就不会启动；WAN 区不开放路由器自身端口。
镜像里没有账号、订阅、节点、令牌或凭据。

## 7. 三种状态

| 状态 | 含义 | 当前 |
|---|---|---|
| 编译通过 | Actions 用锁定的源码与 feed 完成构建并产出镜像 | 待 Actions 运行给出 |
| 静态布局匹配 | 镜像的分区合同与启动链合同逐项一致 | 已由源码与设备树核实 |
| 本机验证通过 | 真机启动、容量、MAC、服务行为都验证过 | **未完成** |

在第三项完成前，本目录中的固件只能标记为“候选、未真机验证”。

## 8. 仍然未决的项（UNRESOLVED）

1. 设备的 WAN MAC 取值 —— 需在原厂布局上读取 `ethaddr` 并在部署时写入 `/etc/nx30pro/wan-mac`；
2. WireGuard 服务端 —— 5.4 底座没有内核模块，需要更新的内核或用户态实现；
3. sing-box 后端 —— 需要能在本底座工具链上构建的 feed revision；
4. Tailscale 的 LuCI 管理界面 —— 需要既新又与 21.02 兼容的 luci revision；
5. 容器存储驱动 —— 需在真机最终可写空间上验证 `fuse-overlayfs`；
6. 镜像实际大小与剩余 overlay 空间 —— 由首次成功构建的报告与真机测试给出；
7. 每个服务的运行行为 —— 需带部署配置的真机测试。
