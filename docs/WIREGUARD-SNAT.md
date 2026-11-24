# WireGuard 工业网精准 SNAT

本页是 [`WIREGUARD-VPS-ROUTING.md`](WIREGUARD-VPS-ROUTING.md) 的 Full 版操作摘要。示例地址均为占位符，不代表现场可用。

## 为什么需要 SNAT

PLC/HMI 常只有固定 IP 且没有默认网关。工程师经 WireGuard 访问时，TR3000 必须把已授权流量的源地址转换为自身 plant 地址，使设备把响应发回同一二层的 TR3000。不能对整个 plant 网段做宽泛 masquerade，也不能开放任意 Peer、目标或端口。

## 前置门禁

- 已实机确认 plant 物理接口和一个未占用的本机地址；
- `plant` DHCPv4、DHCPv6、RA、NDP 全部关闭；
- `network.wg` 已配置，工程师 Peer 的 AllowedIPs 精确包含其隧道 `/32`；
- WAN/STA/USB 与 plant 不重叠；
- 操作已获现场授权，先对测试 PLC/HMI 验证。

示例只授权工程师 `10.77.0.10` 访问测试网段 TCP 102：

```sh
sh /root/scripts/plant-access.sh enable \
  --peer 10.77.0.10 \
  --plant-cidr 192.168.20.0/24 \
  --plant-ip 192.168.20.254 \
  --protocol tcp \
  --ports 102
```

撤销该 Peer 的全部本项目授权：

```sh
sh /root/scripts/plant-access.sh disable --peer 10.77.0.10
```

用 `fw4 check`、`nft list ruleset`、`conntrack` 和两侧抓包确认源 Peer、目标、端口、SNAT 地址与回程。关闭授权后，新连接必须立即失败。LuCI 的 WireGuard 服务按钮只控制隧道入口，不能替代此授权。

VPS 需启用经批准的 IP 转发和防火墙规则；TR3000 Peer 的 AllowedIPs 只包含该站点隧道地址及获批现场前缀。不同客户使用相同现场子网时，必须分离路由域/VPN 实例或设计地址映射，不能把重叠前缀同时发布到一个路由表。

PROFINET DCP、LLDP 和二层发现不穿越普通 WireGuard。TIA Portal 应使用已知固定 IP；远程写程序仍需要变更窗口、现场人员、安全联锁和独立回滚授权。
