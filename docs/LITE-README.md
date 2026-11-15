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
| feed revisions | [`feeds/devices/tr3000-lite.lock`](../feeds/devices/tr3000-lite.lock) |

上游仓库说明其默认 U-Boot Mod profile 使用 112 MiB UBI；该 profile 不是 128 MiB 原厂布局，也不是 256 MiB profile。脚本会在构建前检查选中的 profile 和 DTS 值，偏离时立即失败。上游本身可能随时更新；工作流只使用表中的固定 commit，不跟踪可变分支。

## 包选择

[`configs/lite.seed`](../configs/lite.seed) 是覆盖上游配置的原生 OpenWrt `CONFIG_...` 差异，不是完整 `.config`。它保留构建基线并显式选择 LuCI 中文、HTTPS、Lite 专用 `luci-app-tr3000-lite`（网络 → 工业 LAN）、WireGuard、USB RNDIS/CDC-Ether、OpenSSH/SFTP、curl、CA、tcpdump、`ip-full`、`iputils-arping` 和提供 `ubinfo` 的 `ubi-utils`。固件 overlay 会预置空的 `ubihealthd` 配置，避免该包的一次性默认配置为健康监控自动生成启用项；本工作流只使用其只读信息工具。`scripts/configure-lite.sh` 合并差异后执行 `make defconfig`，并验证必需包和禁止包。

不预装 OpenClash、PassWall、sing-box、Tailscale、cloudflared、AdGuard Home、Docker、UPnP、Aurora 或 Bandix。`kmod-usb-net-ipheth` 默认不选；iPhone USB 共享还需要实际验证内核驱动、iOS 版本及用户态依赖（例如 usbmuxd），本构建不承诺兼容。

## 网络安全默认值

- `wan` 使用 DHCP Client，metric 10；不提供 DHCP relay。
- `plant` 是不桥接的独立逻辑接口，`eth1` 默认静态地址 **`192.168.10.254/24` 开机立即生效**，不是 DHCP Client。DHCPv4、DHCPv6、RA、NDP 服务均永久关闭。该地址不是通用现场地址：**LAN 接入工业 HUB 前必须人工确认地址未占用且网段适用**；不适用时保持 LAN 与 HUB 断开，先在隔离环境修改。
- `mgmt` 使用单独的 `br-mgmt` 和 `192.168.77.1/24` 管理地址，DHCP 池为 `192.168.77.100–192.168.77.149`。首次启动的 Lite defaults 脚本为实际检测到的每个无线设备创建一个始终启用的 WPA2-PSK (`psk2`) 管理 AP，SSID 为 `TR3000-Lite-<MAC 末六位大写十六进制>`；没有有效 MAC 时持久保存随机后缀。所有管理 AP 共用由 16 个随机字节生成的 32 位小写十六进制密钥；固件不含固定凭据，脚本不输出密钥。重复运行保留已有管理 SSID/密钥，不创建重复 AP；无无线设备、凭据不完整或提交/验证失败时保留 defaults 脚本以便重试。成功后才写入 `/etc/tr3000-lite/management-ap.initialized`。
- 防火墙默认拒绝转发，允许 `mgmt → wan`；默认还允许 `mgmt → 当前 plant CIDR` 的 ICMP Echo 和普通 TCP 单播，并 SNAT 为当前 plant 地址，因此 PLC/HMI 无默认网关也可回程。UDP、广播/组播发现和其他目标网段不放行。`plant` 不可主动访问 WAN、WireGuard 或 mgmt；WAN 不可访问管理面或工业网。plant 到路由器仅可按门禁启用 HTTPS 443，默认关闭，HTTP/SSH 不开放。
- WireGuard 接口、UDP listener 和工业远程访问默认关闭。没有密钥、PSK、VPS 地址或客户网段被写入固件。
- Lite 配置使用 `eth0`/`eth1` 作为 WAN/plant 的候选 Linux 设备名。上游 DTS 显示两个 MAC，但无法仅靠 DTS 确认机壳上的物理插孔角色；首次部署必须用 `ip link` 配合逐口插拔/链路灯做实机映射核验。若核验不符，不要连接现场网络或执行 `plant-profile.sh`。

## 首次配置与工业 LAN 变更

1. 在可信工位隔离上电，LAN 不接工业 HUB。先核验设备版本、布局和物理端口；默认 plant 地址已经生效，首次启动不会替操作员检查现场冲突。
2. 使用可信 UART/本地控制台设置非空 root 密码；AP defaults 成功后，从权限为 `0600` 的 `/etc/config/wireless` 私下读取随机 SSID/密钥，连接管理 AP，再访问 `https://192.168.77.1`。无法读取随机密钥时应回到控制台，不能假定存在通用 Wi-Fi 密码或首次有线 Web 登录。AP 初始化失败须修复无线发现/配置并重试，不能以绕过标记开启 plant Web 代替。
3. root 密码非空且 `/etc/tr3000-lite/management-ap.initialized` 存在后，才能在“网络 → 工业 LAN”启用 plant HTTPS。AP 初始化本身不开放 plant HTTPS。需要有线管理时，用隔离 PC 的同网段静态地址，先通过上述管理路径启用 HTTPS，之后访问 `https://192.168.10.254`；plant 不提供 DHCP，也不以 ping 响应作为 Web 可达判据。核验设备证书指纹；密钥和密码仅保留在设备/可信密码库，不进入日志或 Artifact。
4. 在“工业 LAN”页面填写地址/前缀并验证，通过后再应用。后端拒绝非法、网络号/广播地址、与 mgmt/活动路由重叠的地址、WAN 设备复用及 ARP 冲突/探测失败。当前地址是已配置地址时，重复应用仍会探测同网段其他主机；自动探测不能替代 HUB 接入前的人工确认。
5. 应用同时生成 network/firewall 配对备份，候选 `fw4 check` 通过后重载，再核验实际地址/路由/防火墙。失败时尽力恢复两个文件；这不是跨配置的 ACID 事务。页面提示当前会话可能断开，应保留控制台及管理 AP 恢复路径。
6. 人工确认当前 plant 地址未占用、网段正确且与上行不重叠后，再接入工业 HUB。变更 plant 地址后，mgmt 放行目标和 SNAT 同步更新；已有远端路由需另外核对，本里程碑不启用 WireGuard 工业访问。

