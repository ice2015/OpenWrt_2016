# HomeProxy 分流（sing-box）

Full 默认编译 `sing-box`（full 变体）与上游 `luci-app-homeproxy`（含简体中文）。HomeProxy 负责生成 sing-box 客户端配置、管理订阅与分流规则、接管 dnsmasq 与 nftables；**不要**再手工运行 sing-box 自带的 `/etc/init.d/sing-box` 服务（首启默认已禁用它，避免两套实例抢端口/抢 nft 表）。

## 配置入口

LuCI **服务 → HomeProxy**：

- **Node Settings**：添加节点或导入订阅。支持 VLESS + WS + TLS：类型选 `vless`，传输选 `ws`，填 path/Host，TLS 开启并填 SNI；也支持上游支持的其它协议与 REALITY。支持 `vless://` 链接导入。
- **Client Settings**：主节点、路由模式、代理模式、LAN 过滤、DNS。
- **Service Status**：运行状态与日志。

凭据（UUID、订阅地址、密码）只存在首启后管理员写入的 `/etc/config/homeproxy` 与订阅缓存；不得提交仓库、写入固件或输出到 CI 日志。

## 路由模式（对应需求的三种模式）

| 需求 | HomeProxy `routing_mode` | 行为 |
| --- | --- | --- |
| 智能分流 | `bypass_mainland_china`（默认）或 `gfwlist` | 国内域名/IP 直连，其余走代理；自带 china/gfw 列表 |
| 全局代理 | `global` | 全部流量走代理 |
| 直连 | `custom` 且默认出口 `direct-out`，或主节点选 `direct` 类型 | 全部直连，不代理 |

`custom` 模式可逐条配置域名/IP 出口，适合精细分流。切换模式后保存并应用，HomeProxy 会重新生成配置并 `fw4 reload`。

## 代理模式与 LAN 透明代理

- `redirect`：仅 TCP；`redirect_tproxy`（默认）：TCP + UDP TProxy；`redirect_tun`/`tun`：Tun 接管（需要 `ip-full` 与 `kmod-tun`，基线已含）。
- LAN 客户端默认按所选模式透明代理；可在 **LAN IP Policy** 用 IP/MAC 列表排除或限定设备。
- 路由器自身流量（DNS、订阅更新、穿透控制连接）按上游规则处理；如遇 DNS 环路，先检查 `dns_port`（默认 5333）与 dnsmasq 转发配置，不要同时运行其它 DNS 劫持工具。

## 启用与停用

```sh
/usr/sbin/tr3000-full-service enable homeproxy
/usr/sbin/tr3000-full-service disable homeproxy
```

未配置主节点时 `/etc/init.d/homeproxy` 拒绝启动，这是预期行为。停用后 HomeProxy 清理自己的 nft 链/表与 dnsmasq 片段；如仍异常，从本地控制台 `fw4 reload` 并检查 `/var/run/homeproxy/homeproxy.log`。

## 版本与验证边界

- sing-box 与 HomeProxy 均来自固定 feed SHA；升级 feed 前先在 Actions 构建并真机验证节点生成、订阅更新与三种路由模式。
- 真机验收见 `devices/tr3000/docs/TEST-PLAN.md` F6/F7：国内直连、指定站点走代理、全局/直连切换、LAN 客户端同样生效。
- 不要把"服务显示运行"当作分流正确；用实际访问与 `nft list ruleset` 核对。
