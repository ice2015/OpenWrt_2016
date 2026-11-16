# WireGuard、VPS 与无默认网关工业网段

以下地址全是文档占位示例，必须替换为规划后的非重叠地址。不要将私钥、PSK、真实 VPS 地址、客户凭据或同名重叠现场网段写入固件或仓库。

**变体边界：**下文 `wg`/`plant-access.sh` 单隧道命令属于旧版/Full 的手工单隧道模型。在当前 TR3000-Lite 架构中，系统已实现规范化的 Direct 直连与 VPS 保底双通道 WireGuard 管理、两阶段离线预配与 LuCI 控制界面，详见专项文档：
- [TR3000-Lite 预配与入网规范](TR3000-LITE-PROVISIONING.md)
- [TR3000-Lite 双通道远程访问运维指南](TR3000-LITE-REMOTE-ACCESS.md)

示例拓扑：

- 现场 PLC/HMI：`192.168.10.0/24`，无默认网关。
- TR3000 plant 地址：安装人员核验冲突后设置为 `192.168.10.254/24`。
- WireGuard：VPS `10.77.0.1`，TR3000 `10.77.0.2/32`，工程师 `10.77.0.10/32`。
- 外层上行：WAN 首选；明确批准的加密 Wi-Fi STA 次之；Lite 默认 USB 路径仅支持 RNDIS/CDC-Ether DHCP 路由棒，不承诺任意手机共享、NCM/QMI/MBIM 或串口拨号。

## 路由与授权模型

TR3000 与 VPS 之间只建立点对点 WireGuard。VPS/工程师侧仅发布被授权的现场前缀；不要将 PLC 的固定 IP 或网关改成 WireGuard 地址。工程师访问 PLC 时，TR3000 上精确限制 `wg → plant` 的源 Peer、现场前缀、协议和目标端口，并把该 Peer 流量 SNAT 为 TR3000 的 plant 地址。PLC 将响应发回同网段的 TR3000；conntrack 还原回程，不需要 PLC 默认网关。

创建 WireGuard UCI Peer 时，`wg` 必须是 WireGuard 接口且 `wg0` 的该 Peer 精确包含工程师 `/32` AllowedIPs。PrivateKey/PSK 应在设备本地安全注入，不要通过固件配置、命令行历史、CI 日志或工单明文传递。

配置已核验的现场地址后，示例仅授权 TCP 102（TIA Portal S7 通信示例端口）：

```sh
sh /root/scripts/plant-access.sh enable \
  --peer 10.77.0.10 \
  --plant-cidr 192.168.10.0/24 \
  --plant-ip 192.168.10.254 \
  --protocol tcp \
  --ports 102
```

此命令不是默认开关，只有在 WireGuard 和 plant profile 已配置、现场网段没有上行重叠且授权获批后才应执行。脚本核验 `wg` 接口、该 `/32` Peer、活动 plant 地址/掩码和路由重叠；未列出的目标端口仍由默认拒绝策略阻断。关闭一个 Peer 的授权：

```sh
sh /root/scripts/plant-access.sh disable --peer 10.77.0.10
```

使用 `fw4 print`、`nft list ruleset` 和现场抓包检查实际生成的规则、SNAT 出口和 conntrack 回程。不要添加 `plant → wan`、`plant → wg` 或全网段通用 masquerade 转发。

## VPS 路由

VPS 上 TR3000 Peer 的 AllowedIPs 需包含其隧道地址和经批准的现场前缀；工程师 Peer 只发布该工程师需要的现场前缀。路由发布也应在 VPS 防火墙中限制到授权 Peer/端口。多客户现场若地址段相同，不能把同一个 `192.168.10.0/24` 同时发布给同一个路由域；应为站点分配独立的虚拟映射/路由域，或使用隔离的 VPN 实例，未经设计不要扩大 AllowedIPs。

示意（占位符不是可直接使用的 WireGuard 配置）：

```text
VPS -> TR3000 peer AllowedIPs: 10.77.0.2/32, <approved-site-prefix>
Engineer -> VPS peer AllowedIPs: 10.77.0.1/32, <approved-site-prefix>
TR3000 -> VPS peer AllowedIPs: 10.77.0.1/32, <approved-engineer-tunnel-/32>
```

