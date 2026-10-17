# -*- coding: utf-8 -*-
"""米家自动化极客版 规则生成工具库（开源向，辅助 AI/人快速编写可导入规则）。

设计目标：业务脚本只声明「节点 + 连线」，平台硬约束与易错点由本库统一兜住——
  · varGet / varChange 仅支持 operator "="（用 "≠" 须改取 output2「否则」分支）
  · 全局变量 ID 必须 11 位纯字母数字（含下划线等会被平台静默丢弃）
  · 链路完整性（非触发节点须有入边、非终端节点须有出边、连线端口存在）
  · 变量引用闭合（被引用的变量必须已 define_var 定义）

典型用法：
    from mijia_rule_kit import RuleBuilder, merge_import_set, dump_json
    rb = RuleBuilder()
    rb.define_var("VtdSegm3kQ7", "string", "深夜", "时间段")
    t = rb.trigger_device(did, urn, 2, 1, "int", "=", 1)
    c = rb.cond_var("VtdSegm3kQ7", "夜间")          # varGet，operator 恒为 "="
    rb.link(t, "output", c, "input")
    ...
    rb.validate(raise_on_error=True)
    rule = rb.build_rule("1781250000001", "书房-自动化", ["灯光自动化"])

寻址/打包：did 取自真实备份、piid 用 miot-spec.org 查（见 references/rule-kit.md）；
打包成 .bak 用 pack_bak() 或 scripts/bak-pack.ps1（见 references/backup.md）。
"""
import json, re, struct, zlib, hashlib, time, os, shutil


def now_millis():
    """当前时间（epoch 毫秒，13 位整数，与平台 lastUpdateTime/规则ID 同格式）。"""
    return int(time.time() * 1000)


def load_device_registry(path):
    """读取由 device_registry.py 生成的设备台账。"""
    with open(path, "r", encoding="utf-8") as f:
        registry = json.load(f)
    if registry.get("schemaVersion") not in {1, 2} or not isinstance(registry.get("devices"), list):
        raise ValueError("无效设备台账：需要 schemaVersion=1 或 2 和 devices 列表")
    return registry


def resolve_confirmed_device(registry, name, room=None, channel=None):
    """按已确认的名称/房间/通道返回唯一设备；歧义或未确认均拒绝生成规则。"""
    candidates = []
    for device in registry.get("devices", []):
        if device.get("status") != "confirmed" or device.get("name") != name:
            continue
        if room is not None and device.get("room") != room:
            continue
        if channel is not None and channel not in device.get("channels", []):
            continue
        candidates.append(device)
    if len(candidates) != 1:
        scope = " / ".join(x for x in (name, room, channel) if x)
        raise ValueError("设备台账中没有唯一已确认条目：%s" % scope)
    device = candidates[0]
    if not device.get("did") or not device.get("urn"):
        raise ValueError("已确认设备缺少 did 或 urn：%s" % name)
    return device


def stamp_update_time(rules, millis=None):
    """把每条规则的 cfg.userData.lastUpdateTime 盖成同一时间戳（默认当前），让导入后列表"编辑于"统一刷新。
    原地修改并返回 rules。用于打包导入集前统一盖章（含从既有 JSON 载入、未经 build_rule 的规则）。"""
    ts = int(millis or now_millis())
    for r in rules:
        r.setdefault("cfg", {}).setdefault("userData", {})["lastUpdateTime"] = ts
    return rules

# 节点分类（校验用）
_TRIGGER_TYPES = {"deviceInput", "varChange", "alarmClock", "onLoad", "timeRange"}
_TERMINAL_TYPES = {"deviceOutput"}
_VAR_NODE_TYPES = {"varGet", "varChange"}          # 仅支持 operator "="
# 可作终端（无出边合法）的节点：动作类与变量赋值类（赋值后可无下游，仅供别处读取）
_TERMINAL_OK = {"deviceOutput", "varSetString", "varSetNumber"}
_VAR_ID_RE = re.compile(r"^[A-Za-z0-9]{11}$")       # 全局变量 ID 格式


