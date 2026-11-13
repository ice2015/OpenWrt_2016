不能把 OpenClash 放进 `common`。TR3000 Lite 是独立构建路径；公共配置会扩散到 TR3000、x86_64、Raspberry Pi 的 OpenWrt/ImmortalWrt 组合，而这些目标尚未完成依赖和容量验证。

只应修改设备专用路径：`configs/lite.seed`、`scripts/configure-lite.sh`、必要时的 `feeds/devices/tr3000-lite.lock`、`tests/scripts/test_scripts.py` 与 `docs/LITE-README.md`。当前 seed 和脚本明确排除 `luci-app-openclash`；改变它之前必须核实固定 feed revision、依赖核心、ABI、许可证、镜像大小与 112 MiB UBI 的可写空间。未经核实不猜值，也不声明可构建或可刷写。
