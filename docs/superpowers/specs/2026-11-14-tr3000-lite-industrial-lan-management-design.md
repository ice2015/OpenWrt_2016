# TR3000 Lite 工业 LAN、多上行与双远程入口设计

## 1. 文档状态

- 日期：2026-11-14
- 状态：已于 2026-11-15 获用户批准；实施须按对应计划逐项执行和验证
- 目标设备：Cudy TR3000 v1，128 MiB NAND，U-Boot Mod 112 MiB UBI
- 固件变体：TR3000 Lite
- 配置层：Lite 设备/变体专用层，不改变 common、通用 TR3000、Full 或其他设备

## 2. 意图

解决当前 Lite 固件刷入后没有可用本地管理入口的问题，并实现“现场人员只完成接线、上电和默认 plant 地址冲突确认，远程调试人员完成其余配置”的最少现场操作部署方式，同时保留工业网络的 DHCP 静默和管理隔离：

- Wi-Fi 作为常驻 AP，为现场调试 PC 提供独立管理网络和 DHCP；
- Wi-Fi 同时支持可选 Client/STA 上行；
- 有线 WAN、Wi-Fi Client 和默认 USB 4G 网卡按 `10/20/30` 优先级自动切换；
- 物理 LAN `eth1` 连接现场工业 HUB，带一个可修改的默认静态地址；
- LAN 地址及前缀可通过专用 LuCI“工业 LAN”页面安全修改；
- Wi-Fi 调试 PC 和已授权 WireGuard Peer 可通过三层路由及 SNAT 访问工业设备；
- 工业设备不需要配置默认网关；
- Cloudflare DDNS 作为具备公网入站条件时的首选 WireGuard 直连入口；
- TR3000 主动连接固定 VPS，作为 CGNAT、端口不可达或 DDNS 直连失败时的备用入口；
- 不把现场密码、WireGuard 密钥、VPS 地址或客户网段秘密写进仓库。

## 3. 当前事实与问题

当前 `files/etc/config/network` 将 `eth1` 定义为 `plant` 且使用 `proto 'none'`；`192.168.77.1/24` 绑定在没有成员的 `br-mgmt`。`files/etc/config/dhcp` 只在 `mgmt` 上启用 DHCP，并永久关闭 `plant` 的 DHCPv4、DHCPv6、RA 与 NDP。固件没有预置无线 AP，因此刷机后：

- LAN 不分配地址，也没有可访问的路由器 IP；
- `br-mgmt` 没有实际接入端口；
- 用户没有串口时无法进入 LuCI 完成首次部署。

现有 `plant-profile.sh` 已实现 IPv4/CIDR 校验、活动路由重叠检查、ARP 地址冲突检查、配置备份和网络重载失败回滚。新页面应调用受限后端复用这些能力，不能用 LuCI 普通接口页绕过安全检查。

## 4. 已考虑方案

### 方案 A：仅启用 Wi-Fi 管理，plant 默认无地址

最安全，不会在首次启动时与现场设备冲突；但网线不能作为首次管理入口，也不满足用户要求的出厂 LAN 管理能力。

### 方案 B：仅给 plant 设置默认静态地址

刷机后可直接通过网线管理，但没有独立 Wi-Fi 调试入口；把设备接入未知现场网段前仍存在默认地址冲突风险。

### 方案 C：Wi-Fi 与 LAN 桥接为同一管理网络

实现简单，但会把管理 DHCP 广播送入工业 HUB，并破坏管理网与工业网隔离，不采用。

### 选定方案：A 与 B 结合、保持三层隔离

Wi-Fi 提供始终可用的独立管理网络；plant 提供可修改的默认静态地址。两者不桥接。跨网段访问通过明确的 firewall4 规则和 SNAT 完成。

远程入口采用双路径：VPS 是逐台初始化、首次远程开通和 CGNAT 场景的可靠基础通道；当现场已核实具备公网 UDP 入站条件时，远程 PC 优先尝试 Cloudflare DDNS 直连，失败时手动切换到固定 VPS。两个 WireGuard 配置二选一，不同时激活。DDNS 的“主用”是条件性低延迟优化，不是所有现场都保证可用。

## 5. 默认网络拓扑

