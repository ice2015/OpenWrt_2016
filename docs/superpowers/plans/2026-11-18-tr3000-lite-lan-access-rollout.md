# TR3000-Lite 接入段交付（文档与产物验证） Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让仓库文档与固件实际行为一致，并用一个真实构建证明出厂固件带着可用的接入段（`192.168.10.1/24` + DHCP + 管理 AP）。

**Architecture:** 只改文档与验证步骤，不改固件行为。文档以 Lite 操作说明为主入口，新增一份接入/工业模式操作手册；真机验收清单重写为可执行的 T1–T10。产物验证用 GitHub Actions 的 `build-lite.yml` 在本分支构建，再解包 sysupgrade 镜像核对接入段配置、无线配置缺失与契约版本。

**Tech Stack:** Markdown、Python `unittest`（文档契约测试）、GitHub Actions `build-lite.yml`、`unsquashfs`（产物核对）。

**Spec:** `docs/superpowers/specs/2026-11-18-tr3000-lite-lan-access-design.md`（§6.9 文档更新、§7 升级路径、§8 真机验收）

## Global Constraints

- 固定地址：`lan` = `192.168.10.1/24`，DHCP 池 `192.168.10.100-249`；`plant` 默认 `192.168.20.254/24`（仅工业模式）。
- 文档必须写明：**升级本固件必须不保留配置刷机**（`sysupgrade -n`），否则旧结构仍在且会失联。
- 文档不得写出固定无线凭据、root 密码或任何现场参数；随机 SSID/密钥只描述读取方式。
- 真机验收项只能写在 `docs/TEST-PLAN.md`，不得把未验证行为写成已实现。
- 固件编译只在 GitHub Actions；本地不编译。

## Review Focus

1. 文档里若仍出现 `192.168.77` / `br-mgmt` / `mgmt` 段描述，读者会按旧地址配置设备 —— 必须逐条核对。
2. "首次接入"路径必须与固件一致：插线 → DHCP → `https://192.168.10.1`；不能再要求串口读随机 SSID 才能上网。
3. 工业模式的切换条件与回退方式必须写清（切走有线管理路径）。
4. 产物核对必须验证镜像内**没有** `/etc/config/wireless`（固件不带凭据）。

---

### Task 1: 文档同步

**Files:**
- Modify: `docs/LITE-README.md`
- Modify: `docs/TEST-PLAN.md`
- Modify: `docs/TR3000-LITE-PROVISIONING.md`
- Modify: `docs/TR3000-LITE-REMOTE-ACCESS.md`
- Modify: `docs/SINGBOX-SPLIT-ROUTING.md`
- Modify: `docs/cudy-tr3000-uboot-flashing-record.md`
- Create: `docs/TR3000-LITE-LAN-ACCESS.md`
- Modify: `README.md`
- Modify: `docs/superpowers/specs/2026-11-14-tr3000-lite-industrial-lan-management-design.md`（标注被取代部分）
- Test: `tests/structure/test_repository_contract.py`

**Interfaces:**
- Consumes: Task 1–7（实现计划）的最终行为：`lan` 段、`plant` 模式切换、`tr3000-lite-plant` 新命令、`tr3000-lite-wifi` 服务。
- Produces: 与固件一致的文档；文档契约测试（无残留旧网段/旧段名、新手册存在且被 README 链接）。

- [x] **Step 1: 写失败的文档契约测试**

在 `tests/structure/test_repository_contract.py` 新增：

```python
def test_lite_documents_describe_the_access_segment(self) -> None:
    handbook = ROOT / "docs/TR3000-LITE-LAN-ACCESS.md"
    self.assertTrue(handbook.is_file(), "missing the Lite access segment handbook")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    self.assertIn("docs/TR3000-LITE-LAN-ACCESS.md", readme)
    for document in ("docs/LITE-README.md", "docs/TR3000-LITE-PROVISIONING.md",
                     "docs/TR3000-LITE-REMOTE-ACCESS.md", "docs/SINGBOX-SPLIT-ROUTING.md"):
        text = (ROOT / document).read_text(encoding="utf-8")
        self.assertNotIn("192.168.77", text, document + " still documents the retired management segment")
        self.assertNotIn("br-mgmt", text, document + " still documents the retired management bridge")
```

