# 米家极客版自动化规则编写

> 配套：.bak 打包/解包见 `references/backup.md`；导入控制台+自验证+执行日志见 `references/console.md`。
> 入门教程见 `references/beginner.md`。

## 必须记住的硬约束（详情见 references/platform-notes.md）

- `varGet`/`varChange` 只支持 `=`；表达「≠」取 `output2` 否则分支。设备节点支持全套比较符。
- 全局变量 ID 必须 11 位纯字母数字，否则被静默丢弃。
- 枚举状态（如人在传感器有人/无人）必须 `operator:"include"` + 数组 `v1`，否则编辑器白屏。
- 只有触发节点会主动触发；`deviceGet`/`varGet` 是被动门，必须有上游信号。
- `logicAnd`/`logicOr` 是锁存语义，记住每路最新值；下游动作前要复核当前状态，避免误触发。
- 「持续 X 时间」用 `statusLast`，每个事件源各挂一个；不要多源共用一个 `delay`（会被重复上报不停重置）。
- `delay`/`statusLast` 卡的 `cfg.value`+`cfg.unit` 要和 `props.timeout` 一致，库已自动写入。
- `alarmClock` 不认星期/节假日过滤；需要时用 `timeRange` 接 `condition`（库里 `workday_gate`）。
- 写固定开/关前先 `deviceGet` 查当前状态；切换类动作不套用预检。
- 触发卡的 `preload`（启用时查询一次）对占用、照度、场景类触发一般关闭，避免重启时重放动作。

节点 JSON 结构与 25 种节点类型见 `references/nodes.md`。

## 设备寻址（MIoT-Spec-V2）

`did` 定位设备实例，`urn` 描述型号，`siid/piid` 属性、`siid/aiid` 动作。
🚨 **did 必须取自用户导出的真实备份，严禁虚构**；蓝牙子设备 did 带 `blt.` 前缀。
💡 **不靠样本查 piid**：拿到型号（urn 第 5 段如 `xiaomi-ceil02`）后用 MIoT 官方 spec 权威查全属性表：用你的联网工具打开 `https://miot-spec.org/miot-spec-v2/instance?type=<完整urn>`。spec 给标准能力，**写入语义仍需导入实测复核**。控制台点设备时自身就请求该 spec 接口，印证其权威性。
注意：**备份 JSON 不含设备名称/房间**（前端拿 did 实时查网关渲染）。建议为项目维护一份「did→名称/房间/型号/urn」映射表。

### 规则前先解析设备台账

把用户说的「客厅右键」翻译成设备地址前，先读与这份完整备份对应的 `设备台账.json`，用 `resolve_confirmed_device()` 取唯一的 `confirmed` 条目；同名、未映射或通道不明时停下来找用户确认。台账怎么生成见 `references/backup.md`。设备设置类需求还要用 MIoT spec 把界面文字对应到 `siid/piid/value`，枚举值不能把 `On` 直接当成 `true` 或 `1`。

“通电后默认状态”是设备配置属性：规则的 `onLoad` 只在规则启用/重载时写入，真正的上电行为由开关在之后断电恢复时执行。用户明确要求上线时，才把该规则设为启用。

人在传感器 Pro 的分区寻址见 `references/platform-notes.md` 末尾。

## 安全默认值与全量导入

- 此本地构造器已将 `build_rule()` 默认改为 `enable=False`；生成新规则时仍显式传 `enable=False`，仅在用户明确要求启用时设为 `True`。
- `merge_import_set()` 默认不再附加水印；实际构建时显式用 `add_watermark=False`，除非用户要求水印。
- `.bak` 恢复是**全量替换**。改现有家庭时，从最新完整备份解包，保留全部规则、全局变量和规则级变量，再加入修改；不可将仅含新规则的文件当增量导入。
- `validate()` 只检查结构和部分变量引用，不能证明设备 ID/MIoT 参数、网关兼容性或物理行为正确。
- “状态切换”应使用已核实的 `call_action()` 及其 `siid/aiid/ins`；不要用固定开/关属性写入代替切换。