控制台可使用固定后端（不要用旧 `plant-profile.sh` 绕过配对防火墙更新）：

```sh
/usr/sbin/tr3000-lite-plant status --json
/usr/sbin/tr3000-lite-plant validate --address 192.168.10.254/24
/usr/sbin/tr3000-lite-plant apply --address 192.168.10.254/24 --allow-luci true --allow-mgmt true
# 用 apply 返回的真实 backup_id 替换 BACKUP_ID：
/usr/sbin/tr3000-lite-plant restore --backup-id BACKUP_ID
```

备份目录 `/etc/tr3000-lite/backups` 仅 root 可读，最多保留五对已完成备份。检查返回 JSON 的 `checks`、`backup_id` 和 `rollback`；恢复 HTTPS 已启用的旧备份也必须通过当前 root/AP 门禁。若报告降级回滚或管理仍不可达，保持 HUB 断开，用控制台检查两个配置、接口和防火墙；不可把命令返回成功当作实际链路恢复。备份恢复不替代固件/Factory 分区备份。

## 上行和 WireGuard

固件包含轻量 `lite-uplink-watch` procd 服务：每 15 秒区分 netifd 接口状态和两个 IPv4 ping 探测结果；连续 3 次全部失败后将该出口默认路由 metric 暂时增加 1000，连续 2 次恢复后还原。WAN、STA、USB 的基础 metric 为 10/20/30；WAN 恢复会自动抢回优先级。实际无线 STA/USB 设备仍需安装人员核验并启用，默认逻辑接口为 `wwan`/`usbwan` 且不自动启动，不会猜测设备名。ICMP 探测只表示探测地址可达；若现场网络屏蔽 ICMP，应选择允许探测的目标，并验证失联、恢复、DNS 和路由收敛。

默认路由出口发生变化且 WireGuard 接口已启用时，服务会重启 `wg` 网络接口以触发重新握手；Peer 仍建议按现场 NAT 情况设置 `PersistentKeepalive = 25`。必须对真实上行切换做测试，不能把链路 up 等同于 VPS 可达。见[WireGuard/VPS 路由指南](WIREGUARD-VPS-ROUTING.md)。

管理 Wi-Fi 不桥接到 plant。首次部署必须在可信串口/本地控制台设置非空 root 密码，并从权限为 `0600` 的 `/etc/config/wireless` 读取该设备生成的管理 SSID/密钥；不要把密钥贴入日志或构建产物。AP 初始化本身不启用 plant HTTPS 或远程管理；控制器只有在非空 root 密码和 AP 初始化标记同时存在时才允许启用 plant HTTPS。首次启动无线设备发现、双频 AP 与 STA 共存、STA 断线期间管理 AP 持续可用、mgmt HTTPS/SSH 登录、plant HTTPS 门禁及 Linux 文件权限仍需真机验证。`wpad-openssl` 固定为必需包，最终配置拒绝其他 `wpad-*` 提供者。

## 构建与产物

GitHub Actions → **TR3000 Lite firmware** → Run workflow。工作流使用 Ubuntu 22.04、固定源码和 feed revisions；通过 `make defconfig`，最多 4 路并发编译，下载失败重试，编译并行失败时退回单线程。Artifacts 含 sysupgrade 镜像、SHA256、包清单、配置、源码提交、feed 锁定信息、上游许可证和构建日志，以及仅含公开默认值的 `lite-runtime-contract.txt`。构建脚本检查最终 `selected-packages.txt` 必须精确包含 `CONFIG_PACKAGE_luci-app-tr3000-lite=y`；契约记录接口/CIDR、HTTPS 门禁和 DHCP/访问/SNAT 策略，不包含无线密钥或密码，也不证明设备已启动。

仅接受路径 `bin/targets/mediatek/filogic/` 下文件名包含 `cudy_tr3000-v1-ubootmod` 的非空 `sysupgrade.bin`。它是系统升级镜像，不代表 Factory、BL2、FIP 或所有 U-Boot 刷写方式都兼容；不要用于未经确认的启动分区或跨布局保留旧配置升级。

当前 Windows 工作区只能运行仓库验证；固件编译由 Linux GitHub Runner 执行。除源码和配置校验外，本次没有执行真实固件构建、设备启动或联网测试。所有验收项见[测试计划](TEST-PLAN.md)，硬件相关项仍需真机执行。

## 工业现场限制

TIA Portal 对已知固定 IP 的常规三层单播通信可经路由/VPN 使用，但 PROFINET DCP、LLDP 和广播/多播发现不能直接跨越三层 WireGuard。远程 PLC 程序下载/变更属于高风险操作，必须有明确授权、现场安全联锁、变更窗口、现场人员确认和断线应对/回滚流程。
