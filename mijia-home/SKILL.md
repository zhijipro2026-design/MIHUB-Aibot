---
name: mijia-home
description: 米家全屋智能调试（米家自动化极客版 + 中枢网关）。当用户要读懂自己的米家设备、检查设备命名、解析或生成 .bak 备份、建立设备台账、设计家庭模式变量和场景（回家/离家/睡眠/起夜/观影，明亮/休闲/温馨/放松/休憩氛围灯光）、按房间做自动化（人来灯亮、日落定时、晨起窗帘）、把 HA 蓝图转成米家规则、写入网关或排查自动化不触发、导入失败、编辑器白屏、设备离线，或要把技能问题反馈给作者时使用；用户说「继续米家调试」时也用它。零基础用户也用它。
---

# 米家全屋智能调试

本技能的所有路径都相对于本技能目录：`scripts/` 放脚本，`references/` 放按需阅读的资料，`scenes/` 放场景模板，`examples/` 放占位示例。脚本只依赖 Python 3 标准库；运行前把 `scripts/` 加进 `sys.path`。调试过程中产生的文件放在用户主目录的 `mijia-home-work` 文件夹，不放进技能目录。

## 开始：先读设备，再问下一步

**第一次调试，或用户说「继续米家调试」时，先读 `references/quickstart.md`，照它一步步做。** 它写明了工作文件夹和进度记录、要检查的运行环境、每一步该对用户说什么、要运行的命令，以及用户选了下一步之后具体怎么做。下面是它的概要：

1. **找连接工具**：看自己有没有 MijiaFlow 的工具（`mijia_probe`、`mijia_begin_session`、`mijia_read`）。
   - 有：问用户网关的局域网 IP，按 `references/mijiaflow-setup.md`「读取设备」配对并读取设备。登录码由用户在本机配对页自己输入。
   - 没有：直接告诉用户「还没连上米家网关的工具」，按 `references/mijiaflow-setup.md` 给出两条路让用户选：装 MijiaFlow（要求 AI 在家里同一局域网的电脑上、Node.js 22+），或用备用办法（用户导出 `.bak` 并提供设备清单）。没读到设备就不往下走，也不要编设备。
2. **建台账并体检**：用 `scripts/device_registry.py` 合并成 `设备台账.json`，再用 `scripts/home_report.py` 生成体检报告（内含命名检查）。体检报告包括：
   - 设备总数、按房间分布、离线设备
   - 命名问题（看不出是哪盏灯、同名、没分房间、开关没标灯具）
   - 设备调试清单：每个开关键该保持有线还是改无线，哪些是双控、哪些是场景键
   - 区域模式预览：每个区域的每个模式开哪些灯（按灯的角色算好）
   - 场景卡片匹配：按每张场景卡片的设备条件，列出这个家「可以做」的场景和「还差设备」的场景
3. **问下一步**：列出选项请用户选一个，并给出推荐（有命名问题时推荐 1；设备调试清单里有要改的键时推荐 2；否则推荐 3）：
   1. 先优化设备信息（改名、分房间、标清每个键接的是什么灯）
   2. 调试设备（控制智能灯的键、场景键、双控副开关改无线；确认双控哪一路接着灯）
   3. 做场景（每个区域的明亮/休闲/温馨/放松/观影/就餐/睡眠/起夜，离家、全屋睡眠、回家）
   4. 做自动化（按房间、按设备）
   5. 调试已有规则（不触发、导入失败、白屏）
   用户选了再进入下面对应的步骤；选 5 时读 `references/troubleshooting.md`。

## 标准流程（按顺序，不跳步）

