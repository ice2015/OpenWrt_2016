# TR3000 Lite / Full 测试计划

## 仓库/CI 层检查（逐次记录执行结果）

- `bash scripts/validate.sh`
- `python -m unittest discover -s tests -v`
- `sh -n` 对 Lite shell 脚本语法检查
- CI 在构建时检查固定 commit、feed commit、唯一目标 profile、112 MiB DTS 值和镜像文件名/非空状态；Lite 还检查 sysupgrade tar 的目标 `CONTROL`、100 MiB 上限、实际镜像必需包及 Ruby/额外 USB 网卡排除项；U-Boot CI 检查 128 MiB multi-layout 的 BL2/FIP 输出名。
- Full CI 额外检查 sysupgrade tar 的目标 `CONTROL`、100 MiB 安全上限、可选包与输入一致，并输出 `TR3000-128M-112M-Full` 工件。

这些是预期的自动化检查；仅当相关命令实际通过后才可标为已执行。它们不证明固件能在实机启动或可安全刷写。

## 尚需 Linux Runner / 上游执行

| 检查 | 预期 |
| --- | --- |
| Lite workflow 完整构建 | 固定源码/feed revisions 可取，`make defconfig` 通过，Lite 包选择满足 seed，生成目标 profile 的非空 sysupgrade；最终 `build.config` 与 `selected-packages.txt` 含 `luci-app-tr3000-lite=y`、唯一 `wpad-openssl` 提供者；验证本地 LuCI 包实际编译 |
| Full workflow 完整构建 | 默认 Tailscale/sing-box 存在、cloudflared 不存在；三项开关组合与最终配置/包清单一致，LuCI 本地包可编译，镜像通过 profile/布局/tar/大小门禁 |
| U-Boot workflow | 只生成一个目标 TR3000 2025 BL2 和 multi-layout FIP；不包含 256 MiB 产物 |
| 工件完整性 | 每个固件/U-Boot 镜像的 SHA256 可在异机复核；配置、完整镜像包/版本清单 `image-packages.manifest` 及包名视图、commit、feed revisions、许可证和日志随 Artifact 上传；Lite 另含最终 `profile.dts` 和无凭据 `lite-runtime-contract.txt`，与 Lite overlay 默认值和已上传配置相符，不能当作设备实测；`target-package-index.txt` 只是仓库索引，不得冒充已安装包清单 |
| Lite 多上行 | 固定三项 USB 网卡包、Lite 专用 daemon/库/hotplug/status 路径入镜像；UCI 默认顺序10/20/30、失败/成功阈值3/2、15秒最小轮间休眠；只读页面/窄 ACL 编译成功，不改变 Full 的旧 watcher |

## 已有证据与后续构建的界限

