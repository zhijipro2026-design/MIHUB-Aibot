# 第一次调试：逐步剧本

用户第一次说「帮我调试米家全屋智能」，或说「继续米家调试」时，**照这份剧本一步步做**，每一步做完再进下一步。引号里的话可以直接发给用户（按情况改写）。不确定时先问用户，不要自己猜设备、IP、编号或配置路径。

全程顺序固定：**读取设备 → 建台账 → 体检（含命名检查）→ 问下一步 → 生成 → 写入 → 验证**。

## 第 1 步：工作文件夹、进度记录、运行环境

1. 在用户主目录建工作文件夹 `mijia-home-work`（Windows：`%USERPROFILE%\mijia-home-work`，macOS/Linux：`~/mijia-home-work`）。本次调试的所有文件（`devices.json`、备份、`设备台账.json`、`体检报告.md`、生成脚本和规则）都放这里，**不要放进技能目录**。
2. 文件夹里已有 `进度.md`：先读它，从上次停下的地方继续，并告诉用户「上次做到了 …，我们从这里继续」。
3. 没有就新建 `进度.md`，用这个格式，之后每完成一步就更新：

   ```
   # 米家调试进度
   - 网关地址：http://<网关IP>/
   - MijiaFlow：未安装 / 已安装待重启 / 可读写 / 只读
   - Python 命令：py -3（或 python3 / python）
   - 最新备份：<文件名.bak>
   - 用户选的下一步：1/2/3/4
   ## 记录
   - <日期> 做了什么；下一步做什么
   ```

   不要把登录码、配对地址、确认语、planToken 之类写进去，它们只在当次会话有效。
4. 检查运行环境，结果写进 `进度.md`：
   - **Python 3**：Windows 先试 `py -3 --version`，再试 `python --version`、`python3 --version`；macOS/Linux 试 `python3 --version`。**只有打印出 `Python 3.x` 版本号才算装了**（Windows 上没有版本号输出、或弹出微软商店的，都是没装）。记下能用的命令，下文写作 `<python>`。
   - 没有 Python：告诉用户「检查脚本要用 Python 3：到 https://www.python.org/downloads/ 下载安装，安装时勾选 Add python.exe to PATH，装完重启我。」用户不想装也能继续，你就自己读 JSON，按 `scripts/naming_check.py` 和 `scripts/home_report.py` 里的规则手工做同样的检查。
   - **Node.js**：`node -v`，要 v22 或更高（只有装 MijiaFlow 需要）。没有或版本低时，告诉用户到 https://nodejs.org/ 下载 LTS 版安装（Windows 也可以用 `winget install OpenJS.NodeJS.LTS`），装完重启 AI 客户端，让新的 PATH 生效。

本文里 `<技能目录>` 指 `mijia-home` 文件夹的完整路径（`SKILL.md` 所在的文件夹）。命令里的路径一律加引号，Windows 用户名有空格或中文时才不会出错，例如：

```
py -3 "C:\Users\张三\.claude\skills\mijia-home\scripts\home_report.py" "设备台账.json"
```

## 第 2 步：连上网关，读取设备

先看自己的工具里有没有 `mijia_probe`、`mijia_begin_session`、`mijia_read`。

### 没有这些工具

对用户说：

> 「要读取你家的设备，需要先装一个连接米家中枢网关的小工具 MijiaFlow（开源、免费）。需要满足三个条件：我运行在你家里、和网关连同一个网络的电脑上；电脑装了 Node.js 22 或更高版本；你能在米家 App 里拿到中枢网关的六位登录码。可以吗？如果暂时不方便，也可以用备用办法，不过要多花一些手工。」