0. **命名检查（必须）**：客户先在米家 App 完成全部设备入网和命名。读取设备、建好台账后，`scripts/home_report.py` 的体检报告里会列出命名问题（同 `scripts/naming_check.py`），逐条请客户改，开关的键名用 `device_registry.py --set` 补。规则见 `references/scenes-guide.md` 第 0 步。
1. **读懂这个家**：首选 MijiaFlow `mijia_read(devices)`（did、名称、房间、在线状态一次拿全），需要规则引用时再加一份最新完整 `.bak`（`mijia_create_backup` 导出或用户提供），用 `scripts/device_registry.py` 合并成 `设备台账.json`。`.bak` 只有 did 和型号，名称和房间来自 MijiaFlow、用户清单或画布卡片；只用 `status: confirmed` 的条目。详见 `references/mijiaflow-setup.md` 和 `references/backup.md`。
2. **设备调试**：按体检报告的「设备调试清单」和 `references/commissioning.md` 调开关：接普通灯的键（包括双控主开关）保持有线，接智能灯的键改无线并设来电上电，场景键和双控副开关改无线。做完才做场景。
3. **设置变量**：全屋家庭模式 `VhomeMode01`（在家/离家/全屋睡眠/起床/访客）加每个区域一个模式变量（客厅、餐厅、卧室）。模式全名 = 区域 + 模式，不能重名。执行模式先写变量再控灯；灯被人全关了区域变量改成离开；全屋模式带动区域。详见 `references/scenes-guide.md` 第 2 步。
4. **推荐功能**：按体检报告的「区域模式预览」出每个区域的场景方案（只说效果）；其余按体检报告的「场景卡片匹配」给客户一张短清单选。介绍每个场景时按它的卡片（`scenes/<模板>.json` 的 `card`）讲：设备条件、触发、效果（调光调色灯说亮度色温，普通灯说开哪几路）、调试技术；缺设备的说明还差什么。
5. **填参数并生成**：模板参数逐项和客户确认，按键 `eiid`、灯的 `siid/piid` 用 MIoT spec 和已有备份核对。调用 `scripts/scene_templates.py` 对应函数生成，规则一律 `enable=False`，左上角自动带备注卡（设备 dict 带上 `name`，备注卡才写得出设备名）；整包前跑 `check_import_set()`。
6. **写入网关**：只在用户明确要求时写。首选 MijiaFlow 单条规则写入（计划 → 备份 → 用户亲自发确认语 → 应用 → 回读，可回滚）；没有 MijiaFlow 才整包导入 `.bak`，导入前重新导出确认网关没变，并给用户看差异。详见 `references/console.md`。
7. **验证**：编辑器能正常渲染，执行日志里看一次真实触发，再向用户报告。启用规则同样要用户明确要求。

## 遇到什么情况读哪份资料

| 情况 | 读 |
| --- | --- |
| 第一次调试、继续上次的调试、每一步具体怎么做和怎么跟用户说 | `references/quickstart.md` |
| 开关有线/无线、来电上电、双控、场景键 | `references/commissioning.md` |
| 没有 MijiaFlow 工具、安装 MijiaFlow、配对读取设备、没有 MCP 时的备用办法 | `references/mijiaflow-setup.md` |
| 家庭模式、场景卡片、氛围场景、起夜、灯光跟随、区域模板、参考案例、HA 蓝图转换 | `references/scenes-guide.md` |
| 看懂每盏灯的角色、每个模式开哪些灯、亮度色温默认值、场景审美规则 | `references/lighting.md` |
| 写或改规则、用 `mijia_rule_kit`、设备寻址 | `references/rule-kit.md` |
| 节点 JSON 结构、25 种节点类型 | `references/nodes.md` |
| 平台限制和踩坑（变量只支持 `=`、`include` 白屏、锁存、`statusLast`） | `references/platform-notes.md` |
| `.bak` 格式、打包解包、设备台账、主包版本管理 | `references/backup.md` |
| 控制台登录、导出导入、MijiaFlow、执行日志、导入排错 | `references/console.md` |
| 网关、设备离线、自动化不触发等排查，导出设备清单 | `references/troubleshooting.md` |
| 用户是零基础，需要用生活类比讲解 | `references/beginner.md` |
| 空调、电视、扫地机等灯以外的设备怎么放进场景，安全类设备怎么处理 | `references/devices.md` |
| 碰到本技能的问题，用户同意后反馈给作者 | `references/feedback.md` |