```text
                       Cloudflare DNS-only DDNS
远程 PC -- Direct WG ---------------------> TR3000 wg-direct
    |
    +-- VPS WG -- 固定公网 VPS -- outbound WG --> TR3000 wg-vps
                 （两条客户端隧道二选一）

现场上行：Ethernet WAN (10) > Wi-Fi STA (20) > USB 4G DHCP (30)
                                            |
现场调试 PC -- Wi-Fi AP/mgmt 192.168.77.1 --+-- TR3000
                                            |
                                            +-- plant 192.168.10.254/24
                                                       |
                                                  工业 HUB -- PLC/HMI
```

默认值：

- `mgmt`：`192.168.77.1/24`，仅管理 Wi-Fi AP 使用；
- `mgmt` DHCP：`192.168.77.100` 至 `192.168.77.149`；
- `plant`：`eth1`，默认 `192.168.10.254/24`；
- `plant` DHCPv4、DHCPv6、RA、NDP：始终关闭；
- `wan`：保持 `eth0` DHCP Client；
- `wwan`：可选 Wi-Fi Client/STA DHCP 上行，metric 20；
- `usbwan`：默认支持呈现为 RNDIS 或 CDC-Ether 普通网卡并通过 DHCP 上网的免驱 4G 路由棒，metric 30；
- `wg-direct`：TR3000 作为远程 PC 的 WireGuard 服务端；
- `wg-vps`：TR3000 主动连接固定 VPS 的备用出站隧道。

`192.168.10.254/24` 开机立即生效，但只是部署默认值，不能描述为适用于所有现场。现场人员在把 LAN 接入工业 HUB 前，必须人工确认该地址未占用且网段适用；若不适用，则保持 LAN 未接入 HUB，由远程人员经 VPS/LuCI 修改并确认后再接入。用户明确接受保留这一次人工冲突确认，不采用 plant 首次启动隔离模式。

## 6. Wi-Fi AP 与 Client

固件启用检测到的无线射频，并创建绑定到 `mgmt` 的管理 AP。设计约束：

- SSID 使用设备可识别但不含客户信息的名称，例如 `TR3000-Lite-<MAC后六位>`；
- 不提交通用明文密码，也不创建开放 AP；
- 对检测到且可用的 radio 幂等创建相同 SSID、相同密钥的 mgmt AP；已有非空密钥时不得在重启或升级时轮换；
- SSID 后缀优先取设备基准 MAC 的后六位十六进制字符；取不到时生成并持久化本机唯一随机后缀，不能退化为固定通用 SSID；
- 首次启动使用 `/dev/urandom` 在设备本地生成至少 128 bit、仅含安全 ASCII 的随机 WPA2 密钥，并保存为仅 root 可读配置；
- 操作员先通过隔离的 LAN 默认地址进入 LuCI，查看并立即更换管理 Wi-Fi 密钥和 root 密码，再把设备接入现场网络；
- 不硬编码国家/地区、信道或现场射频参数，沿用上游设备默认并由部署人员依法配置；
- 若无线初始化失败，LAN 默认地址仍是恢复管理入口。

管理 AP 始终开启，Wi-Fi Client/STA 是独立的可选上行开关。支持 AP-only、AP+Client 和 Client 断线但 AP 继续工作的状态；不提供会让 Client 故障顺带关闭管理 AP 的联动。Client 可由现场调试 PC 通过管理 AP/LuCI 配置，也可在发货前注入一个经过批准的标准手机热点配置。AP 与 STA 可以并存，但必须遵守硬件/驱动并发约束：

- 优先使用不同射频分别承载管理 AP 和 STA；
- 共用同一射频时，AP 信道跟随 STA，扫描、漫游或 STA 重连可能短暂中断管理 AP；
- 不猜测 `radio0`/`radio1` 的物理频段，运行时读取实际 wireless 配置并做真机验证；
- Client 使用 `wwan` DHCP、metric 20；扫描页面只允许人工选择网络，不自动连接开放或未知 SSID；
- 可以保存多个明确批准的热点配置并设置优先级，但密钥只保存在设备私有配置中；
- 没有有线 WAN 时，现场调试 PC 可先连接管理 AP，在 LuCI 选择手机热点并输入密码；`wwan` 获取网络后，TR3000 主动恢复 VPS 隧道；
- Wi-Fi Client 密钥是设备私有运行配置，不进入仓库、构建日志或 Artifact。

