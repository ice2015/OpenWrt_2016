先不要清缓存。已确认根因是上游 `CONFIG_CCACHE_DIR="/workdir/.ccache"` 覆盖了 GitHub Runner 的实际目录；即使 Actions 显示 cache miss，删缓存也不能修复路径不一致。

先检查 artifact 的 `build.config` 中 `CONFIG_CCACHE_DIR` 是否为本次 Runner 的临时 ccache 路径，再查看 `build_dir/host/m4*/config.log` 的第一条底层编译错误。当前修复由 `build-lite.sh` 把实际目录通过 `--ccache-dir` 传给 `configure-lite.sh`。只有路径正确且 config.log 明确显示缓存条目损坏时，才轮换精确 cache key；不要同时清理下载缓存或整个生成目录。
