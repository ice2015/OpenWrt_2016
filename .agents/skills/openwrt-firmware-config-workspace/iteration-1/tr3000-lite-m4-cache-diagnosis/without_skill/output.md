建议按 GitHub Actions 的 TR3000 Lite 专用流程处理；不要运行通用 `scripts/build.sh`，通用 TR3000 清单目前仍是 `UNRESOLVED`。

1. 先从失败任务的 Artifact 保存 `logs/build.log` 和 `logs/build-serial-retry.log`。
2. 在 GitHub Actions Caches 中删除 `tr3000-lite-Linux-` 开头的缓存；工作流实际缓存 `$RUNNER_TEMP/tr3000-lite/ccache` 与 `dl`。
3. 重新运行 TR3000 Lite firmware 工作流，不要在 Windows 原生环境直接编译。
4. 如果清空后仍复现，则检查 `build_dir/host/m4*/config.log`，并定位第一条稳定编译或链接错误。

`cannot compute suffix of object files` 不一定就是缓存损坏；它只是 Autoconf 上层错误。优先排查磁盘、宿主 GCC/链接器、缺少头文件、ccache 权限或下载包。脚本会在并行失败后用 `-j1 V=s` 重试，因此串行日志通常最有诊断价值。
