# 穿透通道：WireGuard / Cloudflare Tunnel / Tailscale

Full 的三条穿透通道都是**从外面回到家里**的方向，出厂全部关闭。凭据只在首启后由管理员写入设备本机受限文件，不入仓库、固件、Artifact 或 CI 日志。科学上网的出站代理传输由 sing-box/HomeProxy 承担，不在本页范围。

## WireGuard（入站回家）

路由器跑标准 `wg` 接口，外面的设备（手机/笔记本）作为 Peer 拨入，访问家里的 LAN。

配置顺序：

1. LuCI **网络 → 接口 → 添加新接口**，协议选 WireGuard，生成密钥对，监听端口默认 `51820`；把外面设备的公钥加为 Peer，`AllowedIPs` 填该设备的隧道地址 `/32`。
2. 防火墙放行（出厂预置、默认全关，按需逐条启用）：
   - `tr3000_full_wg_listener`：WAN 侧 UDP 51820 监听放行——没有它握手到不了路由器；
   - `tr3000_full_wg_mgmt`：`wg` 侧 TCP 22/443 管理面放行；
   - `tr3000_full_wg_icmp`：`wg` 侧 ping 放行。
   `wg → lan` 转发已预置（回家的人能进 LAN）；**没有** `wg → wan` 转发（回家不等于借家里出口上网）。
3. 对端用 DDNS 主机名（见 `docs/DDNS-CLOUDFLARE.md`）或公网 IP 作为 Endpoint；家宽公网 IP 变化时 DDNS 自动跟进。
4. 也可在 **服务 → TR3000 Full** 用开关启停 WireGuard listener（只控制监听规则与接口，不替代上面的 Peer 配置）。

验证：对端握手成功、能 ping 通 `192.168.10.1`、能打开 `https://192.168.10.1`；关闭 listener 后新连接立即失败。家宽若是运营商 NAT（无公网 IPv4），WireGuard 入站不可用，改用 Tailscale 或 Cloudflare Tunnel。

## Cloudflare Tunnel（Argo）

出站隧道，把家里的 Web 服务经 Cloudflare Access 认证后暴露到公网域名；不需要公网 IP、不开入站端口。

- 默认编译 `cloudflared` 与 `luci-app-cloudflared`（构建开关 `include_cloudflared`，默认开；镜像超 100 MiB 门禁时构建失败，不绕过）。
- 在 Cloudflare Zero Trust 创建 Tunnel 与 Access 策略，把 token 写入设备本机 root-only 文件（`0600`），在 LuCI **服务 → Cloudflared** 或 `/usr/sbin/tr3000-full-service enable cloudflared` 启用。
- 无凭据参考：`/etc/tr3000-full/examples/cloudflared.yml.example`（占位域名，不可直接使用）。
- 只暴露经过 Access 认证的 Web 应用；不要把 SSH/管理面直接挂到公共 hostname。停用后从外网验证 hostname 立即失效。

## Tailscale（可选备用）

免打洞的备用远程通道，适合家宽无公网 IP 的场景。

- **默认不编译**：构建时 `include_tailscale=true` 才加入镜像（体积考虑）。运行状态默认关闭。
- 启用前在 Tailscale 管理端设置最小 ACL；auth key 只在设备本地注入，不入仓库/日志。
- 在 **服务 → TR3000 Full** 或 `/usr/sbin/tr3000-full-service enable tailscale` 启停。
- 与 WireGuard 可共存；注意两者同时运行时的路由表与 DNS，不要同时发布重叠子网。

## 共同纪律

- 三条通道默认关闭是出厂不变量，CI 契约测试锁住；不要为了"方便"在固件里预开。
- WAN 侧管理面始终关闭；管理只从 `lan` 或已授权的隧道进入。
- 真机验收见 `docs/TEST-PLAN.md` F11/F12。
