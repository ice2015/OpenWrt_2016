# TR3000 Full 综合增强版

本构建只适用于已核实的 **Cudy TR3000 v1、128 MiB NAND、MT7981、`cudy_tr3000-v1-ubootmod`、112 MiB UBI**。它不是原厂 128M、256M、122 MiB UBI、factory、recovery、BL2 或 FIP 镜像。构建成功不等于某一台设备已经满足刷写条件。

## 构建内容

Full 在固定的上游 `config/128muboot.config` 上应用 [`configs/full.seed`](../configs/full.seed)，固定源码、包装仓库与 feeds 的完整 commit SHA。默认编译：

- 标准 LuCI HTTPS、中文和 Bootstrap 主题；
- WireGuard、firewall4、USB RNDIS/CDC、OpenSSH/SFTP、诊断工具；
- Tailscale 与 sing-box，但两者首次启动保持禁用；
- TR3000 Full LuCI 服务页和工业网络安全默认配置。

cloudflared 默认不编译。Aurora、OpenClash、PassWall、UPnP、AdGuard Home、Docker、Bandix 和 dropbear 被显式排除，避免重复代理、DNS、容器、主题和 SSH 栈。

## GitHub Actions

进入 **Actions → TR3000 Full firmware → Run workflow**，可选择：

| 输入 | 默认值 | 作用 |
| --- | --- | --- |
| `include_tailscale` | `true` | 是否编译 Tailscale；不控制运行状态 |
| `include_singbox` | `true` | 是否编译 sing-box；不控制运行状态 |
| `include_cloudflared` | `false` | 是否编译 cloudflared；仍受镜像容量门禁 |
| `release` | `false` | 成功后是否发布带警告的 GitHub prerelease |

工作流固定 Actions 版本和源码提交，最多使用 4 个并行编译任务。失败时仍上传日志；只有通过以下门禁的镜像才能进入 `firmware/`：

- 唯一 profile 是 `cudy_tr3000-v1-ubootmod`；
- DTS UBI 范围为 `0x7000000`，拒绝 `0x7a40000`；
- 文件名匹配目标 sysupgrade，文件非空且为包含目标 `CONTROL` 的 tar；
- 默认不超过 100 MiB，为 112 MiB UBI 留出余量；
- 生成同次构建的 `SHA256SUMS`、最终 `.config`、包清单、feed/source 记录和日志。

Artifact 名为 `TR3000-128M-112M-Full`。失败运行或缺少完整门禁文件的 Artifact 不能视为可刷固件。Release 也只是同一组已验证 CI 文件的分发方式，不增加设备兼容性证明。

## Web 管理

界面使用原生 LuCI Bootstrap。常规接口、防火墙、WireGuard 配置仍使用标准 LuCI 页面；**服务 → TR3000 Full** 只控制固定的 WireGuard、Tailscale、sing-box 和 cloudflared 服务。

- “启用 WireGuard”只启用已配置的 `wg` 隧道入口，不授予 `wg → plant` 权限。
- 工业访问必须再用 [`plant-access.sh`](../scripts/plant-access.sh) 精确限定 Peer、现场网段、协议和端口。
- 未编译的服务显示为不可用，不能在 Web 中凭空开启。
- 控制器拒绝未知服务名；LuCI RPC 执行权限只属于 write ACL，不授予只读委派账号。

也可从本机控制台使用：

```sh
/usr/sbin/tr3000-full-service status --json
/usr/sbin/tr3000-full-service enable tailscale
/usr/sbin/tr3000-full-service disable tailscale
```

启用前必须先写入本地配置和凭据。Token、私钥、UUID、Wi-Fi 密钥和客户地址不得提交仓库、写入公开固件或输出到 Actions 日志。

## 第一次部署

1. 在本地控制台记录设备标签、NAND 芯片、序列批次、`/proc/mtd`、`ubinfo -a`、坏块、当前 BL2/FIP/Factory、启动日志和恢复入口。
2. 将 Factory/RF、bootloader、环境与配置备份到设备外并核验 SHA-256。
3. 实机逐个插拔网线，确认 `eth0`/`eth1` 与物理 WAN/plant 的映射；不能只依赖提示词中的假设。
4. 用 `plant-profile.sh` 指定经现场冲突检测的接口和地址；不要自动使用示例网段。
5. 在本地安全注入 WireGuard/Tailscale/sing-box/cloudflared 配置，权限设为 `0600`，先用测试设备验证。
6. 按 [`TEST-PLAN.md`](TEST-PLAN.md) 区分 CI、模拟环境与真机验收。

## 升级与回滚边界

传输后重新核验镜像 SHA-256，并在目标设备上先运行 `sysupgrade -T <verified-image>`；失败时停止，不能用 `-F` 绕过。跨 fork、跨布局或现有配置兼容性不明时，不默认保留旧配置。具体升级执行前应单独确认镜像、布局、配置策略、断网窗口和恢复方式。

本仓库不提供猜测的 `mtd write`、`dd`、`nandwrite`、擦除命令、MTD 编号或偏移。当前第三方 U-Boot 未经现场识别时，不能远程无人值守更新 BL2/FIP。先阅读 [`UBOOT-SAFETY.md`](UBOOT-SAFETY.md)。

sing-box 失联时可从本地管理口运行 `/root/scripts/singbox-rollback.sh`；它只停止 sing-box 并删除本项目命名的 `tr3000_full_singbox_*` 防火墙段，不删除其他防火墙策略或配置文件。

## 本地校验

原生 Windows 不编译固件，只运行仓库校验：

```sh
bash scripts/validate.sh
python -m unittest discover -s tests -v
```

完整编译、包 ABI、镜像大小和上游下载必须由 GitHub Actions 或 Linux/WSL2 验证；启动、端口映射、NAND 兼容、恢复和工业访问只能在已备份的实验设备验证。
