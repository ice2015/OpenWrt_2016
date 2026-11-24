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
| Full workflow 完整构建 | 默认 sing-box/cloudflared 存在、Tailscale 不存在；三项开关组合与最终配置/包清单一致，LuCI 本地包可编译，镜像通过 profile/布局/tar/大小门禁；编译前断言出厂接入段 overlay 且无工业段/无线配置 |
| U-Boot workflow | 只生成一个目标 TR3000 2025 BL2 和 multi-layout FIP；不包含 256 MiB 产物 |
| 工件完整性 | 每个固件/U-Boot 镜像的 SHA256 可在异机复核；配置、完整镜像包/版本清单 `image-packages.manifest` 及包名视图、commit、feed revisions、许可证和日志随 Artifact 上传；Lite/Full 另含最终 `profile.dts` 和无凭据的 `lite-runtime-contract.txt`/`full-runtime-contract.txt`，与各自 overlay 默认值和已上传配置相符，不能当作设备实测；`target-package-index.txt` 只是仓库索引，不得冒充已安装包清单 |
| Lite 多上行 | 固定三项 USB 网卡包、Lite 专用 daemon/库/hotplug/status 路径入镜像；UCI 默认顺序10/20/30、失败/成功阈值3/2、15秒最小轮间休眠；只读页面/窄 ACL 编译成功；Full 使用同机制的 Full 命名控制器（单 `wg` 重启语义） |

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
13. Full LuCI 默认 Argon 主题（Bootstrap 可切回）；服务页只能控制固定服务（WireGuard/Tailscale/HomeProxy/Cloudflare Tunnel），未编译项不可启用，首次启动 WireGuard listener、Tailscale、homeproxy、sing-box 本体、cloudflared 都关闭。
14. Tailscale 与 WireGuard 共存不抢路由；HomeProxy 未配节点不启动，配节点后按所选模式分流；cloudflared 仅暴露 Access 保护的测试 Web 服务。
15. 停用 homeproxy 后其 nft 链/表与 dnsmasq 片段被清理，LuCI/SSH 本地管理和其他防火墙规则仍存在。

## Full 家用路由器真机验收（F1–F14，非 CI）

| # | 用例 | 期望 |
| --- | --- | --- |
| F1 | 全新刷机（不保留配置）上电，插网线 | PC 拿到 192.168.10.x，网关 192.168.10.1 |
| F2 | `ping 192.168.10.1` | 通 |
| F3 | 浏览器 `https://192.168.10.1` | 进 LuCI（Argon 主题），可设 root 密码 |
| F4 | 连管理 WiFi | 拿到 192.168.10.x，可 ping，可进 LuCI |
| F5 | 扫描周围热点 | 看不到开放默认热点；只有 `TR3000-Full-XXXXXX` 且为 WPA2 |
| F6 | HomeProxy 配好 VLESS+WS+TLS 节点，路由模式切“智能分流” | 国内直连、指定站点走代理；LAN 客户端同样生效 |
| F7 | 路由模式切“全局” | 全部流量走代理；切“直连”后全部直连 |
| F8 | `logread \| grep -i mtwifi` | 无 `wait_for network.interface.lan` 超时错误 |
| F9 | 拔掉 WAN 网线，Wi-Fi 中继接入 | 默认路由切到 wwan，WAN 恢复后切回 |
| F10 | USB 手机共享接入 | usbwan 起，默认路由切到 usbwan |
| F11 | LuCI 启停 WireGuard / Cloudflare Tunnel / homeproxy | 状态与实际进程一致 |
| F12 | LuCI DDNS 用 Cloudflare provider | 域名解析到当前公网 IP |
| F13 | Argon 主题下切 Bootstrap | 可切换成功，重启后保持 |
| F14 | 升级本固件（保留旧配置） | 若存在旧工业配置结构，服务页明确提示并要求 `sysupgrade -n`；不自动改写配置 |