AP 密钥展示属于经过 LuCI 身份验证的本机管理行为，不写入构建日志、Artifact README 或公开仓库。

## 7. “工业 LAN”LuCI 页面

新增 Lite 专用 LuCI 包，建议命名为 `luci-app-tr3000-lite`，页面入口为“网络 → 工业 LAN”。不复用 Full 服务开关页面，避免把 Lite 专用网络策略提升到共享层。

### 页面显示

- 实际 plant 设备名、链路状态和当前 IPv4/CIDR；
- DHCPv4、DHCPv6、RA、NDP 永久关闭状态；
- 从 plant 访问路由器 Web 管理的状态；
- Wi-Fi 管理网访问 plant 的状态；
- WireGuard 已授权 Peer 访问 plant 的状态；
- 最近一次配置备份及应用结果，不显示任何密钥。

### 可修改字段

- plant IPv4 地址；
- 前缀长度；
- 是否允许 plant 到路由器的 HTTPS 管理；
- 是否允许 `mgmt → plant` 的 ICMP 与 TCP；
- “所有已配置 WireGuard Peer 访问 plant”的总开关及同步状态。

物理接口默认为经当前 TR3000 Lite 合同使用的 `eth1`。页面可以显示接口，但不允许在未重新执行真机端口映射核验的情况下任意切换到 WAN 设备。

### 应用前检查

后端必须按顺序执行：

1. 校验 IPv4、前缀长度以及地址不是网络号或广播地址；
2. 拒绝与 `mgmt`、WAN、活动 STA/USB 上行、WireGuard 隧道和其他活动路由重叠；
3. 确认目标设备存在且不是 WAN 设备；
4. 使用 `arping -D` 检查地址冲突；检查失败视为不安全，不能继续；
5. 备份 `/etc/config/network` 与 `/etc/config/firewall`；
6. 生成候选 UCI 配置并运行 `fw4 check`；
7. 顺序提交并重载网络与防火墙，再核对接口地址、路由和 firewall4 状态；任何阶段失败都尽力恢复两个备份并重新加载；
8. 返回版本化 JSON 供 LuCI 显示；stderr 不返回密钥、任意命令或不必要的内部路径。

该流程提供经过验证的候选配置和失败回滚，但不能宣称跨 network/firewall 的 ACID 原子性。断电、驱动异常和“重载成功但管理路径仍不可达”必须留给真机故障注入验证。

## 8. 数据面与远程入口

### Wi-Fi 管理 PC 到 plant

- 允许 `mgmt → plant` 的 ICMP Echo 和普通 TCP 单播访问当前 plant CIDR；
- 对这些连接执行 SNAT，源地址改为当前 plant IP；
- PLC/HMI 即使没有默认网关，也会把响应交回同网段的 TR3000；
- UDP 默认不开放，后续按工业协议明确增加端口白名单；
- 不转发二层广播、组播发现或任意以太网帧。

### WireGuard PC 到 plant

- 生产 WireGuard 私钥、Peer 和 VPS 信息不编入通用镜像；每台设备在发货前通过安全配置工位注入唯一配置；
- 页面使用一个总开关授权 `wg0` 中所有合规 Peer，不要求操作员逐个 Peer 开启；
- 后端分别枚举 `wg-direct` 的直接 Peer 和 `wg-vps` 路径登记的远程客户端源地址，只把精确 IPv4 `/32` 加入授权源集合；发现宽泛网段、重复地址、无 IPv4 `/32` 或无法解析的 Peer 时同步整体失败关闭并在 LuCI 报警，不能退化为放开整个 WireGuard zone；
- 总开关启用后，网络重载、WireGuard 配置变化和 plant 地址变化都会触发同步，使以后新增的合规 `/32` Peer 自动获得相同权限，删除的 Peer 自动移出授权集合；
- 授权集合内的 Peer 可使用 ICMP Echo 和普通 TCP 单播访问当前 plant CIDR；
- 每个 Peer 仍使用精确源 `/32`、当前目标 CIDR及 SNAT 到当前 plant IP；
- 修改 plant CIDR 后，后端同步重建本机规则；VPS 和远端 Peer 的路由/AllowedIPs 必须由管理者同步修改，页面明确提示但不擅自改远端系统；
- 未登记或不合规 Peer、UDP、其他目标网段及 plant 主动访问 WireGuard 继续拒绝。

