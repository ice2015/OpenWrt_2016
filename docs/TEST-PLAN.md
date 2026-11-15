# TR3000 Lite / Full 测试计划

## 仓库/CI 层检查（逐次记录执行结果）

- `bash scripts/validate.sh`
- `python -m unittest discover -s tests -v`
- `sh -n` 对 Lite shell 脚本语法检查
- CI 在构建时检查固定 commit、feed commit、唯一目标 profile、112 MiB DTS 值和镜像文件名/非空状态；U-Boot CI 检查 128 MiB multi-layout 的 BL2/FIP 输出名。
- Full CI 额外检查 sysupgrade tar 的目标 `CONTROL`、100 MiB 安全上限、可选包与输入一致，并输出 `TR3000-128M-112M-Full` 工件。

这些是预期的自动化检查；仅当相关命令实际通过后才可标为已执行。它们不证明固件能在实机启动或可安全刷写。

## 尚需 Linux Runner / 上游执行

| 检查 | 预期 |
| --- | --- |
| Lite workflow 完整构建 | 固定源码/feed revisions 可取，`make defconfig` 通过，Lite 包选择满足 seed，生成目标 profile 的非空 sysupgrade；最终 `build.config` 与 `selected-packages.txt` 含 `luci-app-tr3000-lite=y`、唯一 `wpad-openssl` 提供者；验证本地 LuCI 包实际编译 |
| Full workflow 完整构建 | 默认 Tailscale/sing-box 存在、cloudflared 不存在；三项开关组合与最终配置/包清单一致，LuCI 本地包可编译，镜像通过 profile/布局/tar/大小门禁 |
| U-Boot workflow | 只生成一个目标 TR3000 2025 BL2 和 multi-layout FIP；不包含 256 MiB 产物 |
| 工件完整性 | 每个固件/U-Boot 镜像的 SHA256 可在异机复核；配置、包清单、commit、feed revisions、许可证和日志随 Artifact 上传；Lite 另含无凭据 `lite-runtime-contract.txt`，与 Lite overlay 默认值和已上传配置相符，不能当作设备实测 |

## 必须在已备份的实验设备验证

1. 记录机壳版本、NAND 型号/容量、坏块、`/proc/mtd`、`ubinfo -a`、启动器版本与当前布局；所有分区备份异机保存并核验 SHA256。
2. 用 `ip link` 并逐个插拔网线/观察链路灯验证实际 WAN、plant 端口映射；核对 DTS，不得仅以 Linux 接口编号推断物理插孔。
3. 工业接口抓包确认 DHCPv4 Offer/Ack 为零，DHCPv6、RA、NDP 服务未发送；管理 AP 与 plant 不桥接。
4. Lite 隔离上电，确认 `eth1` 默认 `192.168.10.254/24`，与 `br-mgmt` 的 `192.168.77.1/24` 分离。通过可信控制台设置 root 密码、私下取得本机随机 AP 凭据；确认双 radio 加密 AP、管理网 DHCP `.100–.149`、mgmt HTTPS/SSH 和重复启动不轮换凭据。空 root 或缺 AP 标记时 plant HTTPS 必须关闭，满足两项门禁并显式启用后仅 443 可达，80/22 不开放。**接入 HUB 前人工确认 plant 地址未占用且网段适用**；不适用先隔离修改。
5. WAN DHCP 上网；依次加入已确认的 STA 和 USB 上行，验证 metric、互联网健康探测、失联切换、恢复、DNS 和 WireGuard 重新握手。
6. Lite 管理 AP PC 对无默认网关的模拟 PLC 固定 IP：默认 ICMP Echo/TCP 可达，抓包核对 SNAT 为当前 plant IP 及 conntrack 回程；关闭 mgmt 开关后拒绝，UDP/其他网段/广播发现始终拒绝。WireGuard 工业访问默认关闭，其获准 Peer/目标端口与 SNAT 的验证属于后续远程里程碑，不计为本次已实现。
7. 验证 plant、WAN 与 WireGuard 之间的主动新建连接均按默认策略拒绝；WAN 不能访问 LuCI/SSH。
8. 模拟酒店/手机上行与 plant 重叠，确认脚本阻止配置，且不安装冲突路由；模拟 ARP 地址冲突，确认 network/firewall 两文件均不变。通过“工业 LAN”验证/应用有效 CIDR，确认 mgmt 规则与 SNAT 同步变更，页面会话断开警告及真实返回状态正确。
9. 仅在隔离模拟环境验证 TIA Portal 固定 IP 单播连接；确认 DCP/LLDP/广播发现不跨三层；严禁将程序下载测试等同于生产许可。
10. 经批准的实验台断电/重启、网络断开和已验证 UART/恢复流程演练；确认恢复旧配置、保留 Factory/RF 数据和回滚步骤。
11. Lite 故障注入：候选 fw4 检查失败、network 重载失败、firewall 重载失败、应用后地址/路由缺失时，配对恢复并核验；恢复失败应返回降级状态。验证真实备份权限/保留五对、按 backup_id 恢复、HTTPS 恢复门禁、断电/重启持久性与 AP 控制台恢复，不宣称 ACID。
12. Lite 两射频实际频段、监管设置及 AP+STA 共存：STA 扫描/断线、上行故障和重连时管理 AP 保持可用；共射频短暂中断需记录。无线设备未发现或初始化失败不能留下开放 AP/成功标记。
13. Full LuCI 使用 Bootstrap；服务页只能控制固定服务，未编译项不可启用，首次启动 WireGuard listener、Tailscale、sing-box、cloudflared 都关闭。
14. Tailscale 与 WireGuard 共存不抢 plant 路由；sing-box 默认 direct 且不代理 plant/mgmt/VPN 端点；cloudflared 仅暴露 Access 保护的测试 Web 服务。
15. 执行 `singbox-rollback.sh` 后 sing-box 停止，只有 `tr3000_full_singbox_*` 防火墙段被移除，LuCI/SSH 本地管理和其他防火墙规则仍存在。

任何测试未执行都应保持“未验证”状态。不得在生产 PLC、无人值守现场或未备份设备上进行刷机、断电或程序下载实验。