任何测试未执行都应保持“未验证”状态。不得在生产 PLC、无人值守现场或未备份设备上进行刷机、断电或程序下载实验。

## 真机验收的可执行用例（Full）

仓库提供两个可选的真机测试入口，默认全部跳过，不影响 CI：

| 入口 | 命令 | 覆盖 |
| --- | --- | --- |
| SSH 设备契约 | `TR3000_FULL_DEVICE=192.168.10.1 python -m unittest tests.device.test_tr3000_full_device -v` | 出厂网络、防火墙默认关闭、远程服务默认停止、Argon 主题、Cloudflare DDNS 模板、受管 WPA2 AP 与凭据权限、无线无超时、上行状态结构、LuCI 包落地 |
| LuCI 功能 | `TR3000_FULL_DEVICE=192.168.10.1 TR3000_FULL_LUCI_PASS=<root 密码> node tests/device/luci-functional.mjs` | 真实浏览器操作 LuCI：仪表盘与主题、TR3000 Full 服务页与按钮可用性、多上行页、HomeProxy/DDNS/Cloudflared/WireGuard 上游页、无线页受管 AP 与开放默认 AP 状态、防火墙区、主题回退项 |

SSH 入口需要免密（密钥）root 登录；LuCI 入口使用自签证书，因此忽略 HTTPS 错误。
按操作者要求（2026-11-24），后续刷入后的验收**保持出厂空 root 密码**：引导脚本只注入 SSH 公钥、不设密码；LuCI 套件在空密码下断言出厂警告存在（T1.3 的双分支）。空密码期间 LAN 内任何人可经 LuCI/ttyd 取得 root，属出厂设计（F3 要求首启设密码），验收完成后若设备转入日常使用应自行设置密码。每个用例都输出 PASS/FAIL 与证据，失败项必须回到源码修复并补回归用例，不得以“环境问题”结案，除非能给出可复现的证据。

## 2026-11-20 真机验收轮次（Full，设备固件 = 本分支 `edd3c46` 内容）

设备：MT7981 / Cudy TR3000 v1 ubi 112M，`ImmortalWrt 24.10-SNAPSHOT r0+33648-ec9ef10efc`。设备上的 `/usr/sbin/tr3000-full-*`、`/etc/init.d/tr3000-full-*` 与本分支逐字节一致（md5 相同），因此本轮结果对应本分支代码。

**已验证通过（实机）**

- 出厂网络：`lan` = `br-lan`(eth1) = `192.168.10.1/24`，DHCP `100`–`249`；`wan`/`wwan`/`usbwan` metric 10/20/30；无 `plant`、无 `mgmt`。
- 防火墙：`wg` 区、`wg → lan` 转发存在，`wg → wan` 不存在，三条 WireGuard 规则默认 `enabled 0`。
- 远程服务默认关闭：homeproxy / sing-box / cloudflared / tailscale 均未运行；HomeProxy 未配节点不启动，且不残留 nft 表、dnsmasq 片段或进程。
- 主题 Argon 生效（`luci.main.mediaurlbase=/luci-static/argon`），Bootstrap 仍可切回。
  - F13 实测通过，但 LuCI 24.10 的“系统 → 系统 → 语言和风格”页面只有 **Save**（仅暂存）：切换主题需再点顶栏 “Unsaved Changes: N” → 下拉 **Apply unchecked** 才会提交。已写入 `docs/FULL-README.md`。
  - 该暂存语义对页面上的普通字段（如主机名）同样成立，属于上游 LuCI 行为，不是本固件的缺陷。
- DDNS 出厂为禁用的 `cloudflare.com-v4` 模板，无凭据。
- `logread` 无 `wait_for network.interface.lan` 超时。

**本轮发现并已修复的缺陷（源码级修复 + 回归用例，实机未随固件复验）**

