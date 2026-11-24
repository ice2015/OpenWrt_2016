# 新增设备指南

新增设备不需要修改核心脚本。以下示例使用稳定 ID `new-router`；ID 只使用小写字母、数字和连字符，创建后不要因显示名称变化而重命名。

## 1. 核实上游信息

分别在目标 OpenWrt/ImmortalWrt revision 中核实：

- 厂商、完整型号和硬件 revision；
- `target`、`subtarget` 和 `profile`；
- bootloader、闪存布局和升级镜像限制；
- 实际产物文件名模式；
- 两个发行版是否都支持该设备。

不能确认的字段填写精确字符串 `UNRESOLVED`。不要复制相似型号的 profile 作为猜测值。

## 2. 创建设备清单

硬件与目标发行版支持核实之前，先建立 `devices/new-router/README.md` 的待适配说明，不新增可构建目标，也不猜测 `supported_distributions` 来通过校验。核实后创建 `manifests/devices/new-router.json`，参考现有 schema，至少填写：

- `id` 与 `display_name`；
- `supported_distributions`；
- `target`、`subtarget`、`profile`；
- 配置层和产物模式；
- `notes` 中的刷写、版本或硬件警告。

清单中的路径必须是仓库内相对路径，禁止 `..` 或绝对路径，也不能引用其他设备目录；所有未知硬件字段继续保持 `UNRESOLVED`。

## 3. 添加设备层

按实际需要创建：

```text
devices/new-router/config.config
devices/new-router/files/
devices/new-router/patches/
devices/new-router/build/
```

只需配置片段时不要创建空补丁或 overlay。任何新增路径都必须在设备清单中显式引用。

## 4. 校验结构

从仓库根目录运行：

```sh
bash scripts/validate.sh
bash scripts/list-targets.sh
python -m unittest discover -s tests -v
```

列表中应出现预期发行版/设备组合。如果仍有 `UNRESOLVED`，状态应显示为 `unresolved`。

## 5. 检查构建就绪状态

```sh
python tools/manifest.py resolve \
  --distribution openwrt \
  --device new-router \
  --require-build-ready
```

状态码 `3` 表示仍有必填构建值未确认。只有命令返回 `0` 后，才可以继续实现或触发真实构建阶段。

## 6. 提交和 Actions 验证

Pull Request 会运行只读结构校验，不会使用 Secrets 或编译固件。合并前检查改动是否只影响目标设备；如果修改公共层，应明确列出对所有既有设备的影响。

当设备已经过真实硬件验证后，再把对应设备加入发布或定时矩阵。保留解析后的 `.config`、源码 commit、包列表、固件校验和和刷写测试记录。

