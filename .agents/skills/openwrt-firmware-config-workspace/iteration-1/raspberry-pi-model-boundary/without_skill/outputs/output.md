目前不能填写具体的 Raspberry Pi 构建目标，也不应为了“今天提交”猜一个常见型号。仓库已经有 ImmortalWrt 入口：

- `manifests/devices/raspberry-pi.json` 已包含 `"immortalwrt"`。
- `configs/devices/raspberry-pi.config` 已作为设备配置层引用。

在型号和源码版本未确定前，我会保持：

```json
"target": "UNRESOLVED",
"subtarget": "UNRESOLVED",
"profile": "UNRESOLVED"
```

原因是 Raspberry Pi 3、4、5 对应的 subtarget/profile 不同；同时 `manifests/sources.json` 中 ImmortalWrt 的 `revision` 也仍为 `UNRESOLVED`。仓库规则明确禁止从相似设备或“常见型号”猜这些值。

确定“完整型号 + ImmortalWrt commit/tag”后，才会修改：

- `manifests/devices/raspberry-pi.json`：填写经该 revision 核实的 `target`、`subtarget`、`profile`、产物匹配规则和型号说明。
- `configs/devices/raspberry-pi.config`：加入对应的原生 `CONFIG_TARGET_...` 选择及仅属于该型号的硬件配置。
- 必要时更新 `manifests/sources.json` 的 ImmortalWrt 固定 revision；这是发行版级改动，会影响所有 ImmortalWrt 设备，不能作为 Raspberry Pi 私有设置随意修改。

因此今天可以提交的真实结论是：现有仓库已经正确表达“支持 ImmortalWrt，但具体 Raspberry Pi 型号未决”，没有新的安全改动可做。请先指定例如“Raspberry Pi 4B”或“Raspberry Pi 5”及硬件版本；否则这些三个字段必须继续保持 `UNRESOLVED`。
