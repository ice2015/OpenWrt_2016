# TR3000-Lite 接入段与工业模式

本手册描述 TR3000-Lite 固件的**出厂状态**与**工业模式切换**。设备只有两个网口：`eth0`（2.5G，WAN）与 `eth1`（1G，唯一 LAN 口）。出厂时这个 LAN 口属于操作员**接入段**；接入工业 HUB 时才由操作员显式交给**工业段**。

> 升级到本固件必须**不保留配置**刷机（`sysupgrade -n` 或首次安装）。旧版 Lite 配置没有接入段，保留后设备仍按旧结构工作，既没有可用地址也没有 DHCP。检测到旧结构时固件会在日志和 LuCI 顶部给出提示。

## 1. 出厂状态（接入模式）

| 项 | 值 |
| --- | --- |
| 接入段接口 | `lan`，设备 `br-lan`（成员 `eth1` + 管理 AP） |
| 路由器地址 | `192.168.10.1/24` |
| DHCP 池 | `192.168.10.100–192.168.10.249` |
| 管理 AP | `TR3000-Lite-<无线设备 MAC 后 6 位大写十六进制>`，WPA2-PSK (`psk2`) |
| AP 密钥 | 每台设备随机生成（32 位小写十六进制），只存在于 `0600` 的 `/etc/config/wireless` |
| 工业段 | `plant` **默认不启用**（`proto none`，不绑定 `eth1`，无地址） |
| 防火墙 | `lan` 段允许接入并转发到 WAN；`plant`/`wan` 段默认拒绝 |

出厂行为：

- 插上网线，PC 立刻拿到 `192.168.10.x`，网关与 DNS 都是 `192.168.10.1`；`ping 192.168.10.1` 通。
- 浏览器打开 `https://192.168.10.1` 进 LuCI（首次访问按提示设置 root 密码）。
- 管理 AP 始终启用且加密；固件**不预置** `/etc/config/wireless`，凭据在首启时生成，不出现在镜像、构建日志或 Artifact 里。
- 驱动栈是 mt_wifi（`kmod-mt_wifi`）。驱动每次重建无线配置时可能带出它自己的开放默认 AP，`/etc/init.d/tr3000-lite-wifi` 会在每次启动检查并重新禁用它，同时补齐受管 AP；只有全部 radio 都有受管 AP 且没有开放的 AP 时才写 `/etc/tr3000-lite/management-ap.initialized` 就绪标记。

## 2. 首次接入步骤

1. 在可信工位上电，**LAN 口先不接工业 HUB**。
2. 插网线：确认 PC 拿到 `192.168.10.x`；或连管理 AP（SSID 见设备丝印/控制台，密钥从 `0600` 的 `/etc/config/wireless` 私下读取，不要贴进日志或工单）。
3. `ping 192.168.10.1` 应通；浏览器打开 `https://192.168.10.1`，设置非空 root 密码（远程访问与 plant Web 的门禁都依赖它）。
4. 在 LuCI「网络 → 无线」确认管理 AP 为 WPA2 加密，且**没有**出现 `ImmortalWrt-2.4G` / `ImmortalWrt-5G` 这类开放热点。
5. 需要上网时，PC 直接把 `192.168.10.1` 当网关即可（`lan → wan` 转发默认允许）。

## 3. 工业模式（把唯一 LAN 口交给工业网）

工业段与接入段不能共用同一个物理口的两套地址，因此切换是**显式动作**：

1. 在「网络 → TR3000 Lite → 工业 LAN」页面填入 plant 地址（默认 `192.168.20.254/24`），点「启用 plant 模式」。
2. 后端会：把 `eth1` 从 `br-lan` 摘出交给 `plant`、设置静态地址、禁用 plant 段 DHCP、写入 `lan → plant` 的 ICMP/TCP 放行与 SNAT，并生成 network/firewall 配对备份；候选配置通过 `fw4 check` 后才重载并核验实况，失败尽力回滚。
3. **切换前必须确认管理 AP 已就绪**（页面会显示 AP 状态）。交出有线口后，管理路径只剩 WiFi；AP 未就绪时按钮不可用，只能由本地控制台显式强制。
4. 切换后：
   - 插线接入的 PC **拿不到地址**（plant 段不提供 DHCP），也 **ping 不通** 路由器（ICMP 默认关闭）；
   - 无默认网关的 PLC/HMI 仍可由接入段单向访问（ICMP Echo 与普通 TCP 单播 + SNAT），UDP、广播/组播发现不放行；
   - 路由器管理面改从 `https://192.168.10.1`（WiFi）访问；plant 段自身只按门禁开放 443。
5. 接入工业 HUB 前，人工确认 plant 地址未被占用、网段适用且与上行不重叠。
6. 需要退回时，在同一页面点「退回接入模式」：`eth1` 回到 `br-lan`，`192.168.10.x` 的 DHCP 立即恢复。

## 4. 控制台接口

固定后端 `/usr/sbin/tr3000-lite-plant`（不要用旧的 `plant-profile.sh`，它不做配对备份与回滚）：

```sh
/usr/sbin/tr3000-lite-plant status --json
/usr/sbin/tr3000-lite-plant validate --address 192.168.20.254/24
/usr/sbin/tr3000-lite-plant enable-plant --address 192.168.20.254/24
/usr/sbin/tr3000-lite-plant disable-plant
/usr/sbin/tr3000-lite-plant apply --address 192.168.20.254/24 --allow-luci true --allow-mgmt true
# 用 apply 返回的真实 backup_id 替换 BACKUP_ID：
/usr/sbin/tr3000-lite-plant restore --backup-id BACKUP_ID
```

- `status --json` 返回 `mode`（`lan`/`plant`）、`lan.cidr`、`lan.dhcp_pool`、`plant.active`、`plant.cidr`、`ap_ready`、`legacy_config_detected`、`checks`、`backup_id`、`rollback`。
- `enable-plant` 在管理 AP 未就绪时拒绝（`management_not_initialized`）；本地控制台可显式强制。
- `apply` 只在工业模式有效（plant 未接管 `eth1` 时报 `invalid_device`）。
- 备份目录 `/etc/tr3000-lite/backups` 仅 root 可读，最多保留五对；`rollback` 为 `degraded` 时必须保持 HUB 断开并用控制台检查，不要把命令成功当作链路恢复。

无线侧：

```sh
/usr/sbin/tr3000-lite-wifi status --json   # ready / radio_count / managed_aps / open_aps ...
/usr/sbin/tr3000-lite-wifi repair          # 幂等修复，受管 AP 缺失或开放 AP 复活时使用
```

## 5. 未验证项

本手册描述的是**固件预期行为**。以下仍需真机验证（清单见 [测试计划](TEST-PLAN.md)）：实际 DHCP 交付、WiFi AP 在 mt_wifi 上的实际起停、工业模式切换后的实况、端口物理角色（`eth0`/`eth1` 与机壳插孔的对应）、可写 overlay 余量。