### Cloudflare DDNS 直连

- 每台设备使用独立、稳定的 DNS 主机名，例如 `tr3000-001.example.com`；
- Cloudflare 记录必须为 DNS-only，不使用不能代理普通 WireGuard UDP 的 HTTP 代理模式；
- API Token 不进入仓库或通用 Artifact，在发货前注入，文件仅 root 可读，LuCI/日志不得回显完整值；
- Token 权限限制为专用 DDNS Zone 的 DNS 编辑；设备失窃或报废时可单独撤销其 Token 和 DNS 记录；
- 当前 Lite 数据面只设计 IPv4；活动上行变化后重新检测出口 IPv4 并更新 A 记录。此阶段不发布 AAAA，除非以后单独加入并验证 `wan6`、IPv6 路由、防火墙和 WireGuard 入站；DNS 更新成功不等于 UDP 入站可达；
- DDNS 只解决公网地址变化，不解决上级 NAT、CGNAT、入站防火墙或端口映射；
- 远程 PC 的 Direct 配置以设备 DDNS 名称和 WireGuard 监听端口为 Endpoint。

### VPS 备用

- `wg-vps` 从 TR3000 主动向固定公网 VPS 发起连接，适用于 CGNAT 和不可配置端口映射的现场；
- 使用独立于 Direct 的设备密钥、隧道地址和防火墙 zone，不能把两条路径混成同一个 Peer 的多个 Endpoint；
- VPS 只路由已登记远程调试 PC `/32` 到对应设备，不允许不同客户/设备横向访问；
- TR3000 对经 VPS 到达的远程 PC 仍按精确源 `/32`、当前 plant CIDR 和 SNAT 规则授权；
- 远程 PC 保存 `TR3000-<ID>-Direct` 与 `TR3000-<ID>-VPS` 两个配置，优先激活 Direct，握手失败时关闭 Direct 再激活 VPS；不得同时激活并抢占相同 plant 路由。

用户已接受 Windows 端手工二选一，不在本阶段开发自动探测/自动切换客户端。操作文档必须给出握手成功判据、关闭旧隧道、启用备用隧道和清理冲突路由的步骤。

### 远程客户端精确路由

- 两个客户端配置都包含 TR3000 对应的 WireGuard 管理 `/32` 和当前 plant CIDR；
- plant CIDR 改变后，LuCI 显示并生成新的精确 `AllowedIPs`；远程调试人员接受在 Windows WireGuard 中修改这一行；
- 客户端私钥始终在远程 PC 生成和保存，TR3000/VPS 只保存公钥；
- 不默认使用 `0.0.0.0/0`，避免把调试 PC 的普通上网流量送往现场。

### 远程 LuCI

- Direct 和 VPS 两条 WireGuard 路径分别只允许已登记 `/32` Peer访问 TR3000 本机 HTTPS 443；
- 使用各隧道的设备管理地址访问 LuCI，不通过 WAN 暴露 Web；
- WireGuard 认证不能替代 LuCI/root 登录认证，未设置 root 密码时不得启用远程 Web 管理；
- “访问工业设备”和“访问 LuCI HTTPS”使用两个独立总开关；
- 远程修改 plant 地址不会改变 WireGuard 管理地址，但页面必须提示同步客户端 plant `AllowedIPs`；
- 远程修改 WAN、WireGuard Endpoint、监听端口或密钥必须有明确失联警告和可验证回滚路径。

### 默认 USB 4G 边界

- 默认只支持表现为 RNDIS 或 CDC-Ether 普通 USB 网卡、由设备自身完成 SIM/APN/蜂窝拨号并向 TR3000 提供 DHCP 的免驱 4G 路由棒；
- 不默认加入 QMI、MBIM、NCM、传统串口拨号、ModemManager、`usb-modeswitch` 或厂商专用包；
- hotplug 只能从已支持驱动和明确的 netdev 关系识别 `usbwan`，不能根据猜测的固定 `usb0` 名称抢占任意网卡；
- 实际 USB 棒若不呈现为上述网卡类型，必须按准确型号/USB ID 另行设计和验证。

