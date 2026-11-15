# Cudy TR3000 v1 DHCP U-Boot 编译获取、刷入与排障操作指南

本文档整理自针对 **Cudy TR3000 v1（MediaTek MT7981 / 128 MiB SPI NAND）** 的 DHCP U-Boot 编译产物获取、Web 界面刷写、新引导验证以及后续系统排障的完整实操记录。

---

## 一、 硬件与固件环境门禁

在进行任何引导程序（Bootloader）操作前，必须严格确认硬件信息：

| 检查项 | 目标要求 | 风险警告 |
| :--- | :--- | :--- |
| **设备型号** | Cudy TR3000 v1 | 必须以机身底部标签与原厂信息为准，不可套用于其他类似型号。 |
| **SoC 芯片** | MediaTek MT7981B (Filogic 820) | 双核 AArch64 架构。 |
| **闪存容量** | **128 MiB SPI NAND** | **绝对禁止刷入 256 MiB 固件/U-Boot，否则直接变砖。** |
| **操作环境** | 本地有线网线直连电脑 | **严禁远程无人值守刷写。** |

---

## 二、 编译产物获取与文件识别

### 1. GitHub Actions 产物下载
1. 进入 GitHub 仓库对应工作流（`TR3000 DHCP U-Boot`）运行页面。
2. 点击左侧导航栏的 **`Summary`（摘要）**。
3. 滚动到页面底部 **`Artifacts`（产物）** 列表。
4. 找到并下载压缩包：
   * 产物名称：`tr3000-dhcp-uboot-128m-multilayout`（下载后为 `.zip` 格式）。

### 2. 压缩包内文件说明
解压后进入 `images/` 目录，包含以下核心文件：

```text
images/
├── bl2-mt7981_cudy_tr3000-v1_2025_md5-....bin
├── fip-mt7981_cudy_tr3000-v1_2025-Yuzhii-dhcpd-fixed-parts-multi-layout_md5-....bin  <-- [待刷入文件]
└── SHA256SUMS
```

* **`fip-...-multi-layout....bin`（约 980 KB）**：
  U-Boot 本体及设备树包（包含 TF-A BL31、U-Boot 2025、DHCP 服务以及多分区布局切换逻辑）。**Web 界面更新引导程序只需刷入该文件**。
* **`bl2-...bin`（约 237 KB）**：
  第一阶段引导预加载镜像（Preloader）。若设备已有可用 U-Boot，通常无需重新写入 BL2。
* **`SHA256SUMS`**：
  哈希校验清单，解压后建议在终端核验散列值，确保文件未损坏。

---

## 三、 在已有 U-Boot Web 恢复界面中刷入

> [!CAUTION]
> 引导程序刷写期间（约 30 秒至 1 分钟），**绝对禁止断电、拔掉网线或刷新网页**，否则会导致硬件变砖。

### 详细操作步骤

1. **连接与访问**：
   * 电脑网线连接路由器 **LAN** 口。
   * 电脑网卡配置静态 IP：
     * IP 地址：`192.168.1.2`
     * 子网掩码：`255.255.255.0`
     * 默认网关：`192.168.1.1`
   * 浏览器访问 `http://192.168.1.1`，进入旧版 U-Boot Web 恢复页面。

2. **选择目标选项与文件**：
   * 在页面单选项或标签页中，**务必勾选 `Bootloader`（或“引导程序 / U-Boot”）**，不要勾选 `Firmware`（固件）。
   * 点击“浏览 / 选择文件”，选中解压出来的：
     ```text
     fip-mt7981_cudy_tr3000-v1_2025-Yuzhii-dhcpd-fixed-parts-multi-layout_....bin
     ```

3. **上传并执行更新**：
   * 点击 **`Update` / `Upload`（更新/上传）** 按钮。
   * 等待页面进度条走完及设备完成闪存写入并自动重启。

---

## 四、 新版 DHCP U-Boot 验证

新版 U-Boot 具备 **DHCP 服务** 和 **多分区布局支持（Multi-layout）**：

1. **恢复电脑设置**：
   * 将电脑网卡恢复为 **“自动获取 IP 地址（DHCP）”**。
2. **触发 U-Boot 恢复模式**：
   * 拔掉路由器电源。
   * 用卡针顶住机身背部的 **Reset** 键，插上电源。
   * **持续按住 5~8 秒**，待指示灯闪烁后松开。
3. **验证结果**：
   * 电脑网卡会自动分配到 `192.168.1.x` 段 IP。
   * 访问 `http://192.168.1.1`，界面展示多布局（Multi-layout）选择，证明新 U-Boot 部署成功。

---

## 五、 后续刷入 Lite 固件的典型故障与原理剖析

