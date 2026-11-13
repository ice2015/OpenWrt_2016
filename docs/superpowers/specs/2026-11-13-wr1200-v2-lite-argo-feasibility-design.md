# Cudy WR1200 2.0 Lite 工业远程维护与 ARGO 可行性方案

## 1. 文档状态

- 日期：2026-11-13
- 状态：设计与可行性结论；不授权实施
- 精确设备：Cudy WR1200 2.0
- 结论：**No-Go——不建议在该硬件上实现用户要求的完整 Lite + 本机 ARGO 客户端方案**
- 本文不修改 manifest、配置、脚本、工作流或固件，不执行构建、下载、刷写或真机操作

## 2. 用户目标

目标是把低成本 Cudy 路由器批量下发至工业现场，提供：

- LuCI 管理
- WireGuard 工业远程维护
- 管理网、工业网与上行网络隔离
- 有线/Wi-Fi/USB 上行检测与切换
- USB 网卡上行
- 基础网络诊断
- 在 OpenWrt 本机运行 ARGO/Cloudflare Tunnel 客户端 `cloudflared`，当 WireGuard 或普通管理路径出现问题时，经 Cloudflare Access 远程进入该路由器的 LuCI/SSH

ARGO 只作为路由器自身的应急管理入口，不承载 PLC/HMI 日常业务流量，也不发布整个工业网段。

## 3. 已核实硬件事实

用户提供的截图与 Cudy 官方 WR1200 2.0 产品资料一致：

| 项目 | WR1200 2.0 |
| --- | --- |
| CPU | 580 MHz 单核，MIPS24KEc（官方数据表标示 MT7628） |
| Flash | 8 MB（64 Mbit）NOR |
| RAM | 64 MB（512 Mbit）DDR2 |
| Wi-Fi | 2.4 GHz 300 Mbps + 5 GHz 867 Mbps，2×2 |
| Ethernet | 5个10/100 Mbps端口，1 WAN + 4 LAN |
| USB | 官方接口清单未列出USB端口 |
| 官方固件下载包 | 约7.09–7.21 MB；下载包大小不能直接等同闪存占用，但说明容量极紧 |

参考：

- Cudy WR1200 2.0 官方规格：https://www.cudy.com/de-de/products/wr1200-2-0
- Cudy WR1200 2.0 官方下载中心：https://www.cudy.com/en-us/pages/download-center/wr1200-2-0
- Cudy WR1200 数据表：https://www.cudy.com/cdn/shop/files/WR1200_2.1_Datasheet_NEW.pdf

目前未从 OpenWrt 官方设备树和硬件表中核实到 WR1200 2.0 的原生设备 profile、分区定义、安装镜像或恢复流程。它不能套用 TR1200 v1 的 `cudy_tr1200-v1` profile，也不能套用 WR1000、WR1300 或 TR3000 的 profile。以下值必须保持 `UNRESOLVED`：

- OpenWrt target/subtarget/profile
- 精确闪存分区布局
- Wi-Fi 5 GHz 芯片及校准数据位置
- 交换机/VLAN端口映射
- Factory/sysupgrade产物规则
- 厂商签名、首次安装和恢复方式

在这些值被精确核实前，任何自定义固件都不是可刷写产物。

## 4. 直接 ARGO 客户端的容量结论

OpenWrt 24.10 的 `mipsel_24kc` 软件包仓库中，`cloudflared_2025.5.0` IPK 大约为 **7977.6 KB**：

https://downloads.openwrt.org/releases/packages-24.10/mipsel_24kc/packages/

WR1200 2.0 的整个 NOR 只有 8 MB，其中还必须容纳：

- Bootloader和环境区
- Factory/校准数据
- Linux内核
- 根文件系统
- 网络、Wi-Fi、交换机和防火墙组件
- LuCI
- WireGuard
- 可写overlay及配置

因此 `cloudflared` 包本身已经接近或超过整机可用于固件的空间，不可能再与完整OpenWrt系统及上述功能共同放入内部闪存。即使自行裁剪、UPX压缩或使用定制Go构建，也不能形成适合批量现场交付的可维护余量；运行时还会给64 MB RAM和580 MHz单核CPU带来显著压力。

**结论：WR1200 2.0 内部闪存方案中，本机 `cloudflared` 是确定性 No-Go，不进入构建试验。**

## 5. USB功能结论

用户要求USB网卡作为备用上行，但WR1200 2.0官方规格只列出5个百兆RJ45端口，没有USB Host端口。因此：

- 不能按TR1200/TR3000的方式加入RNDIS/CDC-Ether USB上行；
- 不能用USB存储做extroot来容纳`cloudflared`；
- 不考虑焊接USB、改板或使用未经核实的内部测试点，批量交付不接受此类硬件改造。

**结论：USB网卡能力在WR1200 2.0上也是硬件No-Go。**

## 6. 其余 Lite 能力评估

即使移除ARGO和USB，8 MB Flash / 64 MB RAM对现代OpenWrt仍非常紧张；而WR1200 2.0的官方原生OpenWrt支持尚未核实。

| 功能 | 判断 |
| --- | --- |
| 基础路由、防火墙、VLAN | 理论可行，但依赖设备profile和交换机映射 |
| WireGuard | 算法和包本身可在MT7628级设备运行，但存储、吞吐与稳定性需实测 |
| LuCI | 可能需要极限精简；与完整诊断、WireGuard共同存在时余量风险高 |
| 工业网隔离 | 逻辑可设计，但必须先核实物理端口、交换机和VLAN映射 |
| 上行检测 | 轻量POSIX shell可以实现，但不能弥补硬件和profile缺口 |
| 基础诊断 | 只能保留极小子集 |
| OpenSSH/SFTP | 不适合；即使实验也应优先Dropbear |
| `cloudflared` | 内部Flash确定不可行 |
| USB网卡 | 无USB Host，确定不可行 |

