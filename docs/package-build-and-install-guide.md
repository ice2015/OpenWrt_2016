# OpenWrt 插件编译与导入实战指南

本文档总结了在本项目及标准 OpenWrt / ImmortalWrt 环境下，**编译特定插件**的两大主流方案（固件集成 vs SDK 独立编译），以及**将独立编译出的 `.ipk` 安装包导入并部署到运行中路由器**的完整流程与避坑规范。

---

## 一、方案对比与选型

| 维度 | 方案 A：固件整体编译 (In-Tree Firmware) | 方案 B：SDK 独立单包编译 (Single IPK) |
| :--- | :--- | :--- |
| **产物形态** | 完整固件镜像（`sysupgrade.bin`） | 单独安装包（`.ipk`） |
| **GitHub Actions 耗时** | 约 30 ~ 50 分钟 | **仅需 3 ~ 5 分钟** |
| **适合对象** | 核心组件、网络驱动、内核模块（`kmod-*`）、常用长驻功能 | 独立小工具、纯 LuCI Web 界面、第三方实验性插件 |
| **路由器部署方式** | 进入后台执行 sysupgrade 刷机（保留配置） | **无需刷机**，直接传输到路由器执行 `opkg install` |
| **依赖安全性** | 编译期严格校验，依赖完全闭环，无兼容性问题 | 运行时动态依赖，受当前系统的内核版本及依赖库限制 |

---

## 二、方案 A：通过 GitHub Actions 整体编译进固件

当插件是长期需要的基础功能，或属于内核驱动模块（`kmod-*`）时，推荐直接打入固件。

### 1. 配置原则
项目遵循分层优先级规则：
```text
common → distribution → device → local
```
* 如果该插件仅供特定硬件使用（例如仅针对 TR3000），修改设备级配置文件，严禁随意直接写入 `common` 层。

### 2. 核心操作步骤
1. **确认软件源（Feed）**：
   * 官方/通用插件：检查对应设备的 feed lock 文件（如 `feeds/devices/tr3000-lite.lock`）。
   * 第三方定制插件：在 lock 文件中补充 Git 仓库 URL 与固定的 **40 位完整 Commit SHA**，确保构建可复现。
2. **在 Seed 配置中启用插件**：
   * **Lite 固件**：修改 `configs/lite.seed`
   * **Full 固件**：修改 `configs/full.seed`
   * 命名规范：
     * 普通应用程序：`CONFIG_PACKAGE_<name>=y`
     * LuCI 管理页面：`CONFIG_PACKAGE_luci-app-<name>=y`
     * 配套中文语言包：`CONFIG_PACKAGE_luci-i18n-<name>-zh-cn=y`
     * 内核驱动模块：`CONFIG_PACKAGE_kmod-<name>=y`
3. **检查配置门禁与避坑**：
   * 检查 `scripts/configure-lite.sh`（或 `configure-full.sh`），确保新增插件不在排除包循环中。
   * **警惕隐式重型依赖**：避免引入如 `ruby`、`python3`、`rust/host` 等会在云端触发数小时自举编译的依赖项。
4. **本地自动化校验**：
   ```powershell
   bash scripts/validate.sh
   python -m unittest discover -s tests -v
   ```
5. **提交并触发云端构建**：
   ```powershell
   git add configs/
   git commit -m "feat(config): add luci-app-example to TR3000"
   git push
   gh workflow run build-lite.yml
   ```
6. **产物获取**：构建完成后，在 GitHub Actions Artifacts 下载固件，通过常规方式刷入路由器。

---

## 三、方案 B：通过 GitHub Actions 快速编译单包 `.ipk`

若不想重刷系统，只想单独编译一个特定插件，最推荐的做法是在 GitHub Actions 中使用**预编译的 OpenWrt SDK**。

### 1. 工作流配置（`.github/workflows/build-package.yml`）
在仓库中提供一个支持手动动态传参的轻量工作流：

```yaml
name: Build Single Package IPK

on:
  workflow_dispatch:
    inputs:
      package_name:
        description: '要编译的包目录名（如 iperf3 或 luci-app-wrtbwmon）'
        required: true
      package_repo:
        description: '第三方插件 Git 仓库地址（若为官方源自带包可留空）'
        required: false
        default: ''

jobs:
  build:
    runs-on: ubuntu-22.04
    steps:
      - name: Checkout repository
        uses: actions/checkout@v4

      - name: Setup OpenWrt SDK
        run: |
          # 下载匹配硬件架构（以 MT7981 Filogic aarch64 为例）的预编译 SDK
          SDK_URL="https://downloads.immortalwrt.org/releases/23.05.3/targets/mediatek/filogic/immortalwrt-sdk-23.05.3-mediatek-filogic-filogic_gcc-12.3.0_musl.Linux-x86_64.tar.zst"
          wget -qO - "$SDK_URL" | tar -I zstd -xf - --strip-components=1

      - name: Add Package Source
        run: |
          if [ -n "${{ inputs.package_repo }}" ]; then
            git clone "${{ inputs.package_repo }}" "package/${{ inputs.package_name }}"
          fi
          ./scripts/feeds update -a
          ./scripts/feeds install -a

      - name: Compile Package
        run: |
          make defconfig
          make "package/${{ inputs.package_name }}/compile" -j$(nproc) V=s

      - name: Upload IPK Artifacts
        uses: actions/upload-artifact@v4
        with:
          name: "${{ inputs.package_name }}-ipk"
          path: bin/packages/**/*.ipk
          if-no-files-found: error
```