- [x] **Step 2: 跑测试确认失败**

Run: `python3 -m unittest tests.structure.test_repository_contract.RepositoryContractTests.test_lite_documents_describe_the_access_segment -v`
Expected: FAIL（手册不存在、README 未链接、文档仍含旧网段）。

- [x] **Step 3: 写新手册 `docs/TR3000-LITE-LAN-ACCESS.md`**

内容必须覆盖：出厂状态（接入模式：`lan` = `192.168.10.1/24`、DHCP `.100–.249`、管理 AP `TR3000-Lite-<MAC 后 6 位>` WPA2、随机 key 从 `0600` 的 `/etc/config/wireless` 读取）、首次接入步骤（插线或连 WiFi → 拿到 `192.168.10.x` → `ping 192.168.10.1` → `https://192.168.10.1`）、工业模式（LuCI「网络 → TR3000 Lite → 工业 LAN」→「启用 plant 模式」，默认 `192.168.20.254/24`，DHCP 永久关闭、ICMP 关闭、仅按门禁开 443）、回退（「退回接入模式」，有线恢复 DHCP）、控制台命令（`status --json` / `validate` / `apply` / `enable-plant` / `disable-plant` / `restore`）、升级必须 `sysupgrade -n`、真机验收见 `docs/TEST-PLAN.md`。

- [x] **Step 4: 同步既有文档**

- `docs/LITE-README.md`：把“网络安全默认值”里的 `mgmt`/`192.168.77` 段改为 `lan`/`192.168.10.1`；首次配置流程改为“插线或连 WiFi 即得地址”；plant 改为“按需接管唯一 LAN 口”；控制器示例改为新命令；`plant_https_gate` 改为 root 密码 + 显式启用。
- `docs/TEST-PLAN.md`：把 Lite 段的旧条目改为新的 T1–T10 清单（出厂可达、AP 加密且无开放热点、工业模式切换与回退、旧配置提示）。
- `docs/TR3000-LITE-PROVISIONING.md`、`docs/TR3000-LITE-REMOTE-ACCESS.md`、`docs/SINGBOX-SPLIT-ROUTING.md`：`192.168.77` → `192.168.10`，`br-mgmt`/`mgmt` → `lan`。
- `docs/cudy-tr3000-uboot-flashing-record.md`：段落表格改为新结构；保留旧镜像现象作为历史记录并标注已被本设计取代。
- `docs/superpowers/specs/2026-11-14-...md`：顶部标注“管理段与无线栈部分已被 2026-11-18 设计取代”。
- `README.md`：在文档索引里加入 `docs/TR3000-LITE-LAN-ACCESS.md`。

- [x] **Step 5: 跑测试确认通过**

Run: `python3 -m unittest tests.structure.test_repository_contract -v`
Expected: PASS。

- [x] **Step 6: 提交**

```bash
git add docs/ README.md tests/structure/test_repository_contract.py
git commit -m "docs(lite): document the access segment and the industrial mode switch"
```

---

### Task 2: GitHub Actions 构建与产物核对

**Files:**
- 无仓库改动（验证步骤）。

**Interfaces:**
- Consumes: 本分支的固件构建（`build-lite.yml`）与 `tr3000-lite-128m-ubootmod-112m` 产物。
- Produces: 一次成功构建的运行记录与镜像内容核对结论。

- [x] **Step 1: 推送分支（需要人工确认）**

Run: `git push -u origin feature/tr3000-lite-factory-access`
Expected: 推送成功；推送前先向用户确认（对远端仓库的写操作）。

- [x] **Step 2: 触发构建**

Run: `gh workflow run build-lite.yml --ref feature/tr3000-lite-factory-access`
Expected: 运行进入队列；用 `gh run list` 取到运行号。

