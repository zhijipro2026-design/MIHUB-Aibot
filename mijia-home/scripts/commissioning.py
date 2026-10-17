# -*- coding: utf-8 -*-
"""设备调试分析（只读）：从设备台账里看懂每盏灯和每个键，给出调试清单。

  · 灯具清单：每盏灯（智能灯 + 开关上接普通灯的键）在哪个区域、什么角色、由哪个键控制
  · 双控：同一区域里、不同开关上同名的键 = 同一盏灯，只有一路真正接着灯
  · 场景键：键名是模式/场景名（休闲模式、离开客厅…）
  · 无线模式清单：哪些键该改成无线、哪些必须保持有线

区域按灯名开头判断（「餐厅天花灯带」在餐厅），不按开关装在哪个房间。
"""
import os
import sys
from collections import OrderedDict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lighting import classify_role, is_sensor_owned  # noqa: E402

SCENE_WORDS = ("模式", "场景", "离开", "离家", "回家", "就餐", "观影", "小聚", "明亮", "休闲", "温馨", "放松",
               "休憩", "睡眠", "起床", "全开", "全关", "总开", "总关")
LAMP_WORDS = ("灯",)
WIRELESS_WORDS = ("无线",)


def urn_type(d):
    return ((d.get("urn") or "").split(":") + [""] * 4)[3]


def is_switch(d):
    t = urn_type(d)
    return t == "switch" or (not t and "switch" in (d.get("model") or ""))


def is_light(d):
    return urn_type(d) == "light"


def key_kind(name):
    """键的用途：scene（场景键）/ lamp（接灯）/ wireless（写明了无线）/ unknown。"""
    n = name or ""
    if any(w in n for w in WIRELESS_WORDS):
        return "wireless"
    if any(w in n for w in LAMP_WORDS) and not n.endswith("模式"):
        return "lamp"
    if any(w in n for w in SCENE_WORDS):
        return "scene"
    return "unknown"


def area_of(name, room, rooms):
    """灯名里出现了别的房间名，就算那个房间；否则用设备所在房间。最长匹配优先。"""
    n = name or ""
    for r in sorted(rooms, key=len, reverse=True):
        if r and r in n:
            return r
    return room or "未分房间"


def analyze(registry):
    devices = registry.get("devices", [])
    rooms = sorted({d.get("room") for d in devices if d.get("room")})
    smart_names = {(d.get("room"), d.get("name")) for d in devices if is_light(d)}
    lamps = OrderedDict()      # (区域, 灯名) → {...}
    scene_keys, unknown_keys = [], []
    for d in devices:
        room = d.get("room") or "未分房间"
        if is_light(d):
            area = area_of(d.get("name"), room, rooms)
            role, why = classify_role(d.get("name"))
            lamps.setdefault((area, d.get("name")), {"area": area, "name": d.get("name"), "role": role, "why": why,
                                                     "tunable": True, "did": d.get("did"), "keys": []})
        if not is_switch(d):
            continue
        for i, ch in enumerate(d.get("channels", [])):
            kind = key_kind(ch)
            ref = {"switch": d.get("name") or d.get("did"), "did": d.get("did"), "index": i + 1, "key": ch, "room": room}
            if kind == "scene":
                scene_keys.append(ref)
            elif kind == "lamp":
                area = area_of(ch, room, rooms)
                k = (area, ch)
                if k not in lamps:
                    role, why = classify_role(ch)
                    lamps[k] = {"area": area, "name": ch, "role": role, "why": why,
                                "tunable": (room, ch) in smart_names or (area, ch) in smart_names,
                                "did": None, "keys": []}
                lamps[k]["keys"].append(ref)
            elif kind == "unknown":
                unknown_keys.append(ref)
    for lp in lamps.values():
        lp["sensor"] = is_sensor_owned(lp["name"])
        lp["dual"] = len(lp["keys"]) > 1
    return {"lamps": list(lamps.values()), "scene_keys": scene_keys, "unknown_keys": unknown_keys}


def wireless_plan(info):
    """调试清单：[(开关·键, 应设成, 原因)]。"""
    plan = []
    for lp in info["lamps"]:
        keys = lp["keys"]
        if not keys:
            continue
        label = lambda k: "%s·第%d键「%s」" % (k["switch"], k["index"], k["key"])
        if lp["tunable"]:
            for k in keys:
                plan.append((label(k), "无线 + 来电上电", "控制的是智能灯：继电器常通，灯一直有电，按键只发事件"))
        elif lp["dual"]:
            plan.append(("、".join(label(k) for k in keys), "先确认哪一路接着灯",
                         "这几个键同名，是双控。接着「%s」的那一路保持有线（改无线灯会关不掉），其余改无线，"
                         "由双控规则切主开关的继电器。请客户单独关掉每一路，看灯灭不灭" % lp["name"]))
        else:
            plan.append((label(keys[0]), "保持有线", "接着普通灯「%s」" % lp["name"]))
    for k in info["scene_keys"]:
        plan.append(("%s·第%d键「%s」" % (k["switch"], k["index"], k["key"]), "无线", "场景键，只发事件，不通断任何灯"))
    for k in info["unknown_keys"]:
        plan.append(("%s·第%d键「%s」" % (k["switch"], k["index"], k["key"]), "问客户",
                     "看不出接的是什么：接普通灯就改成灯名，场景键就改成场景名"))
    return plan


# ---------- 改无线：已知型号的属性 ----------
# 来自 home.miot-spec.com 的 spec，并在真机备份的规则里见过（规则加载时写 mode=1）。
# 每个键：siid、工作模式属性 mode（1 = 无线开关）、通电后状态属性 power_on（1 = 上电）。
# 不在表里的型号，按 references/commissioning.md 第 3 步去查 spec，查到后记进 进度.md。
KNOWN_SWITCH_MODES = {
    "tnv-sw2d01": {
        "spec": "tnv.switch.sw2d01",
        "keys": {1: {"siid": 2, "mode": 6, "power_on": 5}, 2: {"siid": 3, "mode": 4, "power_on": 3}},
        "wireless": 1, "wired": 0, "power_on_value": 1,
        "note": "mode 用扩展工作模式（0 有线和无线、1 无线开关…）；另有一个基础 mode（左 piid2/右 piid2，1=无线），二选一，以读回为准",
    },
}


def model_of(urn):
    """urn 第 6 段是型号，例如 tnv-sw2d01；查 spec 时把 - 换成 . 并补品类：tnv.switch.sw2d01。"""
    parts = (urn or "").split(":")
    return parts[5] if len(parts) > 5 else ""


def switch_mode_writes(did, urn, key_index, wireless=True, power_on=False, name=None):
    """一个键改无线（可选再设通电后上电）要写的属性列表；型号不在 KNOWN_SWITCH_MODES 里返回 None。
    power_on=True 只给接着智能灯的那一路用：继电器常通，灯一直有电。"""
    m = KNOWN_SWITCH_MODES.get(model_of(urn))
    if not m or key_index not in m["keys"]:
        return None
    k = m["keys"][key_index]
    w = [{"did": did, "urn": urn, "siid": k["siid"], "piid": k["mode"],
          "value": m["wireless"] if wireless else m["wired"], "name": (name or "第%d键" % key_index) + "·工作模式"}]
    if power_on:
        w.append({"did": did, "urn": urn, "siid": k["siid"], "piid": k["power_on"], "value": m["power_on_value"],
                  "name": (name or "第%d键" % key_index) + "·通电后上电"})
    return w
