# -*- coding: utf-8 -*-
"""场景选项清单（只读）：按客户家里已有的设备，列出能做的场景，给客户挑。

用法：python scene_options.py 设备台账.json [--out 场景选项.md] [--json 场景选项.json]

  · 客户看 Markdown：编号、场景、效果、用到你家的哪些设备、现在能不能做。
  · AI 读 JSON：每个选项用哪个模板函数、传什么参数。客户回复编号后，只做客户选的。
  · 「基础」是每家都要的配套（家庭模式、灯全关同步、双控），客户选了任何区域场景就自动带上，不单独问。
  · 「先问」的选项（小爱提醒）只问一次要不要，客户说要才做，不主动加。
同样的台账永远得到同样的清单，所以不同的 AI 给客户看到的选项是一样的。
"""
import argparse
import json
import os
import sys
from collections import OrderedDict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lighting import modes_for_area, plan_lights, tunable_values, MODE_SAY, MODE_TUNABLE, BRIGHTNESS_ORDER  # noqa: E402
from commissioning import analyze  # noqa: E402
from home_report import category  # noqa: E402
from scene_templates import mode_full_name  # noqa: E402
from device_playbook import PLAYBOOK, SAFETY, NOT_IN_SCENES, REMINDERS, ALARMS  # noqa: E402

BEDROOM_WORDS = ("卧", "老人房", "儿童房", "客房")
BATH_WORDS = ("卫", "浴", "洗手间", "厕")
PASS_WORDS = ("过道", "走廊", "玄关", "楼梯", "衣帽间", "卫", "浴", "洗手间", "厕")
RECOMMENDED_MODES = ("温馨", "观影", "就餐", "睡眠")


def _cats(devices):
    by = OrderedDict()
    for d in devices:
        by.setdefault(category(d).rstrip("?"), []).append(d)
    return by


def _names(ds):
    return [d.get("name") or d.get("did") for d in ds]


