# -*- coding: utf-8 -*-
"""根据设备台账生成「全屋设备体检」报告（Markdown），给客户看并决定下一步。只读。

用法：python home_report.py 设备台账.json [--out 体检报告.md]
内容：设备总数、按房间的设备清单、离线设备、命名问题、每个房间能做的模板和还缺的设备。
设备类型按 urn 里的类型判断，没有 urn 时按型号关键词猜；猜出来的类型标「?」，要和客户核对。
"""
import argparse
import json
import os
import sys
from collections import OrderedDict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from naming_check import check as naming_issues  # noqa: E402
from lighting import LAYERS, classify_layer, modes_for_area, plan_lights  # noqa: E402
from commissioning import analyze, wireless_plan  # noqa: E402

SCENES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scenes")

# urn 设备类型 → 类别
URN_TYPES = {
    "light": "灯", "switch": "开关", "outlet": "插座",
    "wireless-switch": "无线按键", "remote-control": "无线按键", "scene-panel": "无线按键",
    "occupancy-sensor": "人在传感器", "motion-sensor": "人体传感器",
    "magnet-sensor": "门窗传感器", "illumination-sensor": "光照传感器",
    "curtain": "窗帘", "window-opener": "窗帘", "air-conditioner": "空调", "thermostat": "空调",
    "speaker": "音箱", "lock": "门锁", "gateway": "网关", "hub": "网关",
    "temperature-humidity-sensor": "温湿度传感器",
}
# 没有 urn 时按型号关键词猜
MODEL_HINTS = [
    ("magnet", "门窗传感器"), ("occupancy", "人在传感器"), ("motion", "人体传感器"),
    ("light", "灯"), ("ceil", "灯"), ("bulb", "灯"), ("lamp", "灯"),
    ("switch", "开关"), ("plug", "插座"), ("curtain", "窗帘"), ("acpartner", "空调"),
    ("wifispeaker", "音箱"), ("lock", "门锁"), ("hub", "网关"), ("gateway", "网关"),
]

from device_playbook import EXTRA_URN_TYPES, EXTRA_MODEL_HINTS  # noqa: E402
URN_TYPES.update({k: v for k, v in EXTRA_URN_TYPES.items() if k not in URN_TYPES})
MODEL_HINTS += EXTRA_MODEL_HINTS


def category(d):
    parts = (d.get("urn") or "").split(":")
    if len(parts) > 3 and parts[3] in URN_TYPES:
        return URN_TYPES[parts[3]]
    model = (d.get("model") or "").lower()
    for word, cat in MODEL_HINTS:
        if word in model:
            return cat + "?"
    return "其他?"


def has(cats, *names):
    return any(c.rstrip("?") in names for c in cats)


def count(cats, names):
    return sum(1 for c in cats if c.rstrip("?") in names)


BATH_WORDS = ("卫", "浴", "洗手间", "厕")


def load_cards():
    """读 scenes/ 里每个模板的场景卡片（card 字段）。"""
    out = []
    try:
        with open(os.path.join(SCENES_DIR, "index.json"), encoding="utf-8") as f:
            idx = json.load(f)
    except (OSError, ValueError):
        return out
    for t in idx.get("templates", []):
        try:
            with open(os.path.join(SCENES_DIR, t["file"]), encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError, KeyError):
            continue
        if d.get("card"):
            out.append((t["id"], d["name"], d["card"]))
    return out


def match_card(card, room_cats, home_cats, bath_cats):
    """返回 (必需条件都满足, 缺的必需项, 缺的可选项)。"""
    miss, miss_opt = [], []
    for m in card.get("match", []):
        pool = {"本房间": room_cats, "全屋": home_cats, "卫生间": bath_cats}.get(m.get("where"), room_cats)
        if count(pool, m["cats"]) < m.get("count", 1):
            (miss_opt if m.get("optional") else miss).append(m["role"])
    return not miss, miss, miss_opt


def room_fits(card, room):
    words = card.get("roomWords") or []
    return not words or any(w in room for w in words)


def light_layers(items):
    """本房间的灯：调光灯（智能灯）列表、普通灯（开关的键）按层分好、看不出层的键。"""
    tunable, layers, unknown = [], OrderedDict((k, []) for k in LAYERS), []
    for d in items:
        cat = category(d).rstrip("?")
        if cat == "灯":
            tunable.append(d.get("name") or "未命名")
        elif cat == "开关":
            for ch in d.get("channels", []):
                lay = classify_layer(ch)
                (layers[lay] if lay else unknown).append(ch)
    return tunable, layers, unknown


