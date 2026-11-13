不建议把 OpenClash 放进 `common`，应做成“显式选用”的功能配置。原因很明确：

- `configs/lite.seed` 当前明确禁用 `luci-app-openclash`。
- `scripts/configure-lite.sh` 会检查禁止包，发现 OpenClash 被选中就直接构建失败。
- `docs/LITE-README.md` 和 Lite 需求都明确“不预装 OpenClash”。
- `manifests/sources.json` 会把 `common` 同时应用到所有设备及 OpenWrt、ImmortalWrt；放进去会无差别影响 x86、树莓派等目标，不符合分层规则。
- TR3000 Lite 使用 112 MiB UBI，OpenClash 及其核心、规则集会显著占用镜像和可写空间，不能未经容量验证直接启用。

建议修改方案：

1. 在 `configs/lite.seed` 中将 OpenClash 从显式禁用改为 `CONFIG_PACKAGE_luci-app-openclash=y`。
2. 在 `scripts/configure-lite.sh` 中把 `luci-app-openclash` 从禁止包列表移除，并加入必需包验证列表。
3. 在 `feeds/devices/tr3000-lite.lock` 增加 OpenClash 软件源并固定完整 commit SHA；未核验值不能猜。
4. 更新 `docs/LITE-README.md` 及 TR3000 Lite 需求说明。
5. 更新测试并在 CI 中检查最终镜像尺寸、包清单及剩余空间。

为方便其他设备以后使用，可以新增独立的可选片段，例如 `configs/features/openclash.config`，由各设备或构建 profile 显式引用；不要修改公共配置与 feed。

完成后应运行 `bash scripts/validate.sh` 和 `python -m unittest discover -s tests -v`，并在 GitHub Actions 实际编译验证。