def build_options(registry):
    devices = registry.get("devices", [])
    info = analyze(registry)
    cats = _cats(devices)
    keys_ready = bool(info["scene_keys"]) or bool(cats.get("无线按键"))
    key_hint = "需要一个场景键：开关上空着的键改成无线，或用无线按键、场景面板"
    opts = []

    def add(group, name, say, uses, builder, params, status="可以做", missing=(), recommended=False,
            ask_first=False, base=False):
        opts.append({"group": group, "name": name, "say": say, "uses": list(uses), "builder": builder,
                     "params": params, "status": status, "missing": list(missing), "recommended": recommended,
                     "ask_first": ask_first, "base": base})

    # ---- 基础配套 ----
    add("基础", "家庭模式（在家/离家/全屋睡眠/起床/访客）", "网关记住现在家里是什么状态，别的场景按它判断",
        [], "home_mode_var_definition / build_mode_switch_rule", {}, base=True)
    if any(lp["dual"] for lp in info["lamps"]):
        dual = [lp["name"] for lp in info["lamps"] if lp["dual"]]
        add("基础", "双控", "不同开关上同名的键控制同一盏灯：%s" % "、".join(dual), dual,
            "build_dual_control_rule", {}, status="先调试", missing=["先确认哪一路接着灯"], base=True)

    # ---- 区域模式 ----
    by_area = OrderedDict()
    for lp in info["lamps"]:
        by_area.setdefault(lp["area"], []).append(lp)
    for area, lps in by_area.items():
        modes = modes_for_area(area)
        lights = [{"name": lp["name"], "role": lp["role"]} for lp in lps if lp["role"] and not lp["sensor"]]
        if not modes or not lights:
            continue
        has_tunable = any(lp["tunable"] for lp in lps)
        seen, distinct = {}, []
        for m in modes:
            on, off, _u = plan_lights(m, lights)
            on_names = tuple(x["name"] for x in on)
            if m not in ("睡眠", "离开"):
                if not on_names:
                    continue                                  # 这个区域做不出这个模式（会全黑）
                if on_names in seen and not has_tunable:
                    continue                                  # 和前一个模式开的灯一样、又没调光灯：客户分不出来
                seen.setdefault(on_names, m)
                distinct.append(m)
            say = MODE_SAY.get(m, "")
            if has_tunable and m in MODE_TUNABLE:
                v = tunable_values(m, area)
                say += "（调光灯 %d%%、%dK）" % (v["brightness"], v["ct"])
            if on_names and m != "明亮":
                say += "。亮：%s" % "、".join(on_names)
            elif m == "明亮":
                say += "。灯全开"
            add(area, mode_full_name(area, m), say, [lp["name"] for lp in lps], "build_area_mode_rule",
                {"area": area, "mode": m}, status="可以做" if keys_ready else "先调试",
                missing=[] if keys_ready else [key_hint], recommended=m in RECOMMENDED_MODES)
        cycle = [m for m in distinct if m not in ("就餐", "观影")]
        if len(cycle) >= 2:
            add(area, "%s一键轮换" % area, "一个键每按一次换一个模式：%s" % " → ".join(cycle), [],
                "build_mode_cycle_rule", {"area": area}, status="可以做" if keys_ready else "先调试",
                missing=[] if keys_ready else ["需要 1 个空着的无线键"])
        step = [m for m in BRIGHTNESS_ORDER if m in distinct]
        if len(step) >= 2:
            add(area, "%s上下键调光" % area, "上键一档一档变亮、下键一档一档变暗（%s）" % " → ".join(step), [],
                "build_brightness_step_rule", {"area": area}, status="可以做" if keys_ready else "先调试",
                missing=[] if keys_ready else ["需要 2 个空着的无线键"])
        if has_tunable:
            add(area, "%s灯光跟随" % area, "之后随手打开的调光灯，自动按这个区域当前模式的亮度色温亮",
                [lp["name"] for lp in lps if lp["tunable"]], "build_light_follow_rule",
                {"area": area}, recommended=True)
        add(area, "%s灯全关同步" % area, "这个区域的灯被人全关了，网关记成「离开」", [], "build_area_off_sync_rule",
            {"area": area}, base=True)
        if any(w in area for w in BEDROOM_WORDS):
            baths = [d for d in devices if any(w in (d.get("room") or "") for w in BATH_WORDS)
                     and category(d).rstrip("?") in ("人在传感器", "人体传感器")]
            add(area, "%s起夜" % area, "睡眠模式下按床头键开灯，再按一下关；%s" %
                ("卫生间没人了自动关" if baths else "没有卫生间传感器，就靠再按一下关"),
                _names(baths), "build_night_wake_rule", {"area": area},
                status="可以做" if keys_ready else "先调试", missing=[] if keys_ready else ["床头键改成无线"],
                recommended=True)

    # ---- 按房间的感应 ----
    sensors = cats.get("人在传感器", []) + cats.get("人体传感器", [])
    for room in OrderedDict((d.get("room"), 1) for d in sensors if d.get("room")):
        if any(w in room for w in PASS_WORDS):
            ss = [d for d in sensors if d.get("room") == room]
            lamps = [lp["name"] for lp in info["lamps"] if lp["area"] == room or any(
                k["room"] == room for k in lp["keys"])]
            add(room, "%s人来灯亮" % room, "有人灯亮，没人一会儿自动关；睡眠时只开最暗的灯", _names(ss) + lamps,
                "build_presence_light_rule", {"room": room}, status="可以做" if lamps else "还差设备",
                missing=[] if lamps else ["这个房间的灯还没接进米家（智能灯，或开关上接灯的键）"], recommended=True)

    # ---- 按房间的保底 ----
    MAX_ON_WORDS = ("阳台", "储物", "庭院", "花园", "车库", "地下室", "杂物")
    for room in OrderedDict((d.get("room"), 1) for d in devices if d.get("room")):
        if any(w in room for w in MAX_ON_WORDS):
            ds = [d for d in devices if d.get("room") == room and category(d).rstrip("?") in ("灯", "开关", "插座")]
            if ds:
                add(room, "%s开着太久自动关" % room, "这里的灯或插座忘了关，开了 2 小时自动关", _names(ds),
                    "build_max_on_rule", {"room": room, "minutes": 120})

    # ---- 全屋 ----
    add("全屋", "离家", "一键离家：所有区域记成离开，灯全关%s" % ("、窗帘关上" if cats.get("窗帘") else ""),
        [], "build_home_cascade_rule", {"home_mode": "离家"}, status="可以做" if keys_ready else "先调试",
        missing=[] if keys_ready else [key_hint], recommended=True)
    add("全屋", "全屋睡眠", "一键睡觉：卧室进睡眠，其他区域灯全关，过道留最暗的夜灯", [],
        "build_home_cascade_rule", {"home_mode": "全屋睡眠"}, status="可以做" if keys_ready else "先调试",
        missing=[] if keys_ready else [key_hint], recommended=True)
    locks = cats.get("门锁", []) + [d for d in cats.get("门窗传感器", []) if any(
        w in (d.get("room") or "") + (d.get("name") or "") for w in ("玄关", "入户", "门厅", "大门"))]
    add("全屋", "回家", "离家状态下开门，家里自动切回在家，玄关和客厅亮暖光", _names(locks),
        "build_arrive_home_rule", {}, status="可以做" if locks else "还差设备",
        missing=[] if locks else ["智能门锁或入户门窗传感器"])
    add("全屋", "日落自动开灯", "太阳下山前半小时开客厅的氛围灯，到点自动关", [],
        "build_sunset_schedule_rule", {})
    curtains = cats.get("窗帘", [])
    add("全屋", "起床开窗帘", "工作日日出时窗帘自动打开，睡眠和离家时不开", _names(curtains),
        "build_sunrise_curtain_rule", {}, status="可以做" if curtains else "还差设备",
        missing=[] if curtains else ["电动窗帘"])
    if sensors:
        add("全屋", "临时不让感应关灯", "想让灯一直亮时按一下，人走了灯也不灭；关灯、离家或睡觉后自动恢复", [],
            "build_motion_pause_rule", {}, status="可以做" if keys_ready else "先调试",
            missing=[] if keys_ready else ["需要 1 个空着的无线键"])
    add("全屋", "开关分开的两个键", "床头或门口一个键只管开、一个键只管关，关时可以顺手关窗帘", [],
        "build_on_off_keys_rule", {}, status="可以做" if keys_ready else "先调试",
        missing=[] if keys_ready else ["需要 2 个空着的无线键"])
    panels = cats.get("无线按键", [])
    if panels and len(by_area) >= 2:
        add("全屋", "遥控器分区控制", "一个遥控器或场景面板管几个区域，每个区域一个开键、一个关键", _names(panels),
            "build_zone_remote_rule", {})
    plugs = cats.get("插座", [])
    add("全屋", "定时开关", "每天几点开、几点关，可以只选工作日或周末（鱼缸灯、门头灯、灯串）", _names(plugs),
        "build_time_schedule_rule", {})
    batt = [d for c in ("门窗传感器", "人体传感器", "人在传感器", "无线按键", "温湿度传感器") for d in cats.get(c, [])]
    speakers = cats.get("音箱", [])
    if batt:
        add("全屋", "传感器低电量提醒", "哪个传感器快没电了提前告诉你换电池，免得自动化突然不灵%s" %
            ("（小爱播报）" if speakers else "（AI 下次读设备时告诉你）"), _names(batt), "build_low_battery_rule", {})
    if speakers:
        add("全屋", "离家/睡觉前小爱提醒", "离家或睡觉时，小爱提醒窗没关、空调还开着这类事", _names(speakers),
            "build_speaker_reminder_rule", {}, ask_first=True)

    # ---- 灯以外的设备：挂在场景下面的顺带动作 ----
    by_cat = OrderedDict()
    for d in devices:
        by_cat.setdefault(category(d).rstrip("?"), []).append(d)

    def extras(scene, area=None):
        out = []
        key = "离开<区域>" if scene == "离开" else scene
        for cat, items in PLAYBOOK.items():
            ds = by_cat.get(cat, [])
            if area:
                ds = [d for d in ds if area in (d.get("room") or "") or area in (d.get("name") or "")]
            if scene == "观影":
                ds = [d for d in ds if "客厅" in (d.get("room") or "") + (d.get("name") or "")]
            for sc, say, default, how in items:
                if sc == key and ds:
                    out.append({"say": say.format(area=area or ""), "devices": _names(ds), "default": default, "how": how, "category": cat})
        return out

    for o in opts:
        if o["builder"] == "build_home_cascade_rule":
            o["extras"] = extras(o["params"]["home_mode"])
        elif o["builder"] == "build_arrive_home_rule":
            o["extras"] = extras("回家")
        elif o["builder"] == "build_area_mode_rule" and o["params"]["mode"] in ("观影", "离开"):
            o["extras"] = extras(o["params"]["mode"], o["params"]["area"] if o["params"]["mode"] == "离开" else None)

    for cat, text in REMINDERS.items():
        if by_cat.get(cat):
            add("全屋", "%s提醒" % cat, text, _names(by_cat[cat]) + _names(speakers), "build_device_notify_rule",
                {"category": cat}, status="可以做" if speakers else "还差设备", missing=[] if speakers else ["小爱音箱"])
    for cat, text in ALARMS.items():
        if by_cat.get(cat):
            add("全屋", "%s报警" % cat.replace("传感器", ""), text + "；只报警，不自动关阀门", _names(by_cat[cat]) + _names(speakers),
                "build_device_notify_rule", {"category": cat, "volume": 90},
                status="可以做" if speakers else "还差设备", missing=[] if speakers else ["小爱音箱"], recommended=True)

    known = set(PLAYBOOK) | set(SAFETY) | set(NOT_IN_SCENES) | set(REMINDERS) | set(ALARMS)
    unknown = [d for d in devices if category(d).rstrip("?") not in known]
    safety = [d for d in devices if category(d).rstrip("?") in SAFETY and category(d).rstrip("?") not in ALARMS]
    opts.append({"group": "说明", "name": "_unknown", "devices": [
        {"name": d.get("name") or d.get("did"), "urn": d.get("urn"),
         "category": category(d).rstrip("?") if not category(d).startswith("其他")
         else (((d.get("urn") or "").split(":") + [""] * 4)[3] or "不认识的类型")} for d in unknown],
        "base": True, "ask_first": False, "info": True})
    opts.append({"group": "说明", "name": "_safety", "devices": [
        {"name": d.get("name") or d.get("did"), "category": category(d).rstrip("?")} for d in safety],
        "base": True, "ask_first": False, "info": True})

    n = 0
    for o in [x for x in opts if not x["base"] and not x["ask_first"]] + [x for x in opts if x["ask_first"]]:
        n += 1
        o["no"] = n
    return opts


