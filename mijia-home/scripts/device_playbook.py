# -*- coding: utf-8 -*-
"""灯以外的设备在基础场景里该做什么（常见设备对照表）。

每一项是一个「顺带动作」，挂在某个场景下面，给客户单独勾选：
  scene    挂在哪个场景：离家、回家、全屋睡眠、起床、观影（客厅）、离开<区域>
  say      给客户看的一句话
  default  True = 清单里默认推荐（客户仍可不勾）；False = 列出来，客户想要才勾
  how      AI 怎么查属性、写什么值（按设备型号的 MIoT spec 核对，查不到就问客户，不猜）

安全类设备（SAFETY）只读状态、只提醒，不放进自动控制；客户明确要求时才按 references/devices.md 的做法另做。
表里没有的设备类型：AI 查 spec，一句话告诉客户它能做什么，再问一次要不要放进哪个场景。
"""

# urn 第 4 段的设备类型 → 类别（补充 home_report.URN_TYPES）
EXTRA_URN_TYPES = {
    "television": "电视", "tv-box": "电视", "projector": "电视",
    "fan": "风扇", "air-purifier": "空气净化器", "air-fresh": "新风", "humidifier": "加湿器",
    "dehumidifier": "除湿机", "vacuum": "扫地机", "water-heater": "热水器", "heater": "取暖器",
    "bath-heater": "浴霸", "washer": "洗衣机", "dryer": "烘干机", "dishwasher": "洗碗机",
    "camera": "摄像头", "airer": "晾衣架", "refrigerator": "冰箱", "kettle": "电热水壶",
    "gas-sensor": "燃气传感器", "smoke-sensor": "烟雾传感器", "submersion-sensor": "水浸传感器",
    "flood-sensor": "水浸传感器", "valve": "水阀", "water-valve": "水阀", "gas-valve": "燃气阀",
    "towel-rack": "毛巾架", "floor-heating": "地暖", "electric-blanket": "电热毯",
}
EXTRA_MODEL_HINTS = [
    ("tv", "电视"), ("fan", "风扇"), ("airpurifier", "空气净化器"), ("airp", "空气净化器"),
    ("airfresh", "新风"), ("humidifier", "加湿器"), ("derh", "除湿机"), ("vacuum", "扫地机"),
    ("waterheater", "热水器"), ("heater", "取暖器"), ("bhf", "浴霸"), ("washer", "洗衣机"),
    ("dishwasher", "洗碗机"), ("camera", "摄像头"), ("airer", "晾衣架"), ("fridge", "冰箱"),
    ("gas", "燃气传感器"), ("smoke", "烟雾传感器"), ("flood", "水浸传感器"), ("valve", "水阀"),
]

# 只读状态、只提醒，不放进自动控制
SAFETY = ("燃气传感器", "烟雾传感器", "水浸传感器", "水阀", "燃气阀", "门锁", "取暖器", "浴霸", "热水器",
          "电热毯", "地暖", "电热水壶", "冰箱")
# 不需要放进场景的（本身就是场景的一部分，或者只当触发条件用）
NOT_IN_SCENES = ("灯", "开关", "无线按键", "人在传感器", "人体传感器", "门窗传感器", "光照传感器",
                 "温湿度传感器", "网关", "音箱", "窗帘", "插座")

P_ON = "找 spec 里的开关属性（on / switch-status），写 false"
P_OFF_ON = "找 spec 里的开关属性（on），写 true"

PLAYBOOK = {
    "空调": [
        ("离家", "离家时关空调", True, P_ON),
        ("全屋睡眠", "睡觉时卧室外的空调关掉，卧室的切到睡眠模式", True,
         "非卧室的写 on=false；卧室的找 mode 或 sleep-mode 属性，取「睡眠」那个值，没有就不动"),
        ("回家", "回家时空调先开起来（用上次的温度和模式）", False, P_OFF_ON),
        ("离开<区域>", "离开{area}时关掉{area}的空调", False, P_ON),
    ],
    "电视": [
        ("离家", "离家时关电视", True, P_ON + "；很多电视只能关不能开，开机不放进场景"),
        ("全屋睡眠", "睡觉时关电视", True, P_ON),
    ],
    "风扇": [
        ("离家", "离家时关风扇", True, P_ON),
    ],
    "空气净化器": [
        ("全屋睡眠", "睡觉时净化器切到睡眠模式，安静不亮灯", True, "找 mode 属性，取「睡眠」那个值"),
        ("回家", "回家时净化器开起来", False, P_OFF_ON),
    ],
    "新风": [
        ("全屋睡眠", "睡觉时新风调到最低档或睡眠模式", True, "找 mode 或 fan-level 属性，取「睡眠」或最低档"),
        ("离家", "离家时新风调到最低档", False, "找 fan-level 属性，取最低档"),
    ],
    "加湿器": [
        ("离家", "离家时关加湿器", True, P_ON),
    ],
    "除湿机": [
        ("离家", "离家时关除湿机", False, P_ON + "；梅雨天客户可能想一直开着，先问"),
    ],
    "扫地机": [
        ("离家", "离家时扫地机开始打扫", False, "找 start-sweep 这类动作（aiid）调用；每天只扫一次的话问客户"),
        ("回家", "回家时扫地机回去充电", False, "找 start-charge / 回充 动作调用"),
    ],
    "摄像头": [
        ("离家", "离家时摄像头打开看家", False, "找 on 或隐私模式（privacy）属性：开摄像头、关隐私"),
        ("回家", "回家时摄像头进隐私模式，不录家里人", False, "找隐私模式属性，写开"),
    ],
    "晾衣架": [
        ("全屋睡眠", "睡觉时关掉晾衣架的灯", False, "找 light 服务的 on 属性，写 false"),
    ],
}
# 窗帘、插座在场景选项里已有，这里只补「观影关窗帘」和「离家关插座」
PLAYBOOK["窗帘"] = [
    ("观影", "观影时客厅窗帘关上", True, "窗帘的 motor-control 写关，或 target-position 写 0（按 spec）"),
    ("全屋睡眠", "睡觉时窗帘关上", True, "同上"),
]
PLAYBOOK["插座"] = [
    ("离家", "离家时关掉客户点名的插座（饮水机、电视插座……），冰箱、路由器的插座不关", False, P_ON),
]

# 单独成项的自动化（设备 + 小爱）
REMINDERS = {
    "洗衣机": "洗衣机洗好了，小爱提醒晾衣服",
    "烘干机": "烘干机烘好了，小爱提醒收衣服",
    "洗碗机": "洗碗机洗好了，小爱提醒",
}
ALARMS = {
    "燃气传感器": "检测到燃气泄漏，小爱大声报警",
    "烟雾传感器": "检测到烟雾，小爱大声报警",
    "水浸传感器": "检测到漏水，小爱报警",
}


def actions_for(category, scene):
    """这个类别的设备在 scene 下的顺带动作 [(say, default, how)]。"""
    out = []
    for sc, say, default, how in PLAYBOOK.get(category, []):
        if sc == scene:
            out.append((say, default, how))
    return out