## 生成工具库 mijia_rule_kit

`scripts/mijia_rule_kit.py`（零依赖，仅 Python 标准库）提供 `RuleBuilder`，业务脚本只声明「节点 + 连线」，平台硬约束由库兜。

```python
import sys; sys.path.insert(0, "<skill目录>/scripts")
from mijia_rule_kit import RuleBuilder, merge_import_set, dump_json, load_import_set_from_file
rb = RuleBuilder()
rb.declare_external_var("Vxxxxxxxxxx")              # 只读引用别处定义的变量
rb.define_var("Vdbgxxxxxx1", "string", "", "调试")    # 本规则引入的变量（ID 须11位纯字母数字）
t = rb.trigger_device(did, urn, 2, 1, "int", "=", 1)
c = rb.cond_var("Vxxxxxxxxxx", "某值")
a = rb.write_device(did, urn, 2, 7, 1)
rb.link(t, "output", c, "input"); rb.link(c, "output", a, "trigger")
rb.auto_layout()                                       # 拓扑分层自动排版
rb.validate(raise_on_error=True)                       # 落边+校验
rule = rb.build_rule("<毫秒时间戳>", "<规则名>", ["<标签>"], enable=False)
# 从最新完整快照开始；导入会覆盖整个规则集，保留所有变量作用域。
base_rules, base_vars, base_scopes = load_import_set_from_file("<最新完整导出>.json")
new_vars = rb.var_definitions()
base_vars.update(new_vars.pop("global", {}))
base_scopes.update(new_vars)
snapshot = merge_import_set(base_rules + [rule], base_vars,
                            rule_var_scopes=base_scopes, add_watermark=False)
dump_json(snapshot, "导入集.json")
```

主要方法：`on_load / trigger_device / trigger_event / trigger_virtual_event / trigger_var / time_range / alarm_periodic / alarm_sun / workday_gate`（触发），`cond_device / cond_var / condition`（条件），`delay / status_last / signal_or / logic_and / logic_or`（流程），`write_device / call_action / fire_virtual_event / tts / set_var`（动作），`link`（连线），`define_var / declare_external_var`（变量），`text_note`（注释卡），`set_band`（意图分组），`auto_layout`（画布自动排版），`validate / build_rule / var_definitions`（组装）。模块函数：`load_rules_from_file / load_import_set_from_file / merge_import_set / dump_json / pack_bak / unpack_bak / pack_main / freeze_main / brand_watermark_rule`。

设备台账辅助函数：`load_device_registry(path)` 读取台账，`resolve_confirmed_device(registry, name, room, channel)` 只会返回唯一的已确认设备，否则抛错。生成脚本应先解析名称到 `did/urn`，再调用 `write_device` 或其他节点构造方法。

### 品牌水印规则

`merge_import_set(rules, vars, add_watermark=False)` 默认不追加品牌标识规则。用户明确需要时才设置 `add_watermark=True`，或单独调用 `brand_watermark_rule(repo_url, version)` 生成。

### 编写新规则的标准流程

1. 取真实地址：导出当前备份解包拿 did；piid/取值范围用 `miot-spec.org`
2. 设计稿先与用户确认逻辑
3. 用 `mijia_rule_kit` 写声明式生成脚本，显式以 `enable=False` 生成 → `validate` 通过。🚨改动既有规则须基于**最新导出全集**合并（导入是覆盖）
4. 写入前准备：有 MijiaFlow 时按单条规则 `set_graph`；没有时打包 .bak（`pack_bak` 或 `scripts/bak-pack.ps1`）
5. 只在用户明确要求时写入网关；整包导入前重新导出确认网关没变，并给用户看差异
6. 编辑器画布自检 + 执行日志回放验证 → 结论回写设计稿
