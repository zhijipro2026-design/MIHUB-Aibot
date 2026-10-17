# -*- coding: utf-8 -*-
"""2.0.8 的按键玩法、暂停感应、定时和保底。占位设备，不能导入真实网关。

  1. 客厅一键轮换：一个键轮流切 明亮 → 休闲 → 温馨 → 放松 → 休憩，另一个键全关
  2. 客厅上下键调光：上键更亮、下键更暗
  3. 遥控器分区控制：一个场景面板管客厅和餐厅
  4. 临时不让感应关灯（全屋）+ 过道人来灯亮（会看暂停状态）
  5. 定时开关：鱼缸灯 18:00 开、23:00 关
  6. 开着太久自动关：阳台灯 2 小时
  7. 传感器低电量提醒：低于 20% 记下设备名，小爱播报
  8. 离家顺带关空调、关电视（灯以外的设备，见 references/devices.md）
  9. 洗衣机洗好了，小爱提醒；漏水报警（只播报，不关阀门）
运行：python example_more_scenes.py  → 产物：更多场景示例.json（写在当前文件夹）
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
from scene_templates import (build_mode_cycle_rule, build_brightness_step_rule, build_zone_remote_rule,
                             build_motion_pause_rule, build_presence_light_rule, build_time_schedule_rule,
                             build_max_on_rule, build_low_battery_rule, home_mode_var_definition, area_variables,
                             motion_pause_var_definition, low_battery_var_definition, _power,
                             build_home_cascade_rule, build_device_notify_rule, device_write)
from mijia_rule_kit import merge_import_set, check_import_set, dump_json

SW = "urn:miot-spec-v2:device:switch:0000A003:placeholder-sw:1"
LT = "urn:miot-spec-v2:device:light:0000A001:placeholder-light:1"
OCC = "urn:miot-spec-v2:device:occupancy-sensor:0000A0BF:placeholder-occ:1"
PLUG = "urn:miot-spec-v2:device:outlet:0000A002:placeholder-plug:1"
MAG = "urn:miot-spec-v2:device:magnet-sensor:0000A016:placeholder-mag:1"
SPK = "urn:miot-spec-v2:device:speaker:0000A015:xiaomi-lx06:2"

def key(did, siid, name):
    return {"did": did, "urn": SW, "siid": siid, "eiid": 1, "name": name}

def plain(did, siid, name):
    return {"did": did, "urn": SW, "name": name, "power": {"siid": siid, "piid": 1}}

smart = {"did": "PLACEHOLDER_L1", "urn": LT, "name": "客厅落地灯", "power": {"siid": 2, "piid": 1},
         "brightness": {"siid": 2, "piid": 2}, "ct": {"siid": 2, "piid": 3}}
living = [plain("PLACEHOLDER_SW4", 2, "客厅泛光灯"), plain("PLACEHOLDER_SW4", 3, "客厅筒灯"),
          plain("PLACEHOLDER_SW5", 2, "客厅磁吸轨道灯"), plain("PLACEHOLDER_SW5", 3, "客厅电视灯带"), smart]
dining = [plain("PLACEHOLDER_SW7", 2, "餐厅吊灯"), plain("PLACEHOLDER_SW8", 2, "餐厅天花灯带")]
hall = plain("PLACEHOLDER_SW9", 2, "过道筒灯")
speaker = {"did": "PLACEHOLDER_SPK", "urn": SPK, "name": "客厅小爱", "play_text": {"siid": 5, "aiid": 1}}
AC = {"did": "PLACEHOLDER_AC", "urn": "urn:miot-spec-v2:device:air-conditioner:0000A004:placeholder-ac:1", "name": "客厅空调"}
TV = {"did": "PLACEHOLDER_TV", "urn": "urn:miot-spec-v2:device:television:0000A010:placeholder-tv:1", "name": "客厅电视"}
WASHER = "urn:miot-spec-v2:device:washer:0000A029:placeholder-washer:1"
LEAK = "urn:miot-spec-v2:device:submersion-sensor:0000A0xx:placeholder-leak:1"

base = 1700000000400
rules = [
    build_mode_cycle_rule(base + 1, "客厅", [key("PLACEHOLDER_K1", 4, "沙发旁按键·轮换")], living,
                          off_keys=[key("PLACEHOLDER_K1", 5, "沙发旁按键·全关")]),
    build_brightness_step_rule(base + 2, "客厅", [key("PLACEHOLDER_K2", 4, "茶几遥控·上")],
                               [key("PLACEHOLDER_K2", 5, "茶几遥控·下")], living),
    build_zone_remote_rule(base + 3, [
        {"area": "客厅", "on_key": key("PLACEHOLDER_P1", 13, "面板·客厅开"), "off_key": key("PLACEHOLDER_P1", 14, "面板·客厅关"), "lights": living},
        {"area": "餐厅", "mode": "就餐", "on_key": key("PLACEHOLDER_P1", 15, "面板·餐厅开"),
         "off_key": key("PLACEHOLDER_P1", 16, "面板·餐厅关"), "lights": dining}]),
    build_motion_pause_rule(base + 4, [key("PLACEHOLDER_K3", 4, "过道开关·双击暂停")], resume_when_off=[hall]),
    build_presence_light_rule(base + 5, "过道人来灯亮",
                              [{"did": "PLACEHOLDER_S1", "urn": OCC, "siid": 2, "piid": 1, "someone": [1, 2, 3, 4, 5],
                                "no_one": [0], "name": "过道人在传感器"}], [hall], pause=True),
    build_time_schedule_rule(base + 6, (18, 0, 0), (23, 0, 0),
                             [{"did": "PLACEHOLDER_PLUG", "urn": PLUG, "siid": 2, "piid": 1, "value": True, "name": "鱼缸灯插座"}],
                             [{"did": "PLACEHOLDER_PLUG", "urn": PLUG, "siid": 2, "piid": 1, "value": False, "name": "鱼缸灯插座"}],
                             name="鱼缸灯定时"),
    build_max_on_rule(base + 7, [plain("PLACEHOLDER_SW10", 2, "阳台灯")], minutes=120, name="阳台灯-开着太久自动关"),
    build_low_battery_rule(base + 8, [{"did": "PLACEHOLDER_MAG", "urn": MAG, "siid": 3, "piid": 1, "name": "入户门窗传感器"}],
                           speaker=speaker),
    build_home_cascade_rule(base + 9, "离家", {"客厅": "离开", "餐厅": "离开"},
                            [_power(lt, False) for lt in living + dining]
                            + [device_write(AC, 2, 1, False, "客厅空调·关"), device_write(TV, 2, 1, False, "客厅电视·关")]),
    build_device_notify_rule(base + 10, {"did": "PLACEHOLDER_WASHER", "urn": WASHER, "siid": 2, "piid": 1, "dtype": "int",
                                         "operator": "=", "v1": 5, "name": "洗衣机（运行状态=完成）"},
                             speaker, "洗衣机洗好了，记得晾衣服", name="洗衣机洗好提醒"),
    build_device_notify_rule(base + 11, {"did": "PLACEHOLDER_LEAK", "urn": LEAK, "siid": 2, "piid": 1, "dtype": "boolean",
                                         "operator": "=", "v1": True, "name": "厨房水浸传感器"},
                             speaker, "厨房检测到漏水，请马上去看看", volume=90, name="漏水报警"),
]
variables = dict([home_mode_var_definition(), motion_pause_var_definition(), low_battery_var_definition()]
                 + [v for a in ("客厅", "餐厅") for v in area_variables(a)])
draft = merge_import_set(rules, variables, add_watermark=False)
problems = check_import_set(draft)
out = os.path.join(os.getcwd(), "更多场景示例.json")
dump_json(draft, out)
for r in rules:
    print("== %s：%d 张卡片，启用=%s" % (r["cfg"]["userData"]["name"], len(r["nodes"]), r["cfg"]["enable"]))
print("结构检查：%s" % (problems or "通过"))
print("草稿：%s（占位设备，仅演示结构）" % out)