该设备即使做“无ARGO、无USB的极简WireGuard网关”，也属于需要新增原生设备支持、恢复路径研究和高风险容量裁剪的独立研发项目，不应描述为TR3000 Lite移植。

## 7. 方案比较

### 7.1 方案A：WR1200 2.0完整Lite + 本机ARGO + USB

不满足硬件边界：8 MB Flash无法容纳`cloudflared`与系统，设备没有USB Host，且上游profile未核实。

**结论：否决。**

### 7.2 方案B：WR1200 2.0极简WireGuard网关

删除ARGO、USB、OpenSSH/SFTP和大部分诊断/LuCI组件，只保留最小OpenWrt、Dropbear、WireGuard、防火墙和轻量上行检测。

优点是可能利用现有廉价硬件；缺点是仍需开发并验证WR1200 2.0原生支持，容量余量极小，没有第二应急通道，不满足用户原始功能清单。

**结论：只能作为研究样机方向，不建议批量现场产品化。**

### 7.3 方案C：WR1200保持厂商固件，另设现场管理代理

在现场独立Linux工控机、边缘主机或其他受支持设备上运行`cloudflared`和WireGuard，WR1200只承担普通网络接入。

优点是不刷写未知profile；缺点是增加现场设备和依赖，也无法证明厂商固件能满足工业隔离、精确SNAT和批量安全管理要求。

**结论：只有现场已经存在可靠边缘主机时才考虑。**

### 7.4 方案D：更换硬件

选择具备以下最低条件的设备：

- OpenWrt官方支持且有精确设备profile、Factory/sysupgrade和恢复文档；
- 至少32 MB Flash仅适合作为试验下限；若必须内置`cloudflared`，建议128 MB NAND/eMMC级别；
- 至少128 MB RAM，建议256 MB以上；
- 明确的USB Host接口，若USB手机/网卡上行是产品要求；
- 可稳定采购且硬件版本可锁定；
- 有本地恢复、串口或可靠的TFTP/救援机制。

TR3000级别的128 MB NAND、512 MB RAM设备更符合“LuCI + WireGuard + 工业隔离 + 多上行 + USB + 基础诊断 + 本机ARGO”的组合要求。

**结论：推荐。**

## 8. 推荐产品决策

1. 不为WR1200 2.0启动完整Lite + ARGO开发，不制作也不刷写试验固件。
2. 如果已经采购WR1200 2.0，只将其视为普通消费级路由器或极简研究对象，不作为完整工业远程维护终端。
3. 如果本机ARGO和USB上行是硬需求，直接切换至128 MB NAND/eMMC、至少256 MB RAM且OpenWrt已支持的设备。
4. 如果成本必须压到WR1200级别，则放弃`cloudflared`和USB，重新定义产品为“极简WireGuard网关”，并接受它没有独立应急入口。
5. 批量采购前取得3–5台同硬件版本样机，核对SoC、Flash/RAM、端口、恢复方式和OpenWrt支持；任何硬件变更都重新认证。

## 9. 若更换硬件后的目标架构

在满足资源条件的新设备上，推荐保留以下边界：

- WireGuard负责工业设备的三层远程访问和精确SNAT；
- ARGO只代理路由器本机loopback上的LuCI/SSH；
- ARGO不得发布`plant`子网、PLC/HMI端口或任意TCP通配入口；
- 每台设备使用独立Cloudflare Tunnel/Token和WireGuard密钥；
- 基础镜像不含生产凭据，凭据在安全配置站逐台注入并设置`0600`权限；
- Cloudflare Access启用身份策略和MFA，LuCI/SSH仍保留自身认证；
- 有线、Wi-Fi和USB上行按健康状态切换，隧道分别重连；
- 日志限制在RAM，避免持续写Flash；
- ARGO无法恢复不开机、无上行、DNS/时间完全损坏或所有出站被阻断的设备，仍需本地恢复流程。

## 10. 量产门禁（适用于替代硬件）

- 固定源码与feeds完整revision；
- 唯一精确profile，不能用相似设备profile代替；
- `make defconfig`后检查最终`.config`；
- 最终镜像至少保留4 MiB可写overlay，建议保留20%以上Flash余量；
- LuCI、WireGuard、上行检测和`cloudflared`同时运行后，`MemAvailable`至少保留32 MiB；
- 连续72小时无OOM、服务重启风暴或overlay异常增长；
- 验证ARGO只到本机管理面、不能访问工业网；
- 验证单台Token撤销、WireGuard密钥撤销和设备报废流程；
- 先做3–5台工程样机，再做约20台小批试产，最后才扩大批量。

## 11. 仓库状态与后续动作

本次只形成可行性方案。由于目标设备不满足需求且OpenWrt目标字段未核实：

- 不创建`manifests/devices/wr1200-v2.json`；
- 不填写猜测的target/subtarget/profile；
- 不创建配置seed、feed lock、patch、overlay、构建脚本或工作流；
- 不运行固件构建或提供刷写命令。

下一步应由产品侧选择：放弃WR1200 2.0并确定替代硬件，或者正式缩减需求为不含ARGO和USB的极简WireGuard研究样机。前者是本设计的推荐方向。