### plant 到路由器和其他网络

- 默认允许 plant 客户端访问路由器 HTTPS/LuCI；HTTP 仅可用于本机重定向到 HTTPS，不开放 WAN 管理；
- SSH 是否从 plant 开放不在本次范围内，保持关闭；
- plant 不得主动访问 `mgmt`、WireGuard 或 WAN；
- `mgmt` 与 `plant` 不桥接，管理 DHCP 不会进入工业 HUB。

“普通 TCP 访问”在本设计中指已知目标 IPv4 的三层单播 TCP，不保证依赖 PROFINET DCP、广播扫描或其他二层发现机制的工程软件自动发现设备。此类需求需单独设计，不能通过扩大当前转发规则隐式实现。

## 9. 后端与权限边界

新增一个参数受限的 root 后端，例如 `/usr/sbin/tr3000-lite-plant`，提供：

- `status --json`：只读返回当前 plant 状态与策略；
- `validate --address CIDR`：运行格式、路由和 ARP 检查，不写配置；
- `apply --address CIDR ...`：执行原子应用与回滚；
- `restore --backup ID`：仅恢复后端创建且通过路径/所有者检查的备份。

另由同一受限后端或专用同步入口在 network/WireGuard reload 后重建 Direct 与 VPS 两条路径的授权 Peer 集合。同步必须先生成候选集合并完整校验，再替换活动规则；任何一个 Peer 不合规时保留默认拒绝，不留下部分授权状态。

LuCI ACL 只允许执行这个固定后端，不授予任意文件读写、任意 shell 或通配路径权限。固定可执行文件不代表参数天然安全：后端必须拒绝未知/重复选项、路径值、非精确 Peer、WAN 设备和所有未通过格式校验的输入。后端复用 `lite-common.sh` 和 `plant-profile.sh` 的校验函数，并把网络与防火墙作为一次受控变更处理，避免地址已改变而旧 SNAT/目标 CIDR 仍然生效。

后端使用原子锁阻止 `apply`/`restore` 并发交错；备份权限为 `0600`，拒绝符号链接和任意路径，备份 ID 只接受固定字符集，并最多保留最近五组 network/firewall 配对备份。

## 10. 配置层与预计文件

仅修改 TR3000 Lite 相关路径。根 `files/` 当前同时被 Lite 和 Full 复制，因此不能直接在共享根 overlay 中实现本设计；必须增加 Lite 专用 overlay，并由 `configure-lite.sh` 在共享文件之后覆盖：

- `overlays/devices/tr3000-lite/files/etc/config/network`：默认 plant 静态地址；
- `overlays/devices/tr3000-lite/files/etc/config/firewall`：受控的本机管理、mgmt/授权 WG 到 plant 基础策略；
- `overlays/devices/tr3000-lite/files/etc/config/dhcp`：保持 plant DHCP/RA 关闭，并关闭 odhcpd 的 NDP proxy/服务；
- `overlays/devices/tr3000-lite/files/etc/uci-defaults/`：首次启动安全创建管理 AP 与随机密钥；
- `packages/luci-app-tr3000-lite/`：LuCI 页面、菜单和最小 ACL；
- `scripts/`：plant 状态、校验、原子应用、Direct/VPS 授权同步、Cloudflare DDNS 状态和多上行同步；
- `configs/lite.seed`、`scripts/configure-lite.sh`：像 Full 本地 LuCI 包一样把 Lite 包复制进源码树，在 `make defconfig` 后检查必需包，并最后安装 Lite overlay 与后端；
- `tests/`、`docs/LITE-README.md`、`docs/TEST-PLAN.md`、`docs/cudy-tr3000-uboot-flashing-record.md`：更新旧的“plant 默认无 IP、没有 AP、mgmt 不可到 plant”合同、操作说明和验收用例。

不得修改通用 manifests 中仍为 `UNRESOLVED` 的 TR3000 目标，也不得把本改动放进 common 或 Full。

