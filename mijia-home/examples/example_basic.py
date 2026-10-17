# -*- coding: utf-8 -*-
"""米家极客版规则生成示例：两条禁用规则 + 变量 + JSON 导入集草稿。

本示例使用占位符 did 和设备 urn，只演示结构，不可导入真实网关。
运行：python example_basic.py
产物：导入集示例.json。它不是网关完整快照；要导入真实网关，先从最新完整导出保留已有规则和所有变量作用域，再合并并审阅。
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
from mijia_rule_kit import RuleBuilder, merge_import_set, dump_json

# === 占位符（使用时替换为真实值）===
DID_SENSOR = "1234567890ab"           # 人体传感器 did
DID_LIGHT = "0987654321ba"            # 走廊灯 did
URN_SENSOR = "urn:miot-spec-v2:device:occupancy-sensor:0000A001:xiaomi-p1:1"
URN_LIGHT = "urn:miot-spec-v2:device:light:0000A001:xiaomi-ceil02:1"
VAR_DEBUG = "VdbgMod0001"             # 调试模式变量（11位字母数字）
VAR_TIME = "VtdSegm3kQ7"              # 时间段变量

# === 规则 1：走廊自动开灯 ===
rb1 = RuleBuilder(node_prefix="c1")
rb1.define_var(VAR_DEBUG, "string", "开启", "调试模式")
rb1.declare_external_var(VAR_TIME)    # 引用全局时间段变量（由其他规则维护）

# 触发：人体传感器有人
trigger = rb1.trigger_device(DID_SENSOR, URN_SENSOR, 2, 1, "int", "include", [1])
# 条件：时间段 = 夜间
time_gate = rb1.cond_var(VAR_TIME, "夜间")
# 动作：开灯（灯关着才开；开关属性为布尔，siid/piid 以真实设备 spec 为准）
check_off = rb1.cond_device(DID_LIGHT, URN_LIGHT, 2, 1, "boolean", "=", True)
turn_on = rb1.write_device(DID_LIGHT, URN_LIGHT, 2, 1, True)

rb1.link(trigger, "output", time_gate, "input")
rb1.link(time_gate, "output", check_off, "input")
rb1.link(check_off, "output2", turn_on, "trigger")
rb1.auto_layout()
rb1.validate(raise_on_error=True)
rule_light_on = rb1.build_rule("1700000000001", "走廊-自动开灯", ["灯光自动化", "走廊"], enable=False)

# === 规则 2：走廊人走关灯 ===
rb2 = RuleBuilder(node_prefix="c2")
rb2.declare_external_var(VAR_TIME)

# 触发：人体传感器无人
trigger = rb2.trigger_device(DID_SENSOR, URN_SENSOR, 2, 1, "int", "include", [0])
# 持续无人 20 秒（statusLast：人回来就不会关；开发期短时长验证，上线改为 300000=5分钟）
hold = rb2.status_last(20000)
# 预检：灯是否为开（P6 范式：写前预检，避免重复关灯）
check = rb2.cond_device(DID_LIGHT, URN_LIGHT, 2, 1, "boolean", "=", True)
# 动作：关灯
turn_off = rb2.write_device(DID_LIGHT, URN_LIGHT, 2, 1, False)

rb2.link(trigger, "output", hold, "input")
rb2.link(hold, "output", check, "input")
rb2.link(check, "output", turn_off, "trigger")
rb2.auto_layout()
rb2.validate(raise_on_error=True)
rule_light_off = rb2.build_rule("1700000000002", "走廊-人走关灯", ["灯光自动化", "走廊"], enable=False)

# === 合并规则草稿（不附加品牌水印）===
import_set = merge_import_set(
    [rule_light_on, rule_light_off],
    {VAR_TIME: {"type": "string", "value": "白天", "userData": {"name": "时间段"}}},
    add_watermark=False,
)

from mijia_rule_kit import check_import_set
problems = check_import_set(import_set)
assert not problems, problems

# 写出 JSON
out_json = os.path.join(os.getcwd(), "导入集示例.json")   # 写到当前文件夹，不写进技能目录
dump_json(import_set, out_json)
print("JSON 已生成: %s" % out_json)
print("包含 %d 条停用规则；此示例使用占位设备 ID，仅演示结构，不可导入真实网关。" % len(import_set["rules"]))
