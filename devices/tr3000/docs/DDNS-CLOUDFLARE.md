# DDNS：LuCI + Cloudflare

Full 默认编译 `luci-app-ddns`、`ddns-scripts`、`ddns-scripts-cloudflare`，出厂预置一个**禁用**的 Cloudflare 模板（`/etc/config/ddns` 的 `cloudflare_v4` 段，`service_name 'cloudflare.com-v4'`）。DDNS 让 WireGuard 对端用固定域名找到变化中的家宽公网 IP。

## 配置步骤

1. LuCI **服务 → DDNS**，编辑 `cloudflare_v4`（或新建服务，provider 选 `cloudflare.com-v4`）。
2. 填域名：格式 `主机名@根域名`，例如 `home@example.com`（脚本按 `@` 拆分；`@example.com` 表示根域名记录）。
3. 填凭据，两种填法（推荐前者）：
   - **Scoped API Token**：`username` 填字面量 `Bearer`，`password` 填 Cloudflare Token（权限只需该 zone 的 DNS 编辑）。脚本走 `Authorization: Bearer` 头。
   - Global API Key：`username` 填 Cloudflare 账号邮箱，`password` 填 Global API Key。权限过大，不推荐。
4. 可选填 `zone_id` 省去一次 zone 查询；`ip_source network` / `ip_network wan` 表示取 WAN 接口地址（家宽有公网 IPv4 时适用；运营商 NAT 场景 DDNS 无意义，改用 Tailscale/Cloudflare Tunnel）。
5. 勾选启用并保存应用。Token 只存在设备本机 `/etc/config/ddns`（root 权限），不入仓库、固件、Artifact 或 CI 日志。

## 验证

- LuCI DDNS 页显示最近一次更新时间与结果；`logread | grep ddns` 无报错。
- 外部 `nslookup 你的域名` 解析到当前公网 IP；公网 IP 变化后记录在检查周期内跟进。
- 真机验收见 `devices/tr3000/docs/TEST-PLAN.md` F12。

## 边界

- 出厂模板不含任何域名/凭据且 `enabled 0`；未配置时 ddns 服务不产生更新请求。
- 需要其它 provider 时在同一页面选择（`ddns-scripts` 自带大量 provider）；Cloudflare 是默认优先项。