## 11. 错误处理与恢复

- 表单校验失败或 ARP 检查不确定时不写配置；
- 地址变更前同时备份 network/firewall，备份使用 `0600` 权限且不含 Wi-Fi/WireGuard 密钥输出；
- `fw4 check`、网络重载或防火墙重载失败时恢复两份配置；
- 页面在地址改变后显示新的 LAN URL，并提醒当前浏览器连接可能中断；
- 修改 plant 网段不自动修改远端 VPS、其他路由器或 WireGuard Peer；页面列出需要同步的 CIDR；
- U-Boot 恢复入口与 112 MiB U-Boot Mod 系统镜像边界保持不变。
- 发货前必须在安全配置工位设置非空 root 密码、确认随机 Wi-Fi 密钥、注入唯一 VPS/WireGuard/Cloudflare DDNS/设备身份配置，并验证 VPS 远程 LuCI；实施阶段还须核实固定上游源码首次登录是否允许空 root 密码并设置硬门禁。
- 通用 CI Artifact 本身不含生产凭据，不能直接从公开 Artifact 下载后不经逐台配置就投入现场。
- 现场人员至少完成电源、可通过 DHCP 上网的 WAN（或已预配可用 Wi-Fi/USB 上行）、默认 plant 地址人工冲突确认和工业 HUB LAN 接线；没有任何互联网出口时远程管理不可能建立。

## 12. 安全配置工位与交付

用户已确认每台设备发货前必须经过一次安全配置工位初始化。通用 CI Artifact 与可现场使用设备之间的流程为：

1. 下载同一次成功 Actions 运行的 Lite sysupgrade、SHA256 和构建记录并校验；
2. 在已核实的 TR3000 v1、128 MiB、112 MiB U-Boot Mod 设备上安装并首次启动；
3. 设置唯一非空 root 密码，确认未完成此步骤前 Direct、VPS远程 LuCI 和 plant LuCI 均不开放；
4. 生成并保存设备唯一身份、Direct WireGuard 密钥、VPS WireGuard 密钥和隧道地址；
5. 在 VPS 登记设备公钥、精确路由和客户隔离规则；
6. 注入设备唯一 Cloudflare hostname 和受限 API Token；Token 只能作用于专用 DDNS Zone，完整值不进入日志或设备台账明文导出；
7. 确认随机管理 AP 密钥，必要时注入已批准的标准热点 Client 配置；
8. 从独立远程测试端实际通过 VPS 打开 LuCI、检查设备身份、上行、WireGuard 和回滚入口；
9. 生成 Direct/VPS 两个 Windows 客户端模板；客户端私钥在 Windows 端生成，工位只登记公钥；
10. 将设备 ID、公钥、分配地址、hostname、凭据撤销标识和恢复记录写入访问受控的私有设备台账；不保存可直接复用的客户端私钥；
11. 设备报废或遗失时撤销其 VPS Peer、Cloudflare Token/DNS 记录及所有远程 Peer。

设备数量、VPS 公网地址、Cloudflare Zone、设备/Peer 地址池和实际客户分组属于部署输入，不写死在固件。实施提供参数化且拒绝重复分配的工位工具/模板；缺少这些生产输入时只能完成固件与演示配置验证，不能宣称生产远程入口已部署。

## 13. 测试与验收

### 仓库和单元测试