- **用户选装**：按 `references/mijiaflow-setup.md`「安装 MijiaFlow」做。改 MCP 配置前告诉用户要改哪个文件。装好后 `进度.md` 写「MijiaFlow：已安装待重启」，然后按 `references/mijiaflow-setup.md`「让工具出现」告诉用户怎么重启，并说：「重启后对我说『继续米家调试』。」本轮到此结束。
- **重启后工具还是没出现**：按 `references/mijiaflow-setup.md`「常见失败」逐条查，并把你改过的配置文件内容给用户看。
- **用户选备用办法**：按 `references/mijiaflow-setup.md`「备用办法」做，它有自己的完整步骤，做完直接进第 4 步。

### 有这些工具

1. 问用户网关地址：「请告诉我中枢网关的局域网 IP 地址。米家 App 里打开中枢网关的设置能看到；也可以在路由器管理页的设备列表里找。」
2. `mijia_probe("http://<网关IP>/")`，把返回的能力模式写进 `进度.md`：
   - 可读写：照常往下走。
   - **只读**（网关极客版版本和 MijiaFlow 不匹配）：照实告诉用户「现在只能读取，不能直接写规则；写规则要在极客版控制台整包导入备份」。读取照常做，到第 5 步改走 `references/console.md` 的「控制台导入 .bak」。
   - 连不上：按 `references/mijiaflow-setup.md`「常见失败」排查，不要换着 IP 乱试。
3. `mijia_begin_session("http://<网关IP>/")`，把它给出的本机页面地址告诉用户：「请在这台电脑的浏览器打开这个页面，输入米家 App 里中枢网关的六位登录码。登录码只填在那个页面，不要发给我。」
4. 每隔几秒调用 `mijia_session_status()`：
   - `ready`：继续。
   - `failed`（或一直等不到）：那个页面已经作废，**重新调用 `mijia_begin_session`**，把新地址给用户，请用户拿一个新的登录码再输一次。
5. `mijia_read("devices")`。把工具返回内容里的那段 **JSON 文本本身**（不要外面的包装，不要改动、不要删减）保存为 `mijia-home-work\devices.json`。设备很多、你无法完整写出时，告诉用户，改为分批：`mijia_read("devices", {"available": true})` 和 `{"available": false}` 各存一份，`device_registry.py` 先后合并两次。
6. 导出备份：`mijia_create_backup({"fileName": "备份-<日期>.bak", "outputDir": "<mijia-home-work 的完整路径>", "cloud": false})`。`进度.md` 记下文件名。它是后面出问题时的退路，也带着现有规则里的设备引用。
7. `mijia_read("variables", {"scope": "global"})`：有「低电量设备」（`VlowBatt001`）且有值时，先告诉用户哪个设备该换电池。
8. `进度.md` 记「已读取 N 台设备，已备份」。

## 第 3 步：建台账、出体检报告

在 `mijia-home-work` 文件夹里运行：

```
<python> "<技能目录>/scripts/device_registry.py" "备份-<日期>.bak" --mijiaflow-devices "devices.json" --out "设备台账.json"
<python> "<技能目录>/scripts/home_report.py" "设备台账.json" --out "体检报告.md"
<python> "<技能目录>/scripts/scene_options.py" "设备台账.json" --out "场景选项.md" --json "场景选项.json"
```

把 `体检报告.md` 发给用户（太长时先发总数、命名问题、设备调试清单和区域模式预览，房间清单留在文件里）。再加 `--lamps-out "灯具理解.json"` 存一份灯具理解表给自己用，不发给用户。报告里类型带「?」的，请用户确认是什么设备。`场景选项.md` 先留着，用户选「做场景」或「做自动化」时再发。

## 第 4 步：问下一步

对用户说（有命名问题时推荐 1；设备调试清单里有要改的键时推荐 2；否则推荐 3）：