WAN UDP 51820 listener 在默认防火墙中禁用；只有选定 VPN 部署模式、确认外层端口后才可本地启用该单一传输端口。管理端口不能从 WAN 暴露。若 TR3000 作为客户端发起隧道，优先使用出站握手而非开放 listener。

## 新 Lite 的多上行边界

Lite 专用实现不改变 Full 共享 watcher。`wan/wwan/usbwan` 固定基础 metric10/20/30，默认每轮休眠15秒、连续3个全失败轮次降级1000、连续2个成功轮次恢复。探测和锁等待另占时间；轮数不是固定秒数。每接口可配置允许的 IPv4 探测目标；carrier、netifd up、DHCP 地址、默认网关、探测成功和 VPS 握手必须分别判断。

STA 通过标准 LuCI 加入明确批准的加密热点，保留管理 AP，不能使用“替换无线配置”；已有 `wwan` 默认 auto0，需在标准接口页显式启用。共 PHY 时 AP 信道跟随 STA，扫描/重连可能短暂中断管理连接，不能承诺 RF 无间断。USB 按 sysfs 驱动及 USB 父设备识别，不猜固定网卡名；双候选失败关闭，事件遗漏后由守护轮次重新枚举。

重协调器在变更前后重读 netifd 当前租约，只处理精确指纹匹配的默认路由并记下自身临时路由；DHCP 续租后再次收敛，不盲删全部默认路由或覆盖外部配置。更优外部默认路由仍保留，页面发出警告而不假称托管 WAN 正在承载出口。只读“Multi-uplink status”显示健康、基础/有效 metric、地址/网关、USB 驱动/VID/PID 和实际 radio/PHY/信道，不接收或展示密钥。

稳定出口变化目前只发送 `tr3000-lite.uplink-changed` 通知；后续第三阶段才为已完整配置/启用的双 WireGuard 角色和标准 DDNS 添加处理。不能用通知成功代替真实 DNS 更新、VPS 可达或握手证据。最终测试须逐一断开/恢复三个上行、模拟 DHCP renew、VPS 不可达和 DNS 故障，再验证最新握手与授权；`PersistentKeepalive` 只是 NAT 保活辅助。

## 旧版 / Full 上行重连参考（不用于新 Lite）

以下描述保留旧共享脚本的操作背景，Full 本次未改动，仍需独立真机验收。

`lite-uplink-watch` 每 15 秒对 WAN、STA、USB 接口的 IPv4 路由分别做两个 ICMP 探测；连续 3 次失败后将该出口 metric 临时增加 1000，连续 2 次成功后恢复原 metric。默认基础 metric 为 10/20/30。默认逻辑接口名是 `wan`、`wwan` 和 `usbwan`；STA/USB 物理设备需核验后在本地配置并启用。仅 carrier/link up 或 DHCP 成功不能证明互联网可达；ICMP 被阻断时应换用现场允许的探测地址。

活动默认路由出口变化时，本机服务会重启已启用的 `wg` 网络接口以促成重新握手；WireGuard Peer 的 `PersistentKeepalive` 可帮助 NAT 映射与路径恢复，但不能替代验证。切换 WAN/STA/USB 后检查路由、DNS、VPS 可达性和 `wg show` 最新握手；确认探测失败、接口恢复、VPS 不可达、手机睡眠/断开和 DNS 故障时都能按预期恢复。

## 协议边界与作业安全

TIA Portal 对已知固定 IP 的常规三层单播通信可以通过路由/VPN访问；PROFINET DCP、LLDP 和广播/多播设备发现属于二层机制，不能直接穿越三层 WireGuard。需使用现场可达的固定 IP/工程组态，不要把广播转发当作默认修复方式。

远程 PLC 程序下载/在线变更是高风险作业：执行前需授权、变更窗口、现场人员确认、安全联锁和急停/本地控制策略；准备断线时停止写入、现场接管和已验证回滚方案。生产设备不得把 VPN 连通视为自动化作业许可。
