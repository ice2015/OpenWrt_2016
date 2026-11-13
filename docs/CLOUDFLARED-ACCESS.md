# Cloudflare Tunnel / Access

cloudflared 默认不编译，因为 112 MiB UBI 的容量有限。运行 Full workflow 时显式选择 `include_cloudflared=true` 后，配置合并必须保留该包，最终镜像仍需通过 100 MiB 安全上限；超限就让构建失败，不绕过门禁。

## 使用边界

- 只发布经过 Cloudflare Access 身份认证的 HMI/NAS Web 应用；
- 不把 PLC 编程、控制、现场总线或管理端口映射到公共 hostname；
- 私有网络路由也必须限制用户、设备、目的网段和端口；
- token 在首次启动后写入 root-only 文件并设为 `0600`，不得进入 Git、固件、命令历史或 CI 日志；
- 使用包自带的 procd 服务、重启策略和日志限制，不创建后台死循环。

无凭据示例位于 `/etc/tr3000-full/examples/cloudflared.yml.example`。其中 `example.invalid` 与 `192.0.2.0/24` 都是文档占位符。先确认当前包的配置路径和 token-file 支持方式，再复制、修改和检查。

启用前验证 DNS、TLS 时间、出站 TCP 443，以及当前 cloudflared 版本实际需要的 QUIC/HTTP2 出站策略。Cloudflare Access 策略、隧道 ingress 与本机防火墙三层都必须限制访问。

可在 LuCI **服务 → TR3000 Full** 启停，或使用：

```sh
/usr/sbin/tr3000-full-service enable cloudflared
/usr/sbin/tr3000-full-service disable cloudflared
```

停用后从外网验证 hostname/私网路由立即失效，同时本地 HMI 服务保持正常。Cloudflare 控制台显示 Healthy 只证明隧道连接，不证明 Access、目标端口或工业安全策略正确。
