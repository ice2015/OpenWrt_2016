# TR3000-Lite 工业远程维护版

本目录为独立的 Lite 构建，不改变通用多设备构建清单。目标为 Cudy TR3000 v1、128 MiB NAND、MT7981，采用上游 `cudy_tr3000-v1-ubootmod` 设备 profile 的 **112 MiB UBI** 布局。

## 已核验的构建输入

| 项目 | 固定值 |
| --- | --- |
| 设备构建配置和许可证 | [`weekdaycare/immortalwrt-mt7981-cudy-tr3000`](https://github.com/weekdaycare/immortalwrt-mt7981-cudy-tr3000)，commit `cc777dfa3c1964518ddb2c310e8570830b11e954` |
| OpenWrt/ImmortalWrt 源码 | [`padavanonly/immortalwrt-mt798x-6.6`](https://github.com/padavanonly/immortalwrt-mt798x-6.6)，commit `ec9ef10efc65da1e6d1de4e2c043c0e13d08eed8` |
| 设备基线 | 上游 `config/128muboot.config` |
| profile | `cudy_tr3000-v1-ubootmod` |
| UBI DTS | `target/linux/mediatek/dts/mt7981b-cudy-tr3000-v1-ubootmod.dts`，`reg = <0x5c0000 0x7000000>` |
| feed revisions | [`devices/tr3000/lite/feeds.lock`](feeds.lock) |

上游仓库说明其默认 U-Boot Mod profile 使用 112 MiB UBI；该 profile 不是 128 MiB 原厂布局，也不是 256 MiB profile。脚本会在构建前检查选中的 profile 和 DTS 值，偏离时立即失败。上游本身可能随时更新；工作流只使用表中的固定 commit，不跟踪可变分支。

## 包选择

[`devices/tr3000/lite/config.seed`](config.seed) 是覆盖上游配置的原生 OpenWrt `CONFIG_...` 差异，不是完整 `.config`。它保留构建基线并显式选择 LuCI 中文、HTTPS、Lite 专用 `luci-app-tr3000-lite`（网络 → 工业 LAN）、WireGuard、USB RNDIS/CDC-Ether、OpenSSH/SFTP、curl、CA、tcpdump、`ip-full`、`iputils-arping`、提供 `ubinfo` 的 `ubi-utils`，以及提供 `stat` 的 `coreutils-stat`（OpenWrt busybox 不含 `stat`/`od` applet，控制器的属主/权限门禁依赖它；随机数改用 busybox 自带的 `head`+`sha256sum`）。固件 overlay 会预置空的 `ubihealthd` 配置，避免该包的一次性默认配置为健康监控自动生成启用项；本工作流只使用其只读信息工具。`devices/tr3000/build/configure-lite.sh` 合并差异后执行 `make defconfig`，并验证必需包和禁止包。

不预装 OpenClash、PassWall、sing-box、Tailscale、cloudflared、AdGuard Home、Docker、UPnP、Aurora 或 Bandix。`kmod-usb-net-ipheth` 默认不选；iPhone USB 共享还需要实际验证内核驱动、iOS 版本及用户态依赖（例如 usbmuxd），本构建不承诺兼容。

## 网络安全默认值

- `wan` 使用 DHCP Client，metric 10；不提供 DHCP relay。
- `loopback` 接口（`lo`，`127.0.0.1/8`）必须保留：路由器自身的解析器指向 `127.0.0.1` 的 dnsmasq，缺少它时设备无法解析任何域名，NTP 不同步、时钟停在构建日期、TLS 下载报证书“尚未生效”，软件包管理器全部失败（2026-11-24 真机确认）。构建脚本在编译前断言该段存在。
- `lan` 是出厂的接入段：`br-lan`（成员 `eth1` 与管理 AP），路由器地址 **`192.168.10.1/24`**，DHCP 池 `192.168.10.100–192.168.10.249`。插线或连 WiFi 即拿到地址、可 ping 通、可进 `https://192.168.10.1`。工厂设备只有一个 LAN 口，它默认属于接入段而不是工业段。
- `plant` 是不桥接的工业段接口，**默认不启用**（`proto none`，不绑定 `eth1`）。只有操作员在「网络 → TR3000 Lite → 工业 LAN」显式「启用 plant 模式」后，`eth1` 才从 `br-lan` 摘出交给 plant，默认静态地址 **`192.168.20.254/24`**。DHCPv4、DHCPv6、RA、NDP 服务在 plant 段永久关闭。接入工业 HUB 前必须人工确认地址未占用且网段适用。
- 首次启动的 Lite defaults 脚本为实际检测到的每个无线设备创建一个始终启用的 WPA2-PSK (`psk2`) 管理 AP，SSID 为 `TR3000-Lite-<MAC 末六位大写十六进制>`；没有有效 MAC 时持久保存随机后缀。所有管理 AP 共用由 16 个随机字节生成的 32 位小写十六进制密钥；固件不含固定凭据，脚本不输出密钥。重复运行保留已有管理 SSID/密钥，不创建重复 AP；无无线设备、凭据不完整或提交/验证失败时保留 defaults 脚本以便重试。成功后才写入 `/etc/tr3000-lite/management-ap.initialized`。无线栈是 mt_wifi：驱动每次重建无线配置可能带出它自己的开放默认 AP，`/etc/init.d/tr3000-lite-wifi` 每次启动都会检查并重新禁用它，同时补齐受管 AP。
- 防火墙默认拒绝转发，允许 `lan → wan`；默认还允许 `lan → 当前 plant CIDR` 的 ICMP Echo 和普通 TCP 单播，并 SNAT 为当前 plant 地址，因此 PLC/HMI 无默认网关也可回程。UDP、广播/组播发现和其他目标网段不放行。`plant` 不可主动访问 WAN、WireGuard 或接入段；WAN 不可访问管理面或工业网。plant 到路由器仅可按门禁启用 HTTPS 443，默认关闭，HTTP/SSH 不开放。
- WireGuard 接口、UDP listener 和工业远程访问默认关闭。没有密钥、PSK、VPS 地址或客户网段被写入固件。
- Lite 配置使用 `eth0`/`eth1` 作为 WAN/plant 的候选 Linux 设备名。上游 DTS 显示两个 MAC，但无法仅靠 DTS 确认机壳上的物理插孔角色；首次部署必须用 `ip link` 配合逐口插拔/链路灯做实机映射核验。若核验不符，不要连接现场网络或执行 `plant-profile.sh`。

## 首次配置与工业 LAN 变更

详细的接入与切换手册见 [TR3000-Lite 接入段与工业模式](../docs/TR3000-LITE-LAN-ACCESS.md)。

1. 在可信工位隔离上电，LAN 口先不接工业 HUB。先核验设备版本、布局和物理端口。
2. 插网线或连管理 AP，PC 拿到 `192.168.10.x`；`ping 192.168.10.1` 通，浏览器打开 `https://192.168.10.1` 设置非空 root 密码。需要 Wi-Fi 时，从权限为 `0600` 的 `/etc/config/wireless` 私下读取随机 SSID/密钥；固件不含固定凭据，也不能假定存在通用 Wi-Fi 密码。
3. 在“工业 LAN”页面点「启用 plant 模式」把唯一 LAN 口交给工业段。后端会校验地址、生成 network/firewall 配对备份、候选 `fw4 check` 通过后重载并核验实况，失败尽力回滚。切换前必须确认管理 AP 已就绪（交出有线口后管理路径只剩 WiFi）。plant 段不提供 DHCP，也不以 ping 响应作为 Web 可达判据；核验设备证书指纹，密钥和密码仅保留在设备/可信密码库。
4. 在“工业 LAN”页面填写 plant 地址/前缀并验证，通过后再应用。后端拒绝非法、网络号/广播地址、与接入段/活动路由重叠的地址、WAN 设备复用及 ARP 冲突/探测失败。当前地址是已配置地址时，重复应用仍会探测同网段其他主机；自动探测不能替代 HUB 接入前的人工确认。
5. 人工确认当前 plant 地址未占用、网段正确且与上行不重叠后，再接入工业 HUB。变更 plant 地址后，接入段放行目标和 SNAT 同步更新；已有远端路由需另外核对，本里程碑不启用 WireGuard 工业访问。需要退回时点「退回接入模式」，有线口立刻恢复 DHCP。

控制台可使用固定后端（不要用旧 `plant-profile.sh` 绕过配对防火墙更新）：

```sh
/usr/sbin/tr3000-lite-plant status --json
/usr/sbin/tr3000-lite-plant validate --address 192.168.20.254/24
/usr/sbin/tr3000-lite-plant enable-plant --address 192.168.20.254/24
/usr/sbin/tr3000-lite-plant disable-plant
/usr/sbin/tr3000-lite-plant apply --address 192.168.20.254/24 --allow-luci true --allow-mgmt true
# 用 apply 返回的真实 backup_id 替换 BACKUP_ID：
/usr/sbin/tr3000-lite-plant restore --backup-id BACKUP_ID
```

备份目录 `/etc/tr3000-lite/backups` 仅 root 可读，最多保留五对已完成备份。检查返回 JSON 的 `checks`、`backup_id` 和 `rollback`；恢复 HTTPS 已启用的旧备份也必须通过当前 root/AP 门禁。若报告降级回滚或管理仍不可达，保持 HUB 断开，用控制台检查两个配置、接口和防火墙；不可把命令返回成功当作实际链路恢复。备份恢复不替代固件/Factory 分区备份。

## 上行和 WireGuard

### 可选 Wi-Fi Client：只使用标准 LuCI 配置

“工业 LAN”页面提供标准“网络 → 无线”和“网络 → 接口”的入口，不增加接收 Wi-Fi 密码的自定义 shell/RPC 控制器。无 Client 时为 AP-only，加入热点后为 AP+Client；Client 断线或删除其配置不应删除管理 AP。固件不创建默认 STA，也不自动扫描连接未知或开放热点。

在标准无线页面扫描并人工选择**已明确批准的加密热点**，使用 `wwan` 网络并分配到 `wan` 防火墙 zone。**不要勾选“Replace wireless configuration / 替换无线配置”**，该上游选项会删除同一射频上的现有 AP；不要删除管理 AP 或禁用其 radio。随后在标准接口页面为 `wwan` 启用“开机自动运行”，保存并应用；预置 `wwan` 为 DHCP、metric 20、`auto=0`，标准 Join 只绑定接口，不会清除现有 `auto=0`。撤除 STA 时仅删除 Client section，需要时停用 `wwan`，保留管理 AP 与 radio。

优先选择不同射频承载 AP 和 Client；不根据 `radio0`/`radio1` 名字猜测频段。共用射频时，AP 信道跟随 STA，扫描、漫游或重连可能短暂中断管理连接，不保证 RF 无间断。多个已批准热点可通过标准页面保存，密钥仅保留在设备私有配置；此阶段不实现自动选择未知热点或自动轮换已保存热点的功能。若操作者故意选择开放网络，须先确认风险，本项目默认部署不允许这样做。“网络 → TR3000 Lite → Multi-uplink status”显示实际 radio、PHY、运行信道和共享射频警告；未知信道不根据配置值或 radio 名字猜测。本段不构成已通过真机并发验证的声明。

### USB 4G：只自动接管已支持的 USB Ethernet

默认只支持由设备自身完成 SIM/APN/蜂窝拨号、表现为 `rndis_host` 或 `cdc_ether` 普通 USB 网卡并提供 DHCP 的路由棒。热插拔根据真实 sysfs USB 父设备和驱动识别，不猜 `usb0`；PCI/虚拟网卡、NCM、QMI、MBIM、传统串口拨号不在默认范围。自动绑定后启用 `usbwan`；拔出后仅清理本模块拥有的绑定，不抢占 WAN、plant、lan、wwan 或手工接管的接口。

同时出现两台受支持候选设备时，自动路径失败关闭，不会任选第一台；移除多余设备后重试。确需保留多台时必须先由管理员显式规划和手工接管接口，不能依靠自动选择。热插拔事件使用锁；遇到正在应用的工业 LAN 事务时会等待或暂缓，守护进程每轮再做幂等 USB 重扫，避免一次事件遗漏后永远不能恢复。USB 诊断显示驱动、VID/PID、绑定或歧义/阻止状态，不输出 SIM、密码或密钥。

### 健康检查、优先级和只读状态

Lite 专用 `lite-uplink-watch` procd 服务与 Full 的旧共享实现隔离。`wan → wwan → usbwan` 的固定基础 metric 为 `10/20/30`；每轮对各接口配置的 IPv4 目标执行 ICMP 探测，任一目标成功即算该轮成功。默认连续 **3 个失败轮次**把该出口默认路由 metric 增加 1000，连续 **2 个成功轮次**恢复；优先级较高的健康出口恢复后重新优先。配置 `/etc/config/lite-uplink-watch` 的 `globals` 可调整失败/恢复轮数（1–100）及轮间休眠（15–300 秒），每接口最多 8 个有效 IPv4 探测目标。轮次还包含探测/重载耗时，不能把 3 轮误认为固定 45 秒。配置被拒绝时，不改动路由或推进健康计数，页面显示重协调失败而不是沿用无警告的旧正常状态；修正配置后再清除错误。守护进程只使用已验证的休眠间隔，配置错误也不会突破 15 秒最小重试间隔。

接口状态、DHCP 地址/网关和 Internet 探测分别显示。无默认路由/有效网关时标为不可用；ICMP 被阻断的可用网络应选现场允许的备用目标，不会自动猜测公共服务。守护进程在 DHCP 续租和应用前后重读 netifd 数据，原子保存状态并按精确设备/网关/源地址/metric 记录清理自己的临时路由，不盲删全部默认路由。已有更优或等优外部默认路由不被改动，页面会警告并不宣称本模块选定了实际出口；不支持的策略/多路径路由配置须管理员检查，不能依靠本模块重写。

只读“Multi-uplink status”页显示接口、netifd link、地址/网关、基础/有效 metric、健康状态、活动出口、USB 信息及 AP/STA 的实际 radio/PHY/信道。手动“Refresh status”获取新快照；空白/未知值、状态文件缺失、重协调失败或通知失败都有明确提示。该页不接受 Wi-Fi 密码、不授予任意文件权限，也不改变网络。控制台只读入口为 `/usr/sbin/tr3000-lite-uplink-status --json`；`/usr/sbin/lite-uplink-watch reconcile` 可触发一轮健康重协调。

稳定出口切换后，发送受限的 `tr3000-lite.uplink-changed` 通知，并由上行监听器触发双 WireGuard 重新同步与 Cloudflare DDNS 协调。双通道部署、分阶段入网预配与客户端安全指南见：
- [TR3000-Lite 预配与入网规范](../docs/TR3000-LITE-PROVISIONING.md)
- [TR3000-Lite 双通道远程访问运维指南](../docs/TR3000-LITE-REMOTE-ACCESS.md)
- [WireGuard/VPS 路由指南](../docs/WIREGUARD-VPS-ROUTING.md)

管理 Wi-Fi 不桥接到 plant。首次部署必须在可信串口/本地控制台设置非空 root 密码，并从权限为 `0600` 的 `/etc/config/wireless` 读取该设备生成的管理 SSID/密钥；不要把密钥贴入日志或构建产物。AP 初始化本身不启用 plant HTTPS 或远程管理；plant HTTPS 的门禁是非空 root 密码加操作员显式启用，而管理 AP 的就绪状态守卫“交出唯一 LAN 口”这一步。首次启动无线设备发现、双频 AP 与 STA 共存、STA 断线期间管理 AP 持续可用、接入段 HTTPS/SSH 登录、工业模式切换实况、plant HTTPS 门禁及 Linux 文件权限仍需真机验证。`wpad-openssl` 固定为必需包，最终配置拒绝其他 `wpad-*` 提供者。

## 真机发现的问题与本版修复（2026-11-24）

基准固件 `55f42c4` 刷入真机后逐项验证，发现以下静态测试看不见的问题，均已在下一版固件修复并在同一台设备上验证修复有效：

| # | 问题 | 修复 | 真机验证 |
| --- | --- | --- | --- |
| 1 | overlay 缺 `loopback` 接口 → 设备 DNS/NTP/TLS 全灭，`opkg update` 全部失败 | overlay 补回 loopback 段；构建前断言 | `lo` UP 后 dnsmasq 绑定 127.0.0.1:53，NTP 同步，6 个 feed 全部签名校验通过 |
| 2 | 镜像无 `stat`/`od`（busybox 不含），plant 控制器与 AP 脚本在真机必然失败 | seed 选 `coreutils-stat`；`od` 改用 `head`+`sha256sum` | `opkg install coreutils-stat` 后控制器门禁正常；修补后 AP 脚本退出 0 |
| 3 | `uci commit` 留下的 0 字节 `/tmp/.uci/<pkg>` 被误判为待提交修改，AP 初始化与 plant 事务从未成功 | 改用 `[ ! -s ]` 只拒绝非空 delta | 空 delta 走到地址校验；非空 delta 仍拒绝；配置不变 |
| 4 | 管理 AP 未建立，设备广播两个开放热点（`ImmortalWrt-2.4G/5G`，绑在带 DHCP 的 lan） | 问题 2/3 修复后首启脚本正常执行 | 两个开放 AP 被禁用，生成 `TR3000-Lite-<MAC>` WPA2 受管 AP，就绪标记写入 |
| 5 | openssh-server 默认 `PermitRootLogin prohibit-password`，LuCI 设的 root 密码无法 SSH；LuCI SSH 页面因依赖 dropbear 被隐藏 | overlay 增加 sshd drop-in（`PermitRootLogin yes`） | 密码 SSH 登录成功；LuCI 的 dropbear 专属页面仍隐藏（上游行为，OpenSSH 密钥管理页为后续项） |
| 6 | Full 时代遗留脚本（`plant-profile.sh` 等）与死配置 `/etc/config/tr3000-lite` 随 Lite 镜像下发 | Lite 不再安装这些脚本；删除死配置；构建断言 | 静态审计测试锁定 |

配套新增 `tests/structure/test_lite_device_readiness.py`：以从已验证镜像导出的命令清单（`tests/structure/lite-image-commands.txt`）审计所有随镜像脚本的工具调用，并锁定 loopback、空 delta 语义、sshd drop-in 与产物仓库。真机验收新增 T11–T15，见[测试计划](../docs/TEST-PLAN.md)。

## 软件包来源（opkg）

- 镜像预置的 `24.10-SNAPSHOT` 公共镜像源**不可依赖**：snapshot 会被镜像站定期清理，且与固定 revision 构建的镜像存在版本/ABI 漂移。修复 loopback 后公共源可用（真机实测 6 个 feed 签名校验通过），但仅作为应急手段。
- 正式来源是**本次构建自身生成的仓库**：artifact 的 `package-repo/arch/<feed>`、`package-repo/target` 与签名公钥 `key-build.pub`。启用方式与 Full 相同：内网 HTTP 提供仓库 → 改写 `/etc/opkg/distfeeds.conf` → 公钥按 usign 约定（base64 解码后 bytes[2:10] 的 hex）放入 `/etc/opkg/keys/<keyid>` → `opkg update`，`check_signature` 保持开启。详见 [Full 说明的对应章节](../full/README.md)。

## SSH 访问

Lite 使用 `openssh-server`（排除 dropbear）。OpenSSH 默认拒绝 root 密码登录，固件通过 `/etc/ssh/sshd_config.d/99-tr3000-lite.conf` 显式允许 `PermitRootLogin yes` 与 `PasswordAuthentication yes`；root 密码本就是 Lite 的强制门禁（plant HTTPS 与远程访问都要求非空）。首次部署仍应在可信工位设置强口令。LuCI 自带的 SSH-Keys/SSH Access 页面依赖 dropbear，在本固件中隐藏；OpenSSH 的密钥管理需通过控制台或后续专用页面，不要向 `/etc/dropbear/authorized_keys` 写密钥（无效）。

## 构建与产物

GitHub Actions → **TR3000 Lite firmware** → Run workflow。工作流使用 Ubuntu 22.04、固定源码和 feed revisions；通过 `make defconfig`，最多 4 路并发编译，下载失败重试，编译并行失败时退回单线程。Artifacts 含 sysupgrade 镜像、SHA256、包清单、配置、源码提交、feed 锁定信息、上游许可证和构建日志，以及仅含公开默认值的 `lite-runtime-contract.txt`。构建脚本检查最终 `selected-packages.txt` 必须精确包含 `CONFIG_PACKAGE_luci-app-tr3000-lite=y`，还检查镜像实际包清单含 Lite LuCI、`wpad-openssl` 和三项 USB 网卡包，不含 Ruby/libruby 或额外 USB 网卡类型。`image-packages.manifest` 是该 profile 的完整已安装包/版本清单，`packages-manifest.txt` 是其包名视图；可选 `target-package-index.txt` 只是目标专属软件仓库索引，不能替代镜像清单。`profile.dts` 保存最终验证的 112 MiB 源码布局。契约记录公开接口/CIDR、HTTPS/DHCP/SNAT 策略、上行顺序/阈值、USB 驱动和安装路径，不包含无线密钥或密码，也不证明设备已启动。

仅接受路径 `bin/targets/mediatek/filogic/` 下文件名包含 `cudy_tr3000-v1-ubootmod`、不超过 100 MiB、可读 tar 且含正确 `CONTROL` 入口的非空 `sysupgrade.bin`。它是系统升级镜像，不代表 Factory、BL2、FIP 或所有 U-Boot 刷写方式都兼容；不要用于未经确认的启动分区或跨布局保留旧配置升级。

固件编译由 Linux GitHub Runner 执行；本地可在 Linux/WSL2 编译，原生 Windows 只用于编辑和仓库验证。

**当前基准固件**：提交 `55f42c4`（`feature/tr3000-lite-factory-access`）的 [Actions 44449317194](https://github.com/ice2015/OpenWrt_2016/actions/runs/44449317194) 已成功（耗时 1h 25m 37s），产物 `tr3000-lite-128m-ubootmod-112m`，sysupgrade 镜像 20 747 077 字节，SHA256 `e761cb00ffbd3c1b607d046fb2a78cde78f0a29bf06833d00ee4fd4a7a8b9d76`。下载后解包 `root` 分区逐项核对通过：

1. `/etc/config/network` 含 `config interface 'lan'`、`option ipaddr '192.168.10.1'`、`config device 'br_lan'`、`list ports 'eth1'`，`plant` 段为 `proto 'none'` 且**不绑定** `eth1`；
2. `/etc/config/dhcp` 含 `config dhcp 'lan'`、`option limit '150'`、`option dhcpv4 'server'`；
3. 镜像内**不存在** `/etc/config/wireless`；
4. `lite-runtime-contract.txt` 为 `schema_version=2`、`lan_cidr=192.168.10.1/24`、`wireless_stack=mt_wifi`、`management_ap_network=lan`、`plant_default_mode=inactive`；
5. `image-packages.manifest` 含 `luci-app-tr3000-lite` 与 `wpad-openssl`，USB 网卡包恰为 `kmod-usb-net`、`kmod-usb-net-rndis`、`kmod-usb-net-cdc-ether` 三项，不含 Ruby/libruby；
6. `profile.dts` 为 `reg = <0x5c0000 0x7000000>` 的 112 MiB UBI 布局，tar `CONTROL` 为 `cudy_tr3000-v1-ubootmod`；
7. `/usr/sbin` 下 8 个 Lite 控制器、`/usr/lib/tr3000-lite` 下 8 个库/事件脚本、3 个 `init.d` 服务与 3 个 LuCI 视图均在镜像内；无线栈为 mt_wifi（`kmod-mt_wifi`、`mtwifi-cfg`、`wifi-scripts`），无 mac80211/mt7915e。

该基准只证明**构建产物内容正确**，不证明设备已启动、DHCP 实际交付、RF 可用或路由切换正确。更早的 [Actions 43731565747](https://github.com/ice2015/OpenWrt_2016/actions/runs/43731565747)（第一阶段 `012dfec`）仅作历史记录，不再是当前提交的构建证明。每次新里程碑必须检查对应提交的新构建和产物；设备启动、物理端口、联网、射频并发、真实路由切换及可写 overlay 余量仍待真机验证。所有验收项见[测试计划](../docs/TEST-PLAN.md)。

## 工业现场限制

TIA Portal 对已知固定 IP 的常规三层单播通信可经路由/VPN 使用，但 PROFINET DCP、LLDP 和广播/多播发现不能直接跨越三层 WireGuard。远程 PLC 程序下载/变更属于高风险操作，必须有明确授权、现场安全联锁、变更窗口、现场人员确认和断线应对/回滚流程。
