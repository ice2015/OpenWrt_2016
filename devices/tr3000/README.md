# TR3000

- [Lite](lite/README.md)
- [Full](full/README.md)
- [U-Boot](uboot/README.md)

build/ 保存设备构建实现，shared/ 保存本型号共享输入；lite/、full/ 分别保存变体输入。普通 manifest 的未知字段继续保持 UNRESOLVED，不能从专属构建推断所有硬件修订均受支持。

配置优先级保持 common → distribution → device → local；设备层先 shared 再选定变体。固定源码、112 MiB UBI 校验及刷机前硬件核实要求均保持有效。

旧命令入口保留原参数和可执行权限；被 source 的旧库入口使用 Git 符号链接，支持从仓库外的 POSIX sh 或 Bash 加载。固件始终安装真实设备脚本。Windows 未启用符号链接时会看到链接目标占位文本，执行这些库应使用 Linux/WSL 文件系统中的检出；Windows 检出可用于编辑和静态检查。
