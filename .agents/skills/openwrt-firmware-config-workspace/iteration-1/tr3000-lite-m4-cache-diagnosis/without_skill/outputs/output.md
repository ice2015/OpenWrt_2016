建议先下载失败 artifact 的 `build.log` 和 `build-serial-retry.log`，删除 GitHub Actions 中 `tr3000-lite-Linux-` 开头的 ccache 与下载缓存后重跑。若仍复现，再查看 `build_dir/host/m4*/config.log` 的第一条底层错误。

顶层报错不一定表示缓存损坏，也可能是磁盘、宿主工具链、头文件或权限问题。
