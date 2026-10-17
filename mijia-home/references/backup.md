# 米家极客版备份文件（.bak 格式与工具）

> 配套：规则 JSON 结构与节点见 `references/rule-kit.md`；通过控制台导入导出见 `references/console.md`。

## 二进制格式（已完全破解）

```
[4字节小端 uint32: 解压后JSON字节长度] + [raw DEFLATE 压缩的单行JSON(UTF-8)] + [32字节 SHA-256(前两段)]
```

- 🚨 SHA-256 校验尾不可省略——缺失则导入界面点确定后**一直转圈无响应**（实测）
- DEFLATE 为裸流（无 zlib/gzip 包装），任何标准实现压缩均可，无需与官方字节一致（.NET DeflateStream 兼容）

## 工具

### Python（mijia_rule_kit，推荐）

本 skill 依赖的 `mijia_rule_kit.py` 位于 `scripts/`，提供打包/解包，跨平台、与生成器同语言：

```python
import sys; sys.path.insert(0, "<skill目录>/scripts")
from mijia_rule_kit import pack_bak, unpack_bak, merge_import_set
pack_bak(import_set, "out.bak")   # import_set = merge_import_set(rules, vars_global)；写出可导入 .bak
d = unpack_bak("backup.bak")      # .bak → dict，顺带校验长度头与 SHA-256 尾
```

实现要点（自行实现时照抄）：单行紧凑 JSON(`separators=(',',':')`)→ `zlib.compress(js,9)[2:-4]` 取裸 deflate（去 zlib 头2+adler32尾4）→ `[4字节LE 未压缩长度]+deflate` 为 body → 追加 `sha256(body)` 32 字节尾。

### PowerShell（零依赖备选）

`scripts/bak-pack.ps1` / `scripts/bak-unpack.ps1` 提供 PowerShell 版打包/解包，无需 Python：

```powershell
.\scripts\bak-pack.ps1 -JsonPath "规则.json" -OutPath "输出.bak"
.\scripts\bak-unpack.ps1 -BakPath "备份.bak" -OutPath "输出.json" -Pretty
```

## 已验证结论

- 官方导出原文件可原样重导入；自行重打包**带 SHA-256(前缀+deflate) 校验尾**即可成功导入。
- 导入语义为**全量覆盖**（非合并）：改任一条规则也须「导出全集→修改→整体重导」。仅含新规则的 .bak 会替换现有规则集。详见 references/console.md。
- 解包时校验 SHA-256 和声明长度；校验失败或缺失时立即停止，不要继续解析或导入，并保留原始备份。
- 导出的 .bak 解包内容与控制台一致；含全部规则 + 全局变量 + 真实 did。
- 备份会过时：用户导出后又在控制台改过规则，旧备份就不能作为合并基础。写入前重新导出一次，和手头的版本比对。
- 一份台账只对应一个网关。多网关或多户的备份不要混用 did；台账的 `sourceBackup` 必须和当前备份一致。
- 设备改名、换房间或更换设备后，台账里旧的 `confirmed` 会保留下来，要重新跑 MijiaFlow 合并或逐条复核。

## 设备台账：让 did 对应设备名

备份没有房间名和设备显示名，不能靠型号或导出顺序推测。每次拿到新的完整备份后，先生成或刷新同目录的 `设备台账.json`：

```powershell
python .\scripts\device_registry.py "备份.bak"
# 仅在已从网关页面确认后，再写入名称、房间和按键
python .\scripts\device_registry.py "备份.bak" --set "1234567890=客厅主开关|客厅|左键,中键,右键"
```

若已通过 MijiaFlow 的 `mijia_read(devices)` 保存了实时设备字典，优先合并它；它由同一条网关 `getDevList` 响应提供 `did`、名称和房间，不需要为每台设备放置临时卡片：

```powershell
python .\scripts\device_registry.py "备份.bak" --mijiaflow-devices "devices.json" --out "设备台账.json"
# 没有 .bak 时也可从实时读取生成完整设备目录
python .\scripts\device_registry.py --mijiaflow-devices "devices.json" --out "设备台账.json"
```

脚本从备份规则节点提取 `did`、`urn`、`siid/piid/aiid/eiid` 和引用它的规则；MijiaFlow 合并时会确认 `did`、名称、房间、型号和在线状态。MijiaFlow 不提供自定义按键名，按键数组必须保留为空或只填已渲染卡片/用户确认的值。生成规则时只使用 `status: confirmed` 的唯一匹配项。

若备份中没有规则节点，先尝试 MijiaFlow 读取完整设备目录。MijiaFlow 不可用时，再按 `references/console.md` 的「从零建立设备台账」创建一条停用、无连线的 `_台账采集` 规则并重新导出。

## 产物组织与主包版本管理

`mijia_rule_kit` 提供 `pack_main` / `freeze_main` 实现主包的迭代记录与验收固定：

```
主包/                       全屋导入「主包」(全量覆盖包) 的迭代记录
  主包-当前.bak             固定名指针 = 最新构建
  主包-<yyyyMMdd-HHmm>.bak   每次发布的时间戳构建(迭代轨迹)
  已固定/<vN>-<简述>.bak     现场验收通过的里程碑版本
  台账.json / 台账.md        每个构建一行：时间/文件/规则数/状态/规则列表/备注
测试包/                     局部包/探针/实验包
  保留/                     有复用价值，长期留
  临时/                     一次性，用完即清
```

**主包工作流（编辑↔发布↔固定 分离）**：

1. 编辑生成器 → 产出 `导入集.json`
2. 要导入：`pack_main(import_set, root, note="变更摘要", base="网关备份名")` → 打时间戳构建 + 刷新`主包-当前.bak` + 台账记一行（状态**待验收**）
3. 现场验收无误：`freeze_main(root, "v1", note="主卧上线")` → 复制到 `已固定/v1-主卧上线.bak` + 台账标「已固定 v1」
4. 查看台账：台账号位于 `主包/台账.md` 和 `主包/台账.json`

**底层函数**：

```python
from mijia_rule_kit import pack_main, freeze_main
pack_main(import_set, root, note="...", base="...")   # 剥TEST+时间戳构建+刷新当前+台账(待验收)
freeze_main(root, "v1", note="主卧上线")               # 固定最新构建为已验收版本 vN
```

+ **导入选哪个**：日常稳妥用 `已固定/` 里最新 vN；要验最新改动用 `主包-当前.bak`
+ **版本固定时机**：只有现场验收"反馈没问题"才 `freeze` 升 vN
+ **测试规则**（名以 `TEST` 开头）永不进主包