| # | 现象 | 根因 | 修复 | 回归用例 |
| --- | --- | --- | --- | --- |
| B1 | 受管 WPA2 AP 从未生成，mt_wifi 开放默认热点 `ImmortalWrt-2.4G/5G` 持续开放（F5/F4 失败） | AP 脚本把 `/tmp/.uci/wireless` 的**存在**当作“管理员未提交改动”，而 mt_wifi 每次启动都会留下 0 字节空 delta，脚本因此永久以 `pending_wireless` 退出 | 只在 delta **非空**（确有未提交改动）时拒绝；delta 路径提为变量便于测试 | `test_empty_uci_runtime_delta_does_not_block_the_management_ap`、`test_pending_uci_runtime_delta_still_blocks_the_management_ap`、`test_pending_uci_state_delta_still_blocks_the_management_ap`、`test_symlinked_uci_delta_is_rejected` |
| B2 | 同上，脚本改完仍失败 | 脚本用 `od` 生成随机密钥，而本固件 busybox **没有 `od`** applet | 改用 `sha256sum`/`md5sum`/`hexdump` 生成十六进制随机串 | `test_management_ap_does_not_depend_on_the_od_applet` |
| B3 | TR3000 Full 服务页 HomeProxy / Cloudflare Tunnel 的 “Enable” 按钮点了没反应（F11 失败） | LuCI 的 `E()` 用 `setAttribute` 渲染属性，脚本写的 `'disabled': !state.installed` 变成 `disabled="false"`，HTML 仍按“存在即禁用”处理 | 改为按需写入字符串属性 `attributes.disabled = 'disabled'`（与仓库 Lite 页面写法一致） | `test_full_services_view_keets_installed_services_actionable`、`test_local_luci_views_never_render_a_boolean_disabled_attribute` |
| B4 | 全新刷机时受管 AP 仍未生成（开放默认热点依旧开放） | `91-…-management-ap` 与 init 服务都假设 `/etc/config/wireless` 已存在；而 mt_wifi 驱动是在启动过程中异步创建该文件的，首启时两者竞争 → 控制器以 `missing_wireless` 退出，init 服务也只尝试一次 | 控制器首启最多等待 45 s；init 服务改为最多重试 12 次（间隔 10 s） | `test_ap_creation_waits_for_the_radio_driver_configuration`、`test_repair_service_retries_until_the_radio_configuration_exists` |
| B5 | 设备自身无法解析任何域名（opkg update 全败、NTP 永不同步、按域名的 wget 全败）；LAN 客户端不受影响 | Full/Lite 的 network overlay 整体重写时**丢掉了上游的 loopback 段**（设计文档 §6.2 的示例 UCI 也没有），`lo` 永不启动 → dnsmasq（bind-dynamic）绑不上 127.0.0.1，而 `/tmp/resolv.conf` 恰指向 127.0.0.1 | 两个 overlay 补回标准 loopback 段（`lo` + `127.0.0.1/8`） | `test_overlay_networks_keep_the_loopback_interface` |
| B6 | 服务页把“wg 接口未配置”误标为 “Not included in this build”（WireGuard 包实际在镜像里） | 控制器对 wireguard 的 `installed` 语义是“存在 network.wg 接口”，视图却把它与“未编译”共用一个标签 | 视图对 wireguard 单独显示 “wg interface not configured (Network → Interfaces)” | 结构测试断言视图含该分支与文案 |

B4 在 2026-11-22 的全新配置首启中被实测触发（控制器报 `missing_wireless`，而 `/etc/config/wireless` 在启动后数十秒才由 mt_wifi 驱动生成）。B5 在 2026-11-24 由“opkg update 全败”报障触发：实机 `lo` 为 DOWN、dnsmasq 未绑 127.0.0.1；热修复 loopback 后设备解析、NTP（时间从编译日跳到真实时间）与本地监听立即恢复。B1–B6 均位于 Lite/Full 共有文件或两变体同步修改（漂移守卫要求逐字一致）。B5/B6 的修复在 `84fb1d3`/`46b8a91`，**尚未进入已刷固件**，需下次构建+刷机后复验。

