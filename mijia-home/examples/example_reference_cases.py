# -*- coding: utf-8 -*-
"""参考案例：全屋家庭模式 + 区域模式变量。占位设备，不能导入真实网关。
每条规则左上角自动带一张备注卡（用途、触发、效果、设备、生成日期、技能版本）。

  1. 双控：主卧床头副开关（无线）→ 切进门开关接吸顶灯的那一路（那一路保持有线）
  2. 客厅温馨：主灯关，轨道灯、灯带、落地灯开（调光灯 40%/3000K）
  3. 餐厅就餐：餐桌吊灯、筒灯、灯带开
  4. 客厅灯全关同步：人手动把客厅灯全关了 → 客厅模式 = 离开
  5. 全屋睡眠：主卧模式 = 睡眠，客厅、餐厅 = 离开，并关灯
  6. 起夜：主卧模式 = 睡眠 时按床头键，灯关着开到明亮、开着关；主卫无人关灯
  7. 回家：开门且离家 → 在家 → 开玄关筒灯
  8. 客厅灯光跟随：之后打开落地灯，按「客厅亮度」「客厅色温」变量亮
  9. 开关改无线（一次性）：床头副开关的键改无线
 10. 离家小爱提醒（可选，客户说要才做）：窗没关就提醒
运行：python example_reference_cases.py  → 产物：参考案例示例.json（写在当前文件夹）
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
from scene_templates import (build_dual_control_rule, build_area_mode_rule, build_area_off_sync_rule,
                             build_home_cascade_rule, build_night_wake_rule, build_arrive_home_rule,
                             build_light_follow_rule, build_switch_mode_rule, build_speaker_reminder_rule,
                             home_mode_var_definition, area_variables, check_mode_names, _power)
from commissioning import switch_mode_writes
from lighting import modes_for_area
from mijia_rule_kit import merge_import_set, check_import_set, dump_json

SW = "urn:miot-spec-v2:device:switch:0000A003:placeholder-sw:1"
LT = "urn:miot-spec-v2:device:light:0000A001:placeholder-light:1"
OCC = "urn:miot-spec-v2:device:occupancy-sensor:0000A0BF:placeholder-occ:1"
LOCK = "urn:miot-spec-v2:device:lock:0000A038:placeholder-lock:1"
SW2D = "urn:miot-spec-v2:device:switch:0000A003:tnv-sw2d01:1"           # 型号在 KNOWN_SWITCH_MODES 里
SPK = "urn:miot-spec-v2:device:speaker:0000A015:xiaomi-lx06:2"
MAG = "urn:miot-spec-v2:device:magnet-sensor:0000A016:placeholder-mag:1"
speaker = {"did": "PLACEHOLDER_SPK", "urn": SPK, "name": "客厅小爱",
           "play_text": {"siid": 5, "aiid": 1}, "directive": {"siid": 5, "aiid": 5}, "volume": {"siid": 2, "piid": 1}}

def key(did, siid, name):        # 无线键单击（eiid 以真实设备 spec 为准）
    return {"did": did, "urn": SW, "siid": siid, "eiid": 1, "name": name}

def smart(did, name):            # 调光调色灯（piid 以 spec 为准）
    return {"did": did, "urn": LT, "name": name, "power": {"siid": 2, "piid": 1},
            "brightness": {"siid": 2, "piid": 2}, "ct": {"siid": 2, "piid": 3}, "ct_range": [2700, 6500]}

def plain(did, siid, name):      # 智能开关接普通灯的一路（有线）
    return {"did": did, "urn": SW, "name": name, "power": {"siid": siid, "piid": 1}}

AREAS = {a: modes_for_area(a) for a in ("客厅", "餐厅", "主卧")}
problems = check_mode_names(AREAS)
assert not problems, problems

ceiling = plain("PLACEHOLDER_SW1", 2, "主卧吸顶灯")       # 进门开关第 1 路，真正接着灯
bed_pendant = plain("PLACEHOLDER_SW1", 4, "主卧床头吊灯")
living = [plain("PLACEHOLDER_SW4", 2, "客厅泛光灯"), plain("PLACEHOLDER_SW4", 3, "客厅筒灯"),
          plain("PLACEHOLDER_SW5", 2, "客厅磁吸轨道灯"), plain("PLACEHOLDER_SW5", 3, "客厅电视灯带"),
          plain("PLACEHOLDER_SW6", 2, "客厅沙发灯带"), smart("PLACEHOLDER_L1", "客厅落地灯")]
dining = [plain("PLACEHOLDER_SW7", 2, "餐厅吊灯"), plain("PLACEHOLDER_SW7", 3, "餐厅筒灯"),
          plain("PLACEHOLDER_SW8", 2, "餐厅天花灯带")]

base = 1700000000300
rules = [
    build_dual_control_rule(base + 1, [key("PLACEHOLDER_SW2", 5, "主卧床头左开关·第1键（无线）"),
                                       key("PLACEHOLDER_SW3", 5, "主卧床头右开关·第1键（无线）")], ceiling),
    build_area_mode_rule(base + 2, "客厅", "温馨", [key("PLACEHOLDER_K1", 4, "过道面板·客厅温馨")], living),
    build_area_mode_rule(base + 3, "餐厅", "就餐", [key("PLACEHOLDER_K1", 5, "过道面板·餐厅就餐")], dining),
    build_area_off_sync_rule(base + 4, "客厅", living),
    build_home_cascade_rule(base + 5, "全屋睡眠", {"主卧": "睡眠", "客厅": "离开", "餐厅": "离开"},
                            [_power(lt, False) for lt in living + dining]),
    build_night_wake_rule(base + 6, area="主卧",
        bedside_keys=[key("PLACEHOLDER_SW2", 6, "主卧床头左开关·第2键（无线）"),
                      key("PLACEHOLDER_SW3", 6, "主卧床头右开关·第2键（无线）")],
        lights=[ceiling, bed_pendant],
        bathroom_sensors=[{"did": "PLACEHOLDER_S1", "urn": OCC, "siid": 2, "piid": 1, "no_one": [0], "name": "主卫人在传感器"}]),
    build_arrive_home_rule(base + 7,
        {"did": "PLACEHOLDER_LOCK", "urn": LOCK, "siid": 3, "eiid": 1020, "name": "入户门锁"},
        [dict(_power(plain("PLACEHOLDER_SW9", 2, "玄关筒灯"), True), name="玄关筒灯")]),
    build_light_follow_rule(base + 8, living, area="客厅"),
    build_switch_mode_rule(base + 9, switch_mode_writes("PLACEHOLDER_SW2", SW2D, 1, name="主卧床头左开关·第1键")
                                     + switch_mode_writes("PLACEHOLDER_SW3", SW2D, 1, name="主卧床头右开关·第1键")),
    build_speaker_reminder_rule(base + 10, "离家", speaker, volume=50, checks=[
        {"did": "PLACEHOLDER_MAG", "urn": MAG, "siid": 2, "piid": 1, "dtype": "boolean", "operator": "=", "v1": True,
         "name": "客厅窗户传感器", "say": "客厅的窗户还开着，记得关一下"}]),
]

variables = dict([home_mode_var_definition()] + [v for a in AREAS for v in area_variables(a)])
draft = merge_import_set(rules, variables, add_watermark=False)
problems = check_import_set(draft)
out = os.path.join(os.getcwd(), "参考案例示例.json")
dump_json(draft, out)
for r in rules:
    note = next(n for n in r["nodes"] if n["type"] == "nop")
    print("== %s：%d 张卡片，启用=%s" % (r["cfg"]["userData"]["name"], len(r["nodes"]), r["cfg"]["enable"]))
    print(note["cfg"]["contents"][0]["insert"])
print("变量：%s" % "、".join("%s=%s" % (v["userData"]["name"], k) for k, v in variables.items()))
print("结构检查：%s" % (problems or "通过"))
print("草稿：%s（占位设备，仅演示结构）" % out)
