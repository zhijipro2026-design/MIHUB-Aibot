# 极客版规则 JSON 与节点类型

> 写规则或审查节点时按需查阅。

## JSON 结构速查

```jsonc
{
    "version": 2,
    "rules": [{
        "id": "<毫秒时间戳>",
        "cfg": {
            "id": "<同上>",
            "userData": { "name": "<规则名>", "transform": {"x":0,"y":0,"scale":1,"rotate":0},
                          "lastUpdateTime": <毫秒时间戳>, "version": 0, "tags": ["<标签>"] },
            "uiType": "test", "enable": true/false
        },
        "nodes": [ /* 卡片节点，见下 */ ]
    }],
    "variables": { "global": { "<11位字母数字ID>": { "type": "string|number", "value": <初始值>,
                                                   "userData": { "name": "<显示名>" } } } }
}
```

节点通用结构：`{ id, type, cfg:{urn?, pos:{x,y,width,height}, name:<type同名>, version}, inputs:{...:null}, outputs:{<端口>:["目标节点ID.目标端口"]}, props:{...} }`

- **连线**全部记录在源节点 `outputs`，格式 `"节点ID.端口名"`；条件类节点 `output`=成立分支、`output2`=否则分支
- 节点 ID：10 位随机串或 `类型名+毫秒时间戳`；变量 ID：见下「变量 ID 约束」
- `cfg.pos` 只影响画布美观；程序生成时按列×行排版（间距 x≈700, y≈150）避免重叠

## 节点类型表（已覆盖 25 种，遇新类型立即补充）

### 设备类
| type | 卡片 | props 要点 |
| --- | --- | --- |
| deviceInput | 事件/状态更新（触发） | did, siid, piid, dtype(`boolean/int/float/string/number`), operator(`= != < > <= >= include`), v1(include时为数组), preload |
| deviceGet | 查询当前状态（条件） | 同上；output=成立 / output2=否则 双分支 |
| deviceOutput | 执行操作 | 属性写入: {did,siid,piid,value}；动作: {did,siid,aiid,ins:[{piid,value}]}；ins 元素可为变量引用 {piid,id,scope,dtype} |
| deviceInputSetVar | 设备触发赋值 | {did,siid,piid,preload,dtype,id,scope} 设备状态变化时写入变量 |
| deviceGetSetVar | 查询设备赋值 | {did,siid,piid,dtype,id,scope} 查询设备属性写入变量（前面须有触发） |

### 触发类
| type | 卡片 | props 要点 |
| --- | --- | --- |
| timeRange | 时间段 | start/end:{hour,minute,second}, filter（同 alarmClock）；支持跨天 |
| alarmClock | 定时/日出日落 | 定时: {type:"periodicAlarm",hour,minute,second}；日出日落: {type:"sunset",isSunset(true=日落),offset,latitude,longitude}；filter 可选: {day:[1-6,0]}周过滤 / {inHoliday:true/false}节假日过滤 |
| onLoad | 规则加载时触发 | 无 props |
| varChange | 变量变化触发 | id, scope, varType, operator, v1, preload（operator 仅 `=`，见下约束） |

### 逻辑/流程类
| type | 卡片 | 端口与 props |
| --- | --- | --- |
| logicAnd / logicOr | 满足全部/任一条件 | inputs: input0..N；无 props；**latch 语义**（见下） |
| logicNot | 条件取反 | input → output |
| condition | 条件判断 | inputs: trigger+condition；outputs: met/unmet |
| signalOr | 信号或（任一信号到达即放行） | inputs: input0..N |
| delay | 延时（防抖：重触发则重置） | {timeout: 毫秒} |
| statusLast | 状态维持 | {timeout: 毫秒} |
| loop | 循环 | inputs: start/stop；{interval: 毫秒} |
| counter | 计数器（满 n 次放行） | inputs: input/zero(清零)；{n} |
| onlyNTimes | 仅执行 N 次 | inputs: input/zero(重置)；{n} |
| eventSequence | 事件顺序（input1 后 timeout 内 input2） | inputs: input1/input2；{timeout: 毫秒} |
| register | 寄存器（布尔状态保持） | inputs: setTrue/setFalse |
| modeSwitch | 模式切换（循环轮转） | outputs: output0..N |
| **nop** | **文本注释卡**（工具栏「文本」按钮，画布文档/备注，不连线不执行） | 见下 |

**nop 文本注释卡**（给规则加画布注释）：`type:"nop"`，无连线、不参与执行，纯文档。结构特殊——内容/样式/坐标全在 `cfg`：
```json
{"id":"<id>","type":"nop","inputs":{},"outputs":{"output":[]},"props":{},
 "cfg":{"contents":[{"insert":"注释文字\n"}],   // Quill Delta 富文本数组；加粗等加 "attributes":{"bold":true}
        "background":"#80CAFF",                  // 卡片底色
        "pos":{"x":..,"y":..,"width":320,"height":60},"name":"nop","version":1}}
```
校验/排版须特判：nop 无入边出边属正常（勿当悬空报错）、不参与拓扑排版（保留手填坐标）。`mijia_rule_kit` 提供 `text_note(text,x,y,...)`，并已在 validate/auto_layout 里特判；配合 `set_band`+`band_top` 可给每条意图泳道挂分组标题。

### 变量类
| type | 卡片 | props 要点 |
| --- | --- | --- |
| varSetString | 文本变量赋值/文本拼接 | id, scope, elements（表达式 token 列表，见下） |
| varSetNumber | 数值变量赋值/数值运算 | 同上 |
| varGet | 查询变量（条件） | id, scope, varType, operator(仅 `=`), v1；output/output2 双分支 |

**elements 表达式语法**（varSetString/varSetNumber 通用）：token 数组顺序拼接，两种 token：
- `{"type":"const","value":"<文本片段>"}`
- `{"type":"var","id":"<变量ID>","scope":"global|R<规则ID>"}`

数值运算即把函数写进 const 片段拼变量，如 `abs(x)` = `[{const:"abs("},{var:x},{const:")"}]`；已见函数：`abs(x)`、`pow(x,2)`、`log(x,3)`、`now()`。文本拼接同理混排 const/var。

**变量 scope**：全局=`"global"`；本规则变量=`"R<规则ID>"`。✅ **规则变量的定义会序列化进备份**（实测验证：导出→导入→再导出回路后，`variables.R<规则ID>` 域下的变量定义完好保留）。⚠️ 前提：变量必须有卡片引用（无引用的孤立定义可能被平台清理）。规则私有变量优先用规则 scope 而非全局变量，避免全局变量列表膨胀。

