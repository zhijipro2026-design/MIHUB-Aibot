# -*- coding: utf-8 -*-
"""家庭状态模板示例：占位设备，生成 4 条停用规则 + 家庭模式变量的 JSON 草稿。
占位 did 不可导入真实网关。真实使用时，设备一律从 设备台账.json 的 confirmed 条目解析。
运行：python example_home_modes.py  → 产物：家庭状态示例.json
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
from scene_templates import (build_mode_switch_rule, build_mode_scene_rule, build_night_wake_rule,
                             build_sunset_schedule_rule, home_mode_var_definition)
from mijia_rule_kit import merge_import_set, dump_json

SW = "urn:miot-spec-v2:device:switch:0000A003:placeholder-sw:1"
LT = "urn:miot-spec-v2:device:light:0000A001:placeholder-light:1"
OCC = "urn:miot-spec-v2:device:occupancy-sensor:0000A0BF:placeholder-occ:1"

def key(did, siid):            # 无线按键单击事件（eiid 以真实设备 spec 为准）
    return {"did": did, "urn": SW, "siid": siid, "eiid": 1}

def light(did):
    return {"did": did, "urn": LT, "power": {"siid": 2, "piid": 1},
            "on_writes": [{"did": did, "urn": LT, "siid": 2, "piid": 2, "value": 100}]}   # 亮度 100%

bed_lamp, path_light = light("PLACEHOLDER_L1"), light("PLACEHOLDER_L2")
bath_sensor = {"did": "PLACEHOLDER_S1", "urn": OCC, "siid": 2, "piid": 1, "no_one": [0]}

rules = [
    build_mode_switch_rule("1700000000101", [
        {"key": key("PLACEHOLDER_K1", 4), "mode": "全屋睡眠"},
        {"key": key("PLACEHOLDER_K1", 5), "mode": "起床"},
    ]),
    build_mode_scene_rule("1700000000102", "全屋睡眠", [
        {"did": "PLACEHOLDER_L3", "urn": LT, "siid": 2, "piid": 1, "value": False},   # 关客厅主灯
    ]),
    build_night_wake_rule("1700000000103", area="主卧",
        bedside_keys=[key("PLACEHOLDER_K2", 4), key("PLACEHOLDER_K3", 4)],
        lights=[bed_lamp, path_light], bathroom_sensors=[bath_sensor]),
    build_sunset_schedule_rule("1700000000104", 31.23, 121.47, [path_light],
        off_hms=(23, 0, 0), offset_min=-30, days=("mon", "tue", "wed", "thu", "fri")),
]
var_id, var_def = home_mode_var_definition()
from scene_templates import area_var_definition
aid, adef = area_var_definition("主卧")
var_def_all = {var_id: var_def, aid: adef}
draft = merge_import_set(rules, var_def_all, add_watermark=False)
out = os.path.join(os.getcwd(), "家庭状态示例.json")   # 写到当前文件夹，不写进技能目录
dump_json(draft, out)
for r in rules:
    print("%s：%d 张卡片，启用=%s" % (r["cfg"]["userData"]["name"], len(r["nodes"]), r["cfg"]["enable"]))
print("草稿：%s（占位设备，仅演示结构）" % out)

# === 场景发变量 + 灯光跟随 ===
from scene_templates import build_scene_rule, build_light_follow_rule
smart = dict(light("PLACEHOLDER_L4"), brightness={"siid": 2, "piid": 2}, ct={"siid": 2, "piid": 3})
extra = [
    build_scene_rule("1700000000105", "场景-访客", [key("PLACEHOLDER_K4", 4)],
        mode="访客",
        writes=[{"did": "PLACEHOLDER_L3", "urn": LT, "siid": 2, "piid": 1, "value": False}]),
    build_light_follow_rule("1700000000106", [smart]),   # 省略 table = 按五种氛围的默认表
]
for r in extra:
    print("%s：%d 张卡片，启用=%s" % (r["cfg"]["userData"]["name"], len(r["nodes"]), r["cfg"]["enable"]))
dump_json(merge_import_set(rules + extra, var_def_all, add_watermark=False), out)

# === 区域自动化 ===
from scene_templates import build_presence_light_rule, build_arrive_home_rule, build_sunrise_curtain_rule
CUR = "urn:miot-spec-v2:device:curtain:0000A00C:placeholder-cur:1"
hall_s1 = {"did": "PLACEHOLDER_S2", "urn": OCC, "siid": 2, "piid": 1, "someone": [1], "no_one": [0]}
hall_s2 = {"did": "PLACEHOLDER_S3", "urn": OCC, "siid": 2, "piid": 1, "someone": [1], "no_one": [0]}
area = [
    build_presence_light_rule("1700000000107", "走廊-人来灯亮", [hall_s1, hall_s2], [path_light],
        lux={"did": "PLACEHOLDER_S2", "urn": OCC, "siid": 3, "piid": 1, "below": 80}),
    build_arrive_home_rule("1700000000108",
        {"did": "PLACEHOLDER_LOCK", "urn": "urn:miot-spec-v2:device:lock:0000A038:placeholder-lock:1", "siid": 3, "eiid": 1020},
        [{"did": "PLACEHOLDER_L5", "urn": LT, "siid": 2, "piid": 1, "value": True}]),
    build_sunrise_curtain_rule("1700000000109", 31.23, 121.47,
        [{"did": "PLACEHOLDER_C1", "urn": CUR, "siid": 2, "piid": 2, "value": 100}]),
]
for r in area:
    print("%s：%d 张卡片，启用=%s" % (r["cfg"]["userData"]["name"], len(r["nodes"]), r["cfg"]["enable"]))
dump_json(merge_import_set(rules + extra + area, var_def_all, add_watermark=False), out)
