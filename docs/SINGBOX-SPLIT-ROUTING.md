# sing-box 出差分流

Full 默认编译 sing-box，但不配置透明代理、不启用服务、不修改 nftables。示例位于 `/etc/tr3000-full/examples/sing-box.json.example`，只含无效域名和占位 UUID，不能直接投入使用。

## 安全策略

- 默认最终出口为 `direct`，只让明确列出的目的域名/IP 使用 `travel-vps`；
- RFC1918、Tailscale `100.64.0.0/10`、plant、mgmt、WireGuard 端点和 cloudflared 控制流量必须直连；
- 不创建捕获全部 TCP/UDP 的透明 inbound，不接管 PLC/HMI 工业流量；
- DNS 规则需与所安装 sing-box 版本匹配，避免 DNS 环路、泄漏和与 dnsmasq 冲突；
- 从构建 Artifact 的包清单确认实际版本，再对照该版本文档调整字段。

部署步骤：复制示例到该包实际使用的配置路径，替换服务器、UUID、TLS SNI、WS path 和明确代理清单，权限设为 `0600`。启用前先执行该版本提供的配置检查命令，例如：

```sh
sing-box check -c <actual-config-path>
```

不要假定不同版本的配置 schema 相同。检查通过后，从本地管理口启用并验证国内直连、指定目的经 VPS、工业网和 VPN 端点不被代理。断开 VPS 后应仍能本地管理并访问 plant 的获准路径。

回滚：

```sh
/root/scripts/singbox-rollback.sh
```

该脚本停止并禁用 sing-box，只删除以 `tr3000_full_singbox_` 命名的防火墙段，保留配置文件供离线检查。若本地管理也失联，使用已验证的物理管理口/failsafe，不要从远端反复修改 nftables。
