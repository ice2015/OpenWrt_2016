# Tailscale 备用远程访问

Full 默认编译 Tailscale 和 `kmod-tun`，但首次启动停止且禁用。它是 WireGuard 之外的备用管理通道，不能自动接管 plant 路由。

## 启用前

1. 在设备本地安装后注入身份，不把 auth key 写入固件、Git、Actions 参数或日志。
2. 在 Tailscale 管理端设置最小 ACL，只允许指定工程师和设备。
3. 默认不要发布 plant 子网；确需 subnet router 时，先核对与 VPS WireGuard、其他客户重叠网段及 exit node 的冲突，并在管理端显式批准路由。
4. 防火墙仍保持 `tailscale → plant` 默认拒绝。工业访问应采用单独、可审计的目标/端口授权设计。

配置完成后可在 LuCI **服务 → TR3000 Full** 启用，或从本地控制台执行：

```sh
/usr/sbin/tr3000-full-service enable tailscale
```

停用并取消自启：

```sh
/usr/sbin/tr3000-full-service disable tailscale
```

验收时检查设备身份、ACL、批准路由、DNS、exit node 状态，以及 WireGuard 与 Tailscale 同时运行时的路由表。不得仅以 Tailscale 显示 Online 判断工业网访问安全。
