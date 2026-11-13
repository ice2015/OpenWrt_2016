目前不能按“常见 Raspberry Pi”填写具体构建目标。不同型号的 `subtarget`、`profile` 和镜像规则并不通用；仓库规则明确禁止猜测。

仓库已经登记 `immortalwrt/raspberry-pi` 组合。现阶段 `target`、`subtarget`、`profile` 都应保持 `UNRESOLVED`，构建就绪检查继续返回状态码 `3`。

确认精确型号及硬件修订后，才会更新 `manifests/devices/raspberry-pi.json`、`configs/devices/raspberry-pi.config`，并在核实后固定 `manifests/sources.json` 的 ImmortalWrt revision。源码 revision 会影响全部 ImmortalWrt 目标，不能只为 Raspberry Pi 随意修改。收到具体型号和 revision 前不会填写猜测值。
