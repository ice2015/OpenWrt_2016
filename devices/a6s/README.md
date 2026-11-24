# A6S

状态：待适配。本目录仅为说明入口，没有可构建 manifest 或固件支持承诺。

## 预留目录

```text
a6s/
├─ README.md
├─ build/       # 设备构建、配置及镜像检查脚本
├─ files/       # 固件 rootfs 覆盖文件
├─ packages/    # 设备专属软件包
├─ patches/     # 设备专属补丁
├─ runtime/     # 设备运行脚本和库
├─ uboot/       # 配套 U-Boot 输入和说明
└─ docs/        # 初始化、运维和验证文档
```

当前仅预留目录，以 `.gitkeep` 让 Git 保留空目录。尚未划分 Lite/Full 等变体；实际配置、源码锁和构建入口在后续适配时添加。本轮不创建 manifest、固件配置或 Actions 工作流，也不进行编译或刷写。

待核实：厂商、精确型号及硬件修订、闪存容量与启动方式、发行版与源码 revision、上游 profile、镜像类型、软件包策略及验收硬件。未知项保持 UNRESOLVED；不得复制其他设备的配置作为已验证事实。
