目前不能填写具体的 Raspberry Pi 构建目标，也不应为了“今天提交”猜一个常见型号。仓库已有 ImmortalWrt 入口；在型号和源码版本未确定前，`target`、`subtarget`、`profile` 必须保持 `UNRESOLVED`。

确定完整型号和 ImmortalWrt commit/tag 后，才会修改 `manifests/devices/raspberry-pi.json`、`configs/devices/raspberry-pi.config`，必要时更新会影响全部 ImmortalWrt 目标的 `manifests/sources.json`。收到这些信息前没有安全的新配置可提交。