第一阶段 `012dfec` 的 [Actions 43731565747](https://github.com/ice2015/OpenWrt_2016/actions/runs/43731565747) 已成功。下载 sysupgrade 的 SHA256 已复核，tar `CONTROL` 匹配目标，实际 Squashfs 中第一阶段控制器/库/network/dhcp/firewall/AP defaults/LuCI 源码与提交逐字节匹配；实际 opkg 状态有 Lite LuCI 和 `wpad-openssl`，无 Ruby/libruby。这不证明第二/第三阶段已编译，也不证明设备能启动或 RF/路由可用。每一新里程碑需记录对应新 SHA 的成功构建，不能沿用这次历史镜像作验收。

## Lite 多上行自动化覆盖（离线，不等于内核/真机实测）

- 真实 shell 脚本对受控 UCI/netifd/探测输入：3失败/2成功和可调阈值、替代 IP 探测、无网关/默认路由、DHCP 续租/重新安装基础路由、精确源地址与缺省源地址、旧网关清理、无重复路由。
- 对内核路由操作的 double 模拟“metric 属于路由键”：只替换/清理当前租约和拥有日志中的精确 tuple；外部路由和优先级冲突不被覆盖，更优外部默认路由触发警告、不误报活动 WAN；检查命令失败不冒充所有链路断开。
- 实际临时 sysfs 链接：只接管 USB 父设备的 `rndis_host`/`cdc_ether`，拒绝 PCI/虚拟/NCM/QMI/MBIM/缺驱动、非法 VID/PID 和路径逃逸；双候选失败关闭，移除后收敛，既有手工/受保护接口不被抢占。
- 原子锁、跨 plant/USB 的 network 文件串行、插入期间拔出、过期 remove 在重插后到达、重复事件、长 plant 事务导致事件等待超时后的守护进程重扫；失败时恢复原 network，不删除其他进程锁。
- AP/STA 共存配置不轮换 AP 凭据；只读状态接口的参数/字段白名单、无无线密钥/令牌输出；UBus/iwinfo 的 radio/实际 PHY/信道被选择性读取，未知值不从名字猜测。Node 执行真实页面 load/render，检查窄 ACL、标准 LuCI 导航、状态/回滚警告和非预期返回脱敏。
- Lite 双 WireGuard 与 DDNS 离线自动化覆盖：
  - 空 root 密码门禁：root 密码未设或密码为空时，控制器拒绝任何 Direct 监听与远程同步；
  - 未入网状态阻断：缺少 `/etc/tr3000-lite/enrolled` 时，WAN UDP 51820 保持关闭，拒绝建立外部规则；
  - 清单重复与非法输入测试：重复设备 ID、重叠 IP 段、非法 Base64 密钥格式被 `tools/tr3000_lite_provision.py` 立即拒绝；
  - 源地址精确白名单：任何非 `/32` 源地址（如 `0.0.0.0/0`、`/24`、组播/环回）在控制器解析阶段立即撤销全部候选规则，绝不放行宽网段；
  - Cloudflare DDNS 脱敏与异常状态处理：Token 与完整 URL 严禁进入返回 JSON 或日志；私网/CGNAT WAN 正确报告 `private_or_cgnat` 并阻止无效公网更新；API 速率超限或网络超时返回 `error` 且不崩溃；
  - 凭据脱敏核验：测试套件遍历所有控制器、RPC 输出、状态文件与构建工件，断言无任何真实私钥或明文 Token 泄漏。

## 必须在已备份的实验设备验证

1. 记录机壳版本、NAND 型号/容量、坏块、`/proc/mtd`、`ubinfo -a`、启动器版本与当前布局；所有分区备份异机保存并核验 SHA256。
2. 用 `ip link` 并逐个插拔网线/观察链路灯验证实际 WAN、plant 端口映射；核对 DTS，不得仅以 Linux 接口编号推断物理插孔。
3. 工业接口抓包确认 DHCPv4 Offer/Ack 为零，DHCPv6、RA、NDP 服务未发送；管理 AP 与 plant 不桥接。
4. Lite 出厂可达性（对应接入段设计的 T1–T10）：
   - **T1** 全新刷机（不保留配置）上电，插网线：PC 拿到 `192.168.10.x`，网关与 DNS 均为 `192.168.10.1`；
   - **T2** `ping 192.168.10.1` 通；
   - **T3** 浏览器 `https://192.168.10.1` 进 LuCI，可设置 root 密码；
   - **T4** 连管理 AP：拿到 `192.168.10.x`，可 ping 通、可进 LuCI；密钥从 `0600` 的 `/etc/config/wireless` 私下读取；
   - **T5** 扫描周围热点：没有 `ImmortalWrt-2.4G/5G` 开放热点，只有 `TR3000-Lite-<MAC>` 且为 WPA2；
   - **T6** `logread | grep -i mtwifi`：没有 `wait_for network.interface.lan` 超时错误；
   - **T7** LuCI「启用 plant 模式」：成功；插线 PC 不再获得地址、ping 不通路由器；WiFi 管理仍可达；plant 地址 `192.168.20.254/24` 无 DHCP；
   - **T8** LuCI「退回接入模式」：成功；插线重新获得 `192.168.10.x`；
   - **T9** 断电重启（保留配置）：模式与地址保持，管理 AP 仍受管且加密、凭据不轮换；
   - **T10** 用旧版 Lite 配置升级本固件（保留设置）：启动日志与 LuCI 顶部出现“旧版配置结构”提示，不自动改写配置。
   空 root 密码时 plant HTTPS 必须关闭；满足“非空 root 密码 + 显式启用”后仅 443 可达，80/22 不开放。**接入 HUB 前人工确认 plant 地址未占用且网段适用**；不适用先隔离修改。
5. WAN DHCP 上网；从标准 LuCI 加入明确批准的加密 STA（保留管理 AP，禁用替换无线配置选项、显式启用 wwan），再加入已核验 RNDIS/CDC-Ether USB 路由棒。验证10/20/30、3失败/2成功、恢复抢占、DHCP/网关与 DNS。
6. Lite 双 WireGuard 与两阶段入网真机全流程验证：
   - 从纯净固件镜像启动，本地控制台生成 `prepare` 指纹；在离线工作站渲染生成特定设备 bundle；
   - 执行 `tr3000-lite-enroll apply`，验证私钥权限 `0600`、UCI 规则合并与 nftables 规则链链首 prepend 注入；
   - VPS 路由与握手：在以太网、STA 及 4G RNDIS 路由棒三种上行场景下分别验证 VPS 出站握手自愈，确认 `PersistentKeepalive = 25` 保持打洞，远程通过 VPS 访问 LuCI 后台与 SSH；
   - Cloudflare DDNS：在具备真实公网 IPv4 的宽带线路上验证 DDNS A 记录更新，确认 gray-cloud（DNS-only）生效，Direct 端口可达；
   - Direct 故障及手动切换：模拟公网断开或 DDNS 故障，在工程师终端关闭 Direct 隧道并切换至 VPS 隧道，确认通信恢复，验证双通道互斥原则；
   - 现场工业网段变更：在 LuCI 修改 plant 网段为 `192.168.20.0/24`，核验控制器自动更新 SNAT 目标网段，并在客户端同步修改 AllowedIPs 后恢复对新子网 PLC 的访问；
   - 吊销与断电恢复：在 VPS 端注销 Peer 及 Cloudflare 吊销 Token，确认网关自动阻断未授权访问；执行硬断电重启，确认所有权限配置完整持久化保存。
6. 接入段 PC 对无默认网关的模拟 PLC 固定 IP：默认 ICMP Echo/TCP 可达，抓包核对 SNAT 为当前 plant IP 及 conntrack 回程；关闭接入段放行开关后拒绝，UDP/其他网段/广播发现始终拒绝。WireGuard 工业访问默认关闭，其获准 Peer/目标端口与 SNAT 的验证属于后续远程里程碑，不计为本次已实现。
7. 验证 plant、WAN 与 WireGuard 之间的主动新建连接均按默认策略拒绝；WAN 不能访问 LuCI/SSH。
8. 模拟酒店/手机上行与 plant 重叠，确认脚本阻止配置，且不安装冲突路由；模拟 ARP 地址冲突，确认 network/firewall 两文件均不变。通过“工业 LAN”验证/应用有效 CIDR，确认接入段规则与 SNAT 同步变更，页面会话断开警告及真实返回状态正确。
9. 仅在隔离模拟环境验证 TIA Portal 固定 IP 单播连接；确认 DCP/LLDP/广播发现不跨三层；严禁将程序下载测试等同于生产许可。
10. 经批准的实验台断电/重启、网络断开和已验证 UART/恢复流程演练；确认恢复旧配置、保留 Factory/RF 数据和回滚步骤。
11. Lite 故障注入：候选 fw4 检查失败、network 重载失败、firewall 重载失败、应用后地址/路由缺失时，配对恢复并核验；恢复失败应返回降级状态。验证真实备份权限/保留五对、按 backup_id 恢复、HTTPS 恢复门禁、断电/重启持久性与 AP 控制台恢复，不宣称 ACID。
12. Lite 两射频实际频段、监管设置及 AP+STA 共存：STA 扫描/断线、上行故障和重连时管理 AP 配置保持，实测共射频短暂中断并记录持续时间；不得宣称 RF 无间断。对比只读页实际 PHY/信道与工具查询结果，无 iwinfo 时显示未知。无线设备未发现或初始化失败不能留下开放 AP/成功标记。
    - 依次断开/恢复有线、STA、USB；在阈值等待和 DHCP renew/网关变化期间核对实际内核路由，无重复/外部路由误删。人为配置更优外部默认路由，应保留且页面明确不宣称托管出口。
    - 使用屏蔽公共 ICMP 的实验上行，配置允许的替代探测目标；验证不会无休止抖动，恢复轮数符合配置，不能用单次 ping 成败代表互联网或 VPS 可达。
    - 插入不支持的 USB、两台受支持 USB、快速拔插及重插后旧 remove；确认不抢占无关网卡，双候选失败关闭，移除多余候选后恢复。对照 VID/PID/驱动、实际绑定和 DHCP。
    - 在 plant 网络变更持锁时插 USB 并持续到事件等待超时，释放后确认正常守护轮次重扫恢复，不覆盖 plant network/firewall 事务。注入 UCI/网络重载/ifup 失败并检查配置恢复及诊断。
    - 关闭管理 AP、丢失状态文件、损坏诊断 JSON 或使稳定切换通知失败，只读页应显示明确未知/错误，不泄漏密钥、不修改配置。验证重启/停启服务和断电恢复后的路由拥有日志及 USB 重扫行为。
13. Full LuCI 使用 Bootstrap；服务页只能控制固定服务，未编译项不可启用，首次启动 WireGuard listener、Tailscale、sing-box、cloudflared 都关闭。
14. Tailscale 与 WireGuard 共存不抢 plant 路由；sing-box 默认 direct 且不代理 plant/接入段/VPN 端点；cloudflared 仅暴露 Access 保护的测试 Web 服务。
15. 执行 `singbox-rollback.sh` 后 sing-box 停止，只有 `tr3000_full_singbox_*` 防火墙段被移除，LuCI/SSH 本地管理和其他防火墙规则仍存在。

任何测试未执行都应保持“未验证”状态。不得在生产 PLC、无人值守现场或未备份设备上进行刷机、断电或程序下载实验。