def build_report(registry):
    devices = registry.get("devices", [])
    rooms = OrderedDict()
    for d in sorted(devices, key=lambda x: (x.get("room") or "~未分房间", x.get("name") or "")):
        rooms.setdefault(d.get("room") or "未分房间", []).append(d)
    offline = [d for d in devices if d.get("live", {}).get("online") is False]
    unconfirmed = [d for d in devices if d.get("status") != "confirmed"]
    issues = naming_issues(registry)
    all_cats = [category(d) for d in devices]

    lines = ["# 全屋设备体检", ""]
    lines.append("- 设备总数：%d 台，%d 个房间" % (len(devices), len(rooms)))
    lines.append("- 离线：%d 台" % len(offline) + ("（%s）" % "、".join(d.get("name") or d["did"] for d in offline) if offline else ""))
    lines.append("- 名称和房间未确认：%d 台" % len(unconfirmed))
    lines.append("- 命名问题：%d 条" % len(issues))
    lines += ["", "## 按房间", ""]
    for room, items in rooms.items():
        lines.append("**%s**（%d 台）：%s" % (room, len(items), "、".join(
            "%s[%s]" % (d.get("name") or "未命名", category(d)) for d in items)))
    if issues:
        lines += ["", "## 命名问题（建议先改）", ""]
        lines += ["- %s：%s" % (tag, msg) for tag, msg in issues]
    info = analyze(registry)
    plan = wireless_plan(info)
    lines += ["", "## 设备调试清单（先做完，再做场景）", ""]
    if plan:
        lines.append("| 开关·键 | 应设成 | 原因 |")
        lines.append("| --- | --- | --- |")
        lines += ["| %s | %s | %s |" % row for row in plan]
        lines.append("")
        lines.append("接着普通灯的那一路一律保持有线，包括双控的主开关：改成无线后继电器常通，灯就关不掉了。")
    else:
        lines.append("没有需要调整的开关键。")
    lines += ["", "## 区域模式预览", ""]
    by_area = OrderedDict()
    for lp in info["lamps"]:
        by_area.setdefault(lp["area"], []).append(lp)
    unknown_all = []
    for area, lps in by_area.items():
        modes = modes_for_area(area)
        if not modes:
            continue
        lights = [{"name": lp["name"], "role": lp["role"]} for lp in lps if lp["role"]]
        unknown_all += [lp["name"] for lp in lps if not lp["role"]]
        if not lights:
            continue
        parts, same = [], OrderedDict()
        for m in modes:
            if m in ("离开", "睡眠"):
                continue
            on, _off, _u = plan_lights(m, lights)
            names = tuple(x["name"] for x in on)
            same.setdefault(names, []).append(m)
            parts.append("%s：%s" % (m, "、".join(names) or "（全关，需要再加一盏灯带或落地灯）"))
        lines.append("- **%s**（%s）%s" % (area, "、".join(modes), "；".join(parts)))
        dup = [ms for ms in same.values() if len(ms) > 1]
        has_tunable = any(lp["tunable"] for lp in lps)
        for ms in dup:
            lines.append("  - %s 开的灯完全一样%s" % ("、".join(ms), "，只能靠调光灯的亮度色温区分" if has_tunable
                         else "，又没有调光灯，客户会觉得没区别：建议合并成一个，或建议加一路灯带/落地灯"))
    if unknown_all:
        lines.append("")
        lines.append("这些灯看不出作用，AI 结合整个房间判断后再做场景：%s" % "、".join(unknown_all))
    lines += ["", "## 场景卡片匹配", ""]
    cards = load_cards()
    bath_cats = [category(d) for r, items in rooms.items() if any(w in r for w in BATH_WORDS) for d in items]
    can, cannot = [], []
    for cid, cname, card in cards:
        if card.get("scope") == "none":      # 双控、同步这类在调试清单和区域模式里处理
            continue
        if card.get("scope") == "home":
            ok, miss, miss_opt = match_card(card, all_cats, all_cats, bath_cats)
            if card.get("askFirst") and "先问" not in cname:
                cname += "（可选，先问客户要不要）"
            (can if ok else cannot).append(("全屋", cname, miss, miss_opt))
            continue
        for room, items in rooms.items():
            if room == "未分房间" or not room_fits(card, room):
                continue
            rc = [category(d) for d in items]
            ok, miss, miss_opt = match_card(card, rc, all_cats, bath_cats)
            if not ok and not card.get("roomWords") and len(miss) == sum(1 for m in card.get("match", []) if not m.get("optional")):
                continue   # 任意房间的模板，房间里一样设备都没有就不列
            (can if ok else cannot).append((room, cname, miss, miss_opt))
    lines.append("**可以做：**")
    for room, cname, _m, miss_opt in can:
        lines.append("- %s · %s%s" % (room, cname, "（可选：再加 %s 更好）" % "、".join(miss_opt) if miss_opt else ""))
    if not can:
        lines.append("- 暂无")
    if cannot:
        lines += ["", "**还差设备：**"]
        for room, cname, miss, _o in cannot:
            lines.append("- %s · %s：还缺 %s" % (room, cname, "、".join(miss)))
    lines += ["", "开关的键要设成无线模式才能当场景键用；卫生间传感器用于起夜时，请确认和卧室是同一区域。",
              "每个场景的设备条件、效果和调试技术在 scenes/ 的场景卡片里。",
              "给客户挑场景用 scene_options.py：它按这份台账列出带编号的场景选项清单。"]
    lines += ["", "类型后带「?」的是按型号猜的，请核对。", "",
              "米家全屋智能 skills：https://zhijipro.cn/skills/"]
    return "\n".join(lines) + "\n", bool(issues)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # Windows 控制台默认 GBK
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="根据设备台账生成全屋设备体检报告")
    ap.add_argument("registry")
    ap.add_argument("--out")
    ap.add_argument("--lamps-out", help="另存灯具理解表（JSON，给 AI 生成场景用，不发给客户）")
    a = ap.parse_args()
    with open(a.registry, encoding="utf-8") as f:
        registry = json.load(f)
    text, _ = build_report(registry)
    if a.lamps_out:
        with open(a.lamps_out, "w", encoding="utf-8") as f:
            json.dump(analyze(registry), f, ensure_ascii=False, indent=2)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(text)
    sys.stdout.write(text)


if __name__ == "__main__":
    main()