### 1. 故障现象
在 U-Boot 中刷入项目编译生成的 `tr3000-lite-128m-ubootmod-112m`（22 MB）固件并开机后：
* 电脑网线插在 LAN 口，电脑设为自动获取 IP 时，**DHCP 未分配 IP**。
* 电脑手动配置 `192.168.77.2` 后，**PING `192.168.77.1` 完全无响应**。

### 2. 历史故障与当前 Lite 契约

上述现象记录的是旧 Lite 镜像：当时共享 `files/` 将 plant 设为 `proto 'none'`，管理网桥没有接入口，也没有管理 AP。它解释旧镜像行为，不能用来判断当前 Lite 镜像或证明硬件无故障。`22 MB` 是历史观察值，不是当前镜像大小合同。

当前 Lite 专用 overlay 覆盖共享配置，Full 不受此变更影响：

| 项目 | 当前 Lite 默认行为 |
| --- | --- |
| WAN / plant 设备 | 候选 `eth0` / `eth1`，必须逐口插拔验证机壳实际映射 |
| plant | 独立 `eth1`，静态 `192.168.10.254/24` 开机立即生效；DHCPv4、DHCPv6、RA、NDP 服务关闭 |
| mgmt | 独立 `br-mgmt`，`192.168.77.1/24`，加密管理 AP，DHCP 池 `.100–.149`，不与 plant 桥接 |
| mgmt → plant | 默认允许当前 plant CIDR 的 ICMP Echo/TCP，SNAT 为 plant 地址；工业设备无需默认网关；UDP/二层发现不开放 |
| plant → 路由器 | HTTPS 443 默认关闭，设置非空 root 密码且 AP 初始化标记存在后才可显式启用；HTTP/SSH 不开放 |
| WAN / WireGuard | WAN 管理关闭；WireGuard 工业访问及 listener 默认关闭 |

**LAN 接入工业 HUB 前必须人工确认 `192.168.10.254`（或修改后的地址）未占用且网段适用**。不能仅凭构建成功、ARP 自动探测或旧刷机记录认定地址安全。

### 3. 当前首次管理与恢复路径

在可信工位保持 LAN 与 HUB 断开，通过 UART/本地控制台设置 root 密码，私下读取设备生成的 WPA2 管理 SSID/密钥，再连接 AP 访问 `https://192.168.77.1`。随机凭据不在仓库、构建日志或 Artifact 中。plant HTTPS 初始关闭，不能将“静态 PC 直连 LAN”写作首次 Web 开通方式；需要先经控制台/随机 AP 满足 root+AP 门禁并显式启用。没有控制台且不知道随机 AP 凭据时，先在可信工位完成初始化。

“网络 → 工业 LAN”提供 CIDR 验证、应用与策略开关；后端在通过地址/路由/ARP 检查后备份 network/firewall、检查候选 fw4、重载并验证，失败尽力恢复。JSON 中保留 backup_id 和回滚结果；必要时控制台执行 `/usr/sbin/tr3000-lite-plant restore --backup-id BACKUP_ID`，使用真实后端备份 ID。降级回滚需现场检查，不能保证断电和驱动故障下管理必然恢复。

完整操作见 [Lite 部署说明](LITE-README.md) 和 [测试计划](TEST-PLAN.md)。实际首次无线发现、AP+STA 连续可用、Linux 权限、真实 firewall4/netifd 回滚及新镜像启动仍未验证；本记录的历史 U-Boot 成功不能替代这些验收。

---

## 六、 应急脱困与后续方案

### 1. 应急脱困方法（重回 U-Boot 控制台）
由于 U-Boot 处于硬件与内核启动之前，不受 OpenWrt 系统内网络配置的影响：
1. 拔掉电源插头。
2. 卡针顶住 **Reset** 键，插上电源，保持按住 **5~8 秒** 后松开。
3. 电脑网卡配置静态 IP `192.168.1.2`（或使用新版 U-Boot 的自动 DHCP）。
4. 访问 `http://192.168.1.1` 即可重新回到 U-Boot Web 恢复页面。

### 2. 后续系统选择

使用本项目当前 Lite 时，保持管理 AP 与 plant 三层隔离，按上节在可信工位初始化，再确认地址冲突与物理端口映射。不要把 LAN 并入 `br-mgmt` 或在 plant 启用 DHCP 来解决首次登录，这会把管理广播送入工业 HUB。

其他系统必须分别核实精确硬件、128 MiB NAND、112 MiB UBI 布局与安装方法；本文历史 U-Boot Web 记录不构成当前 sysupgrade 镜像通用刷写兼容保证。Lite Artifact 的 `lite-runtime-contract.txt` 仅记录公开预期默认值，应同时核对最终 `build.config`、`selected-packages.txt` 中的 `luci-app-tr3000-lite` 和 sysupgrade SHA256，真机验收仍需单独执行。
