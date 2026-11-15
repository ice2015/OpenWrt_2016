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

[`configs/lite.seed`](../configs/lite.seed) 是覆盖上游配置的原生 OpenWrt `CONFIG_...` 差异，不是完整 `.config`。它保留构建基线并显式选择 LuCI 中文、HTTPS、WireGuard、USB RNDIS/CDC-Ether、OpenSSH/SFTP、curl、CA、tcpdump、`ip-full`、`iputils-arping` 和提供 `ubinfo` 的 `ubi-utils`。固件 overlay 会预置空的 `ubihealthd` 配置，避免该包的一次性默认配置为健康监控自动生成启用项；本工作流只使用其只读信息工具。`scripts/configure-lite.sh` 合并差异后执行 `make defconfig`，并验证必需包和禁止包。

不预装 OpenClash、PassWall、sing-box、Tailscale、cloudflared、AdGuard Home、Docker、UPnP、Aurora 或 Bandix。`kmod-usb-net-ipheth` 默认不选；iPhone USB 共享还需要实际验证内核驱动、iOS 版本及用户态依赖（例如 usbmuxd），本构建不承诺兼容。

## 网络安全默认值

- `wan` 使用 DHCP Client，metric 10；不提供 DHCP relay。
- `plant` 作为不桥接的独立逻辑接口，默认无 IP、无 DHCP Client/Server；DHCPv4、DHCPv6、RA、NDP 均关闭。
- `mgmt` 使用单独的 `br-mgmt` 和 `192.168.77.1/24` 管理地址。首次启动的 Lite defaults 脚本为实际检测到的每个无线设备创建一个始终启用的 WPA2-PSK (`psk2`) 管理 AP，SSID 为 `TR3000-Lite-<MAC 末六位大写十六进制>`；没有有效 MAC 时持久保存随机后缀。所有管理 AP 共用由 16 个随机字节生成的 32 位小写十六进制密钥；固件不含固定凭据，脚本不输出密钥。重复运行保留已有管理 SSID/密钥，不创建重复 AP；无无线设备、凭据不完整或提交/验证失败时保留 defaults 脚本以便重试。成功后才写入 `/etc/tr3000-lite/management-ap.initialized`。
- 防火墙默认拒绝转发；只有 `mgmt → wan` 可转发。`plant` 不可主动访问 WAN、WireGuard 或管理面；WAN 不可访问管理面或工业网。
- WireGuard 接口、UDP listener 和工业远程访问默认关闭。没有密钥、PSK、VPS 地址或客户网段被写入固件。
- Lite 配置使用 `eth0`/`eth1` 作为 WAN/plant 的候选 Linux 设备名。上游 DTS 显示两个 MAC，但无法仅靠 DTS 确认机壳上的物理插孔角色；首次部署必须用 `ip link` 配合逐口插拔/链路灯做实机映射核验。若核验不符，不要连接现场网络或执行 `plant-profile.sh`。

现场 IP 不预设。先隔离工业设备、确认网段未与任何上行网段重叠，再运行只读的 `sh scripts/preflight.sh`，最后通过串口/本地控制台手工提供已核验的设备名和地址：

```sh
sh /root/scripts/plant-profile.sh --device eth1 --address 192.168.10.254/24
```

上例是操作员输入的示例，不会编入固件。脚本会先检查活动路由重叠，再通过 `arping -D` 探测地址冲突；冲突或检查失败时不写配置。修改前的 `/etc/config/network` 会保存到 `/root/network.before-plant-profile.*`。网络重载失败时脚本会尝试恢复旧配置；仍需通过本地控制台验证回滚。

## 上行和 WireGuard

固件包含轻量 `lite-uplink-watch` procd 服务：每 15 秒区分 netifd 接口状态和两个 IPv4 ping 探测结果；连续 3 次全部失败后将该出口默认路由 metric 暂时增加 1000，连续 2 次恢复后还原。WAN、STA、USB 的基础 metric 为 10/20/30；WAN 恢复会自动抢回优先级。实际无线 STA/USB 设备仍需安装人员核验并启用，默认逻辑接口为 `wwan`/`usbwan` 且不自动启动，不会猜测设备名。ICMP 探测只表示探测地址可达；若现场网络屏蔽 ICMP，应选择允许探测的目标，并验证失联、恢复、DNS 和路由收敛。

默认路由出口发生变化且 WireGuard 接口已启用时，服务会重启 `wg` 网络接口以触发重新握手；Peer 仍建议按现场 NAT 情况设置 `PersistentKeepalive = 25`。必须对真实上行切换做测试，不能把链路 up 等同于 VPS 可达。见[WireGuard/VPS 路由指南](WIREGUARD-VPS-ROUTING.md)。

管理 Wi-Fi 不桥接到 plant。首次部署必须在可信串口/本地控制台设置非空 root 密码，并从权限为 `0600` 的 `/etc/config/wireless` 读取该设备生成的管理 SSID/密钥；不要把密钥贴入日志或构建产物。AP 初始化本身不启用 plant HTTPS 或远程管理；控制器只有在非空 root 密码和 AP 初始化标记同时存在时才允许启用 plant HTTPS。首次启动无线设备发现、双频 AP 与 STA 共存、STA 断线期间管理 AP 持续可用、HTTPS/SSH 登录及 Linux 文件权限仍需真机验证。`wpad-openssl` 固定为必需包，最终配置拒绝其他 `wpad-*` 提供者。

## 构建与产物

GitHub Actions → **TR3000 Lite firmware** → Run workflow。工作流使用 Ubuntu 22.04、固定源码和 feed revisions；通过 `make defconfig`，最多 4 路并发编译，下载失败重试，编译并行失败时退回单线程。Artifacts 含 sysupgrade 镜像、SHA256、包清单、配置、源码提交、feed 锁定信息、上游许可证和构建日志。

仅接受路径 `bin/targets/mediatek/filogic/` 下文件名包含 `cudy_tr3000-v1-ubootmod` 的非空 `sysupgrade.bin`。它是系统升级镜像，不代表 Factory、BL2、FIP 或所有 U-Boot 刷写方式都兼容；不要用于未经确认的启动分区或跨布局保留旧配置升级。

当前 Windows 工作区只能运行仓库验证；固件编译由 Linux GitHub Runner 执行。除源码和配置校验外，本次没有执行真实固件构建、设备启动或联网测试。所有验收项见[测试计划](TEST-PLAN.md)，硬件相关项仍需真机执行。

## 工业现场限制

TIA Portal 对已知固定 IP 的常规三层单播通信可经路由/VPN 使用，但 PROFINET DCP、LLDP 和广播/多播发现不能直接跨越三层 WireGuard。远程 PLC 程序下载/变更属于高风险操作，必须有明确授权、现场安全联锁、变更窗口、现场人员确认和断线应对/回滚流程。