> 「体检做完了。下一步想先做哪个？
> 1. 先优化设备信息：改名、分房间、标清开关每个键接的是哪盏灯、是什么灯（筒灯、射灯、灯带…）（推荐：名字清楚了，后面的场景和自动化才不会接错）
> 2. 调试设备：把控制智能灯的键、场景键、双控副开关改成无线，确认双控哪一路接着灯（做场景前必须先做）
> 3. 做场景：每个区域的明亮、休闲、温馨、放松、观影、就餐、睡眠、起夜，以及离家、全屋睡眠、回家
> 4. 做自动化：按房间做人来灯亮、日落定时、晨起开窗帘等
> 5. 调试已有的规则：不触发、导入失败、编辑器白屏」

用户回答后写进 `进度.md`，再按下面做。

### 选 1：优化设备信息

1. 按 `references/scenes-guide.md` 第 0 步的命名规则，给体检里的每条命名问题，以及「设备调试清单」里标「问客户」的键，配上**建议的新名字**，列给用户，例如：「米家智能门锁 → 入户门锁」「主卧床头开关：左键接主卧吸顶灯，右键设成无线键、用来切到睡眠模式」。
2. **设备名和房间**：请用户在米家 App 里改。改完后重新 `mijia_read("devices")` 覆盖 `devices.json`，重跑第 3 步。会话断了（`mijia_session_status` 不是 `ready`）就回第 2 步重新配对。
3. **开关每个键的名字**：MijiaFlow 读不到键名，所以要问用户每个键接的是什么，再写进台账（重新读取设备时会保留）：

   ```
   <python> "<技能目录>/scripts/device_registry.py" --mijiaflow-devices "devices.json" --out "设备台账.json" --set "<did>=主卧床头开关|主卧|主卧吸顶灯,无线键·睡眠"
   ```

   `--set` 的格式是 `did=设备名|房间|键1,键2`，键名按左到右的顺序。
4. 重跑 `home_report.py`，直到命名问题清零或用户说可以了，再回到第 4 步问下一步。

### 选 2：调试设备

读 `references/commissioning.md`，按体检报告的「设备调试清单」逐键做：先确认双控哪一路接着灯，再改无线、设来电上电，最后请用户按键核对。做完把键名写进台账，重跑体检。

### 选 3：做场景

1. **先建变量**（读 `references/scenes-guide.md` 第 2 步）：全屋家庭模式一个；客厅、餐厅、卧室这类区域各三个：模式、亮度、色温（`area_variables("客厅")`）。建之前跑 `check_mode_names()`。家庭模式变量：
   - 先 `mijia_read("variables", {"scope": "global"})`，已经有 `VhomeMode01` 就跳过。
   - 没有就按第 5 步的写入流程创建，计划用：
     `mijia_plan_change("create_variable", {"scope": "global", "id": "VhomeMode01", "type": "string", "value": "在家", "userData": {"name": "家庭模式"}})`
     （这些值就是 `scripts/scene_templates.py` 里 `home_mode_var_definition()` 返回的内容。）
2. **把场景选项发给用户挑**：`场景选项.md` 是脚本按用户家里的设备算出来的，**原样发给用户**，不要自己另编一份选项。请用户回复编号，例如「3、7、11」；拿不准的先选带 ⭐ 的。
   - 编号带小数点的（例如 23.1「离家时关空调」）是挂在场景下面的顺带动作，按 `references/devices.md` 写进那个场景的规则；用户没选就不加。「这些设备我还不熟」里的设备，按 `references/devices.md` 第四节查说明书后问一次。
   - 「现在」一栏写着「先调试」的，要先做选 2；写着「还差设备」的，说清缺什么，用户愿意加设备再做。
   - 「可选（要的话告诉我）」里的小爱提醒只问一次：「离家或睡觉时，要小爱提醒你窗没关、空调还开着吗？」用户说要才做，不要主动加。
   - 选项清单最后的「一起做好」是配套（家庭模式、双控、灯全关同步），用户选了任何区域场景就一起做，不用再问。
   - 每个选项用哪个模板、传什么参数，在 `场景选项.json` 的 `builder` 和 `params` 里。
   - 发之前你可以结合整个房间再看一遍：主灯、亮点、色温是否合理。要改效果，先改台账里灯的角色再重跑脚本，不要只改文字。
