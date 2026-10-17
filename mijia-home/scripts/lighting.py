# -*- coding: utf-8 -*-
"""灯光：看懂每盏灯的角色，按区域模式决定开哪些、亮度色温多少。

客户写的是灯具名（吸顶灯、天花灯带、电视灯带、床头吊灯…）。一个名字 = 位置 + 灯具类型，
角色要两者一起看：同样是吊灯，客厅吊灯是主灯，床头吊灯是补光，餐厅吊灯是就餐的重点光。

依据（详见 references/lighting.md）：太阳一天的色温亮度变化、GB 50034-2013（长期停留房间 LED ≤4000K）、
Kruithof 曲线（暗光配暖光）、Brown 等 2022（睡前要暗要暖）、分层照明（基础/重点/功能/氛围）。
百分比是灯的输出，不等于照度；装好后按房间实际亮度微调。
"""

# ---------- 角色 ----------
ROLES = ["主灯", "基础", "重点", "氛围", "柜体", "补光", "通行"]
ROLE_DESC = {
    "主灯": "一开满屋亮、最硬的光（吸顶灯、客厅吊灯、大灯、泛光灯）",
    "基础": "没有主灯时把房间照匀（筒灯、面板灯）",
    "重点": "照墙面、窗帘、画、餐桌，出层次（射灯、轨道灯、格栅灯、洗墙灯、窗帘筒灯、餐厅吊灯）",
    "氛围": "间接柔光，最舒服（天花灯带、电视灯带、沙发灯带、床头灯带、灯槽）",
    "柜体": "柜子里的光（鞋柜、餐边柜、吧台、酒柜灯带）",
    "补光": "靠近人、局部做事的光（床头吊灯、床头灯、台灯、落地灯、阅读灯、镜前灯、橱柜筒灯）",
    "通行": "走动用或交给传感器（过道筒灯、过道灯带、玄关筒灯、地脚灯、小夜灯、感应灯）",
}
LAYERS = ROLES  # 兼容 2.0.5

POS_NEAR = ("床头", "书桌", "梳妆", "镜前", "阅读", "床边", "工作台")
POS_PASS = ("过道", "走廊", "玄关", "楼梯", "门口", "入户", "通道")
POS_CABINET = ("鞋柜", "餐边柜", "吧台", "酒柜", "展示柜", "衣柜", "书柜", "橱柜", "柜内", "柜")
POS_DINING = ("餐厅", "餐桌", "吧台", "岛台")
POS_WASH = ("窗帘", "窗户", "窗边", "画", "墙面", "洗墙")

F_MAIN = ("吸顶", "主灯", "大灯", "泛光", "水晶灯", "顶灯")
F_PENDANT = ("吊灯",)
F_DOWN = ("筒灯", "面板灯", "灯盘", "天花灯")
F_ACCENT = ("射灯", "轨道", "磁吸", "格栅", "洗墙", "画灯", "展示灯")
F_STRIP = ("灯带", "灯槽", "线条灯", "灯条")
F_TASK = ("台灯", "落地灯", "床头灯", "阅读灯", "镜前灯", "壁灯", "书桌灯", "柜下灯")
F_NIGHT = ("小夜灯", "夜灯", "地脚灯", "脚灯")


def _has(name, words):
    return any(w in name for w in words)


def classify_role(name):
    """按「位置 + 灯具类型」判断角色，返回 (角色, 依据)；判断不出返回 (None, "")。
    名字里有「感应」的归通行，依据里写「交给传感器」，场景不碰它。"""
    n = name or ""
    if "感应" in n:
        return "通行", "感应灯，交给传感器"
    if _has(n, F_NIGHT):
        return "通行", "夜灯/地脚灯"
    if _has(n, F_STRIP):
        if _has(n, POS_CABINET):
            return "柜体", "柜子 + 灯带"
        if _has(n, POS_PASS):
            return "通行", "过道 + 灯带"
        return "氛围", "灯带"
    if _has(n, F_TASK):
        return "补光", "台灯/落地灯/床头灯类"
    if _has(n, F_ACCENT):
        return "重点", "射灯/轨道/格栅类"
    if _has(n, F_PENDANT):
        if _has(n, POS_NEAR):
            return "补光", "床头/书桌 + 吊灯"
        if _has(n, POS_DINING):
            return "重点", "餐桌/吧台 + 吊灯"
        return "主灯", "吊灯"
    if _has(n, F_DOWN):
        if _has(n, POS_CABINET):
            return "补光", "柜子 + 筒灯"
        if _has(n, POS_PASS):
            return "通行", "过道/玄关 + 筒灯"
        if _has(n, POS_WASH):
            return "重点", "窗帘/墙面 + 筒灯（洗墙）"
        return "基础", "筒灯"
    if _has(n, F_MAIN):
        return "主灯", "吸顶/主灯/泛光"
    return None, ""


