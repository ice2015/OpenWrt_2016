# Tailscale 备用远程通道（Full）

Full 的 Tailscale 是**可选**的免打洞备用远程通道，适合家宽无公网 IPv4、WireGuard 入站不可用的场景。方向是"从外面回到家里"，与 Cloudflare Tunnel 互补。

## 编译与默认状态

- **默认不编译**：运行 Full workflow 时显选择 `include_tailscale=true` 才加入镜像（112 MiB UBI 体积考虑）。
- 编译进镜像后，首次启动仍然**停止且禁用**；在 LuCI **服务 → TR3000 Full** 或控制台启用：

```sh
/usr/sbin/tr3000-full-service enable tailscale
/usr/sbin/tr3000-full-service disable tailscale
```

## 启用前

1. 在设备本地注入身份（auth key 或交互登录），不把 auth key 写入固件、Git、Actions 参数或日志。
2. 在 Tailscale 管理端设置最小 ACL，只允许自己的设备。
3. 默认不发布子网；确需 subnet router 时，在管理端显式批准路由，并核对与 WireGuard 隧道的网段重叠。

## 验收与边界

- 检查设备身份、ACL、批准路由、DNS 状态，以及 WireGuard 与 Tailscale 同时运行时的路由表；两者可共存，但不要同时发布重叠子网。
- 不得仅以 Tailscale 显示 Online 判断家里服务可达；从外部实际访问验证。
- 真机验收见 `docs/TEST-PLAN.md` F11；穿透通道总体边界见 `docs/TUNNEL-ACCESS.md`。