3. 对用户说的样子（起夜为例）：
   > 「起夜：睡眠模式下按床头任意键，灯关着就开到明亮（100%、4000K），开着就关；主卫没人了自动关灯，不做定时关。要用：主卧吸顶灯、主卧床头开关的右键（要设成无线模式）、主卫人在传感器。做吗？」
4. 问清参数：哪个键触发哪个区域模式（键名用模式全名，如「客厅温馨」）；哪些键切全屋模式；普通灯「按需」「只留一路」时开哪几路（`keep`）。设备逐个从台账 `confirmed` 条目里确认。氛围的默认亮度色温见 `references/lighting.md`，用户想改就改。
5. 只做用户选的编号。每个区域：选的每个模式一条 `build_area_mode_rule`，配一条灯全关同步 `build_area_off_sync_rule`；选了灯光跟随就加 `build_light_follow_rule(area=...)`。全屋做：`build_mode_switch_rule`（切全屋模式）、离家和全屋睡眠各一条 `build_home_cascade_rule`。卧室加起夜 `build_night_wake_rule(area=...)`，双控加 `build_dual_control_rule`。完整案例在 `examples/example_reference_cases.py`。生成见第 5 步。

### 选 4：做自动化

1. 和选 3 一样，把 `场景选项.md` 发给用户，请用户挑编号：人来灯亮、日落自动开灯、起床开窗帘、回家、定时开关、开着太久自动关、临时不让感应关灯、传感器低电量提醒等。
2. 人来灯亮（`build_presence_light_rule`）和晨起开窗帘（`build_sunrise_curtain_rule`）默认在「离家」模式下不执行，要用到家庭模式变量。网关上还没有 `VhomeMode01` 时，先做选 3 的第 1 步建变量；用户不要家庭模式，就传 `skip_modes=()`。
3. 每个模板的参数逐项和用户确认（用哪个传感器、哪几盏灯、几点关、照度阈值等），模板说明在 `scenes/*.json` 和 `references/scenes-guide.md`。
4. 日落、日出类模板要经纬度：问用户所在城市，用该城市大致的经纬度（保留两位小数）即可。
5. 生成规则，见第 5 步。

### 选 5：调试已有规则

读 `references/troubleshooting.md`，按里面的「症状 → 检查」表做。

## 第 5 步：生成规则并写入网关

1. **查设备能力**：每台要用到的设备都要知道 `urn`，以及 `siid`/`piid`（属性）或 `siid`/`eiid`（事件）。
   - `urn` 在台账里。台账里 `urn` 是空的：先看备份里有没有规则用过这台设备（台账的 `references` 字段），用 `mijia_read("automations", {"id": "<规则id>"})` 读出那条规则，照抄那个节点的 `cfg.urn` 和编号。
   - 编号按 urn 查官方 spec：`https://miot-spec.org/miot-spec-v2/instance?type=<完整urn>`，打不开就查 `https://home.miot-spec.com/spec/<型号>`（型号例如 `tnv.switch.sw2d01`）。
   - 按键事件编号、哪个键已设成无线模式，因型号和设置而异：查不到或拿不准就问用户，**不要猜**。最稳的做法是照抄网关上已有规则里同一设备的节点。