- [x] **Step 3: 等待构建成功**

Run: `gh run watch <run-id> --exit-status`
Expected: 退出码 0；构建日志包含 native nft 门禁通过。

- [x] **Step 4: 下载并核对产物**

Run: `gh run download <run-id> -n tr3000-lite-128m-ubootmod-112m`
Expected: 得到 sysupgrade 镜像与证据文件。

核对项（解包 `root` 分区后）：
1. `/etc/config/network` 含 `config interface 'lan'`、`option ipaddr '192.168.10.1'`、`config device 'br_lan'`、`list ports 'eth1'`，且 `plant` 段不绑定 `eth1`；
2. `/etc/config/dhcp` 含 `config dhcp 'lan'` 与 `option limit '150'`；
3. 镜像内**不存在** `/etc/config/wireless`；
4. `lite-runtime-contract.txt` 含 `schema_version=2`、`lan_cidr=192.168.10.1/24`、`wireless_stack=mt_wifi`、`management_ap_network=lan`；
5. `image-packages.manifest` 含 `luci-app-tr3000-lite`、`wpad-openssl`，不含 `ruby`/`libruby`。

- [x] **Step 5: 记录结论**

把运行号、产物大小与上述五项核对结果写进最终汇报；未通过项必须显式列出，不得用“构建成功”代替“固件可用”。

**实际结果（基准固件）**：

| 项 | 值 |
| --- | --- |
| 运行 | [Actions 44449317194](https://github.com/ice2015/OpenWrt_2016/actions/runs/44449317194)（`TR3000 Lite firmware`） |
| 提交 | `55f42c4be996aab387062453cf33b2ccc509a8ab`（`feature/tr3000-lite-factory-access`） |
| 状态 / 耗时 | Success / 1h 25m 37s |
| 产物 | `tr3000-lite-128m-ubootmod-112m`，1 个 Artifact |
| 镜像 | `immortalwrt-mediatek-filogic-cudy_tr3000-v1-ubootmod-squashfs-sysupgrade.bin`，20 747 077 字节 |
| SHA256 | `e761cb00ffbd3c1b607d046fb2a78cde78f0a29bf06833d00ee4fd4a7a8b9d76`（已用 `sha256sum -c` 复核） |

五项核对全部通过：接入段 `lan` = `192.168.10.1/24` 且 `br_lan` 含 `eth1`；`dhcp 'lan'` limit 150；`plant` 为 `proto 'none'` 且不绑定 `eth1`；镜像内无 `/etc/config/wireless`；契约 `schema_version=2` / `lan_cidr=192.168.10.1/24` / `wireless_stack=mt_wifi` / `management_ap_network=lan`；包清单含 `luci-app-tr3000-lite` 与 `wpad-openssl`，无 Ruby/libruby。

额外核对（超出上表五项）：`profile.dts` 为 `reg = <0x5c0000 0x7000000>`；tar `CONTROL` 为 `cudy_tr3000-v1-ubootmod`；`/usr/sbin` 下 8 个 Lite 控制器、`/usr/lib/tr3000-lite` 下 8 个库、3 个 `init.d` 服务、3 个 LuCI 视图均在镜像内；无线栈为 mt_wifi，无 mac80211/mt7915e；防火墙 `lan` zone ACCEPT、`lan→wan` 转发、`lan→plant` ICMP/TCP 与 SNAT 指向 `192.168.20.254` 均已就位。

**未通过/未验证项（不得当作已实现）**：全部真机项 T1–T10 仍未执行——设备启动、DHCP 实际交付、管理 AP 在 mt_wifi 上的实际起停与加密、工业模式切换实况、端口物理角色、可写 overlay 余量、射频并发与真实路由切换。

---

## 后续

- 真机验收 T1–T10 需要真实设备与现场网络，由用户在设备旁执行并反馈结果。
- 分支合并/开 PR 按 `superpowers:finishing-a-development-branch` 处理。