def classify_layer(name):
    """兼容 2.0.5：只返回角色。"""
    return classify_role(name)[0]


def is_sensor_owned(name):
    return "感应" in (name or "")


# ---------- 区域模式 ----------
# 调光调色灯的亮度色温；ct=None 表示用灯能调到的最低色温
MODE_TUNABLE = {
    "明亮": {"brightness": 100, "ct": 4000},
    "休闲": {"brightness": 70, "ct": 3500},
    "温馨": {"brightness": 40, "ct": 3000},
    "放松": {"brightness": 20, "ct": 2700},
    "休憩": {"brightness": 8, "ct": None},
    "观影": {"brightness": 15, "ct": 2700},
    "就餐": {"brightness": 80, "ct": 3000},
    "起夜": {"brightness": 100, "ct": 4000},
}
MOOD_TUNABLE = MODE_TUNABLE  # 兼容 2.0.5
MOODS = ["明亮", "休闲", "温馨", "放松", "休憩"]
WORK_ROOMS = ("厨房", "书房", "工作间")
WORK_BRIGHT_CT = 5000

# 每个模式下各角色怎么开：True 开 / False 关 / "按需"（默认关，客户点名才开）/ "一路"（只留一盏）
_ALL_ON = {r: True for r in ROLES}
_ALL_OFF = {r: False for r in ROLES}
MODE_ROLES = {
    "明亮": dict(_ALL_ON),
    "休闲": {"主灯": False, "基础": True, "重点": True, "氛围": True, "柜体": True, "补光": "按需", "通行": True},
    "温馨": {"主灯": False, "基础": False, "重点": True, "氛围": True, "柜体": True, "补光": True, "通行": False},
    "放松": {"主灯": False, "基础": False, "重点": False, "氛围": True, "柜体": False, "补光": "一路", "通行": False},
    "休憩": {"主灯": False, "基础": False, "重点": False, "氛围": "一路", "柜体": False, "补光": False, "通行": False},
    "观影": {"主灯": False, "基础": False, "重点": False, "氛围": True, "柜体": False, "补光": False, "通行": False},
    "就餐": {"主灯": False, "基础": True, "重点": True, "氛围": True, "柜体": True, "补光": False, "通行": False},
    "睡眠": dict(_ALL_OFF),
    "离开": dict(_ALL_OFF),
}

# 从暗到亮（上下键调亮调暗按这个顺序切模式）
BRIGHTNESS_ORDER = ["休憩", "放松", "温馨", "休闲", "明亮"]

# 给客户看的一句话效果（场景选项清单用）
MODE_SAY = {
    "明亮": "最亮，适合打扫、找东西、来客人",
    "休闲": "不开主灯，光线柔和，平时待着不刺眼",
    "温馨": "主灯不开，只留氛围光和局部光，暖",
    "放松": "很暗很暖，适合躺着休息",
    "休憩": "只留一路最暗的暖光，像烛光，适合睡前",
    "观影": "只留背景光，暗，屏幕上没有反光",
    "就餐": "餐桌那块最亮，菜看起来好吃",
    "睡眠": "这个房间的灯全关，之后按床头键是起夜灯",
    "离开": "这个区域的灯全关",
}