2. **写生成脚本**：在 `mijia-home-work` 新建一个 `.py` 文件：

   ```python
   import json, sys, time
   sys.path.insert(0, r"<技能目录>/scripts")
   from mijia_rule_kit import load_device_registry, resolve_confirmed_device, merge_import_set, check_import_set, dump_json
   from scene_templates import build_mode_switch_rule, home_mode_var_definition

   reg = load_device_registry("设备台账.json")
   sw = resolve_confirmed_device(reg, "主卧床头开关", room="主卧")      # 只认已确认、唯一的设备
   key = {"did": sw["did"], "urn": sw["urn"], "siid": 5, "eiid": 1,      # 编号按第 1 点查到的填
          "name": "主卧床头开关·右键"}                                    # name 会写进规则画布的备注卡

   base = int(time.time() * 1000)                                       # 规则 id：当前毫秒时间戳，每条加 1
   rules = [build_mode_switch_rule(str(base), [{"key": key, "mode": "全屋睡眠"}])]

   var_id, var_def = home_mode_var_definition()
   import_set = merge_import_set(rules, {var_id: var_def})              # 检查时总带上家庭模式变量，网关上已有也一样
   print(check_import_set(import_set) or "检查通过")
   for r in rules:
       dump_json(r, "规则-%s.json" % r["id"])
   ```

   - 规则 id 用毫秒时间戳字符串，先 `mijia_read("automations")` 确认没有重复。
   - 生成的规则都是停用的（`enable=False`）。
   - `check_import_set` 有问题先改，再往下。
   - 更多写法见 `<技能目录>/examples/example_home_modes.py` 和 `example_reference_cases.py`（占位设备，只能参考写法）。
   - 每条规则左上角会自动带一张备注卡（用途、触发、效果、设备、日期、技能版本）。不要删，客户和安装师傅靠它看懂规则。
3. **给用户看**：把每条规则备注卡上的文字发给用户（就是规则里 `type` 为 `nop` 的那张卡），例如「主卧床头开关右键按一下 → 家庭模式变成睡眠」。用户同意再写入。
4. **写入**（每条规则或每个变量分别做一遍）：
   1. `mijia_plan_change("set_graph", <规则-xxx.json 的内容：id、cfg、nodes>)`。变量用 `create_variable`，见选 3。
   2. `mijia_create_backup({"fileName": "写入前-<日期>.bak", "outputDir": "<mijia-home-work 完整路径>", "cloud": false})`。
   3. 把计划给出的差异和**一次性确认语**告诉用户，请用户**自己**把确认语原样发给你。
   4. 用户发来后：`mijia_apply_change(planToken, backupReceipt, 用户发来的确认语)`。planToken 和 backupReceipt 原样传，不要改。
   5. 回读核对：`mijia_read("automations", {"id": "<规则id>"})`。
   6. 结果不对要撤回：用 apply 返回的 `changeId` 和它给出的撤回确认语调 `mijia_rollback(changeId, 撤回确认语)`，撤回确认语同样请用户自己发来。这些凭据在会话结束或重启后就失效，要撤回就在本次会话里做。
5. **只读模式**：第 2 步 probe 是只读时，不能用上面的写入。按 `references/console.md` 的「控制台导入 .bak」做：从最新完整备份合并新规则，整包导入。
6. **启用和验证**：
   - 规则写入后仍是停用状态。用户明确说启用时，再按第 4 点的流程写入，计划用 `mijia_plan_change("set_graph_enabled", {"id": "<规则id>", "enabled": true})`。
   - 请用户在浏览器打开 `http://<网关IP>/`，在极客版控制台里点开这条规则，确认编辑器能正常显示。页面一片空白，就读 `references/platform-notes.md` 里讲枚举属性必须用 `include` 的那一条（写错会白屏）。
   - 请用户实际触发一次（按键、走进房间），再用 `mijia_read("logs", {"pages": 3})` 找这条规则的执行记录。MijiaFlow 自带的 `mijiaflow://guide/log-diagnosis` 资源和 `mijia_diagnose` 提示词讲了怎么看日志。看到真实执行记录后，才告诉用户成功。
7. `进度.md` 记下写入了哪些规则、是否启用、验证结果。

## 结束一次调试

- 调用 `mijia_end_session()`。
- 给用户一段小结：做了什么、哪些规则还停用、下一步建议，末尾附「米家全屋智能 skills：https://zhijipro.cn/skills/」。
- 本次碰到了技能本身的问题时，按 `references/feedback.md` 问用户要不要反馈。
