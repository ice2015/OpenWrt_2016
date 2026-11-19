# Cloudflare Tunnel / Access（Full）

Full 默认编译 `cloudflared` 与 `luci-app-cloudflared`（构建开关 `include_cloudflared`，默认开）。用途：把家里的 Web 服务（NAS、相册、测试站点）经 Cloudflare Access 身份认证后暴露到公网域名——出站隧道，不需要公网 IP，不开入站端口。

## 体积门禁

cloudflared 二进制较大，最终镜像仍须通过 100 MiB 安全上限；超限就让构建失败，不绕过门禁。若默认组合超限，把 `include_cloudflared` 改回 `false` 并记录取舍（见 spec D4/D6）。

## 使用边界

- 只发布经过 Cloudflare Access 认证的 Web 应用；
- 不把 SSH、路由器管理面或任何控制端口直接映射到公共 hostname；
- 私有网络路由（如启用）也必须限制用户、设备、目的网段和端口；
- token 在首次启动后写入 root-only 文件并设为 `0600`，不得进入 Git、固件、命令历史或 CI 日志；
- 使用包自带的 procd 服务与重启策略，不创建后台死循环。

无凭据示例位于 `/etc/tr3000-full/examples/cloudflared.yml.example`（占位域名，不可直接使用）。先确认当前包的配置路径和 token-file 支持方式，再复制、修改和检查。

## 启用与验证

```sh
/usr/sbin/tr3000-full-service enable cloudflared
/usr/sbin/tr3000-full-service disable cloudflared
```

或在 LuCI **服务 → Cloudflared** / **服务 → TR3000 Full** 操作。

启用前验证 DNS、TLS 时间、出站 TCP 443，以及当前 cloudflared 版本实际需要的 QUIC/HTTP2 出站策略。Cloudflare Access 策略、隧道 ingress 与本机防火墙三层都必须限制访问。

停用后从外网验证 hostname 立即失效，同时家里本地服务保持正常。Cloudflare 控制台显示 Healthy 只证明隧道连接，不证明 Access 策略或目标端口正确。真机验收见 `docs/TEST-PLAN.md` F11。
