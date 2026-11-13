当前两个项目 Artifact 都不要刷：Lite sysupgrade 和 DHCP U-Boot 都只覆盖 128 MiB。没有可推荐给 256 MiB 设备的文件；不要用 `-F` 或猜测的原始写入命令。旧技能能通过通用硬件、NAND 和布局检查阻止混刷，但 Artifact 名和 128 MiB-only 边界来自额外读取项目工作流与文档。
