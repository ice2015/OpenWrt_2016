# TR3000-Lite 双通道工业远程访问运维指南 (Remote Access Guide)

本文档说明 Cudy TR3000-Lite 固件中的“Direct 直连”与“VPS 转发”双通道 WireGuard 远程访问拓扑、网络安全隔离、SNAT 机制、Windows 客户端互斥原则及现场排障流程。

> [!IMPORTANT]
> 仓库代码与文档中出现的 IP 地址、网段和公钥均为拓扑示例占位符，实际部署时应根据规划分配。

---

## 1. 双通道访问拓扑与定位 (Topology & Demarcation)

```
                 +-------------------------------------------------------+
                 |                 Cloudflare DNS (Gray Cloud)           |
                 |               tr3000-b001.example.com -> WAN IP       |
                 +-------------------------------------------------------+
                                           ^
                                           | DDNS A Record
                                           v
[Engineer Laptop] ==================> [TR3000-Lite WAN] (UDP 51820)
                  Direct WireGuard       (wg_direct: 10.77.0.2/32)
                  (10.77.0.10/32)                 |
                                                  | SNAT to 192.168.10.254
                                                  v
                                      +------------------------+
                                      | Plant Network (eth1)   |
                                      | 192.168.10.0/24        |
                                      | PLC: 192.168.10.100    |
                                      +------------------------+
                                                  ^
                                                  | SNAT to 192.168.10.254
                                                  |
[Engineer Laptop] ---> [VPS Proxy Server] ====> [TR3000-Lite wg_vps]
(10.88.0.20/32)        (10.88.0.1/32)            (10.88.0.2/32)
                       VPS Fallback WireGuard
```

| 通道 | 接口名 | 定位与触发条件 | 性能与限制 |
| :--- | :--- | :--- | :--- |
| **Direct 直连** | `wg_direct` | **首选高带宽通道**。仅在 WAN 具备独立公网 IPv4 且 UDP 51820 未被阻断时可用；配合 Cloudflare DDNS 解析。 | 延迟低、带宽完全由本地宽带决定。要求现场有公网 IPv4。 |
| **VPS 回传** | `wg_vps` | **保底自愈通道**。网关主动向 VPS 发起出站握手（开启 `PersistentKeepalive = 25`）。 | 适用于 4G/5G 路由棒、多层 NAT、大网 CGNAT 或 Wi-Fi STA 上行环境。受 VPS 带宽中转限制。 |

---

## 2. Windows 客户端互斥原则 (Mutual Exclusivity)

> [!CAUTION]
> **严禁在工程师 Windows 客户端同时激活 Direct 与 VPS 两个 WireGuard 配置隧道！**

### 为什么必须互斥？
1. 两个隧道的目标现场工业网段相同（例如均为 `192.168.10.0/24`）。
2. 若同时启动两个隧道，Windows 内核路由表将针对同一子网出现两条相同 metric 的路由条目，导致非对称路由或路由抖动，造成 TIA Portal / STEP 7 握手连接中断或数据包丢失。
3. **运维切换规范**：
   - 优先激活 Direct 配置文件。
   - 若 Direct 连接失败（例如出差现场网络无公网 IP 或 DDNS 故障），**先停用 Direct 隧道**，再激活 VPS 隧道。

---

## 3. 客户端配置文件规范 (Client Configuration Templates)

### 3.1 Direct 直连客户端配置 (`tr3000-direct.conf`)

```ini
[Interface]
PrivateKey = <Engineer_Direct_Private_Key>
Address = 10.77.0.10/32
DNS = 192.168.77.1

[Peer]
PublicKey = <TR3000_Direct_Public_Key>
Endpoint = tr3000-b001.example.com:51820
# 仅路由远程网关接口与目标工业网段，绝不做全网重定向 (No 0.0.0.0/0)
AllowedIPs = 10.77.0.2/32, 192.168.10.0/24
```

### 3.2 VPS 保底客户端配置 (`tr3000-vps.conf`)

```ini
[Interface]
PrivateKey = <Engineer_VPS_Private_Key>
Address = 10.88.0.20/32
DNS = 10.88.0.1

[Peer]
PublicKey = <VPS_Server_Public_Key>
Endpoint = vps.example.com:51820
# 路由 VPS 隧道节点、TR3000 节点及目标工业网段
AllowedIPs = 10.88.0.1/32, 10.88.0.2/32, 192.168.10.0/24
PersistentKeepalive = 25
```

---

## 4. 工业网络转发与 SNAT 安全机制 (SNAT & Security)

现场 PLC、HMI 等工业设备通常配置为静态 IP 且**不设默认网关**（Default Gateway 为空），无法跨三层网段回程。

TR3000-Lite 采用精细化 nftables 链与源地址转换 (SNAT)：
1. **源地址精确白名单**：仅放行来自已授权 `/32` Peer 地址的流量（如 `10.77.0.10/32` 或 `10.88.0.20/32`），任何大段掩码（如 `/0` 或 `/24`）均在控制器加载阶段被立即拒绝并注销整个候选规则。
2. **目标 SNAT**：经过核验的 WireGuard 进站流量在转发给 `eth1` (plant) 接口时，被自动 SNAT 为网关的静态 plant 地址（默认 `192.168.10.254`）。
3. **回程透明**：PLC 仅感知到来自同网段 `192.168.10.254` 的连接请求，将响应发回网关；网关内核 conntrack 模块自动将数据还原并通过原 WireGuard 隧道送回工程师终端。
4. **禁止主动出站**：防火墙严禁 plant 网段主动访问 WAN、WireGuard 或管理面；绝不开启通配 masquerade。

---

## 5. 现场工业网段变更操作规程 (Plant CIDR Change Workflow)

当现场因 IP 冲突需要将工业子网由 `192.168.10.0/24` 变更为例如 `192.168.20.0/24` 时：

1. **设备端变更**：
   - 登录 LuCI Web 界面：“网络 → 工业 LAN”；
   - 填写新 IP/掩码：`192.168.20.254/24`；
   - 点击“验证”，无冲突后点击“保存并应用”；
   - 设备将原子化更新 network/firewall 配置，自动将 SNAT 出口和内核规则链重定向至 `192.168.20.254`。
2. **客户端更新**：
   - 工程师在“网络 → TR3000 Lite → 远程访问”页面或控制台查看提示；
   - 工程师修改本地 Windows WireGuard 配置文件中的 `AllowedIPs`：
     ```ini
     # 将 192.168.10.0/24 修改为 192.168.20.0/24
     AllowedIPs = 10.77.0.2/32, 192.168.20.0/24
     ```
   - 在 Windows WireGuard 客户端中停用并重新激活隧道。

---

## 6. LuCI 远程访问控制界面说明

在 Web 导航中访问：“网络” → “TR3000 Lite” → “远程访问” (`admin/network/tr3000-lite/remote-access`)：

- **状态仪表板**：展示设备入网状态、安全门禁状态、Direct/VPS 通道状态、最新握手时间及 Cloudflare DDNS 运行状态。
- **总控开关**：
  - **允许远程访问 LuCI 管理后台 (`allow_luci`)**：允许授权的远程 Peer 访问路由器的 Web/SSH 管理界面。默认关闭。
  - **允许远程访问现场工业网段 (`allow_plant`)**：允许授权的远程 Peer 穿透访问 PLC/HMI 等现场设备。默认关闭。
- **客户端路由参考**：界面根据当前实际生效的 plant 网段，动态生成工程师客户端所需的 `AllowedIPs` 文本，便于一键复制。
