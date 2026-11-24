# TR3000-Lite 真机验证修复（下一版固件） Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复基准固件 `55f42c4`（Actions 44449317194）刷入真机后暴露的 6 个问题，使下一版固件出厂即可：解析域名/同步时钟/更新软件包、建立加密管理 AP、执行工业模式事务、用 root 密码 SSH 登录。

**Architecture:** 全部修复落在 Lite 设备层（overlay、seed、configure/build 脚本）与测试层；不改 Full、不改通用清单。每个修复先在真机复现根因，再改仓库，再把修复后的脚本/配置放回同一台设备验证，最后用静态契约测试锁定。

**Tech Stack:** OpenWrt UCI/overlay、busybox/coreutils、openssh-server、Python unittest、真机 SSH + LuCI（Playwright）。

**Spec:** 无独立 spec；根因证据见 `docs/LITE-README.md`「真机发现的问题与本版修复」与 SKILL「已知调试问题」新增条目。

## Global Constraints

- 不改 Full 分支与通用设备清单；`plant-profile.sh`/`plant-access.sh` 仍归 Full 使用，只是不再装进 Lite 镜像。
- 不引入 mac80211；无线仍按 mt_wifi 语义。
- 不在固件/产物中写入凭据；随机 SSID/key 仍只在首启生成。
- 真机验证不得把唯一 LAN 口交给 plant（操作员经有线接入）；事务验证只用不改变配置的探针。

## 问题与修复对照（全部已在真机验证）

| # | 根因（真机证据） | 仓库修复 | 真机复验 |
|---|---|---|---|
| 1 | overlay 缺 `loopback` → `lo` DOWN → dnsmasq 不绑 127.0.0.1:53 → 设备 DNS/NTP/TLS 全灭 → `opkg update` 全失败 | `overlays/.../etc/config/network` 补 loopback；`build-lite.sh` 编译前断言 | 补段后 `opkg update` 6 feed 签名通过；`opkg install coreutils-stat` 成功 |
| 2 | busybox 无 `stat`/`od`；27 处 `stat -c` 门禁与 AP/DDNS 的 `od` 随机数在真机必失败 | seed 加 `coreutils-stat`；`od` → `head -c \| sha256sum \| cut` | 装包后 `stat` 正常；修补 AP 脚本退出 0 |
| 3 | `uci commit` 留下 0 字节 `/tmp/.uci/<pkg>`，`[ ! -e ]` 误判 → AP 初始化 `pending_wireless`、plant 事务 `pending_firewall_state` | AP 脚本与 plant 控制器改 `[ ! -s ]`；conf2dir 覆盖仍按存在拒绝 | 空 delta 走到 `management_overlap`；非空 delta 仍拒绝；配置不变 |
| 4 | 问题 2/3 叠加 → 管理 AP 从未建立，两个开放热点绑在带 DHCP 的 lan | 随 2/3 修复 | 开放 AP `disabled=1`；`TR3000-Lite-B515F0` WPA2 ×2；marker 写入；`ready:true` |
| 5 | openssh 默认 `PermitRootLogin prohibit-password`；LuCI SSH 页依赖 dropbear 被隐藏 | overlay 加 `etc/ssh/sshd_config.d/99-tr3000-lite.conf`；configure 断言 | 密码 SSH 登录成功 |
| 6 | Full 遗留脚本/死配置随 Lite 镜像下发；公共 snapshot feed 不可依赖 | configure 只装 `preflight.sh`、删 Full defaults 与死配置；build 产物带 `package-repo/` + `key-build.pub` | 静态审计锁定；仓库启用方式见 LITE-README |

## Tasks

- [x] **Task 1: 真机根因取证**（SSH + LuCI Playwright；lo/dnsmasq/resolv.conf、`/tmp/.uci` 0 字节、`stat`/`od` 缺失、sshd 默认值、开放 AP 现状）
- [x] **Task 2: loopback 修复 + 构建断言**（`network` overlay、`build-lite.sh`）
- [x] **Task 3: 工具依赖修复**（`lite.seed` coreutils-stat；AP 脚本与 ddns-event 的随机数改 busybox 工具）
- [x] **Task 4: 空 delta 语义修复**（AP 脚本、`tr3000-lite-plant.sh`）
- [x] **Task 5: SSH drop-in + configure 断言**
- [x] **Task 6: 清理 Full 遗留与死配置**（configure-lite 安装列表、删除 `etc/config/tr3000-lite`）
- [x] **Task 7: 产物自带软件仓库**（`build-lite.sh` package-repo + key-build.pub，架构取自最终 .config）
- [x] **Task 8: 回归测试**（`tests/structure/test_lite_device_readiness.py` + `shell_tools.py` + 镜像命令清单；更新 plant/build-evidence/scripts/repository-contract 夹具；红→绿验证审计能检出旧 od/stat）
- [x] **Task 9: 真机复验修复**（问题 1–5 逐项在同一台设备验证；不交出 LAN 口）
- [x] **Task 10: 文档与 SKILL 同步**（LITE-README 新章节、TEST-PLAN T11–T15、SKILL 已知调试问题 5 条 + 快速参考 + 常见错误）
- [ ] **Task 11: 全量测试 + validate + 提交**
- [ ] **Task 12: 推送并触发 `build-lite.yml`，下载新产物核对**（需要人工确认远端写操作；新镜像必须含 loopback、coreutils-stat、sshd drop-in、无 Full 遗留脚本、package-repo）
- [ ] **Task 13: 新固件不保留配置刷机 + T1–T15 真机验收**（用户在设备旁执行）

## 后续项（本期不做）

- OpenSSH 密钥管理的 LuCI 页面（上游页面依赖 dropbear；不要向 `/etc/dropbear/authorized_keys` 写密钥）。
- 保留配置升级的旧结构自动迁移（仍按设计 §7 强制 `sysupgrade -n`）。
- `lan` 接入段地址可配置。