**opkg 软件源结论（2026-11-24 实测）**

- 镜像预置源 `mirrors.vsean.net/.../24.10-SNAPSHOT/...` 在 B5 修复后仍不可用：官方 ImmortalWrt snapshot 路径已 404（snapshot 会被镜像站定期清理），vsean 返回 302。**固定修订版本的固件不能依赖活的 snapshot 镜像**，这是 snapshot 发行模型的固有问题，不是本仓库缺陷。
- 正确源是构建自身生成的仓库（`bin/packages` + `bin/targets/.../packages`，含 `Packages.sig`）。实验室已验证完整链路：仓库上传到设备 `/tmp/repo` 并用第二个 uhttpd 实例在 `127.0.0.1:8091` 自服务 → 将构建公钥（`key-build.pub`，keyid `f690309031edcade`，文件名算法 = 公钥解码后 bytes[2:10] 的 hex）放入 `/etc/opkg/keys/` → `opkg update` 0 签名失败、12 个列表保留 → 安装/移除 htop 3.5.3-r1 成功，设备包数回到出厂 417。
- 生产化建议（未实施）：把构建仓库随 Artifact 一起发布（或内网镜像），并在文档中说明 keyid 分发步骤；`/etc/opkg.conf` 的 `check_signature` 保持开启。

B1/B2 的修复脚本已手工部署到测试设备验证：`/usr/sbin/tr3000-full-wifi repair` 返回 `ready=true, managed_aps=2, open_aps=0`，受管 AP `TR3000-Full-B515F0`（WPA2 PSK，`network=lan`）上线，开放默认 AP 变为 `disabled 1`，`/etc/config/wireless` 权限从 `0644` 收紧为 `0600`，就绪标记写入。B3 的修复视图已部署到设备验证：已安装服务的按钮 `disabled=false` 且点击后 `homeproxy` 真正变为 `enabled`（未配节点时仍不运行，无残留），随后恢复为禁用状态。

**设备刷写路径的阻塞项（2026-11-22 实测）**

本仓库的 `sysupgrade` 在这台设备上**不能完成刷写**，失败发生在上游平台脚本（`/lib/upgrade/nand.sh`），与本仓库代码无关：

- `sysupgrade -T` 通过、stage1 正常交接，但设备重启后仍是**旧固件**。
- 手动复现平台步骤得到明确错误：`ubimkvol: error 28 (No space left on device)` 与 `ubirmvol /ubiupdatevol: error 16 (Resource busy)`。
- 原因：本机 UBI 容量已被占满（`Amount of available logical eraseblocks: 0`，`rootfs_data` 占 560 LEB），而 `rootfs` 卷挂在 `/rom`、`rootfs_data` 被 overlay 引用，平台脚本的“删卷重建”在运行中的系统里必然失败。只有在 initramfs（无任何挂载）里才可能成功，而上游脚本并未把数据卷从占用状态释放。
- 另外，`/proc/mtd` 的 `u-boot-env` 分区 CRC 校验不通过（`fw_printenv` 报 `Bad CRC, using default environment`）；该状态在**刷写前**的备份里已存在，不是本次操作造成。U-Boot 仍能按 112M 布局启动，但恢复界面的地址可能落到默认 env 的 `192.0.2.1`。

结论：在本机不要反复尝试 `sysupgrade`；改用该机型文档化的 **U-Boot 网页恢复**（按住 Reset 上电 → U-Boot Web → 选 112M 布局 → 上传 ubootmod 固件包）。仓库只记录已核实的现象与命令，不提供猜测性的写入命令（见 `docs/UBOOT-SAFETY.md`）。

**Actions 重建曾受阻（2026-11-22，已解决）**：含 B4 修复的 `bf51604` 推送后，run `44989416511`（含 rerun）与 `44991385258` 均在 0 个 step 内失败，annotation 为账户计费问题，与代码无关。账户侧处理后重新触发的 run **`44998662801`** 构建成功，产物已核验并刷入设备（见下节实机验收）。