class RuleBuilder:
    """单条规则的节点图构造器。节点按创建顺序编号 b001、b002……（确定性，便于回归比对）。"""

    def __init__(self, node_prefix="b"):
        self.nodes = []          # 节点列表
        self.edges = []          # (src_id, src_port, dst_id, dst_port)
        self.var_defs = {}       # {var_id: (scope, {type,value,userData})}，scope="global" 或 "R<规则ID>"
        self.band = {}           # {node_id: 意图分组序号}，auto_layout 据此把不同意图簇上下拉开
        self._seq = 0
        self._prefix = node_prefix

    # ---------- 内部 ----------
    def _nid(self):
        self._seq += 1
        return "%s%03d" % (self._prefix, self._seq)

    def _add(self, typ, version, inputs, outputs, props, urn=None, x=0, y=0):
        _id = self._nid()
        cfg = {"pos": {"x": x, "y": y, "width": 320, "height": 130}, "name": typ, "version": version}
        if urn:
            cfg["urn"] = urn
        self.nodes.append({"id": _id, "type": typ, "cfg": cfg, "inputs": inputs, "outputs": outputs, "props": props})
        return _id

    # ---------- 触发器（inputs 为空，纯触发）----------
    def on_load(self, x=0, y=0):
        """规则加载/启用时触发（可用于变量兜底初始化）。"""
        return self._add("onLoad", 1, {}, {"output": []}, {}, None, x, y)

    def trigger_device(self, did, urn, siid, piid, dtype, operator, v1, preload=False, x=0, y=0):
        """设备状态变化触发。设备节点支持全套 operator：= != < > <= >= include。"""
        return self._add("deviceInput", 0, {}, {"output": []},
                         {"did": did, "siid": siid, "piid": piid, "preload": preload, "dtype": dtype,
                          "operator": operator, "v1": v1}, urn, x, y)

    def trigger_event(self, did, urn, siid, eiid, arguments=None, x=0, y=0):
        """设备事件触发（按键单击/双击/长按、门锁开门等，按 eiid 寻址）。
        arguments 可选：事件参数过滤 [{"piid":1,"dtype":"string","operator":"=","v1":"..."}]。
        形状取自真机备份（2025-05）：props={did,siid,eiid,arguments}，cfg.version=1。"""
        props = {"did": did, "siid": siid, "eiid": eiid}
        if arguments:
            props["arguments"] = list(arguments)
        return self._add("deviceInput", 1, {}, {"output": []}, props, urn, x, y)

    def trigger_virtual_event(self, hub_did, hub_urn, name, siid=4, eiid=1, x=0, y=0):
        """监听中枢网关「虚拟事件」（跨规则调用场景）。xiaomi-hub1 实测 siid4/eiid1，参数 piid1=事件名；
        其他网关型号须先查 spec 或已有备份确认 siid/eiid。"""
        return self.trigger_event(hub_did, hub_urn, siid, eiid,
                                  [{"dtype": "string", "piid": 1, "operator": "=", "v1": name}], x, y)

    def trigger_var(self, var_id, value, var_type="string", preload=True, scope="global", x=0, y=0):
        """变量变为指定值时触发（varChange）。operator 恒为 "="（平台仅支持）。"""
        return self._add("varChange", 1, {}, {"output": []},
                         {"preload": preload, "id": var_id, "scope": scope, "varType": var_type,
                          "operator": "=", "v1": value}, None, x, y)

    def time_range(self, start_hms, end_hms, filter=None, x=0, y=0):
        """时间段（纯触发，无输入口）。作被动条件须接 condition.condition 槽。start/end=(h,m,s)。
        filter 可选：{"inHoliday": False}=仅法定工作日生效 / {"inHoliday": True}=仅法定节假日 /
        {"day":[1-6,0]}=指定周几（真机样本证实 timeRange 卡认 inHoliday，2026-06-20）。"""
        sh, sm, ss = start_hms
        eh, em, es = end_hms
        return self._add("timeRange", 0, {}, {"output": []},
                         {"start": {"hour": sh, "minute": sm, "second": ss},
                          "end": {"hour": eh, "minute": em, "second": es}, "filter": dict(filter or {}), "mingTextShow": False}, None, x, y)

    def alarm_periodic(self, hour, minute, second=0, days=None, in_holiday=None, x=0, y=0):
        """每日定时触发。⚠️ days/in_holiday 这两个 filter **alarmClock 卡不认**（2026-06-20 实测：
        inHoliday:false 仍每天照响）——要「法定工作日/节假日」过滤请改用 `workday_gate()`（timeRange 卡承载）。
        本方法保留 filter 参数仅为兼容；正常用法是不传过滤、每天触发。"""
        if days:
            flt = {"day": list(days)}
        elif in_holiday is not None:
            flt = {"inHoliday": in_holiday}
        else:
            flt = {}
        n = self._add("alarmClock", 1, {}, {"output": []},
                      {"type": "periodicAlarm", "isSunset": False, "hour": hour, "minute": minute, "second": second, "filter": flt}, None, x, y)
        self.nodes[-1]["cfg"]["happenType"] = "now"
        self.nodes[-1]["cfg"]["tempOffset"] = 0
        return n

    def workday_gate(self, hour, minute, second=0):
        """法定工作日定时门。返回 (alarm, time_range, condition) 三节点 ID。
        机制：alarmClock 每天 hh:mm:ss 触发 → 喂 condition.trigger；全天 timeRange(00:00:00~23:59:59,
        filter inHoliday:false) → 喂 condition.condition，当天若是法定工作日则「在区间」→ met，否则 unmet。
        ⚠️ 不在 alarmClock 上挂 inHoliday（那个 filter alarmClock 不认，会每天照响）——工作日判定由
        timeRange 卡承载（真机样本实证 timeRange filter inHoliday:false=法定工作日，含调休补班、排法定假）。
        调用方：把 condition 'met' 接下游、把三节点 set_band；可继续串「上学模式」等总闸。"""
        alarm = self.alarm_periodic(hour, minute, second)
        tr = self.time_range((0, 0, 0), (23, 59, 59), filter={"inHoliday": False})
        gate = self.condition()
        self.link(alarm, "output", gate, "trigger")
        self.link(tr, "output", gate, "condition")
        return alarm, tr, gate

    def alarm_sun(self, is_sunset, offset_min, latitude, longitude, x=0, y=0):
        """日出(is_sunset=False)/日落(True)触发，offset_min 分钟偏移（可负）。"""
        n = self._add("alarmClock", 1, {}, {"output": []},
                      {"type": "sunset", "isSunset": is_sunset, "offset": offset_min,
                       "latitude": latitude, "longitude": longitude, "filter": {}}, None, x, y)
        self.nodes[-1]["cfg"]["happenType"] = "now"
        self.nodes[-1]["cfg"]["tempOffset"] = 0
        return n

    # ---------- 条件（input → output 成立 / output2 否则）----------
    def cond_device(self, did, urn, siid, piid, dtype, operator, v1, x=0, y=0):
        """查设备当前状态作条件。设备节点支持全套 operator。"""
        return self._add("deviceGet", 0, {"input": None}, {"output": [], "output2": []},
                         {"did": did, "siid": siid, "piid": piid, "dtype": dtype, "operator": operator, "v1": v1}, urn, x, y)

    def cond_var(self, var_id, value, var_type="string", scope="global", x=0, y=0):
        """查变量值作条件（varGet）。operator 恒为 "="；"≠某值" 请取本节点 output2「否则」分支。"""
        return self._add("varGet", 1, {"input": None}, {"output": [], "output2": []},
                         {"id": var_id, "scope": scope, "varType": var_type, "operator": "=", "v1": value}, None, x, y)

    # ---------- 流程 ----------
    def delay(self, ms, x=0, y=0):
        """延时（防抖：重触发则重置）。运行值在 props.timeout(毫秒)，UI 显示在 cfg.value+cfg.unit。"""
        _id = self._add("delay", 0, {"input": None}, {"output": []}, {"timeout": ms}, None, x, y)
        # UI 显示用 cfg.value + cfg.unit（实测：缺则延时卡时间/单位空白）。用秒，单位字符串 "s" 已证合法
        node = self.nodes[-1]
        node["cfg"]["unit"] = "s"
        node["cfg"]["value"] = ms // 1000 if ms % 1000 == 0 else ms / 1000.0
        return _id

    def condition(self, x=0, y=0):
        """当-如果-就：trigger + condition 输入，met/unmet 输出。常配 timeRange 作被动时段判断。"""
        return self._add("condition", 1, {"trigger": None, "condition": None}, {"met": [], "unmet": []}, {}, None, x, y)

    def status_last(self, ms, x=0, y=0):
        """状态维持了一段时间（statusLast）：input 收到信号后维持 ms 才 output。
        ⚠️ 与 delay 区别：delay 是去抖（重触发即重置计时）；statusLast 量「状态保持时长」。
        用途：实现「区域持续无人 X 秒」——人在传感器Pro 各分区的 p3/p4「有人/无人持续时长」
        MIoT spec 明示【不支持，请使用极客版计时器】，故用本卡。结构同 delay(单in/out+timeout)，version=1。"""
        _id = self._add("statusLast", 1, {"input": None}, {"output": []}, {"timeout": ms}, None, x, y)
        node = self.nodes[-1]
        node["cfg"]["unit"] = "s"
        node["cfg"]["value"] = ms // 1000 if ms % 1000 == 0 else ms / 1000.0
        return _id

    # ---------- 逻辑合并（多路输入 input0..inputN-1 → 单 output）----------
    def signal_or(self, n_inputs=2, x=0, y=0):
        """信号或：任一路信号到达即放行（无 latch，适合把多个按键事件汇成一个入口）。"""
        inputs = {"input%d" % i: None for i in range(n_inputs)}
        return self._add("signalOr", 0, inputs, {"output": []}, {}, None, x, y)

    def logic_and(self, n_inputs=2, x=0, y=0):
        """逻辑与：所有输入路均成立时放行（latch：各路记住最新真假，任一路更新时若全真则触发）。
        合并"有人 AND 时段 AND 照度"等多维条件，比串接长链清爽（旧规则范式）。"""
        inputs = {"input%d" % i: None for i in range(n_inputs)}
        return self._add("logicAnd", 0, inputs, {"output": []}, {}, None, x, y)

    def logic_or(self, n_inputs=2, x=0, y=0):
        """逻辑或：任一输入路成立即放行（latch 同上）。合并"传感器1有人 OR 传感器2有人"等多源同义条件。"""
        inputs = {"input%d" % i: None for i in range(n_inputs)}
        return self._add("logicOr", 1, inputs, {"output": []}, {}, None, x, y)

    # ---------- 动作 ----------
    def write_device(self, did, urn, siid, piid, value, x=0, y=0):
        """写设备属性（设灯即亮：写灯亮度/色温/场景会顺带点亮）。"""
        return self._add("deviceOutput", 0, {"trigger": None}, {"output": []},
                         {"did": did, "siid": siid, "piid": piid, "value": value}, urn, x, y)

    def call_action(self, did, urn, siid, aiid, ins, x=0, y=0):
        """调用设备动作（aiid）。ins=[{piid,value} 或 {piid,id,scope,dtype} 变量引用]。"""
        return self._add("deviceOutput", 1, {"trigger": None}, {"output": []},
                         {"did": did, "siid": siid, "aiid": aiid, "ins": ins}, urn, x, y)

    def fire_virtual_event(self, hub_did, hub_urn, name, siid=4, aiid=1, x=0, y=0):
        """触发中枢网关「虚拟事件」，由 trigger_virtual_event(name) 的规则接收。xiaomi-hub1 实测 siid4/aiid1。"""
        return self.call_action(hub_did, hub_urn, siid, aiid, [{"piid": 1, "value": name}], x, y)

    def tts(self, speaker_did, speaker_urn, var_id, siid=7, aiid=3, scope="global", x=0, y=0):
        """音箱朗读字符串变量内容（先 set_var 写文本再朗读）。"""
        return self.call_action(speaker_did, speaker_urn, siid, aiid,
                                [{"piid": 1, "id": var_id, "scope": scope, "dtype": "string"}], x, y)

    def set_number(self, var_id, value, scope="global", x=0, y=0):
        """数字变量赋值（varSetNumber）。value 可以是数字，也可以是函数表达式字符串，如 "hours()"、"month()"。
        形状取自真机备份：elements=[{"type":"const","value":"<数字或表达式>"}]，cfg.version=0。"""
        return self._add("varSetNumber", 0, {"input": None}, {"output": []},
                         {"id": var_id, "scope": scope, "elements": [{"type": "const", "value": str(value)}]}, None, x, y)

    def write_device_var(self, did, urn, siid, piid, var_id, vmin, vmax, step=1, scope="global", x=0, y=0):
        """把数字变量的当前值写进设备属性（例如灯的亮度、色温直接读「客厅亮度」变量）。
        形状取自真机备份：props={did,siid,piid,id,scope,dtype:"number",min,max,step}，cfg.version=1。"""
        return self._add("deviceOutput", 1, {"trigger": None}, {"output": []},
                         {"did": did, "siid": siid, "piid": piid, "id": var_id, "scope": scope, "dtype": "number",
                          "min": vmin, "max": vmax, "step": step}, urn, x, y)

    def set_var(self, var_id, text=None, elements=None, scope="global", x=0, y=0):
        """文本变量赋值/拼接。text=纯常量；或传 elements（[{type:const|var,...}] token 列表）。"""
        if elements is None:
            elements = [{"type": "const", "value": text if text is not None else ""}]
        return self._add("varSetString", 1, {"input": None}, {"output": []},
                         {"id": var_id, "scope": scope, "elements": elements}, None, x, y)

    # ---------- 文本注释（画布文档卡，不连线/不执行）----------
    def text_note(self, text=None, x=40, y=40, width=320, height=None, background="#80CAFF", contents=None):
        """画布注释卡（type=nop）：纯文档，不参与连线与执行，auto_layout 不动其坐标。
        text=纯文本（自动补换行）；或传 contents=Quill Delta 数组做富文本（如加粗 {"attributes":{"bold":True}}）。
        background 为卡片底色（编辑器调色板色值，默认蓝 #80CAFF）。手动给 x/y 定位。
        height 省略则按内容字数与 width 估算折行高度（CJK 计 1、其它计半字宽），避免长文本溢出卡片。"""
        if contents is None:
            t = text if text is not None else ""
            contents = [{"insert": t if t.endswith("\n") else t + "\n"}]
        if height is None:
            # 字宽/行高取自编辑器实测校准（字号13px/行高20px；CJK≈13px、其它≈7px，左右内边距~16px）
            usable = max(1, width - 16)
            text_lines = "".join(str(seg.get("insert", "")) for seg in contents).split("\n")
            wrapped = 0
            for ln in text_lines:
                px = sum(13 if ord(c) > 0x2E7F else 7 for c in ln)
                wrapped += max(1, -(-px // usable))                      # 每显式行按像素宽向上取整折行数
            if text_lines and text_lines[-1] == "":                      # 去掉末尾换行产生的空行
                wrapped -= 1
            # 注释卡内是 Quill 编辑器，.ql-editor 有对称的上下各 20px 内边距 + 1px 边框×2。
            # 卡高 = 上20 + 文字(行数×20) + 下20 + 边框2 = 行数×20 + 42，此时上下各 20px 真正居中（实测校准）。
            height = max(1, wrapped) * 20 + 42
        _id = self._nid()
        cfg = {"contents": contents, "background": background,
               "pos": {"x": x, "y": y, "width": width, "height": height}, "name": "nop", "version": 1}
        self.nodes.append({"id": _id, "type": "nop", "cfg": cfg, "inputs": {}, "outputs": {"output": []}, "props": {}})
        return _id

    def band_top(self, band):
        """返回某意图分组所有（非注释）节点排版后的最小 y；须在 auto_layout 之后调用。用于把band标题注释对齐到该簇顶部。"""
        ys = [n["cfg"]["pos"]["y"] for n in self.nodes if self.band.get(n["id"]) == band and n["type"] != "nop"]
        return min(ys) if ys else None

    # ---------- 意图分组（排版用：同 band 的链聚在一起，不同 band 之间额外拉开间距）----------
    def set_band(self, band, *node_ids):
        """把若干节点标记为同一意图簇（如"进房点灯""人走关灯"）。auto_layout 会按 band 在列内分块、块间加大间距。"""
        for nid in node_ids:
            self.band[nid] = band
        return node_ids

    # ---------- 连线 ----------
    def link(self, src, sport, dst, dport):
        """连线（记于源节点 outputs）。支持扇出/扇入（同口可连多目标、多源可连同口）。"""
        self.edges.append((src, sport, dst, dport))

    # ---------- 变量定义 ----------
    def define_var(self, var_id, var_type, value, name, scope="global"):
        """定义本规则引入的变量。scope="global" 为全局变量，"R<规则ID>" 为规则内变量（不污染全局列表）。
        2026-06-14 实测：规则 scope 变量在导出→导入回路后完好存活（有卡片引用前提下）。"""
        if not _VAR_ID_RE.match(var_id):
            raise ValueError("变量 ID 必须 11 位纯字母数字（含下划线等会被平台静默丢弃）：%r" % var_id)
        self.var_defs[var_id] = (scope, {"type": var_type, "value": value, "userData": {"name": name}})
        return var_id

    def declare_external_var(self, var_id):
        """声明本规则只读引用、但由别处定义的变量（如已上线的「时间段」），仅用于通过引用闭合校验。"""
        self.var_defs.setdefault(var_id, None)
        return var_id

    # 各类型卡片自然宽高（取自真实备份的上限并留余量；编辑器按内容自然渲染，故排版须按真实尺寸避免重叠）
    NODE_SIZE = {
        "deviceInput": (600, 210), "deviceGet": (760, 170), "deviceOutput": (700, 170),
        "deviceInputSetVar": (580, 210), "deviceGetSetVar": (590, 170),
        "timeRange": (580, 120), "alarmClock": (560, 160), "varChange": (470, 160),
        "varGet": (540, 130), "varSetString": (740, 120), "varSetNumber": (760, 120),
        "onLoad": (180, 110), "condition": (320, 150), "delay": (300, 120),
        "logicAnd": (180, 240), "logicOr": (180, 270), "logicNot": (180, 110),
        "signalOr": (180, 190), "modeSwitch": (180, 190), "register": (180, 150),
        "counter": (360, 150), "onlyNTimes": (400, 150), "eventSequence": (540, 150),
        "loop": (520, 150), "statusLast": (300, 130),
    }
    _DEFAULT_SIZE = (760, 220)

    def auto_layout(self, col_gap=80, row_gap=50, x0=60, y0=60, band_gap=160):
        """按图拓扑分层 + 各类型真实宽高自动排版，覆盖所有节点 cfg.pos（含 width/height）。
        触发器在最左层，沿连线向右逐层；列 x 按该列最宽卡片累积、列内行 y 按各卡片高度累积——
        任意规则零重叠且紧凑。要求图为 DAG（常规规则均满足；含环时环上节点退回第 0 层）。
        列内排序优先按 set_band 的意图分组，再按创建序；相邻 band 之间额外加 band_gap 垂直间距，
        让不同意图的整套流程上下拉开、便于人类阅读。在 build_rule 前调用，业务脚本无需手填坐标。"""
        from collections import deque
        succ = {n["id"]: [] for n in self.nodes}
        indeg = {n["id"]: 0 for n in self.nodes}
        for (src, _sp, dst, _dp) in self.edges:
            if src in succ and dst in indeg:
                succ[src].append(dst); indeg[dst] += 1
        layer = {nid: 0 for nid in indeg}
        indeg_w = dict(indeg)
        q = deque([nid for nid in indeg if indeg_w[nid] == 0])
        while q:
            u = q.popleft()
            for v in succ[u]:
                if layer[v] < layer[u] + 1:
                    layer[v] = layer[u] + 1
                indeg_w[v] -= 1
                if indeg_w[v] == 0:
                    q.append(v)
        # nop（文本注释卡）不参与自动排版，保留其手填坐标
        laid = [n for n in self.nodes if n["type"] != "nop"]
        # 写入各节点自然宽高
        for n in laid:
            w, h = self.NODE_SIZE.get(n["type"], self._DEFAULT_SIZE)
            n["cfg"]["pos"]["width"], n["cfg"]["pos"]["height"] = w, h
        creation_idx = {n["id"]: i for i, n in enumerate(self.nodes)}
        by_layer = {}
        for n in laid:
            by_layer.setdefault(layer[n["id"]], []).append(n)
        # 列 x 按该列最宽卡片累积
        col_x, acc_x = {}, x0
        for lyr in sorted(by_layer):
            col_x[lyr] = acc_x
            acc_x += max(n["cfg"]["pos"]["width"] for n in by_layer[lyr]) + col_gap
        # 泳道布局：每个意图分组(band)占一条贯穿所有列的固定 y 区间，列内同 band 节点在该区间内堆叠。
        # 这样不同意图的整套流程真正上下分区，band_top 也有确定值（便于挂分组标题注释）。
        bands_sorted = sorted({self.band.get(n["id"], 0) for n in laid})
        cell = {}  # (band, lyr) -> [节点...]（按创建序）
        for n in laid:
            cell.setdefault((self.band.get(n["id"], 0), layer[n["id"]]), []).append(n)
        for c in cell.values():
            c.sort(key=lambda n: creation_idx[n["id"]])
        def cell_height(nodes):
            return sum(n["cfg"]["pos"]["height"] for n in nodes) + row_gap * max(0, len(nodes) - 1)
        # 每条泳道高度 = 该 band 在各列中最高的一格
        band_h = {b: max([cell_height(cell.get((b, l), [])) for l in by_layer] or [0]) for b in bands_sorted}
        band_y, acc = {}, y0
        for b in bands_sorted:
            band_y[b] = acc
            acc += band_h[b] + band_gap
        for (b, lyr), ns in cell.items():
            y = band_y[b]
            for n in ns:
                n["cfg"]["pos"]["x"] = col_x[lyr]
                n["cfg"]["pos"]["y"] = y
                y += n["cfg"]["pos"]["height"] + row_gap
        return self

    # ---------- 落边 + 校验 ----------
    def _materialize_edges(self):
        idmap = {n["id"]: n for n in self.nodes}
        # 先清空 outputs 端口已有内容由调用方保证为空；这里仅追加
        for src, sport, dst, dport in self.edges:
            if src not in idmap or dst not in idmap:
                raise ValueError("连线引用未知节点 %s/%s" % (src, dst))
            if sport not in idmap[src]["outputs"]:
                raise ValueError("节点 %s 无输出口 %s" % (src, sport))
            if dport not in idmap[dst]["inputs"]:
                raise ValueError("节点 %s 无输入口 %s" % (dst, dport))
            tgt = "%s.%s" % (dst, dport)
            if tgt not in idmap[src]["outputs"][sport]:
                idmap[src]["outputs"][sport].append(tgt)

    def validate(self, raise_on_error=False):
        """落边并做完整性/约束校验，返回问题列表（空=通过）。"""
        # 重置所有 outputs 端口为列表再落边（保证可重复调用）
        for n in self.nodes:
            for port in n["outputs"]:
                n["outputs"][port] = []
        self._materialize_edges()
        errs = []
        indeg = {n["id"]: 0 for n in self.nodes}
        outdeg = {n["id"]: 0 for n in self.nodes}
        for n in self.nodes:
            for port, tgts in n["outputs"].items():
                outdeg[n["id"]] += len(tgts)
                for t in tgts:
                    indeg[t.split(".")[0]] += 1
        defined_ids = set(self.var_defs.keys())
        for n in self.nodes:
            t = n["type"]
            if t == "nop":          # 文本注释卡：无连线、不执行，跳过完整性校验
                continue
            if t not in _TRIGGER_TYPES and indeg[n["id"]] == 0:
                errs.append("悬空(无入边)非触发节点: %s %s" % (n["id"], t))
            if t not in _TERMINAL_OK and outdeg[n["id"]] == 0:
                errs.append("悬空(无出边)非终端节点: %s %s" % (n["id"], t))
            op = n["props"].get("operator")
            if t in _VAR_NODE_TYPES and op is not None and op != "=":
                errs.append("变量节点 %s 用了非'='算子 %r（平台仅支持'='，用 output2 表达'≠'）" % (n["id"], op))
            vid = n["props"].get("id")
            if isinstance(vid, str) and vid.startswith("V") and vid not in defined_ids:
                errs.append("引用未定义/未声明变量: %s in %s" % (vid, n["id"]))
            for inn in n["props"].get("ins", []):
                iid = inn.get("id")
                if iid and iid not in defined_ids:
                    errs.append("ins 引用未定义/未声明变量: %s in %s" % (iid, n["id"]))
        if raise_on_error and errs:
            raise AssertionError("规则校验失败:\n  " + "\n  ".join(errs))
        return errs

    # ---------- 组装 ----------
    def build_rule(self, rule_id, name, tags=None, enable=False, last_update_time=None):
        """产出单条规则 dict（会先 validate 落边）。lastUpdateTime 省略则取当前时间（毫秒），
        让控制台列表"编辑于"反映本次生成/导入；可显式传值固定（如回归比对需确定性输出时）。"""
        self.validate(raise_on_error=True)
        return {
            "id": str(rule_id),
            "cfg": {"id": str(rule_id),
                    "userData": {"name": name, "transform": {"x": 0, "y": 0, "scale": 1, "rotate": 0},
                                 "lastUpdateTime": int(last_update_time or now_millis()), "version": 0, "tags": tags or []},
                    "uiType": "test", "enable": enable},
            "nodes": self.nodes,
        }

    def var_definitions(self):
        """返回本规则引入的变量定义，按 scope 分组：{"global": {id:def}, "R<规则ID>": {id:def}}。
        declare_external_var 的占位 None 被排除。"""
        result = {}
        for var_id, entry in self.var_defs.items():
            if entry is None:
                continue
            scope, vdef = entry
            result.setdefault(scope, {})[var_id] = vdef
        return result


# ---------- 模块级：合并多规则为导入集（导入=全量覆盖，须含所有要保留的规则）----------
def merge_import_set(rules, variables_global, rule_var_scopes=None, add_watermark=False,
                     watermark_repo_url=None, watermark_version=None):
    """rules=[rule dict...]，variables_global={id:def...}，rule_var_scopes={"R<规则ID>": {id:def}}。
    产出 {version,rules,variables{global, R<id>...}} 顶层结构。
    add_watermark=True 时自动在规则列表末尾追加品牌标识规则（nop 文本卡片标注仓库/版本/时间）。
    watermark_repo_url/watermark_version 可覆盖水印中的仓库地址/版本号。"""
    variables = {"global": dict(variables_global)}
    if rule_var_scopes:
        for scope_key, vars_dict in rule_var_scopes.items():
            variables[scope_key] = dict(vars_dict)
    rules_out = list(rules)
    seen = {}
    for r in rules_out:
        rid = str(r.get("id"))
        if rid in seen:
            raise ValueError("规则 ID 重复：%s（「%s」与「%s」）。新规则请换一个毫秒时间戳 ID" % (
                rid, seen[rid], r.get("cfg", {}).get("userData", {}).get("name", "")))
        seen[rid] = r.get("cfg", {}).get("userData", {}).get("name", "")
    if add_watermark:
        rules_out.append(brand_watermark_rule(
            repo_url=watermark_repo_url, version=watermark_version))
    return {"version": 2, "rules": rules_out, "variables": variables}


def check_import_set(import_set):
    """整包写入前的跨规则检查，返回问题列表（空=通过）：规则 ID 重复、规则内节点 ID 重复、
    全局变量 ID 格式不合法、规则引用了导入集里不存在的变量。"""
    issues = []
    variables = import_set.get("variables", {})
    for vid in variables.get("global", {}):
        if not _VAR_ID_RE.match(vid):
            issues.append("全局变量 ID 不是 11 位纯字母数字，会被平台丢弃：%s" % vid)
    defined = {(scope, vid) for scope, items in variables.items() for vid in items}
    rule_ids = set()
    for r in import_set.get("rules", []):
        rid = str(r.get("id"))
        name = r.get("cfg", {}).get("userData", {}).get("name", rid)
        if rid in rule_ids:
            issues.append("规则 ID 重复：%s" % rid)
        rule_ids.add(rid)
        node_ids = [n.get("id") for n in r.get("nodes", [])]
        dups = {x for x in node_ids if node_ids.count(x) > 1}
        if dups:
            issues.append("规则「%s」内节点 ID 重复：%s" % (name, ", ".join(sorted(dups))))
        for n in r.get("nodes", []):
            props = n.get("props", {})
            refs = [(props.get("scope"), props.get("id"))] if n.get("type", "").startswith("var") else []
            refs += [(x.get("scope"), x.get("id")) for x in props.get("ins", []) if x.get("id")]
            for el in props.get("elements", []):
                if el.get("type") == "var":
                    refs.append((el.get("scope"), el.get("id")))
            for scope, vid in refs:
                if vid and (scope or "global", vid) not in defined:
                    issues.append("规则「%s」引用了导入集里没有的变量：%s/%s" % (name, scope or "global", vid))
    return issues


def load_rules_from_file(path):
    """读已有导出/规则 JSON，返回 (rules列表, variables.global字典)。"""
    d = json.load(open(path, encoding="utf-8"))
    return d.get("rules", []), d.get("variables", {}).get("global", {})

def load_import_set_from_file(path):
    """读取完整导入集，返回 (rules, global_vars, scoped_vars)，保留所有变量作用域。"""
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    variables = d.get("variables", {})
    global_vars = dict(variables.get("global", {}))
    scoped_vars = {scope: dict(items) for scope, items in variables.items() if scope != "global"}
    return d.get("rules", []), global_vars, scoped_vars


def relayout_rule(rule, bands=None, **layout_kwargs):
    """给已有规则 dict（含 nodes，连线编码在各节点 outputs 的 "dstId.dstPort" 串）重新自动排版：
    从 outputs 反解连线 → 复用 auto_layout（拓扑分层 + 各类型真实宽高 + 可选意图分组）→ 回写每个节点 cfg.pos。
    用于把非本库生成/旧的规则统一成清爽排版。bands={node_id:band} 可选。原地修改并返回 rule。"""
    rb = RuleBuilder()
    rb.nodes = rule["nodes"]
    rb.band = dict(bands or {})
    for n in rule["nodes"]:
        for port, tgts in (n.get("outputs") or {}).items():
            for t in tgts:
                if isinstance(t, str) and "." in t:
                    dst, dport = t.split(".", 1)
                    rb.edges.append((n["id"], port, dst, dport))
    rb.auto_layout(**layout_kwargs)
    return rule


def dump_json(obj, path):
    json.dump(obj, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


# ---------- .bak 打包 / 解包（米家极客版备份格式）----------
# 格式：[4字节 LE uint32 未压缩JSON字节长度] + [raw DEFLATE(单行紧凑JSON,UTF-8)] + [32字节 SHA-256(前缀+deflate)]
def pack_bak(import_set, path):
    """把导入集 dict 打包为可导入的 .bak。import_set 为 merge_import_set 的产出（{version,rules,variables}）。"""
    js = json.dumps(import_set, ensure_ascii=False, separators=(",", ":")).encode("utf-8")  # 单行紧凑
    deflate = zlib.compress(js, 9)[2:-4]            # 去 zlib 头(2)与 adler32(4) ⇒ raw deflate
    body = struct.pack("<I", len(js)) + deflate
    bak = body + hashlib.sha256(body).digest()
    with open(path, "wb") as f:
        f.write(bak)
    return path


def unpack_bak(path):
    """严格校验长度头与 SHA-256 尾，再解包 .bak 为导入集 dict。"""
    raw = open(path, "rb").read()
    if len(raw) < 37:
        raise ValueError(".bak 太短：缺少长度头、压缩数据或 SHA-256 尾")
    body, digest = raw[:-32], raw[-32:]
    if hashlib.sha256(body).digest() != digest:
        raise ValueError("SHA-256 校验失败；拒绝解包")
    n = struct.unpack("<I", raw[:4])[0]
    d = zlib.decompressobj(-15)
    js = d.decompress(body[4:]); js += d.flush()
    if not d.eof or d.unused_data or d.unconsumed_tail:
        raise ValueError("DEFLATE 数据不完整或包含多余字节")
    if len(js) != n:
        raise ValueError("未压缩长度不符: 声明 %d 实际 %d" % (n, len(js)))
    return json.loads(js.decode("utf-8"))


# ---------- 主包发布 / 版本固定（导入主包的迭代记录与验收固定）----------
# 约定：导出目录下分两类——
#   主包/      全屋导入「主包」(全量覆盖包)的迭代记录：时间戳构建 + 主包-当前.bak 指针 + 台账 + 已固定/
#   测试包/    局部/探针/实验包：保留/ (有复用价值) 与 临时/ (一次性，可随时清)
# 工作流：编辑生成器→出 JSON；要导入→pack_main 打时间戳构建(待验收)；现场验收无误→freeze_main 固定 vN。
MAIN_DIR = "主包"
TEST_DIR = "测试包"


def _fmt_ts(ms, compact=False):
    """毫秒时间戳 → 文件名用 'yyyyMMdd-HHmm'(compact) 或台账用 'yyyy-MM-dd HH:mm'。"""
    t = time.localtime(ms / 1000)
    return time.strftime("%Y%m%d-%H%M" if compact else "%Y-%m-%d %H:%M", t)


def _split_test_rules(import_set):
    """剥离规则名以 'TEST' 开头的规则（不进主包），返回 (clean_set, [被剥离规则名])。
    同时丢弃这些 TEST 规则的 scope 变量(variables 里 'R<id>' 且 id 不再被任何保留规则使用)。"""
    keep, dropped = [], []
    for r in import_set.get("rules", []):
        nm = r.get("cfg", {}).get("userData", {}).get("name", "")
        (dropped if nm.startswith("TEST") else keep).append(r)
    kept_ids = {r["id"] for r in keep}
    clean = dict(import_set)
    clean["rules"] = keep
    variables = import_set.get("variables")
    if isinstance(variables, dict):
        clean["variables"] = {k: v for k, v in variables.items()
                              if k == "global" or not k.startswith("R") or k[1:] in kept_ids}
    return clean, [r.get("cfg", {}).get("userData", {}).get("name", "?") for r in dropped]


def _ledger_path(root):
    return os.path.join(root, MAIN_DIR, "台账.json")


def _load_ledger(root):
    p = _ledger_path(root)
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {"entries": []}


def _render_ledger_md(root, ledger):
    lines = [
        "# 主包台账（全屋灯光导入主包迭代记录）", "",
        "> 🤖 自动生成，请勿手改（由 mijia_rule_kit.pack_main / freeze_main 维护）。",
        "> 要导入最新：用 `主包-当前.bak`（=最新构建）；要稳妥导入：用 `已固定/` 里最新 vN。",
        "> 状态含义：待验收=已打包未现场验 / 已固定vN=验收通过的里程碑 / 废弃。", "",
        "| 构建时间 | 文件 | 正式规则数 | 状态 | 规则列表 | 来源基底 | 备注 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for e in ledger.get("entries", []):
        lines.append("| %s | %s | %s | %s | %s | %s | %s |" % (
            e.get("build_time", ""), e.get("file", ""), e.get("rules_count", ""),
            e.get("status", ""), "/".join(e.get("rule_names", [])),
            e.get("base", ""), e.get("note", "")))
    open(os.path.join(root, MAIN_DIR, "台账.md"), "w", encoding="utf-8").write("\n".join(lines) + "\n")


def _save_ledger(root, ledger):
    os.makedirs(os.path.join(root, MAIN_DIR), exist_ok=True)
    json.dump(ledger, open(_ledger_path(root), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    _render_ledger_md(root, ledger)


def pack_main(import_set, root, note="", base="", exclude_test=True, build_ms=None,
              add_watermark=True, watermark_repo_url=None, watermark_version=None):
    """打包「全屋导入主包」的一次迭代构建。
      · exclude_test：剥离 TEST* 规则（测试规则归测试包另管，不进主包）；
      · add_watermark：末尾追加品牌标识规则（nop 文本卡片，默认开启）；
      · 写时间戳构建 主包/主包-<yyyyMMdd-HHmm>.bak，并刷新固定名指针 主包/主包-当前.bak；
      · 台账(JSON+MD) prepend 一行，状态「待验收」。
    base=来源基底说明（如网关备份文件名），note=本次变更摘要。返回时间戳构建路径。"""
    ms = int(build_ms or now_millis())
    clean, dropped = (_split_test_rules(import_set) if exclude_test else (dict(import_set), []))
    if add_watermark:
        clean.setdefault("rules", [])
        clean["rules"] = list(clean["rules"])
        clean["rules"].append(brand_watermark_rule(
            repo_url=watermark_repo_url, version=watermark_version))
    rule_names = [r.get("cfg", {}).get("userData", {}).get("name", "?") for r in clean.get("rules", [])]
    main_dir = os.path.join(root, MAIN_DIR)
    os.makedirs(main_dir, exist_ok=True)
    fname = "主包-%s.bak" % _fmt_ts(ms, compact=True)
    build_path = os.path.join(main_dir, fname)
    pack_bak(clean, build_path)
    pack_bak(clean, os.path.join(main_dir, "主包-当前.bak"))
    ledger = _load_ledger(root)
    ledger["entries"].insert(0, {
        "build_ms": ms, "build_time": _fmt_ts(ms), "file": fname,
        "rules_count": len(rule_names), "rule_names": rule_names,
        "status": "待验收", "version": None, "frozen_file": None,
        "dropped_test": dropped, "base": base, "note": note,
    })
    _save_ledger(root, ledger)
    return build_path


def freeze_main(root, version, note="", build_file=None):
    """把某次构建固定为「已验收」版本：复制到 主包/已固定/<version>-<note>.bak，台账标记「已固定 vN」。
    build_file 省略则固定最新一次构建（台账 entries[0]）。version 形如 'v1'。返回固定文件路径。"""
    ledger = _load_ledger(root)
    entries = ledger.get("entries", [])
    if not entries:
        raise ValueError("台账为空，无可固定构建")
    ent = entries[0] if not build_file else next((e for e in entries if e["file"] == build_file), None)
    if ent is None:
        raise ValueError("台账无此构建: %s" % build_file)
    main_dir = os.path.join(root, MAIN_DIR)
    frozen_dir = os.path.join(main_dir, "已固定")
    os.makedirs(frozen_dir, exist_ok=True)
    safe = note.strip().replace("/", "_").replace(" ", "")
    frozen_name = ("%s-%s.bak" % (version, safe)) if safe else ("%s.bak" % version)
    shutil.copyfile(os.path.join(main_dir, ent["file"]), os.path.join(frozen_dir, frozen_name))
    ent["status"] = "已固定 %s" % version
    ent["version"] = version
    ent["frozen_file"] = "已固定/" + frozen_name
    if note:
        ent["note"] = (ent.get("note", "") + " ｜固定:" + note).strip(" ｜")
    _save_ledger(root, ledger)
    return os.path.join(frozen_dir, frozen_name)


# ---------- 品牌水印规则（标识规则由 mijia-geek-skills 生成）----------
_WATERMARK_DEFAULTS = {
    "repo_url": "https://zhijipro.cn/skills/",
    "version": "2.0.9",
    "skills_used": "mijia-home",
}


def brand_watermark_rule(repo_url=None, version=None, generated_at=None, skills_used=None):
    """生成一条品牌标识规则（仅含 nop 文本注释卡），用于标明本套规则由 mijia-geek-skills 生成。

    参数：
        repo_url:    GitHub 仓库地址，省略用默认值
        version:     版本号，省略用默认值 "1.0.0"
        generated_at: 生成时间字符串，省略取当前时间
        skills_used: 使用技能列表字符串，省略用默认值

    返回：单条规则 dict，可直接 append 到 import_set['rules']。

    极客版中表现为规则名「⚙ 本套规则由 mijia-geek-skills 生成」，
    点击进入画布可查看仓库地址、版本、生成时间等元信息。
    """
    repo = repo_url or _WATERMARK_DEFAULTS["repo_url"]
    ver = version or _WATERMARK_DEFAULTS["version"]
    sk = skills_used or _WATERMARK_DEFAULTS["skills_used"]
    ts = generated_at or time.strftime("%Y-%m-%d %H:%M:%S")
    text = (
        "本套自动化规则使用 mijia-geek-skills 生成\n\n"
        "仓库：%s\n"
        "版本：%s\n"
        "生成时间：%s\n"
        "使用技能：%s\n\n"
        "mijia-geek-skills 是一套面向 AI 编程助手的\n"
        "米家极客版自动化技能包，帮助用户用自然语言\n"
        "描述需求、自动生成可导入规则。\n"
        "详见 %s"
    ) % (repo, ver, ts, sk, repo)
    rb = RuleBuilder(node_prefix="wm")
    rb.text_note(text, x=40, y=40, width=620, height=280, background="#80CAFF")
    rule_id = "wm%d" % now_millis()
    return rb.build_rule(rule_id, "⚙ 本套规则由 mijia-geek-skills 生成",
                         tags=["系统标识", "mijia-geek-skills"], enable=True)