### 2. 触发与下载产物
在本地终端中直接发起编译：
```powershell
# 编译第三方插件示例
gh workflow run build-package.yml `
  -f package_name="luci-app-example" `
  -f package_repo="https://github.com/someone/luci-app-example.git"

# 约 3~5 分钟完成后，下载生成的 IPK 压缩包
gh run download -n "luci-app-example-ipk"
```

---

## 四、将编译好的 `.ipk` 导入 OpenWrt 的全流程

拿到编译好的 `.ipk` 文件后，按以下标准步骤导入路由器并运行：

### 步骤 1：导入前准备与环境检查

1. **检查路由器架构兼容性**：
   登录路由器终端执行：
   ```sh
   opkg print-architecture
   ```
   输出中应包含当前插件的目标架构（例如 `aarch64_cortex-a53` 或通用架构 `all`）。

2. **检查可用存储空间（非常关键！）**：
   ```sh
   df -h /overlay
   ```
   * 确保 `/overlay` 可用空间大于插件体积的 3 倍以上。
   * **警告**：若 `/overlay` 空间被占满至 100%，会导致路由器配置无法保存甚至变砖重启循环。

---

### 步骤 2：将 `.ipk` 上传到路由器

> [!IMPORTANT]
> **始终将临时安装包上传到 `/tmp` 目录**。  
> `/tmp` 挂载于内存（tmpfs），读写速度极快，且路由器重启后会自动清理，不占用宝贵的持久闪存空间。

#### 方式 1：使用 SCP / SFTP 命令行传输（推荐）
在宿主机（Windows / macOS / Linux）终端中执行：
```powershell
# 将当前目录下的所有相关 ipk 上传到路由器的 /tmp 目录
scp *.ipk root@192.168.1.1:/tmp/
```

#### 方式 2：使用图形化工具传输
使用 **WinSCP**、**FinalShell** 或 **MobaXterm**：
1. 协议选择 `SCP` 或 `SFTP`。
2. 主机填路由器 IP（如 `192.168.1.1`），用户名为 `root`，输入登录密码。
3. 导航到路由器的 `/tmp/` 目录，将电脑上的 `.ipk` 拖拽进去。

#### 方式 3：通过 LuCI Web 管理界面上传
若路由器已预装软件包管理界面：
1. 打开网页管理后台，进入 **系统 (System) -> 软件包 (Software)**。
2. 点击 **上传软件包 (Upload Package)** 按钮。
3. 选择本地的 `.ipk` 文件并点击上传安装。

---

### 步骤 3：在路由器上执行安装

通过 SSH 登录路由器执行安装命令：
```sh
ssh root@192.168.1.1
cd /tmp
```

#### 1. 基础安装命令
```sh
opkg install ./<插件文件名>.ipk
```
如果同时有主程序和中文语言包，可以一次性安装：
```sh
opkg install ./luci-app-*.ipk ./luci-i18n-*.ipk
```

#### 2. 处理依赖缺失问题
如果插件依赖其他官方公共库（例如 `curl`、`libopenssl`、`iptables` 等）：
```sh
# 先更新软件源索引，使 opkg 能自动联网补齐缺失的依赖
opkg update
opkg install ./<插件文件名>.ipk
```

#### 3. 忽略内核版本号严格校验（慎用）
对于某些内核驱动（`kmod-*`），如果由于内核哈希（vermagic）细微差异报错：
```text
Collected errors:
 * satisfy_dependencies_for: Cannot satisfy the following dependencies for kmod-...
```
可在确保内核主版本完全兼容的前提下，添加忽略依赖参数强制安装：
```sh
opkg install --force-depends ./kmod-example.ipk
```
*(注意：此参数仅限确实兼容的驱动，严禁对跨主版本的内核模块强装，否则可能引发内核崩溃 Kernel Panic)*。

---

### 步骤 4：刷新缓存与启动服务

安装完成后，通常需要让 LuCI 界面识别新插件并启动后台服务：

1. **刷新 LuCI 网页缓存**（解决安装后 Web 界面不显示菜单的问题）：
   ```sh
   rm -rf /tmp/luci-indexcache /tmp/luci-modulecache/
   /etc/init.d/rpcd restart
   /etc/init.d/uhttpd restart
   ```
2. **启用并启动后台服务**：
   如果插件带有后台守护进程：
   ```sh
   # 设置开机自启
   /etc/init.d/<服务名> enable
   # 立即启动服务
   /etc/init.d/<服务名> restart
   ```
3. **检查运行状态**：
   ```sh
   /etc/init.d/<服务名> status
   logread | tail -n 30
   ```

---

### 步骤 5：卸载与清理

1. **清理安装包缓存**：
   安装完成后，删除 `/tmp` 中的安装包释放内存：
   ```sh
   rm -f /tmp/*.ipk
   ```
2. **卸载插件**（若不再需要）：
   ```sh
   # 停止并禁用服务
   /etc/init.d/<服务名> stop
   /etc/init.d/<服务名> disable

   # 卸载软件包
   opkg remove <包名>
   opkg remove luci-app-<包名> luci-i18n-<包名>-zh-cn
   ```
