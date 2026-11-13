# 配置分层规则

## 固定优先级

每种构建输入都使用相同优先级：

```text
common → distribution → device → local
```

- **common**：全部设备和发行版都需要的最小设置。
- **distribution**：OpenWrt 或 ImmortalWrt 独有差异。
- **device**：目标、驱动、文件系统和硬件专属设置。
- **local**：个人网络、实验包、私密文件及机器差异；不提交。

如果一个设置只服务一台设备，不要为了“方便”上移到公共层。公共层变化会影响全部设备，应作为跨目标改动审查。

## 原生配置片段

`configs/` 中使用 OpenWrt 原生 `CONFIG_...` 语法，不引入第二套配置语言。初始片段只有说明性注释，不预设 LuCI、软件包、镜像大小或网络行为。

未来的准备流程会按清单顺序合并片段，然后运行 `make defconfig`。解析后的完整 `.config` 是构建报告，不是手工维护的源文件。

## Feeds

公共额外 feeds 写入 `feeds/common.conf`，发行版差异分别写入 `feeds/openwrt.conf` 和 `feeds/immortalwrt.conf`。设备专属 feeds 只有确实无法共享时才添加，并在设备清单中明确引用。

上游默认 feeds 仍由对应源码树管理；本仓库文件用于附加或有意覆盖，并需要在构建报告中记录最终来源和 revision。

## Rootfs overlays

- 公共文件：`overlays/common/files/`
- 设备文件：`overlays/devices/<device-id>/files/`
- 私有文件：`local/` 下的未跟踪 overlay

不要提交密码、SSH 私钥、Wi-Fi 凭据或个人公网配置。需要模板时提交无敏感值的示例，并让部署阶段注入真实值。

## Patches

- 公共补丁：`patches/common/`
- 发行版补丁：`patches/distributions/<distribution-id>/`
- 设备补丁：`patches/devices/<device-id>/`

补丁文件使用数字前缀表达顺序，例如 `010-fix-device-tree.patch`。说明补丁适用的上游 revision 范围和是否已提交上游；源码升级后必须重新验证。

## 本地覆盖

`local/` 中除 README 外全部被忽略。它适合个人配置，但不能作为 GitHub Actions 默认构建的隐式依赖。CI 需要的敏感数据必须通过明确的 Secrets 输入，并禁止传入来自 fork 的 Pull Request。

