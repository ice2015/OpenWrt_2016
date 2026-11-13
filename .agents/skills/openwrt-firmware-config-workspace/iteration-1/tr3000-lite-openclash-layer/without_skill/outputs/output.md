不建议把 OpenClash 放进 `common`。`configs/lite.seed` 当前明确禁用 `luci-app-openclash`，`scripts/configure-lite.sh` 会验证禁止包；公共层会无差别影响 x86、树莓派等目标。

如果改变 Lite 定位，应只更新 Lite seed、配置验证、固定 feed、文档和测试，并在 GitHub Actions 检查最终包清单、镜像尺寸与剩余空间。未经核实的软件源 revision 不能猜。
