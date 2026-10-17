# -*- coding: utf-8 -*-
"""米家极客版「家庭状态 + 场景 + 区域自动化」模板生成函数。

每个函数输入：从设备台账解析出的真实设备（did/urn）+ 模板参数；输出：一条停用的规则 dict。
函数内部只用 mijia_rule_kit 的 RuleBuilder，不臆造节点形状。

设备参数约定（全部来自 status=confirmed 的台账条目 + MIoT spec 核对）：
  key    = {"did","urn","siid","eiid", "arguments"?}            按键事件（单击/双击等）
  write  = {"did","urn","siid","piid","value"}                    属性写入
         | {"did","urn","siid","aiid","ins":[...]}                 动作调用
  light  = {"did","urn","power":{"siid","piid"}, "on_writes":[write...]}
           power 为开关属性（布尔）；on_writes 为「明亮/场景」时要写的属性（亮度、色温等），可为空
  sensor = {"did","urn","siid","piid","no_one":[0]}               人在/人体传感器「无人」枚举值
  每个设备 dict 都可以带 "name"（台账里的设备名/键名），备注卡的「设备」一行就用它。

备注卡：每个模板函数都有 note 参数，默认 None = 按 scenes/<模板>.json 的 card 自动生成一张画布备注卡
（放在左上角：用途、触发、效果、设备、生成日期、技能版本、网址）；传字符串用自己的文字；传 False 不加。
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mijia_rule_kit import RuleBuilder, _WATERMARK_DEFAULTS  # noqa: E402
from lighting import (tunable_values, plain_plan, plan_lights, light_follow_table,  # noqa: E402
                      area_follow_table, modes_for_area, MODE_ROLES, MODE_TUNABLE)
import hashlib  # noqa: E402
from lighting import BRIGHTNESS_ORDER  # noqa: E402

SKILL_VERSION = _WATERMARK_DEFAULTS["version"]
SCENES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scenes")
NOTE_BG = "#FFE58F"   # 备注卡底色（浅黄，和品牌卡的蓝色区分）

HOME_MODE_VAR = "VhomeMode01"           # 家庭模式全局变量（11 位纯字母数字）
# 全屋家庭模式只放跨区域的状态；区域里的明亮/温馨/睡眠/观影/就餐等放在各区域自己的变量里。
# 全屋用「全屋睡眠」，不和卧室的「睡眠」同名。
HOME_MODES = ["在家", "离家", "全屋睡眠", "起床", "访客"]
WEEKDAY = {"mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6, "sun": 0}


# ---------- 小工具 ----------
def _write(rb, w):
    if "aiid" in w:
        return rb.call_action(w["did"], w["urn"], w["siid"], w["aiid"], w.get("ins", []))
    return rb.write_device(w["did"], w["urn"], w["siid"], w["piid"], w["value"])


def _chain(rb, src, port, writes):
    """把一组写入串成链（与真机场景规则同形：上一卡 output → 下一卡 trigger）。返回最后一张卡。"""
    prev, prev_port = src, port
    for w in writes:
        n = _write(rb, w)
        rb.link(prev, prev_port, n, "trigger")
        prev, prev_port = n, "output"
    return prev


def _power(light, value):
    p = light["power"]
    return {"did": light["did"], "urn": light["urn"], "siid": p["siid"], "piid": p["piid"], "value": value}


def _is_on(rb, light):
    p = light["power"]
    return rb.cond_device(light["did"], light["urn"], p["siid"], p["piid"], "boolean", "=", True)


def _bright_writes(lights):
    out = []
    for lt in lights:
        out.append(_power(lt, True))
        out.extend(lt.get("on_writes", []))
    return out


def _off_writes(lights):
    return [_power(lt, False) for lt in lights]


def _keys_entry(rb, keys):
    """多个按键事件 → signalOr → 单一入口。只有一个键时直接返回该事件卡。"""
    evs = [rb.trigger_event(k["did"], k["urn"], k["siid"], k["eiid"], k.get("arguments")) for k in keys]
    if len(evs) == 1:
        return evs[0], "output"
    gate = rb.signal_or(len(evs))
    for i, e in enumerate(evs):
        rb.link(e, "output", gate, "input%d" % i)
    return gate, "output"


def _card(card_id):
    try:
        with open(os.path.join(SCENES_DIR, card_id + ".json"), encoding="utf-8") as f:
            return json.load(f).get("card", {})
    except (OSError, ValueError):
        return {}


def _names(*groups):
    """从若干设备 dict / 列表里取 name（去重保序），给备注卡的「设备」一行。"""
    out = []
    for g in groups:
        items = g if isinstance(g, (list, tuple)) else [g]
        for d in items:
            if isinstance(d, dict):
                n = d.get("name") or (d.get("key") or {}).get("name")
                if n and n not in out:
                    out.append(n)
    return out


def rule_note(title, trigger=None, effect=None, auto_off=None, devices=(), extra=(), date=None):
    """拼备注卡文字。title 如「【起夜】主卧」。"""
    lines = [title]
    if trigger:
        lines.append("触发：" + trigger)
    if effect:
        lines.append("效果：" + effect)
    if auto_off:
        lines.append("自动关：" + auto_off)
    if devices:
        lines.append("设备：" + "、".join(devices))
    lines.extend(extra)
    lines.append("生成：%s · mijia-home %s · zhijipro.cn/skills" % (date or time.strftime("%Y-%m-%d"), SKILL_VERSION))
    return "\n".join(lines)


def _auto_note(card_id, name, devices=(), effect=None, trigger=None):
    c = _card(card_id)
    return rule_note("【%s】" % name, trigger or c.get("trigger"), effect or c.get("effect"), c.get("autoOff"), devices)


def _finish(rb, rule_id, name, tags, note=None):
    """note：文字 = 在画布左上角放备注卡，其余卡片整体下移；None/False/空 = 不加。"""
    if note:
        nid = rb.text_note(note, x=60, y=20, width=420, background=NOTE_BG)
        h = next(n for n in rb.nodes if n["id"] == nid)["cfg"]["pos"]["height"]
        rb.auto_layout(y0=20 + h + 40)
    else:
        rb.auto_layout()
    return rb.build_rule(str(rule_id), name, tags, enable=False)


def _resolve_note(note, card_id, name, devices=(), effect=None, trigger=None):
    if note is False:
        return None
    if note is None:
        return _auto_note(card_id, name, devices, effect, trigger)
    return note


def mood_light_writes(light, mood, room=""):
    """调光调色灯在某氛围下要写的属性：开灯 → 亮度 → 色温（light 需带 brightness/ct 的 siid/piid，可只给其一；
    可带 "ct_range": [最低K, 最高K] 让色温夹在灯的范围内）。可直接当 light["on_writes"] 用。"""
    v = tunable_values(mood, room, light.get("ct_range"))
    out = [_power(light, True)]
    for prop in ("brightness", "ct"):
        if prop in light:
            out.append({"did": light["did"], "urn": light["urn"], "siid": light[prop]["siid"],
                        "piid": light[prop]["piid"], "value": v[prop]})
    return out


def area_var_id(area):
    """区域模式变量 ID：Varea + 区域名的 6 位哈希（共 11 位字母数字），同一个区域名永远得到同一个 ID。
    写入前先读网关已有变量，确认这个 ID 和显示名「<区域>模式」都没被别的变量占用。"""
    return "Varea" + hashlib.md5(area.encode("utf-8")).hexdigest()[:6]


def area_var_definition(area, initial="离开"):
    """区域模式变量定义：(id, {"type","value","userData":{"name":"<区域>模式"}})。"""
    return area_var_id(area), {"type": "string", "value": initial, "userData": {"name": "%s模式" % area}}


def area_level_var_ids(area):
    """区域的两个数字变量 ID：(亮度, 色温)。Vbri / Vcct + 区域名的 7 位哈希，共 11 位。"""
    h = hashlib.md5(area.encode("utf-8")).hexdigest()[:7]
    return "Vbri" + h, "Vcct" + h


def area_level_var_definitions(area, mode="休闲"):
    """区域亮度、色温两个数字变量的定义，初始值取 mode 的默认值。名字是「<区域>亮度」「<区域>色温」。"""
    v = tunable_values(mode, area)
    bid, cid = area_level_var_ids(area)
    return [(bid, {"type": "number", "value": v["brightness"], "userData": {"name": "%s亮度" % area}}),
            (cid, {"type": "number", "value": v["ct"], "userData": {"name": "%s色温" % area}})]


def area_variables(area, initial="离开"):
    """一个区域要建的全部变量：模式（文字）、亮度、色温（数字）。"""
    return [area_var_definition(area, initial)] + area_level_var_definitions(area)


def mode_full_name(area, mode):
    """模式全名 = 区域 + 模式，例如 客厅温馨、主卧睡眠；「离开」放前面，读作 离开客厅、离开餐厅。
    规则名、场景键名、备注卡都用它。"""
    if mode == "离开":
        return "离开%s" % area
    return "%s%s" % (area, mode)


def check_mode_names(areas):
    """检查模式名冲突：区域模式全名之间、区域模式全名和全屋模式之间都不能重名，区域变量 ID 也不能撞。
    areas = {区域: [模式...]}。返回问题列表，空 = 通过。"""
    problems, seen, ids = [], {m: "全屋" for m in HOME_MODES}, {}
    for area, modes in areas.items():
        vid = area_var_id(area)
        if vid in ids:
            problems.append("区域「%s」和「%s」的变量 ID 相同，请给其中一个区域换个名字" % (area, ids[vid]))
        ids[vid] = area
        for m in modes:
            full = mode_full_name(area, m)
            if full in seen:
                problems.append("模式名「%s」重复（%s 和 %s）" % (full, seen[full], area))
            seen[full] = area
            if m in HOME_MODES:
                problems.append("区域「%s」的模式「%s」和全屋模式同名，请换个说法" % (area, m))
    return problems


def home_mode_var_definition(initial="在家", var_id=HOME_MODE_VAR):
    """家庭模式变量定义，放进导入集 variables.global，或经 MijiaFlow create_variable 创建。"""
    return var_id, {"type": "string", "value": initial, "userData": {"name": "家庭模式"}}


# ---------- 模板 1：切换家庭模式 ----------
def build_mode_switch_rule(rule_id, switches, var_id=HOME_MODE_VAR, name="家庭模式-切换", note=None):
    """switches=[{"key": key, "mode": "全屋睡眠"}, ...]：按某键 → 家庭模式变量写为对应值。"""
    rb = RuleBuilder(node_prefix="ms" + str(rule_id)[-6:])
    rb.declare_external_var(var_id)
    for sw in switches:
        if sw["mode"] not in HOME_MODES:
            raise ValueError("未知家庭模式：%s" % sw["mode"])
        k = sw["key"]
        ev = rb.trigger_event(k["did"], k["urn"], k["siid"], k["eiid"], k.get("arguments"))
        sv = rb.set_var(var_id, sw["mode"])
        rb.link(ev, "output", sv, "input")
    eff = "；".join("%s→%s" % ((sw["key"].get("name") or "按键"), sw["mode"]) for sw in switches)
    return _finish(rb, rule_id, name, ["家庭状态"],
                   _resolve_note(note, "home-mode-switch", name, _names([sw["key"] for sw in switches]), eff))


# ---------- 模板 2：模式场景（模式一变，执行一组设备状态）----------
def build_mode_scene_rule(rule_id, mode, writes, var_id=HOME_MODE_VAR, name=None, note=None):
    """家庭模式变为 mode 时执行 writes。preload=False，避免规则重载/网关重启时重放场景。"""
    rb = RuleBuilder(node_prefix="sc" + str(rule_id)[-6:])
    rb.declare_external_var(var_id)
    t = rb.trigger_var(var_id, mode, preload=False)
    _chain(rb, t, "output", writes)
    name = name or ("场景-%s" % mode)
    return _finish(rb, rule_id, name, ["家庭状态", "场景"],
                   _resolve_note(note, "mode-scene", name, _names(writes)))


# ---------- 模板 3：按模式分流的按键（同一个键，不同模式做不同的事）----------
def mode_router(rb, entry, entry_port, branches, default=None, var_id=HOME_MODE_VAR):
    """branches=[(mode, attach_fn)]；attach_fn(rb, src, port) 负责接该模式下的动作。
    变量节点只支持「=」，所以按 varGet(=A).output2 → varGet(=B) … 逐级下沉，最后一级 output2 接 default。"""
    src, port = entry, entry_port
    for mode, attach in branches:
        g = rb.cond_var(var_id, mode)
        rb.link(src, port, g, "input")
        attach(rb, g, "output")
        src, port = g, "output2"
    if default is not None:
        default(rb, src, port)


def toggle_lights(lights):
    """返回 attach_fn：首灯开着 → 全部关；否则全部按 on_writes 开（以首灯状态为准，固定开/关写入）。"""
    def attach(rb, src, port):
        chk = _is_on(rb, lights[0])
        rb.link(src, port, chk, "input")
        _chain(rb, chk, "output", _off_writes(lights))
        _chain(rb, chk, "output2", _bright_writes(lights))
    return attach


def build_night_wake_rule(rule_id, bedside_keys, lights, bathroom_sensors=(), sleep_mode="睡眠",
                          var_id=None, name="卧室-起夜", note=None, area=None):
    """起夜：卧室的区域模式=睡眠 时（area=卧室名，读「<卧室>模式」变量），床头任意键 → 灯关着就明亮开灯、开着就关灯；
    同区域卫生间传感器报无人（仍在睡眠模式且灯开着）→ 关灯。不加定时自动关。
    非睡眠模式下按键不在本规则处理（保留按键原有功能或由其他模式分支负责）。"""
    if not bedside_keys or not lights:
        raise ValueError("起夜模板需要至少 1 个床头按键和 1 盏灯")
    if var_id is None:
        if not area:
            raise ValueError("起夜要读卧室的区域模式变量：传 area（如 主卧），或直接传 var_id")
        var_id = area_var_id(area)
        if name == "卧室-起夜":
            name = "%s-起夜" % area
    rb = RuleBuilder(node_prefix="nw" + str(rule_id)[-6:])
    rb.declare_external_var(var_id)
    entry, port = _keys_entry(rb, bedside_keys)
    mode_router(rb, entry, port, [(sleep_mode, toggle_lights(lights))], var_id=var_id)
    for s in bathroom_sensors:
        t = rb.trigger_device(s["did"], s["urn"], s["siid"], s["piid"], "int", "include",
                              list(s.get("no_one", [0])), preload=False)
        g = rb.cond_var(var_id, sleep_mode)
        rb.link(t, "output", g, "input")
        chk = _is_on(rb, lights[0])
        rb.link(g, "output", chk, "input")
        _chain(rb, chk, "output", _off_writes(lights))
    return _finish(rb, rule_id, name, ["家庭状态", "起夜"],
                   _resolve_note(note, "night-wake", name, _names(bedside_keys, lights, list(bathroom_sensors))))


# ---------- 模板 4：日落定时开、固定时间关（对应 HA 蓝图 Daily Sun-Based Scheduler）----------
def build_sunset_schedule_rule(rule_id, latitude, longitude, lights, off_hms, offset_min=-30,
                               days=("mon", "tue", "wed", "thu", "fri", "sat", "sun"),
                               set_mode=None, var_id=HOME_MODE_VAR, name="日落定时开关", note=None):
    """日落(+offset_min 分钟) 且「今天在所选星期、且尚未到关灯时间」→ 可选写家庭模式 → 开灯；
    每天 off_hms 定时 → 逐灯检查开着才关。
    · 星期过滤与「过了关灯时间就不开」由 timeRange(12:00 → off_hms, day 过滤) 接 condition 实现，
      因为 alarmClock 卡不认 filter（库内实测记录）。off_hms 早于 12:00 时为跨天区间（如到 01:00）。
    · 修正 HA 原蓝图的坑：日落晚于关灯时间时，原蓝图开灯后要到次日才关；这里直接不开。"""
    rb = RuleBuilder(node_prefix="ss" + str(rule_id)[-6:])
    sun = rb.alarm_sun(True, offset_min, latitude, longitude)
    window = rb.time_range((12, 0, 0), tuple(off_hms), filter={"day": [WEEKDAY[d] for d in days]})
    gate = rb.condition()
    rb.link(sun, "output", gate, "trigger")
    rb.link(window, "output", gate, "condition")
    src, port = gate, "met"
    if set_mode:
        rb.declare_external_var(var_id)
        sv = rb.set_var(var_id, set_mode)
        rb.link(src, port, sv, "input")
        src, port = sv, "output"
    _chain(rb, src, port, _bright_writes(lights))
    off = rb.alarm_periodic(*off_hms)
    for lt in lights:
        chk = _is_on(rb, lt)
        rb.link(off, "output", chk, "input")
        _chain(rb, chk, "output", [_power(lt, False)])
    eff = "日落%+d 分钟开灯，%02d:%02d 关灯" % (offset_min, off_hms[0], off_hms[1])
    return _finish(rb, rule_id, name, ["区域自动化", "定时"],
                   _resolve_note(note, "sunset-schedule", name, _names(lights), eff))


# ---------- 模板 5：场景 = 发出模式变量 + 批量控制 ----------
def build_scene_rule(rule_id, name, keys, mode, writes, var_id=HOME_MODE_VAR, note=None):
    """按场景键 → 先把全屋唯一的家庭模式变量写为 mode → 再批量写设备。
    先写变量再开灯，让「灯光跟随」规则读到的是新模式。"""
    if mode not in HOME_MODES:
        raise ValueError("未知家庭模式：%s" % mode)
    rb = RuleBuilder(node_prefix="sn" + str(rule_id)[-6:])
    rb.declare_external_var(var_id)
    entry, port = _keys_entry(rb, keys)
    sv = rb.set_var(var_id, mode)
    rb.link(entry, port, sv, "input")
    _chain(rb, sv, "output", writes)
    return _finish(rb, rule_id, name, ["场景"],
                   _resolve_note(note, "scene-with-mode", name, _names(keys, writes),
                                 "家庭模式写成「%s」，再批量控制设备" % mode))


# ---------- 模板 6：灯光跟随模式（之后新开的智能灯按模式设色温亮度）----------
def build_light_follow_rule(rule_id, lights, table=None, var_id=HOME_MODE_VAR, name="灯光跟随模式", note=None,
                            area=None):
    """每盏智能灯被打开（开关属性变为 true）→ 按 var_id 当前模式写入 table[模式] 的亮度/色温。
    lights[i] 需含 "brightness":{"siid","piid"}、"ct":{"siid","piid"}（按 MIoT spec 核对，可只给其一）。
    table = {"在家": {"brightness": 80, "ct": 4000}, "观影": {"brightness": 20, "ct": 2700}, ...}
    不在 table 里的模式不改灯（保留灯自己的记忆值）。只管「新开的灯」；已开着的灯由场景规则负责。
    area=区域名：读这个区域的模式变量，table 省略时用 lighting.area_follow_table(area)（明亮 100%/4000K、温馨 40%/3000K…）。
    不给 area：读全屋家庭模式，table 省略 = lighting.light_follow_table()（在家→休闲、起床/访客→明亮），给跟随全屋的过道、卫生间等用。"""
    if area and table is None:
        return build_area_light_follow_rule(rule_id, area, lights,
                                            name=None if name == "灯光跟随模式" else name, note=note)
    if area:
        var_id = area_var_id(area)
        if name == "灯光跟随模式":
            name = "%s-灯光跟随" % area
    if table is None:
        table = light_follow_table()
    rb = RuleBuilder(node_prefix="lf" + str(rule_id)[-6:])
    rb.declare_external_var(var_id)
    for lt in lights:
        p = lt["power"]
        on = rb.trigger_device(lt["did"], lt["urn"], p["siid"], p["piid"], "boolean", "=", True, preload=False)
        branches = []
        for mode, vals in table.items():
            writes = []
            for prop in ("brightness", "ct"):
                if prop in vals and prop in lt:
                    writes.append({"did": lt["did"], "urn": lt["urn"], "siid": lt[prop]["siid"],
                                   "piid": lt[prop]["piid"], "value": vals[prop]})
            if writes:
                branches.append((mode, lambda rb, src, port, w=writes: _chain(rb, src, port, w)))
        if not branches:
            raise ValueError("灯 %s 没有可写的亮度/色温属性，或 table 为空" % lt["did"])
        mode_router(rb, on, "output", branches, var_id=var_id)
    eff = "；".join("%s %d%%/%dK" % (m, v.get("brightness", 0), v.get("ct", 0)) for m, v in table.items())
    return _finish(rb, rule_id, name, ["家庭状态", "灯光跟随"],
                   _resolve_note(note, "light-follow", name, _names(lights), eff))


def build_area_light_follow_rule(rule_id, area, lights, skip_modes=("睡眠",), name=None, note=None):
    """区域灯光跟随（2.0.7）：这个区域的调光灯被打开 → 直接把「<区域>亮度」「<区域>色温」两个变量的值写给灯。
    区域模式规则切模式时会改这两个变量，所以灯总是按当前模式亮；以后想让它跟着太阳变，只要按时间改这两个变量。
    skip_modes：这些模式下不改灯（睡眠时开灯多半是起夜，交给起夜规则）。
    lights[i] 需带 brightness/ct 的 siid/piid，可带 "ct_range": [最低K, 最高K]（默认 2700–6500），
    "brightness_range": [最低, 最高]（默认 1–100）。"""
    var_id = area_var_id(area)
    bid, cid = area_level_var_ids(area)
    rb = RuleBuilder(node_prefix="lv" + str(rule_id)[-6:])
    for v in (var_id, bid, cid):
        rb.declare_external_var(v)
    n_lamps = 0
    for lt in lights:
        if "brightness" not in lt and "ct" not in lt:
            continue
        n_lamps += 1
        p = lt["power"]
        src = rb.trigger_device(lt["did"], lt["urn"], p["siid"], p["piid"], "boolean", "=", True, preload=False)
        port = "output"
        for m in skip_modes:
            g = rb.cond_var(var_id, m)
            rb.link(src, port, g, "input")
            src, port = g, "output2"
        for prop, vid, rng in (("brightness", bid, lt.get("brightness_range", (1, 100))),
                               ("ct", cid, lt.get("ct_range", (2700, 6500)))):
            if prop in lt:
                w = rb.write_device_var(lt["did"], lt["urn"], lt[prop]["siid"], lt[prop]["piid"], vid, rng[0], rng[1])
                rb.link(src, port, w, "trigger")
                src, port = w, "output"
    if not n_lamps:
        raise ValueError("区域「%s」没有带亮度/色温属性的调光灯，不需要灯光跟随" % area)
    name = name or "%s-灯光跟随" % area
    eff = "新开的调光灯按「%s亮度」「%s色温」亮起（%s时不改）" % (area, area, "、".join(skip_modes) or "任何模式")
    return _finish(rb, rule_id, name, ["区域模式", "灯光跟随", area],
                   _resolve_note(note, "light-follow", name,
                                 _names([lt for lt in lights if "brightness" in lt or "ct" in lt]), eff))


# ---------- 区域自动化 ----------
def _event_or_state(rb, spec):
    """spec 含 eiid → 事件触发；否则按属性触发（需 dtype/operator/v1）。"""
    if "eiid" in spec:
        return rb.trigger_event(spec["did"], spec["urn"], spec["siid"], spec["eiid"], spec.get("arguments"))
    return rb.trigger_device(spec["did"], spec["urn"], spec["siid"], spec["piid"], spec["dtype"],
                             spec["operator"], spec["v1"], preload=False)


def _skip_modes(rb, src, port, modes, var_id):
    """当前模式属于 modes 时停下，否则继续；返回继续的 (节点, 端口)。"""
    for m in modes:
        g = rb.cond_var(var_id, m)
        rb.link(src, port, g, "input")
        src, port = g, "output2"
    return src, port


def build_presence_light_rule(rule_id, name, sensors, lights, hold_off_ms=120000, lux=None,
                              skip_modes=("离家",), var_id=HOME_MODE_VAR, note=None, pause=False):
    """人来灯亮、人走灯灭（走廊、卫生间、衣帽间等）。
    sensors[i] = {"did","urn","siid","piid","someone":[1],"no_one":[0]}
    lux 可选 = {"did","urn","siid","piid","below":80}：照度低于 below 才开灯
    · 开：任一传感器有人 → 跳过 skip_modes → (照度够暗) → 灯关着才开。只开电源，亮度色温交给「灯光跟随」。
    · 关：每个传感器各挂独立 statusLast(hold_off_ms)（不用共享 delay，重复上报不会重置）
          → 多传感器时 logicAnd → 再逐个复核「此刻仍无人」（logicAnd 是锁存，不复核会误关）→ 灯开着才关。"""
    if not sensors or not lights:
        raise ValueError("需要至少 1 个传感器和 1 盏灯")
    rb = RuleBuilder(node_prefix="pl" + str(rule_id)[-6:])
    if skip_modes:
        rb.declare_external_var(var_id)
    ons = [rb.trigger_device(s["did"], s["urn"], s["siid"], s["piid"], "int", "include",
                             list(s.get("someone", [1])), preload=False) for s in sensors]
    if len(ons) == 1:
        src, port = ons[0], "output"
    else:
        src = rb.signal_or(len(ons)); port = "output"
        for i, t in enumerate(ons):
            rb.link(t, "output", src, "input%d" % i)
    src, port = _skip_modes(rb, src, port, skip_modes, var_id)
    if lux:
        g = rb.cond_device(lux["did"], lux["urn"], lux["siid"], lux["piid"], "int", "<", lux.get("below", 80))
        rb.link(src, port, g, "input")
        src, port = g, "output"
    chk = _is_on(rb, lights[0])
    rb.link(src, port, chk, "input")
    _chain(rb, chk, "output2", [_power(lt, True) for lt in lights])

    holds = []
    for s in sensors:
        t = rb.trigger_device(s["did"], s["urn"], s["siid"], s["piid"], "int", "include",
                              list(s.get("no_one", [0])), preload=False)
        h = rb.status_last(hold_off_ms)
        rb.link(t, "output", h, "input")
        holds.append(h)
    if len(holds) == 1:
        src, port = holds[0], "output"
    else:
        src = rb.logic_and(len(holds)); port = "output"
        for i, h in enumerate(holds):
            rb.link(h, "output", src, "input%d" % i)
        for s in sensors:
            g = rb.cond_device(s["did"], s["urn"], s["siid"], s["piid"], "int", "include", list(s.get("no_one", [0])))
            rb.link(src, port, g, "input")
            src, port = g, "output"
    if pause:          # 「临时不让感应关灯」：感应暂停 = 暂停 时不关
        rb.declare_external_var(MOTION_PAUSE_VAR)
        g = rb.cond_var(MOTION_PAUSE_VAR, "暂停")
        rb.link(src, port, g, "input")
        src, port = g, "output2"
    chk = _is_on(rb, lights[0])
    rb.link(src, port, chk, "input")
    _chain(rb, chk, "output", _off_writes(lights))
    return _finish(rb, rule_id, name, ["区域自动化", "人来灯亮"],
                   _resolve_note(note, "presence-light", name, _names(sensors, lights)))


def build_arrive_home_rule(rule_id, entry, writes, away_mode="离家", home_mode="在家",
                           var_id=HOME_MODE_VAR, name="玄关-回家", note=None):
    """回家：开门事件（门锁开门 eiid / 门窗传感器打开属性）且当前是「离家」→ 家庭模式改为「在家」→ 执行回家动作。
    在家时开门不触发，避免家人进出反复执行。entry 见 _event_or_state。"""
    rb = RuleBuilder(node_prefix="ah" + str(rule_id)[-6:])
    rb.declare_external_var(var_id)
    t = _event_or_state(rb, entry)
    g = rb.cond_var(var_id, away_mode)
    rb.link(t, "output", g, "input")
    sv = rb.set_var(var_id, home_mode)
    rb.link(g, "output", sv, "input")
    _chain(rb, sv, "output", writes)
    return _finish(rb, rule_id, name, ["区域自动化", "回家"],
                   _resolve_note(note, "arrive-home", name, _names(entry, writes),
                                 "家庭模式改成「%s」→ 开 %s" % (home_mode, "、".join(_names(writes)) or "回家设备")))


def build_sunrise_curtain_rule(rule_id, latitude, longitude, writes, offset_min=0, workday_only=True,
                               skip_modes=("离家",), var_id=HOME_MODE_VAR, name="晨起-开窗帘", note=None):
    """日出(+offset) → (仅法定工作日) → 跳过 skip_modes → 执行 writes（开窗帘等）。
    工作日判定用全天 timeRange(inHoliday:false) 接 condition（alarmClock 不认过滤）。
    想等主人起床再开，就不用本模板，把开窗帘放进「起床」模式场景。"""
    rb = RuleBuilder(node_prefix="sr" + str(rule_id)[-6:])
    sun = rb.alarm_sun(False, offset_min, latitude, longitude)
    src, port = sun, "output"
    if workday_only:
        tr = rb.time_range((0, 0, 0), (23, 59, 59), filter={"inHoliday": False})
        gate = rb.condition()
        rb.link(sun, "output", gate, "trigger")
        rb.link(tr, "output", gate, "condition")
        src, port = gate, "met"
    if skip_modes:
        rb.declare_external_var(var_id)
        src, port = _skip_modes(rb, src, port, skip_modes, var_id)
    _chain(rb, src, port, writes)
    return _finish(rb, rule_id, name, ["区域自动化", "窗帘"],
                   _resolve_note(note, "sunrise-curtain", name, _names(writes)))


# ---------- 模板 7：氛围场景（明亮/休闲/温馨/放松/休憩，调光灯和普通灯分开处理）----------
def build_mood_scene_rule(rule_id, name, keys, mood, room="", tunable=(), plain=(), mode=None, keep=None,
                          extra_writes=(), var_id=HOME_MODE_VAR, note=None):
    """按场景键 → (可选) 先写家庭模式 → 调光调色灯按氛围表设亮度色温 → 普通灯按分层开/关 → extra_writes（窗帘等）。
    tunable[i] 同 light，另需 brightness/ct 的 siid/piid，可带 ct_range；
    plain[i] 同 light（智能开关的一路），需带 name（键名，用来分层）或 layer（泛照明/重点照明/补光/氛围）。
    keep：「一路」「按需」时要开的那几路的名字。分不出层的普通灯直接报错，请客户确认后补 layer。"""
    if not keys:
        raise ValueError("氛围场景需要至少 1 个场景键")
    if not tunable and not plain:
        raise ValueError("氛围场景需要至少 1 盏灯")
    on, off, unknown = plain_plan(mood, list(plain), keep)
    if unknown:
        raise ValueError("这些普通灯分不出是哪一层，请客户确认后给它们加 layer：%s"
                         % "、".join(lt.get("name") or lt["did"] for lt in unknown))
    if not tunable and not on:
        raise ValueError("这个房间在「%s」下所有灯都会关（普通灯只有 %s）。先和客户商量：这一路也开，"
                         "就用 keep 传它的名字；或建议加一路灯带/落地灯" % (mood, "、".join(lt.get("name") or "灯" for lt in off)))
    writes = []
    for lt in tunable:
        writes.extend(mood_light_writes(lt, mood, room))
    writes.extend(_power(lt, True) for lt in on)
    writes.extend(_power(lt, False) for lt in off)
    writes.extend(extra_writes)
    rb = RuleBuilder(node_prefix="md" + str(rule_id)[-6:])
    entry, port = _keys_entry(rb, keys)
    if mode:
        if mode not in HOME_MODES:
            raise ValueError("未知家庭模式：%s" % mode)
        rb.declare_external_var(var_id)
        sv = rb.set_var(var_id, mode)
        rb.link(entry, port, sv, "input")
        entry, port = sv, "output"
    _chain(rb, entry, port, writes)
    parts = []
    if mode:
        parts.append("家庭模式写成「%s」" % mode)
    if tunable:
        v = tunable_values(mood, room)
        parts.append("调光灯 %d%%/%dK" % (v["brightness"], v["ct"]))
    if on:
        parts.append("开 " + "、".join(lt.get("name") or "灯" for lt in on))
    if off:
        parts.append("关 " + "、".join(lt.get("name") or "灯" for lt in off))
    title = name or ("%s-%s" % (room, mood) if room else "场景-" + mood)
    return _finish(rb, rule_id, title, ["场景", "氛围"],
                   _resolve_note(note, "mood-scene", title, _names(keys, list(tunable), list(plain), list(extra_writes)),
                                 "；".join(parts)))


# ---------- 区域模式（全屋家庭模式 + 每个区域一个模式变量）----------
def _light_on_writes(lt, mode, area):
    """开灯：调光调色灯（带 brightness/ct）写 开→亮度→色温；普通灯只写开。"""
    if "brightness" in lt or "ct" in lt:
        if mode in ("睡眠", "离开"):
            return [_power(lt, True)]
        return mood_light_writes(lt, mode, area)
    return [_power(lt, True)]


def build_area_mode_rule(rule_id, area, mode, keys, lights, keep=None, extra_writes=(), name=None, note=None,
                         levels=True):
    """区域模式：按场景键 → 先把「<区域>模式」变量写成 mode → 再改「<区域>亮度」「<区域>色温」两个数字变量
    （levels=False 不改）→ 再按灯的角色开关这个区域的灯 → extra_writes（窗帘等）。
    lights：这个区域的全部灯（调光灯带 brightness/ct 的 siid/piid，普通灯只要 power），每盏带 name（用来判断角色）或 role。
    双控的副开关不要放进来，只放真正接着灯的那一路。名字带「感应」的灯不参与。"""
    if mode not in MODE_ROLES:
        raise ValueError("未知模式：%s" % mode)
    if mode not in modes_for_area(area) and modes_for_area(area):
        raise ValueError("区域「%s」默认没有「%s」模式（可选 %s），确认要加就先改 lighting.AREA_MODES"
                         % (area, mode, "、".join(modes_for_area(area))))
    if not keys:
        raise ValueError("区域模式需要至少 1 个场景键")
    on, off, unknown = plan_lights(mode, list(lights), keep)
    if unknown:
        raise ValueError("这些灯看不出是什么角色，请结合整个房间判断后给它们加 role：%s"
                         % "、".join(lt.get("name") or lt["did"] for lt in unknown))
    if mode not in ("睡眠", "离开") and not on:
        raise ValueError("「%s」下这个区域所有灯都会关，场景会是黑的。用 keep 指定要开的灯，或建议客户加灯带/落地灯"
                         % mode_full_name(area, mode))
    var_id = area_var_id(area)
    rb = RuleBuilder(node_prefix="am" + str(rule_id)[-6:])
    rb.declare_external_var(var_id)
    entry, port = _keys_entry(rb, keys)
    sv = rb.set_var(var_id, mode)
    rb.link(entry, port, sv, "input")
    last = sv
    if levels and mode in MODE_TUNABLE:          # 再改这个区域的亮度、色温变量，灯光跟随读它们
        v = tunable_values(mode, area)
        for vid, val in zip(area_level_var_ids(area), (v["brightness"], v["ct"])):
            rb.declare_external_var(vid)
            n = rb.set_number(vid, val)
            rb.link(last, "output", n, "input")
            last = n
    writes = []
    for lt in on:
        writes.extend(_light_on_writes(lt, mode, area))
    writes.extend(_power(lt, False) for lt in off)
    writes.extend(extra_writes)
    _chain(rb, last, "output", writes)
    full = mode_full_name(area, mode)
    name = name or full
    parts = ["「%s模式」写成 %s" % (area, mode)]
    tun = [lt for lt in on if "brightness" in lt or "ct" in lt]
    if tun and mode in MODE_TUNABLE:
        v = tunable_values(mode, area)
        parts.append("调光灯 %d%%/%dK" % (v["brightness"], v["ct"]))
    if on:
        parts.append("开 " + "、".join(lt.get("name") or "灯" for lt in on))
    if off:
        parts.append("关 " + "、".join(lt.get("name") or "灯" for lt in off))
    return _finish(rb, rule_id, name, ["区域模式", area],
                   _resolve_note(note, "area-mode", full, _names(keys, list(lights), list(extra_writes)), "；".join(parts),
                                 "按 " + "、".join(k.get("name") or "场景键" for k in keys)))


def build_area_off_sync_rule(rule_id, area, lights, off_value="离开", name=None, note=None):
    """同步：这个区域的灯被人全关了 → 「<区域>模式」变量改成 离开（卧室在睡眠时不改，见下）。
    任一灯变成关 → 逐盏确认都关了 → 写变量。卧室请另外传 skip_values 以外的逻辑：睡眠时关灯是正常的，不改成离开。"""
    if not lights:
        raise ValueError("需要这个区域的灯")
    var_id = area_var_id(area)
    rb = RuleBuilder(node_prefix="ao" + str(rule_id)[-6:])
    rb.declare_external_var(var_id)
    trig = []
    for lt in lights:
        p = lt["power"]
        trig.append(rb.trigger_device(lt["did"], lt["urn"], p["siid"], p["piid"], "boolean", "=", False, preload=False))
    if len(trig) == 1:
        src, port = trig[0], "output"
    else:
        src = rb.signal_or(len(trig)); port = "output"
        for i, t in enumerate(trig):
            rb.link(t, "output", src, "input%d" % i)
    for lt in lights:
        p = lt["power"]
        g = rb.cond_device(lt["did"], lt["urn"], p["siid"], p["piid"], "boolean", "=", False)
        rb.link(src, port, g, "input")
        src, port = g, "output"
    for keep_mode in ("睡眠", off_value):      # 已经是睡眠/离开就不改
        g = rb.cond_var(var_id, keep_mode)
        rb.link(src, port, g, "input")
        src, port = g, "output2"
    sv = rb.set_var(var_id, off_value)
    rb.link(src, port, sv, "input")
    name = name or "%s-灯全关同步" % area
    return _finish(rb, rule_id, name, ["区域模式", "同步", area],
                   _resolve_note(note, "area-sync", name, _names(list(lights)),
                                 "%s的灯全关了，「%s模式」改成 %s（睡眠时不改）" % (area, area, off_value)))


def build_home_cascade_rule(rule_id, home_mode, area_values, writes=(), var_id=HOME_MODE_VAR, name=None, note=None):
    """全屋带区域：家庭模式变成 home_mode → 依次把各区域变量写成对应值 → 再执行 writes（关灯、关窗帘等）。
    area_values = {"客厅": "离开", "主卧": "睡眠", ...}。例：离家 → 所有区域 离开；全屋睡眠 → 卧室 睡眠、其余 离开。"""
    if home_mode not in HOME_MODES:
        raise ValueError("未知家庭模式：%s" % home_mode)
    rb = RuleBuilder(node_prefix="hc" + str(rule_id)[-6:])
    rb.declare_external_var(var_id)
    t = rb.trigger_var(var_id, home_mode, preload=False)
    src, port = t, "output"
    for area, val in area_values.items():
        vid = area_var_id(area)
        rb.declare_external_var(vid)
        sv = rb.set_var(vid, val)
        rb.link(src, port, sv, "input")
        src, port = sv, "output"
    _chain(rb, src, port, list(writes))
    name = name or "全屋-%s" % home_mode
    eff = "；".join("%s→%s" % (a, v) for a, v in area_values.items())
    if writes:
        eff += "；再执行 %d 个设备动作" % len(writes)
    return _finish(rb, rule_id, name, ["家庭状态", "区域模式"],
                   _resolve_note(note, "home-cascade", name, _names(list(writes)), eff, "家庭模式变成「%s」" % home_mode))


def build_dual_control_rule(rule_id, secondary_keys, main_light, name=None, note=None):
    """双控：副开关（已设成无线、没接灯）按一下 → 切主开关那一路的继电器：灯开着就关，关着就开。
    main_light 是真正接着普通灯的那一路，必须保持有线：改成无线会让继电器常通，灯关不掉。"""
    if not secondary_keys:
        raise ValueError("需要至少 1 个副开关的无线键")
    rb = RuleBuilder(node_prefix="dc" + str(rule_id)[-6:])
    entry, port = _keys_entry(rb, secondary_keys)
    toggle_lights([main_light])(rb, entry, port)
    lamp = main_light.get("name") or "灯"
    name = name or "双控-%s" % lamp
    return _finish(rb, rule_id, name, ["双控"],
                   _resolve_note(note, "dual-control", name, _names(secondary_keys, main_light),
                                 "按副开关：%s开着就关，关着就开（主开关那一路保持有线）" % lamp))


def build_switch_mode_rule(rule_id, writes, name="开关改无线（一次性）", note=None):
    """开关改无线的一次性规则：规则加载时 → 依次写每个键的工作模式（和通电后状态）。
    writes 用 commissioning.switch_mode_writes() 生成，或按 spec 查到的属性自己写。
    用法：客户同意后写入，启用一次，读回属性核对，然后停用或删掉。
    双控主开关接普通灯的那一路、接普通灯的键，绝不能放进来：改成无线后继电器常通，灯关不掉。"""
    if not writes:
        raise ValueError("需要至少 1 个要写的属性")
    rb = RuleBuilder(node_prefix="sm" + str(rule_id)[-6:])
    t = rb.on_load()
    _chain(rb, t, "output", list(writes))
    eff = "、".join(w.get("name") or "siid%s piid%s=%s" % (w["siid"], w["piid"], w["value"]) for w in writes)
    return _finish(rb, rule_id, name, ["设备调试", "一次性"],
                   _resolve_note(note, "switch-mode", name, (), "写入 " + eff + "。启用一次、读回核对后停用或删掉"))


def speaker_text(speaker, text):
    """小爱音箱播报一段固定文字（play-text）。speaker 需带 play_text={"siid","aiid"}，例如 xiaomi-lx06 是 siid5 aiid1。"""
    a = speaker["play_text"]
    return {"did": speaker["did"], "urn": speaker["urn"], "siid": a["siid"], "aiid": a["aiid"],
            "ins": [{"piid": 1, "value": text}], "name": speaker.get("name")}


def speaker_ai(speaker, prompt):
    """让小爱按一段提示词自己组织语言说出来（execute-text-directive，非静默）。
    speaker 需带 directive={"siid","aiid"}，例如 xiaomi-lx06 是 siid5 aiid5。"""
    a = speaker["directive"]
    return {"did": speaker["did"], "urn": speaker["urn"], "siid": a["siid"], "aiid": a["aiid"],
            "ins": [{"piid": 1, "value": prompt}, {"piid": 2, "value": False}], "name": speaker.get("name")}


def build_speaker_reminder_rule(rule_id, home_mode, speaker, checks=(), text=None, prompt=None, volume=None,
                                var_id=HOME_MODE_VAR, name=None, note=None):
    """可选场景：家庭模式变成 home_mode（离家 / 全屋睡眠）→ 小爱音箱提醒。只在客户说要的时候做。
    checks=[{"did","urn","siid","piid","dtype","operator","v1","name","say"}]：逐项查（例如窗没关、空调还开着），
      条件成立就播报这一项的 say；一项都不成立就不说话。
    不给 checks 时直接说 text；给 prompt 则改用小爱自己组织语言（speaker_ai）。
    volume：播报前先把音量设成这个值（例如 40），睡眠时别太大声。"""
    if home_mode not in HOME_MODES:
        raise ValueError("未知家庭模式：%s" % home_mode)
    if not checks and not (text or prompt):
        raise ValueError("要么给 checks（逐项提醒），要么给 text / prompt")
    rb = RuleBuilder(node_prefix="sr" + str(rule_id)[-6:])
    rb.declare_external_var(var_id)
    src, port = rb.trigger_var(var_id, home_mode, preload=False), "output"
    if volume is not None:
        v = speaker.get("volume") or {"siid": 2, "piid": 1}
        src = _chain(rb, src, port, [{"did": speaker["did"], "urn": speaker["urn"], "siid": v["siid"],
                                      "piid": v["piid"], "value": volume}])
        port = "output"
    say = lambda t: speaker_ai(speaker, t) if prompt else speaker_text(speaker, t)
    if not checks:
        _chain(rb, src, port, [say(prompt or text)])
    else:
        for i, c in enumerate(checks):
            g = rb.cond_device(c["did"], c["urn"], c["siid"], c["piid"], c["dtype"], c["operator"], c["v1"])
            rb.link(src, port, g, "input")
            last = _chain(rb, g, "output", [say(c["say"])])
            if i == len(checks) - 1:
                break
            gap = rb.delay(5000)                       # 等上一句说完再查下一项
            rb.link(last, "output", gap, "input")
            join = rb.signal_or(2)
            rb.link(gap, "output", join, "input0")
            rb.link(g, "output2", join, "input1")
            src, port = join, "output"
    name = name or "%s-小爱提醒" % home_mode
    eff = "；".join(c["say"] for c in checks) if checks else (prompt or text)
    return _finish(rb, rule_id, name, ["家庭状态", "提醒", "可选"],
                   _resolve_note(note, "speaker-reminder", name, _names(speaker, list(checks)), eff,
                                 "家庭模式变成「%s」" % home_mode))


# ---------- 2.0.8：按键玩法、暂停感应、定时、保底关、低电量 ----------
def area_mode_attach(area, mode, lights, keep=None, extra_writes=(), levels=True):
    """返回 attach_fn(rb, src, port)：执行一个区域模式（写模式变量 → 写亮度色温变量 → 开关灯 → extra_writes）。
    和 build_area_mode_rule 做的事一样，给「一个键轮流切」「遥控器分区」「上下键调光」这些组合规则复用。"""
    if mode not in MODE_ROLES:
        raise ValueError("未知模式：%s" % mode)
    on, off, unknown = plan_lights(mode, list(lights), keep)
    if unknown:
        raise ValueError("这些灯看不出是什么角色，请先给它们加 role：%s"
                         % "、".join(lt.get("name") or lt["did"] for lt in unknown))
    if mode not in ("睡眠", "离开") and not on:
        raise ValueError("「%s」下这个区域所有灯都会关，用 keep 指定要开的灯" % mode_full_name(area, mode))

    def attach(rb, src, port):
        var_id = area_var_id(area)
        rb.declare_external_var(var_id)
        sv = rb.set_var(var_id, mode)
        rb.link(src, port, sv, "input")
        last = sv
        if levels and mode in MODE_TUNABLE:
            v = tunable_values(mode, area)
            for vid, val in zip(area_level_var_ids(area), (v["brightness"], v["ct"])):
                rb.declare_external_var(vid)
                n = rb.set_number(vid, val)
                rb.link(last, "output", n, "input")
                last = n
        writes = []
        for lt in on:
            writes.extend(_light_on_writes(lt, mode, area))
        writes.extend(_power(lt, False) for lt in off)
        writes.extend(extra_writes)
        _chain(rb, last, "output", writes)
    return attach


def build_mode_cycle_rule(rule_id, area, keys, lights, modes=None, off_keys=(), keep=None, name=None, note=None):
    """一个键轮流切模式：每按一次切到下一个模式（例如 明亮 → 休闲 → 温馨 → 放松 → 明亮）。
    不另加计数器：按「<区域>模式」变量现在的值决定下一个；不在列表里的值（离开、睡眠…）一律切到第一个。
    off_keys：可选的「关」键，按下 = 离开（全关），下次再按轮换键就从第一个开始。
    modes 省略 = 这个区域的模式里，去掉离开/睡眠/就餐/观影，再去掉开的灯和前一个完全一样的（按了没变化）。"""
    if not keys:
        raise ValueError("需要一个轮换键")
    if modes is None:
        modes, seen = [], set()
        tunable = any("brightness" in lt or "ct" in lt for lt in lights)
        for m in modes_for_area(area):
            if m in ("离开", "睡眠", "就餐", "观影"):
                continue
            on_names = tuple(lt.get("name") for lt in plan_lights(m, list(lights), keep)[0])
            if not on_names or (on_names in seen and not tunable):
                continue
            seen.add(on_names)
            modes.append(m)
    if len(modes) < 2:
        raise ValueError("区域「%s」能轮换的模式不到 2 个，做一个键一个模式就行" % area)
    var_id = area_var_id(area)
    rb = RuleBuilder(node_prefix="mc" + str(rule_id)[-6:])
    rb.declare_external_var(var_id)
    entry, port = _keys_entry(rb, keys)
    branches = [(m, area_mode_attach(area, modes[(i + 1) % len(modes)], lights, keep)) for i, m in enumerate(modes)]
    mode_router(rb, entry, port, branches, default=area_mode_attach(area, modes[0], lights, keep), var_id=var_id)
    if off_keys:
        oe, op = _keys_entry(rb, off_keys)
        area_mode_attach(area, "离开", lights, keep)(rb, oe, op)
    name = name or "%s-一键轮换" % area
    eff = "每按一次：" + " → ".join(modes) + " → " + modes[0] + ("；按关键全关" if off_keys else "")
    return _finish(rb, rule_id, name, ["区域模式", "按键", area],
                   _resolve_note(note, "mode-cycle", name, _names(keys, list(off_keys), list(lights)), eff))


def build_on_off_keys_rule(rule_id, on_keys, off_keys, on_writes, off_writes, name="开关分开的两个键", note=None):
    """一个键只管开、一个键只管关，开关时可以顺带别的（关灯顺手关窗帘）。比「按一下切换」不容易按错。
    on_writes / off_writes：要写的属性列表（灯、窗帘等）。"""
    if not on_keys or not off_keys:
        raise ValueError("需要开键和关键")
    rb = RuleBuilder(node_prefix="oo" + str(rule_id)[-6:])
    e, p = _keys_entry(rb, on_keys)
    _chain(rb, e, p, list(on_writes))
    e, p = _keys_entry(rb, off_keys)
    _chain(rb, e, p, list(off_writes))
    return _finish(rb, rule_id, name, ["按键"],
                   _resolve_note(note, "on-off-keys", name, _names(on_keys, off_keys, list(on_writes), list(off_writes)),
                                 "开键：%d 个动作；关键：%d 个动作" % (len(on_writes), len(off_writes))))


def build_zone_remote_rule(rule_id, zones, name="遥控器分区控制", note=None):
    """一个多键遥控器或场景面板，每组键管一个区域。
    zones=[{"area": "客厅", "on_key": key, "off_key": key, "mode": "温馨", "lights": [...]}, ...]
    开键 = 这个区域的常用模式（mode，默认温馨），关键 = 离开。"""
    if not zones:
        raise ValueError("需要至少一个区域")
    rb = RuleBuilder(node_prefix="zr" + str(rule_id)[-6:])
    parts, devs = [], []
    for z in zones:
        mode = z.get("mode") or "温馨"
        if z.get("on_key"):
            e, p = _keys_entry(rb, [z["on_key"]])
            area_mode_attach(z["area"], mode, z["lights"], z.get("keep"))(rb, e, p)
            devs.append(z["on_key"])
        if z.get("off_key"):
            e, p = _keys_entry(rb, [z["off_key"]])
            area_mode_attach(z["area"], "离开", z["lights"], z.get("keep"))(rb, e, p)
            devs.append(z["off_key"])
        parts.append("%s：开=%s，关=%s" % (z["area"], mode_full_name(z["area"], mode), mode_full_name(z["area"], "离开")))
    return _finish(rb, rule_id, name, ["区域模式", "按键"],
                   _resolve_note(note, "zone-remote", name, _names(devs), "；".join(parts)))


def build_brightness_step_rule(rule_id, area, up_keys, down_keys, lights, keep=None, name=None, note=None):
    """上下键调亮调暗（稳妥版）：上键切到更亮的模式，下键切到更暗的模式，顺序 休憩 → 放松 → 温馨 → 休闲 → 明亮
    （只用这个区域有的模式）。已经最亮/最暗时保持不变；现在不是这几个模式（离开、睡眠、观影…）时，两个键都切到温馨。"""
    order = [m for m in BRIGHTNESS_ORDER if m in (modes_for_area(area) or BRIGHTNESS_ORDER)
             and plan_lights(m, list(lights), keep)[0]]           # 会全黑的模式不进顺序
    if len(order) < 2:
        raise ValueError("区域「%s」可调的模式不到 2 个" % area)
    mid = "温馨" if "温馨" in order else order[len(order) // 2]
    var_id = area_var_id(area)
    rb = RuleBuilder(node_prefix="bs" + str(rule_id)[-6:])
    rb.declare_external_var(var_id)
    sources = {}                                   # 目标模式 → [(节点, 端口)]，同一个目标只生成一套灯光卡片
    collect = lambda target: (lambda rb, src, port: sources.setdefault(target, []).append((src, port)))
    for keys, step in ((up_keys, 1), (down_keys, -1)):
        if not keys:
            continue
        e, p = _keys_entry(rb, keys)
        branches = []
        for i, m in enumerate(order):
            j = min(max(i + step, 0), len(order) - 1)   # 已经最亮/最暗：再执行一次本模式，等于不变
            branches.append((m, collect(order[j])))
        mode_router(rb, e, p, branches, default=collect(mid), var_id=var_id)
    for target, srcs in sources.items():
        if len(srcs) == 1:
            src, port = srcs[0]
        else:
            src, port = rb.signal_or(len(srcs)), "output"
            for i, (n, pt) in enumerate(srcs):
                rb.link(n, pt, src, "input%d" % i)
        area_mode_attach(area, target, lights, keep)(rb, src, port)
    name = name or "%s-上下键调光" % area
    eff = "上键更亮、下键更暗：" + " → ".join(order) + "；其他状态下按任一键到%s" % mid
    return _finish(rb, rule_id, name, ["区域模式", "按键", area],
                   _resolve_note(note, "brightness-step", name, _names(list(up_keys), list(down_keys)), eff))


MOTION_PAUSE_VAR = "VmotionPau1"     # 全屋「感应暂停」变量：正常 / 暂停


def motion_pause_var_definition(initial="正常"):
    return MOTION_PAUSE_VAR, {"type": "string", "value": initial, "userData": {"name": "感应暂停"}}


def build_motion_pause_rule(rule_id, pause_keys, resume_keys=(), resume_when_off=(),
                            resume_modes=("离家", "全屋睡眠"), var_id=HOME_MODE_VAR, name="临时不让感应关灯", note=None):
    """全屋暂停「人走灯灭」：按暂停键 → 「感应暂停」= 暂停，人来灯亮规则看到暂停就不关灯（build_presence_light_rule 传 pause=True）。
    自动恢复（不会忘了恢复）：按恢复键；或 resume_when_off 里的灯全关了；或家庭模式变成离家、全屋睡眠。
    客户想按区域暂停时，由客户自己提，AI 再给每个区域加一个暂停变量。"""
    if not pause_keys:
        raise ValueError("需要一个暂停键")
    rb = RuleBuilder(node_prefix="mp" + str(rule_id)[-6:])
    rb.declare_external_var(MOTION_PAUSE_VAR)
    e, p = _keys_entry(rb, pause_keys)
    sv = rb.set_var(MOTION_PAUSE_VAR, "暂停")
    rb.link(e, p, sv, "input")
    resumes = []
    if resume_keys:
        resumes.append(_keys_entry(rb, resume_keys))
    if resume_when_off:
        trig = []
        for lt in resume_when_off:
            pw = lt["power"]
            trig.append(rb.trigger_device(lt["did"], lt["urn"], pw["siid"], pw["piid"], "boolean", "=", False))
        src, port = trig[0], "output"
        if len(trig) > 1:
            src = rb.signal_or(len(trig)); port = "output"
            for i, t in enumerate(trig):
                rb.link(t, "output", src, "input%d" % i)
        for lt in resume_when_off:
            g = rb.cond_device(lt["did"], lt["urn"], lt["power"]["siid"], lt["power"]["piid"], "boolean", "=", False)
            rb.link(src, port, g, "input")
            src, port = g, "output"
        resumes.append((src, port))
    for m in resume_modes:
        rb.declare_external_var(var_id)
        resumes.append((rb.trigger_var(var_id, m, preload=False), "output"))
    for src, port in resumes:
        r = rb.set_var(MOTION_PAUSE_VAR, "正常")
        rb.link(src, port, r, "input")
    how = []
    if resume_keys:
        how.append("按恢复键")
    if resume_when_off:
        how.append("这些灯全关")
    if resume_modes:
        how.append("家庭模式变成" + "、".join(resume_modes))
    return _finish(rb, rule_id, name, ["家庭状态", "人来灯亮"],
                   _resolve_note(note, "motion-pause", name, _names(pause_keys, list(resume_keys), list(resume_when_off)),
                                 "按暂停键：人走灯不灭；自动恢复：" + "，或".join(how)))


def build_time_schedule_rule(rule_id, on_hms, off_hms, on_writes, off_writes,
                             days=("mon", "tue", "wed", "thu", "fri", "sat", "sun"), name="定时开关", note=None):
    """每天固定时间开、固定时间关，可选星期几（鱼缸灯、门头灯、灯串）。
    星期过滤用全天 timeRange（带 day 过滤）接 condition，因为 alarmClock 卡不认 filter。"""
    rb = RuleBuilder(node_prefix="ts" + str(rule_id)[-6:])
    dayf = {"day": [WEEKDAY[d] for d in days]}
    for hms, writes in ((on_hms, on_writes), (off_hms, off_writes)):
        if not writes:
            continue
        a = rb.alarm_periodic(*hms)
        if len(days) < 7:
            tr = rb.time_range((0, 0, 0), (23, 59, 59), filter=dayf)
            g = rb.condition()
            rb.link(a, "output", g, "trigger")
            rb.link(tr, "output", g, "condition")
            _chain(rb, g, "met", list(writes))
        else:
            _chain(rb, a, "output", list(writes))
    eff = "%02d:%02d 开，%02d:%02d 关" % (on_hms[0], on_hms[1], off_hms[0], off_hms[1])
    if len(days) < 7:
        eff += "（只在 %s）" % "、".join(days)
    return _finish(rb, rule_id, name, ["定时"],
                   _resolve_note(note, "time-schedule", name, _names(list(on_writes), list(off_writes)), eff))


def build_max_on_rule(rule_id, devices, minutes=120, name=None, note=None):
    """开着太久自动关：每个设备（灯、插座、开关一路）开了 minutes 分钟还开着就关。手动开的、定时开的都管。
    用延时卡：重新开会重新计时；到点先确认还开着再关。卧室和起夜不要用（用户定的：卧室不做定时关）。"""
    if not devices:
        raise ValueError("需要至少一个设备")
    rb = RuleBuilder(node_prefix="mo" + str(rule_id)[-6:])
    for d in devices:
        pw = d["power"]
        t = rb.trigger_device(d["did"], d["urn"], pw["siid"], pw["piid"], "boolean", "=", True, preload=False)
        dl = rb.delay(int(minutes) * 60000)
        rb.link(t, "output", dl, "input")
        chk = _is_on(rb, d)
        rb.link(dl, "output", chk, "input")
        _chain(rb, chk, "output", [_power(d, False)])
    name = name or "开着太久自动关"
    return _finish(rb, rule_id, name, ["保底"],
                   _resolve_note(note, "max-on", name, _names(list(devices)), "开了 %d 分钟还开着就关" % minutes))


LOW_BATTERY_VAR = "VlowBatt001"      # 最近一次低电量的设备名，体检时读出来告诉客户


def low_battery_var_definition():
    return LOW_BATTERY_VAR, {"type": "string", "value": "", "userData": {"name": "低电量设备"}}


def build_low_battery_rule(rule_id, sensors, threshold=20, speaker=None, name="传感器低电量提醒", note=None):
    """低电量提醒（自动化）：任一电池设备的电量低于 threshold → 「低电量设备」变量记下设备名 →（有小爱）播报「XX 电量低，请换电池」。
    sensors[i] = {"did","urn","siid","piid","name"}：电量属性（battery-level），按 spec 核对。
    没有音箱时只记变量，AI 下次读设备或体检时告诉客户。"""
    if not sensors:
        raise ValueError("需要至少一个电池设备")
    rb = RuleBuilder(node_prefix="lb" + str(rule_id)[-6:])
    rb.declare_external_var(LOW_BATTERY_VAR)
    for s in sensors:
        t = rb.trigger_device(s["did"], s["urn"], s["siid"], s["piid"], "int", "<", threshold, preload=False)
        label = s.get("name") or "传感器"
        sv = rb.set_var(LOW_BATTERY_VAR, label)
        rb.link(t, "output", sv, "input")
        if speaker:
            _chain(rb, sv, "output", [speaker_text(speaker, "%s电量低，请换电池" % label)])
    eff = "电量低于 %d%% 记下设备名%s" % (threshold, "，小爱播报" if speaker else "")
    return _finish(rb, rule_id, name, ["保底", "提醒"],
                   _resolve_note(note, "low-battery", name, _names(list(sensors), speaker or {}), eff))


def build_device_notify_rule(rule_id, trigger, speaker, text, volume=None, name=None, note=None):
    """设备状态 → 小爱播报（洗衣机洗好了、漏水、燃气、烟雾报警）。
    trigger：事件 {"did","urn","siid","eiid"} 或属性 {"did","urn","siid","piid","dtype","operator","v1"}，按 spec 核对，
    例如洗衣机「运行状态 = 完成」、水浸传感器「有水 = true」。报警类建议 volume=80 以上。
    只播报、不控制设备：关水阀、关燃气阀要客户明确要求才另做。"""
    rb = RuleBuilder(node_prefix="dn" + str(rule_id)[-6:])
    src, port = _event_or_state(rb, trigger), "output"
    writes = []
    if volume is not None:
        v = speaker.get("volume") or {"siid": 2, "piid": 1}
        writes.append({"did": speaker["did"], "urn": speaker["urn"], "siid": v["siid"], "piid": v["piid"], "value": volume})
    writes.append(speaker_text(speaker, text))
    _chain(rb, src, port, writes)
    name = name or "%s-小爱播报" % (trigger.get("name") or "设备")
    return _finish(rb, rule_id, name, ["提醒"],
                   _resolve_note(note, "device-notify", name, _names(trigger, speaker), "小爱说：" + text))


def device_write(device, siid, piid, value, name=None):
    """场景里顺带控制一台设备（关空调、窗帘关上……）的一次属性写入，放进 writes / extra_writes。"""
    return {"did": device["did"], "urn": device["urn"], "siid": siid, "piid": piid, "value": value,
            "name": name or device.get("name")}