# 每个区域可用的模式（AI 可按客户的房间增减）
AREA_MODES = [
    (("客厅", "起居"), ["明亮", "休闲", "温馨", "放松", "休憩", "观影", "离开"]),
    (("餐厅", "饭厅"), ["就餐", "明亮", "休闲", "温馨", "离开"]),
    (("卧", "老人房", "儿童房", "客房"), ["明亮", "休闲", "温馨", "放松", "休憩", "睡眠", "离开"]),
]
# 不单独设模式、跟随全屋的区域
FOLLOW_HOME_AREAS = ("过道", "走廊", "玄关", "卫生间", "卫", "浴", "厨房", "阳台", "楼梯", "衣帽间", "储物", "洗衣")


def modes_for_area(area):
    """区域可用的模式列表；跟随全屋的区域返回 []；其他房间（书房、茶室等）给一组基本模式。"""
    a = area or ""
    for words, modes in AREA_MODES:
        if any(w in a for w in words):
            return list(modes)
    if any(w in a for w in FOLLOW_HOME_AREAS):
        return []
    return ["明亮", "休闲", "温馨", "离开"]


def clamp_ct(ct, ct_range=None):
    """色温超出灯的范围时取最接近的值；ct=None 取范围下限，没有范围就用 2700K。"""
    lo, hi = (ct_range or (2700, 6500))
    if ct is None:
        return lo
    return max(lo, min(hi, ct))


def tunable_values(mode, room="", ct_range=None):
    """调光调色灯在某模式下的 {"brightness","ct"}，已按灯的色温范围夹好。"""
    if mode not in MODE_TUNABLE:
        raise ValueError("模式「%s」没有调光默认值（可选 %s）" % (mode, "、".join(MODE_TUNABLE)))
    v = MODE_TUNABLE[mode]
    ct = v["ct"]
    if mode == "明亮" and any(w in (room or "") for w in WORK_ROOMS):
        ct = WORK_BRIGHT_CT
    return {"brightness": v["brightness"], "ct": clamp_ct(ct, ct_range)}


# 家庭模式 → 跟随全屋的区域（过道、卫生间等）里新开的调光灯用哪个模式的亮度色温。
# 离家、全屋睡眠不改灯（全屋睡眠时开灯多半是起夜）。
MODE_TO_MOOD = {"在家": "休闲", "起床": "明亮", "访客": "明亮"}


def light_follow_table(mode_to_mood=None, ct_range=None):
    m2m = mode_to_mood or MODE_TO_MOOD
    return {mode: tunable_values(mood, ct_range=ct_range) for mode, mood in m2m.items()}


def area_follow_table(area, ct_range=None):
    """区域灯光跟随表：{区域模式: {"brightness","ct"}}，只含有调光默认值、且该模式下会开灯的模式。"""
    out = {}
    for m in modes_for_area(area):
        if m in MODE_TUNABLE:
            out[m] = tunable_values(m, area, ct_range)
    return out


def light_role(lt):
    return lt.get("role") or lt.get("layer") or classify_role(lt.get("name"))[0]


def plan_lights(mode, lights, keep=None):
    """某模式下每盏灯开还是关（调光灯和普通灯一起算）。
    lights=[{"name": "客厅筒灯", ...}]，可带 "role" 覆盖自动判断；名字带「感应」的灯不参与（交给传感器）。
    keep=客户点名要开的灯名（一个或一组）：任何模式下都开；「一路」只开 keep 里的，不给就取该角色第一盏。
    返回 (on, off, unknown)。"""
    if mode not in MODE_ROLES:
        raise ValueError("未知模式：%s（可选 %s）" % (mode, "、".join(MODE_ROLES)))
    rule = MODE_ROLES[mode]
    keep = set([keep] if isinstance(keep, str) else (keep or []))
    on, off, unknown, picked = [], [], [], set()
    for lt in lights:
        if is_sensor_owned(lt.get("name")) and not lt.get("role"):
            continue
        role = light_role(lt)
        if role is None:
            unknown.append(lt)
            continue
        how = rule[role]
        name = lt.get("name")
        if name in keep:
            ok = True
        elif how is True or how is False:
            ok = how
        elif how == "按需":
            ok = False
        else:  # 一路
            ok = (name in keep) if keep else role not in picked
            if ok:
                picked.add(role)
        (on if ok else off).append(lt)
    return on, off, unknown


def plain_plan(mood, plain_lights, keep=None):
    """兼容 2.0.5。"""
    return plan_lights(mood, plain_lights, keep)