在同一 worktree 用 `scripts/build-full.sh`（与 `build-full.yml` 相同的源/feed 固定版本、`--include-tailscale false --include-singbox true --include-cloudflared true`）完成一次完整编译：

| 项 | 结果 |
| --- | --- |
| 产物 | `TR3000-128M-112M-Full-immortalwrt-mediatek-filogic-cudy_tr3000-v1-ubootmod-squashfs-sysupgrade.bin` |
| 大小 | 39,557,957 字节（37.73 MiB，低于 100 MiB 门禁） |
| SHA-256 | `7218a91dea626cdd65eb1b1cf659e97c1a54260fa00c7947d0c764bdbfec94bf` |
| 校验 | profile `cudy_tr3000-v1-ubootmod`、112 MiB DTS、sysupgrade tar 的 `CONTROL`、包清单与 `full-runtime-contract.txt` 均通过 |
| 镜像内容抽查 | `/usr/sbin/tr3000-full-wifi-ap` 含新 delta 判定与 `sha256sum` 随机源（无 `od`）；`services.js` 含 `attributes.disabled`（无布尔 `disabled`）；`/etc/config/network` 无 plant/mgmt；镜像内无 `/etc/config/wireless` |

本地 WSL2 编译注意：Windows 继承的 `PATH` 里若有 `/mnt/c/Program Files (x86)/...` 这类带空格与括号的路径，U-Boot 包把未加引号的 `PATH` 拼进 `bash -c` 会报语法错误；编译前需清洗 `PATH`（GitHub Actions 无此问题）。

**修复后的编译验证（本地 + Actions）**

Actions 产物（run `44867957843`，head `199f7885`，结论 success）：

| 项 | 结果 |
| --- | --- |
| 产物 | `TR3000-128M-112M-Full-immortalwrt-mediatek-filogic-cudy_tr3000-v1-ubootmod-squashfs-sysupgrade.bin` |
| 大小 | 39,557,957 字节（37.73 MiB，低于 100 MiB 门禁） |
| SHA-256 | `f420ceb82385bf8a5eba222c674dbb1138dc17e50b201b74d1024e109ce12428` |
| 校验 | profile `cudy_tr3000-v1-ubootmod`、112 MiB DTS、sysupgrade tar 的 `CONTROL`、包清单与 `full-runtime-contract.txt` 均通过 |
| 镜像内容抽查 | `/usr/sbin/tr3000-full-wifi-ap` 含新 delta 判定与 `sha256sum` 随机源（无 `od`）；`services.js` 含 `attributes.disabled`（无布尔 `disabled`）；`/etc/config/network` 无 plant/mgmt；镜像内无 `/etc/config/wireless` |
| 与本地构建对比 | 包清单、`full-runtime-contract.txt`、`profile.dts` 与本地编译**完全一致** |

本地编译（同参数，同一 worktree）也成功：产物 37.73 MiB，包清单/`full-runtime-contract.txt`/`profile.dts` 与 Actions 完全一致（镜像二进制 SHA-256 因构建时间戳不同而不同，属预期）。

本地 WSL2 编译注意：Windows 继承的 `PATH` 里若有 `/mnt/c/Program Files (x86)/...` 这类带空格与括号的路径，U-Boot 包把未加引号的 `PATH` 拼进 `bash -c` 会报语法错误；编译前需清洗 `PATH`（GitHub Actions 无此问题）。

**2026-11-22 官方 Artifact 实机验收（全部修复刷入后，结果：通过）**

刷写路径：`sysupgrade` 在本机结构性不可用（见上节），改用 **U-Boot 网页恢复**（Reset+上电 → multi-layout 页 → 112M 布局 → 上传镜像），由现场人员执行成功。