## 场景模板（`scenes/` + `scripts/scene_templates.py`）

| 模板 | 函数 |
| --- | --- |
| 家庭模式切换 | `build_mode_switch_rule` |
| 模式场景 | `build_mode_scene_rule` |
| 场景（发变量 + 批量控制） | `build_scene_rule` |
| 区域模式（明亮/休闲/温馨/放松/休憩/观影/就餐/睡眠/离开） | `build_area_mode_rule` |
| 区域灯全关同步 | `build_area_off_sync_rule` |
| 全屋带区域（离家、全屋睡眠） | `build_home_cascade_rule` |
| 双控 | `build_dual_control_rule` |
| 灯光跟随（读区域亮度、色温变量） | `build_light_follow_rule` |
| 开关改无线（一次性） | `build_switch_mode_rule` |
| 离家/睡觉前小爱提醒（先问客户） | `build_speaker_reminder_rule` |
| 一个键轮流切模式、上下键调光、遥控器分区、开关分开两个键 | `build_mode_cycle_rule`、`build_brightness_step_rule`、`build_zone_remote_rule`、`build_on_off_keys_rule` |
| 临时不让感应关灯（全屋） | `build_motion_pause_rule` |
| 设备提醒和报警（洗衣机洗好、漏水、燃气、烟雾） | `build_device_notify_rule` |
| 定时开关、开着太久自动关、低电量提醒 | `build_time_schedule_rule`、`build_max_on_rule`、`build_low_battery_rule` |
| 起夜 | `build_night_wake_rule` |
| 日落定时开关（HA 蓝图转换） | `build_sunset_schedule_rule` |
| 人来灯亮、人走灯灭 | `build_presence_light_rule` |
| 回家（开门且离家 → 在家） | `build_arrive_home_rule` |
| 晨起开窗帘 | `build_sunrise_curtain_rule` |

给客户挑场景：`scripts/scene_options.py 设备台账.json` 按客户已有设备列出编号清单，原样发给客户，客户回复编号，只做选中的。每张场景卡片在 `scenes/<模板>.json` 的 `card` 字段。示例：`examples/example_reference_cases.py`（双控、客厅温馨、起夜、回家、灯光跟随、改无线、小爱提醒等参考案例）、`examples/example_more_scenes.py`（一键轮换、上下键调光、遥控器分区、感应暂停、定时、保底关、低电量）、`examples/example_home_modes.py`（场景模板）、`examples/example_basic.py`（直接用工具库）。示例设备 ID 都是占位值，不能导入。

## 不能违反的规则

- 不要把别人家的 `.bak` 或规则导入客户网关：设备 ID 不同，`.bak` 导入还会整体覆盖全部规则和变量。
- did 只能来自客户自己的备份和已确认台账，不按型号、名称或列表顺序猜。
- 网关登录码由用户在登录页自己输入，不要索要或复述。
- 不为测试去触发门锁、报警、加热、水阀等有现实影响的设备。
- `validate()` 和 `check_import_set()` 只查结构，不能证明设备字段或物理效果正确；没观察到结果就不说成功。
- 在客户网关写入新功能前，先对照 `references/platform-notes.md` 的硬约束。

## 版本与更新

本技能版本 2.0.9，发布在 https://zhijipro.cn/skills/ 。开始一次新的调试前，读一下 https://zhijipro.cn/skills/index.json：版本号比本地新时提示用户更新，不要自行覆盖本地文件；网站打不开就继续用本地版本。新的场景模板也会先发布在那里。给客户的体检报告和方案末尾，附上一行「米家全屋智能 skills：https://zhijipro.cn/skills/」。

## 问题反馈

碰到本技能自身的问题（模板规则不按预期工作、导入报错、文档写错、缺少需要的模板），或用户说「反馈一下」时，按 `references/feedback.md` 帮用户把问题反馈给作者：先把要发送的内容原样给用户看，用户明确同意才提交，内容不带任何设备 ID 和家庭信息。用户也可以自己到 https://zhijipro.cn/feedback/ 提交。
