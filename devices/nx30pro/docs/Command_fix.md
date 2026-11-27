# H3C NX30 Pro 112M NMBM Full 自编译开发

## 项目目标

在现有 OpenWrt 多设备 GitHub Actions 工程中新增 H3C NX30 Pro。

第一版必须优先复用社区已有实际刷机案例的112M NMBM方案，同时自编译 U-Boot 和固件。

不开发64M版本，不在第一阶段研究114M非NMBM。

## 参考源码

U-Boot 上游：

https://github.com/hanwckf/bl-mt798x

U-Boot 增强版：

https://github.com/Yuzhii0718/bl-mt798x-dhcpd

112M 固件参考：

https://github.com/Galaxian-Explosion/nx30pro-imm-112M-nmbm

ImmortalWrt：

https://github.com/immortalwrt/immortalwrt

兼容性问题：

https://github.com/immortalwrt/immortalwrt/issues/1735

https://github.com/hanwckf/immortalwrt-mt798x/issues/112

112M U-Boot 编译参考：

https://yunpan.plus/t/11793-1-1

## 第一阶段：源码调查

1. 检查上述仓库的分支、Commit、设备树、编译配置及历史 Release。
2. 查找 NX30 Pro 112M U-Boot 已有板级适配。
3. 优先复用已有配置，不从零开发分区。
4. 查找实际刷机成功记录以及对应的固件版本。
5. 确定可复现的 U-Boot 和固件源码组合。
6. 不强制使用 ImmortalWrt 25.12，优先选择经过社区验证的版本。
7. 分析原厂 YAFFS 和 NMBM 坏块风险。
8. 输出源码选型报告及证据链接。

如果无法找到完整可复现的112M成功案例，明确标记为待验证，不得虚构验证结果。

## 第二阶段：U-Boot

- SOC：mt7981
- BOARD：h3c_magic-nx30-pro
- Layout：112M NMBM
- Web Recovery：Enabled
- DHCP Server：Enabled
- TFTP：Enabled
- UART：Enabled
- CPU / DDR 超频：Disabled

优先评估 Yuzhii 的多分区配置。

保留 Factory、MAC 地址和无线校准数据。

固定源码 Commit，生成 BL2、FIP、SHA256 和编译记录。

## 第三阶段：Full 固件

优先使用已有112M设备适配的源码。

集成以下软件：

- LuCI、HTTPS、中文
- Argon 主题
- HomeProxy、Sing-box
- WireGuard
- Tailscale
- FRPC
- DDNS、Cloudflare DDNS
- dnsmasq-full
- SQM、NLBWMon
- WOL、TTYD
- SFTP
- TCPDump、iPerf3、MTR

根据实际源码版本验证软件包兼容性。

不集成 Docker、OpenClash、PassWall2、AdGuard Home。

所有非必要网络服务默认关闭。

## 第四阶段：GitHub Actions

1. 阅读现有 AGENTS.md。
2. 复用现有多设备工程结构。
3. 新增 NX30 Pro 独立设备配置。
4. 同时支持 U-Boot 和 Full 固件编译。
5. 固定源码及 feeds Commit。
6. 自动检查分区、NMBM、UBI、镜像格式和大小。
7. 使用 gh CLI 检查构建及日志。
8. 分别上传 U-Boot 和固件产物。
9. 输出 SHA256、软件包清单和源码锁定记录。
10. 生成 BUILD.md、FLASH.md、RECOVERY.md、TEST-REPORT.md。

## 第五阶段：验收

- U-Boot 编译成功。
- Full 固件编译成功。
- 112M 分区完全一致。
- Web Recovery 正常。
- DHCP Recovery 正常。
- Factory、MAC 地址正常。
- WAN、LAN、Wi-Fi 正常。
- HomeProxy、WireGuard 正常。
- LuCI Sysupgrade 正常。
- 无异常 NMBM、NAND、ECC 和 UBI 错误。
- 完成多次重启、反复升级及72小时稳定性测试。

不自动执行真机刷写，不执行未经验证的 NAND 擦除操作。

第一版112M通过全部真机测试后，保留源码及编译产物，再创建独立 Worktree 研究114M非NMBM方案。

本次开发不涉及114M移植。