镜像：官方 Actions run **`44998662801`**（`bf51604`，含 B1–B4 全部修复），SHA-256 `60cecb043e0903c420665fa69bacca8c99dd66508449a965886a383b52f8d86c`，39,557,957 字节；包清单与前次官方产物一致。设备上 `/usr/sbin/tr3000-full-wifi-ap`、`services.js`、`/etc/init.d/tr3000-full-wifi` 与 Artifact 内同名文件 **md5 逐一相同**，确认设备运行的就是官方产物。

| 验收项 | 结果 | 证据 |
| --- | --- | --- |
| 首启受管 AP（B1+B2+B4 综合） | **通过** | 首启日志 0 次 `pending_wireless/missing_wireless/entropy`；`status --json` → `ready=true, managed_aps=2, open_aps=0`；就绪标记与 `ap-suffix` 已写入 |
| 开放默认热点禁用（F5） | **通过** | `ra0/rax0` 接口 DOWN；`iwinfo ra1/rax1` 实测 ESSID `TR3000-Full-C2AC7B`、`WPA2 PSK (CCMP)` 双频广播 |
| 凭据隐私 | **通过** | `/etc/config/wireless` 0600；SSID 后缀来自随机 `ap-suffix`（本机无线 MAC 不可用时回退），密钥不落日志 |
| LuCI 服务页按钮（B3/F11） | **通过** | 浏览器实测：已安装服务 `disabled=false` 可点；点击 Enable 后设备 `homeproxy enabled=true`、rc.d 创建、**未配节点不启动**（0 进程、无 nft/dnsmasq 残留）；点击 Disable 后完全恢复出厂态 |
| SSH 设备契约套件 | **12/12 通过** | `tests/device/test_tr3000_full_device.py`（网络契约/防火墙默认关/服务默认停/主题/DDNS 模板/受管 AP/凭据权限/无 mtwifi 超时/上行状态结构/LuCI 包落地） |
| LuCI 浏览器功能套件 | **35/35 通过** | `tests/device/luci-functional.mjs`（含 T10.4/T10.5 主题 Bootstrap↔Argon 往返切换并恢复，即 F13 主路径） |
| F8 mtwifi 无超时 | **通过** | `logread` 中 `wait_for network.interface.lan` 计数为 0 |
| F1 DHCP | **部分** | 配置/dnsmasq 运行正确；但测试台工作站为静态地址（.33，不在池内），本次启动无真实 DHCP 客户端证据，租约文件为空 |
| F13 重启后保持 | **未验** | 主题往返已验；“重启后保持”需一次设备重启（低风险，待安排） |
| F4 无线接入 / F6 / F7 / F9 / F10 / F12 / F14 | **未验** | F4 需无线客户端实连（需现场人工/无线网卡）；F6/F7 需真实 VLESS 节点凭据；F9/F10 需第二上行硬件；F12 需 Cloudflare 凭据与公网域名；F14 需保留旧配置升级场景（与 D12 “一律不保留配置”策略冲突，仅验证提示逻辑） |

刷写前备份（factory/fip/bl2/uboot-env/config + 旧固件卷镜像）均在 `local/backup-20261121-1246/`、`local/backup-20261122-1247-preflash/` 并经 SHA-256 核验；官方 Artifact 归档于 `output/actions-artifact-44998662801/`。

历史备注：在确认 `sysupgrade` 不可用之前的排查中，设备曾因诊断性 `pivot_root` 短暂丢失管理面（所有闪存写入均安全失败、卷完整）；后续直接经 U-Boot 恢复模式刷新固件，该状态已随刷写消失。

**仍未验证（需要额外条件，不属于代码缺陷）**

- B1–B4 同时存在于 Lite 变体的同名脚本（漂移守卫要求两份脚本逐字相同），本次按同一改动同步修复，Lite 的真机行为需单独复验。
- F1 的完整 DHCP 发现证据（需一个处于 DHCP 模式的客户端接入 LAN）；F4 无线实连；F6/F7 真实代理节点；F9/F10 第二上行硬件；F12 真实 Cloudflare 凭据；F13 的重启持久性；F14 旧配置提示场景。