- plant 默认地址、DHCP 静默和 mgmt/plant 不桥接的结构测试，并证明 Full 的共享 rootfs 行为未改变；
- 有效/无效 CIDR、网络号、广播地址、重叠路由和 ARP 失败测试；
- WireGuard 总开关、多个精确 `/32` Peer、新增/删除 Peer 自动同步，以及宽泛/重复/无效 AllowedIPs 失败关闭测试；
- Direct/VPS 两个独立接口、zone、管理地址和客户端路由不冲突测试；
- Cloudflare DNS-only 配置、Token 输出脱敏、上行切换更新触发和 CGNAT 不误报直连可用测试；
- AP 与 STA 配置共存、STA 重连不永久删除 AP、WAN/wwan/usbwan `10/20/30` 切换回归测试；
- RNDIS/CDC-Ether hotplug 只认明确 USB netdev、拔插和 DHCP 失败回退测试；
- 多上行状态机使用锁和 netifd 可控配置/metric，不与 DHCP renew 并发直接抢删默认路由；验证滞回、事件去抖和恢复顺序；
- 空 root 密码、未注入唯一密钥/设备身份、重复地址或缺少 VPS/Cloudflare 参数时，远程入口失败关闭测试；
- 工位工具重复运行幂等、设备地址/hostname 重复拒绝、凭据输出脱敏、撤销记录和 sysupgrade 后保留/清除策略测试；
- network/firewall 双配置回滚测试；
- LuCI menu、ACL、固定后端路径和禁止任意文件权限测试；
- Lite 最终 `.config` 包含 `luci-app-tr3000-lite` 及所需依赖；
- Lite 配置合并、必需包和排除包回归测试；
- 运行 `bash scripts/validate.sh`；
- 运行 `python -m unittest discover -s tests -v`。

### GitHub Actions

- 完整构建 TR3000 Lite；
- 检查 Artifact 中最终 `build.config`、包清单、镜像 SHA-256 和非空 sysupgrade；
- 确认镜像仍匹配 `cudy_tr3000-v1-ubootmod` 与 112 MiB UBI；
- 检查镜像大小和可写 overlay 余量。

### 真机验收

1. 隔离环境首次启动，通过默认 plant IP 进入 LuCI；
2. 设置 root 密码和新的 Wi-Fi 密钥，确认 AP 为 WPA2 且 mgmt DHCP 正常；
3. 修改 plant CIDR，确认地址冲突时拒绝应用、成功时规则同步；
4. 确认工业 HUB 上没有 DHCPv4 Offer/Ack、DHCPv6、RA 或 NDP 服务广告；
5. Wi-Fi PC Ping 并用 TCP 连接已知工业设备 IP；确认设备看到源地址为 TR3000 plant IP；
6. 通过 Cloudflare DDNS Direct 和 VPS 备用分别完成远程 LuCI、Ping、TCP 与 SNAT 测试，并验证两个 Windows 隧道二选一；
7. 启用一次 WireGuard 总授权后，所有合规 `/32` Peer完成相同测试；新增/删除 Peer 自动同步，宽泛或无效 AllowedIPs 导致同步失败关闭；
8. 依次断开/恢复 Ethernet WAN、Wi-Fi STA 和 RNDIS/CDC-Ether USB 4G，验证 `10/20/30` 收敛、DDNS 更新及 VPS 隧道重连；
9. plant 设备不能主动访问 mgmt、WireGuard 或 WAN；
10. 验证二层发现不被误描述为可用；
11. 网络或防火墙应用失败时可恢复旧配置；
12. 重启、断电恢复及 U-Boot 恢复入口不受影响。

## 14. 非目标与未验证项

- 通用固件不预置生产 WireGuard 密钥、VPS、Peer、Cloudflare Token 或客户路由；生产值只由已确认的安全配置工位流程逐台注入；
- 不实现 IPv6 DDNS/AAAA、`wan6` 或 IPv6 WireGuard 入站；本阶段 Cloudflare DDNS 只更新 IPv4 A 记录；
- 不把 Cloudflare Token、设备 DDNS 主机名清单或生产 VPS 凭据提交到仓库；
- 不允许 Wi-Fi 与 plant 二层桥接；
- 不开放 plant DHCP、RA 或 odhcpd NDP proxy/服务；不能承诺消灭链路正常工作所需的全部 IPv6 Neighbor Discovery 帧；
- 不实现 PROFINET DCP、广播或组播跨网段代理；
- 不修改 BL2、FIP、U-Boot 或分区布局；
- 不承诺未知 QMI/MBIM/NCM/串口 USB Modem 兼容性；默认 USB 4G 仅指 RNDIS/CDC-Ether DHCP 网卡模式；
- 不保证 DDNS Direct 在 CGNAT、未配置上级端口映射或入站 UDP 被阻止的现场可用；这些现场使用 VPS 路径；
- 当前 Windows 环境不能完成固件编译；无线射频命名、物理端口映射、随机 AP 首启、实际 SNAT 和恢复仍需 GitHub Actions 与 TR3000 真机验证。

