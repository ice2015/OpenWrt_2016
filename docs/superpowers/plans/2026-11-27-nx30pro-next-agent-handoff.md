# NX30 Pro 固件与 U-Boot 重做：下一 Agent 交接

## 当前任务

按已批准设计，从头重做 H3C Magic NX30 Pro 的 U-Boot 与 112M 固件构建方案。旧实现、
旧 source lock 和旧 GitHub Actions 只作为失败证据与设备适配参考，不视为可继续发布的
实现。

## 强制阅读顺序

1. 根目录 `AGENTS.md`。
2. `.agents/skills/openwrt-firmware-config/SKILL.md`。
3. `manifests/devices/nx30pro.json` 与 `manifests/sources.json`。
4. `docs/configuration-layers.md`。
5. 批准的设计：
   `docs/superpowers/specs/2026-11-27-nx30pro-firmware-uboot-redesign.md`。
6. U-Boot 实施计划：
   `docs/superpowers/plans/2026-11-27-nx30pro-uboot-redesign.md`。
7. 固件实施计划：
   `docs/superpowers/plans/2026-11-27-nx30pro-firmware-redesign.md`。
8. `devices/nx30pro/docs/Command_fix.md`；它已同步为批准后的中文需求源，固件计划
   Task 1 需要增加契约测试，防止它再次与设计稿漂移。

## 已批准决策

### 总体

- 选择方案 A：重建 OpenWrt/ImmortalWrt 21.02、Linux 5.4 配套栈。
- 固件候选来源为 `hanwckf/immortalwrt-mt798x` 的新锁定 commit；不得直接复用旧
  Galaxian commit 作为构建底座。
- `Galaxian-Explosion/nx30pro-imm-112M-nmbm` 只提供 112M DTS/profile 移植证据。
- 保持仓库 `common → distribution → device → local` 分层和 NX30PRO 设备隔离。
- 未核实值保持 `UNRESOLVED`，不得为了让检查通过而猜 revision、profile 或产物名。

### U-Boot

- 来源：`https://github.com/Yuzhii0718/bl-mt798x-dhcpd`，实施时固定完整 commit。
- Board：`h3c_magic-nx30-pro`；SoC：MT7981。
- 默认布局：`immortalwrt-112m`。
- 唯一备选布局：原厂 `default`。
- `MULTI_LAYOUT=1`，`FIXED_MTDPARTS=1`。
- Web UI 提供白名单布局选择器，只能选择上述两个标签；不允许任意 `mtdparts`。
- 启用：DHCPD、Web failsafe、固件恢复、BL2/FIP 升级、TFTP、UART、只读备份。
- 禁用：Factory 写入、Flash Editor、通用环境编辑、Web 终端、Telnet、UBI 管理、
  CPU/DDR 超频。
- 第一版固件是 Linux 5.4，因此优先评估 SP1 ATF；最终版本必须有证据，不能猜。

### 固件核心硬门禁

以下任何一项在真实 `make defconfig` 后缺失，都必须拒绝该源码/feeds 组合，不能进入
正式编译：

- LuCI、HTTPS、简体中文、Argon 与 Bootstrap 回退。
- PassWall **4.68** + Xray Core/Xray Plugin。
- DDNS。
- Tailscale。
- ZeroTier。
- Docker。
- Argo 隧道（`cloudflared`）。

以下必须尝试并报告，但允许因旧底座不兼容而延期：Cloudflare DDNS、FRPC、
dnsmasq-full、SQM、NLBWMon、WOL、TTYD、SFTP、tcpdump、iperf3、MTR。

HomeProxy、sing-box、OpenClash、PassWall2、AdGuard Home 不进入第一版。WireGuard 在
Linux 5.4 上若无可验证实现，保持 `UNRESOLVED`。

所有非必要网络服务默认关闭；任何令牌、域名、密码、密钥、Wi-Fi 凭据、现场 IP 或
真实 MAC 都不得写入镜像或仓库。

## 已确认的旧 Action 问题

- 最新旧固件运行：GitHub Actions run `45579764579`，在配置阶段失败，未进入正式
  编译，也未生成固件。
- `make defconfig` 删除了 PassWall、Xray、cloudflared、DDNS、ZeroTier、Docker、
  Argon 等声明为必需的包。
- 日志同时出现大量依赖不存在，证明旧源码与锁定 feeds 不是兼容组合。
- 旧 U-Boot Action 虽生成 BL2/FIP，但只证明可编译；未与成功固件配对、未真机验证，
  两次构建还因时间戳产生不同哈希。

## 执行顺序

1. 使用 `superpowers:subagent-driven-development`（推荐）或
   `superpowers:executing-plans` 执行 U-Boot 计划 Tasks 1–6。
2. 不执行 U-Boot 计划 Task 7，除非用户在执行时再次明确授权触发 U-Boot Action。
3. 执行固件计划 Tasks 1–7。
4. 不执行固件计划 Task 8 的 defconfig probe 或 Action，除非用户再次明确授权。
5. 每项任务按计划先写失败测试、确认失败、最小实现、确认通过、再提交。
6. 修改完成后运行：

   ```sh
   bash scripts/validate.sh
   python -m unittest discover -s tests -v
   ```

7. 静态测试通过不代表固件或 U-Boot 已编译，更不代表真机验证通过。

## 当前禁止事项

- 本轮对话明确要求：不要触发任何 GitHub Action，不要执行固件或 U-Boot 编译。
- 不得通过 push、workflow dispatch、`gh workflow run` 或其他方式间接触发构建。
- 不得刷写、擦除 NAND 或提供未经验证的物理偏移命令。
- 不得修改 `work/`、`output/`、`cache/`。
- 不得将旧 Action 的绿色 U-Boot 状态写成兼容或真机验证成功。

## 当前文件状态

- 新设计、两份实施计划、本交接文件以及已同步的
  `devices/nx30pro/docs/Command_fix.md` 当前均可能是未跟踪文件；实施前先运行
  `git status --short`，不得覆盖用户其他改动。
- 本轮只创建/修订文档，没有修改构建脚本、配置、workflow 或测试。
- 本轮没有运行固件/U-Boot 编译，也没有触发 GitHub Actions。

## 完成标准

- 两份计划中未授权的静态实现任务完成并通过仓库校验与全部单元测试。
- source lock、feed lock、分区合同、最终配置门禁与工作流静态合同一致。
- 两个 workflow 仍仅支持 `workflow_dispatch`，且没有被执行。
- 报告清楚区分：静态验证、Actions 候选构建、真机验证。
- 未执行的远程构建和真机事项继续保持未完成/`UNRESOLVED`。