def render(opts):
    lines = ["# 你家能做的场景", "",
             "下面是按你家已有的设备列出来的场景。回复编号就行，比如「1、3、5」；不确定的可以先选带 ⭐ 的。", ""]
    group = None
    for o in opts:
        if o["base"] or o["ask_first"] or o.get("info"):
            continue
        if o["group"] != group:
            group = o["group"]
            lines += ["", "**%s**" % group, "", "| 编号 | 场景 | 效果 | 现在 |", "| --- | --- | --- | --- |"]
        now = o["status"] if not o["missing"] else "%s：%s" % (o["status"], "；".join(o["missing"]))
        lines.append("| %d | %s%s | %s | %s |" % (o["no"], o["name"], " ⭐" if o["recommended"] else "", o["say"], now))
        for i, x in enumerate(o.get("extras") or [], 1):
            lines.append("| %d.%d | ↳ %s%s | 用到：%s | 可以一起做 |" % (o["no"], i, x["say"], " ⭐" if x["default"] else "",
                                                               "、".join(x["devices"])))
    ask = [o for o in opts if o["ask_first"]]
    if ask:
        lines += ["", "**可选（要的话告诉我）**", ""]
        lines += ["- %d. %s：%s" % (o["no"], o["name"], o["say"]) for o in ask]
    info = {o["name"]: o["devices"] for o in opts if o.get("info")}
    if info.get("_unknown"):
        lines += ["", "**这些设备我还不熟，会先查它的说明书再问你要不要放进场景：**", ""]
        lines.append("、".join("%s（%s）" % (d["name"], d["category"]) for d in info["_unknown"]))
    if info.get("_safety"):
        lines += ["", "**这些设备只看状态、不放进自动控制（安全起见）：**", ""]
        lines.append("、".join("%s（%s）" % (d["name"], d["category"]) for d in info["_safety"]))
    lines += ["", "带小数点的编号（比如 24.1）是挂在上面那个场景里的顺带动作，想要就一起回复。"]
    base = [o for o in opts if o["base"] and not o.get("info")]
    if base:
        lines += ["", "选了上面任何一个，下面这些会一起做好，不用单独选：", ""]
        lines += ["- %s：%s" % (o["name"], o["say"]) for o in base]
    lines += ["", "米家全屋智能 skills：https://zhijipro.cn/skills/"]
    return "\n".join(lines) + "\n"


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="按已有设备列出可选场景")
    ap.add_argument("registry")
    ap.add_argument("--out")
    ap.add_argument("--json", help="另存给 AI 用的选项（模板函数和参数）")
    a = ap.parse_args()
    with open(a.registry, encoding="utf-8") as f:
        registry = json.load(f)
    opts = build_options(registry)
    text = render(opts)
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(opts, f, ensure_ascii=False, indent=2)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(text)
    sys.stdout.write(text)


if __name__ == "__main__":
    main()
