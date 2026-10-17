# -*- coding: utf-8 -*-
"""检查设备台账里的命名是否能让 AI 看懂（第 0 步）。只读，不改台账。

用法：python naming_check.py 设备台账.json
检查：未分房间、出厂默认名、同房间重名、多键开关缺键名、未确认条目。
"""
import json
import re
import sys
from collections import Counter

GENERIC_KEYS = {"左键", "中键", "右键", "按键1", "按键2", "按键3", "按键4", "键1", "键2", "键3"}
DEFAULT_ROOMS = {"", "默认房间", "未分配", "Default Room"}
FACTORY_WORDS = re.compile(r"米家|小米|Xiaomi|Mijia|Aqara|智能开关|智能插座|无线开关|传感器|网关")
MODEL_LIKE = re.compile(r"[A-Za-z]+[-.][A-Za-z0-9]+|\d{3,}")
PLACE_WORDS = re.compile(r"客厅|卧|厨|卫|浴|餐|书房|玄关|门厅|入户|阳台|走廊|过道|楼梯|衣帽|洗衣|儿童|老人|茶室|影音|车库|花园|露台")


def looks_factory(name, room):
    """型号样式一律算出厂名；品牌/品类词只在名字里看不出位置时才算。"""
    if MODEL_LIKE.search(name):
        return True
    has_place = bool(PLACE_WORDS.search(name)) or bool(room and room in name)
    return bool(FACTORY_WORDS.search(name)) and not has_place


def check(registry):
    issues = []
    devices = registry.get("devices", [])
    pairs = Counter((d.get("room"), d.get("name")) for d in devices if d.get("name"))
    for d in devices:
        did, name, room = d.get("did"), d.get("name") or "", d.get("room") or ""
        tag = "%s（%s）" % (name or "未命名", did)
        if d.get("status") != "confirmed":
            issues.append((tag, "名称和房间还没确认"))
        if not name:
            issues.append((tag, "没有设备名"))
        elif looks_factory(name, room):
            issues.append((tag, "看起来是出厂名，请改成「位置+用途」，如 客厅主灯、卫生间人在传感器"))
        if room in DEFAULT_ROOMS:
            issues.append((tag, "没有分房间"))
        if name and pairs[(d.get("room"), name)] > 1:
            issues.append((tag, "同一房间里有重名"))
        urn_type = ((d.get("urn") or "").split(":") + [""] * 4)[3]
        is_switch = urn_type == "switch" or (not urn_type and "switch" in (d.get("model") or ""))
        if is_switch and not d.get("channels"):
            issues.append((tag, "开关的每个键还没有名字：接普通灯用灯名，无线键用位置名（MijiaFlow 读不到键名，问用户后用 device_registry.py --set 补上）"))
        generic = [c for c in d.get("channels", []) if c in GENERIC_KEYS]
        if generic:
            issues.append((tag, "键名 %s 只说明了位置：接普通灯的键改成灯名，无线键写明位置和用途" % "、".join(generic)))
    return issues


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # 非中文 Windows 控制台
    except Exception:
        pass
    if len(sys.argv) != 2:
        sys.exit("用法：python naming_check.py 设备台账.json")
    with open(sys.argv[1], encoding="utf-8") as f:
        registry = json.load(f)
    issues = check(registry)
    total = len(registry.get("devices", []))
    if not issues:
        print("%d 台设备命名检查通过" % total)
        return
    print("%d 台设备，发现 %d 个命名问题：" % (total, len(issues)))
    for tag, msg in issues:
        print("- %s：%s" % (tag, msg))
    sys.exit(1)


if __name__ == "__main__":
    main()
