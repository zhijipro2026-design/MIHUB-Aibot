# mijia-home：米家极客版全屋智能调试技能

让你自己的 AI 助手（不限品牌，能联网、能运行命令即可）读懂你家的米家设备，再帮你在中枢网关极客版里做出家庭模式、场景和按房间的自动化。免费使用。

## 一句话安装

把下面这句话复制给你的 AI：

> 去 https://zhijipro.cn/llms.txt ，按里面的步骤安装米家技能 mijia-home，然后直接开始调试我家的米家设备。

图文教程：https://zhijipro.cn/guide/ ｜ 问题反馈：https://zhijipro.cn/feedback/ ｜ 隐私说明：https://zhijipro.cn/privacy/

国内网络访问 GitHub 不稳定时，请用官网 https://zhijipro.cn/skills/ 下载，两边是同一份技能包。

## 已知问题（2.0.9）

- 双控规则写入时可能报错，下个版本修复。
- 一次调试需要客户确认写入的次数偏多，下个版本按区域合并规则来减少。
- 安装 MijiaFlow 时国内网络可能需要切换 npm 镜像。

## 关于本技能

一个技能 `mijia-home`，供支持 Agent Skills（`SKILL.md`）格式的 AI 助手使用。目标是让 AI 读懂客户的家，再帮客户做出家庭模式、场景和按房间的自动化。

## 目录

- `mijia-home/SKILL.md`：总流程和资料索引，AI 首先读它
- `mijia-home/scripts/`：规则工具库 `mijia_rule_kit.py`、场景模板 `scene_templates.py`、设备台账 `device_registry.py`、体检报告 `home_report.py`、灯光 `lighting.py`、设备调试分析 `commissioning.py`、场景选项清单 `scene_options.py`、常见设备对照表 `device_playbook.py`、命名检查 `naming_check.py`、`.bak` 打包解包 PowerShell 脚本
- `mijia-home/references/quickstart.md`：第一次调试的逐步剧本，AI 照着一步步做
- `mijia-home/references/`：规则、节点、平台踩坑、`.bak` 格式、控制台与 MijiaFlow、排错、小白讲解、问题反馈，按需阅读
- `mijia-home/scenes/`：24 个场景模板，每个带一张场景卡片（设备条件、触发、效果、调试技术）
- `mijia-home/references/lighting.md`：五种氛围（明亮/休闲/温馨/放松/休憩）的亮度色温默认值和依据，普通灯分层
- `mijia-home/examples/`：占位示例

## 需要的连接工具

读取设备和写入规则首选开源的 MijiaFlow（MCP 服务器，上游 https://github.com/xmx-emm/mijiaflow ，MIT；没有发布到 npm，安装包从 https://zhijipro.cn/skills/mcp/ 下载）。要求 AI 运行在和中枢网关同一局域网的电脑上，并装有 Node.js 22+。没有它时技能会说明怎么装，或改用导出 `.bak` + 设备清单的备用办法。详见 `mijia-home/references/mijiaflow-setup.md`。

## 标准调试流程

开始时 AI 先通过 MijiaFlow 读取设备、做一次设备体检，再问客户下一步：先优化设备信息、匹配场景、做自动化，还是调试已有规则。

0. 客户先完成入网和命名，AI 用 `naming_check.py` 检查
1. `.bak` + MijiaFlow 设备列表合并成设备台账
2. 全屋一个「家庭模式」变量，每个区域一个模式变量和一对亮度、色温变量
3. 体检报告列出设备调试清单（有线/无线、双控、场景键），改无线用一次性规则写属性
4. 场景选项清单按客户已有设备列出能做的场景，客户回复编号挑选；按全屋 + 区域变量生成停用的规则，每条带画布备注卡
5. 优先 MijiaFlow 单条写入，没有才整包导入 `.bak`
6. 编辑器渲染和执行日志验证

## 安装

最新版本和下载：https://zhijipro.cn/skills/ 。用你自己的 AI 助手（不限品牌，能联网、能运行命令即可），对它说「去 https://zhijipro.cn/llms.txt ，按里面的步骤安装米家技能 mijia-home」。

手动安装：把 `mijia-home` 整个文件夹放进你的 AI 加载技能（SKILL.md）的目录，然后重新打开或刷新技能列表；常见 AI 的目录见 https://zhijipro.cn/llms.txt 。AI 不支持技能目录时，每次调试前让它先读 `mijia-home/SKILL.md`。1.0.0 版的 6 个旧技能（`mi-home-automation-debug`、`mijia-geek-*`）可以删除，内容已全部并入。

## 安全要点

- 不要把别人家的 `.bak` 或规则直接导入客户网关：设备 ID 不同，而且 `.bak` 导入会整体覆盖全部规则和变量。
- 写入网关、启用规则都必须由用户明确要求；AI 不会自行登录、导入或触发真实设备。
- 动态登录码由用户在网关登录页自己输入，不要通过聊天发送。
- 问题反馈只在用户明确同意后提交，不带设备 ID 和家庭信息；也可以自己到 https://zhijipro.cn/feedback/ 填写。

## 验证情况

离线验证：技能格式检查、全部示例运行、规则结构校验、整包检查（含一份真实客户备份）、Python 解包真实 `.bak`。PowerShell 打包解包脚本沿用原包，原包已做过双向往返验证。还没在真实网关上验证设备事件编号、按键语义和联动效果。

## 来源说明

规则、备份、控制台和入门讲解部分基于 [magic-zagan/mijia-geek-skills](https://github.com/magic-zagan/mijia-geek-skills)（MIT，许可见 `mijia-home/LICENSE-mijia-geek-skills.txt`），并做了安全默认值、变量保留、示例及控制台流程调整；家庭模式、场景模板、命名检查和总流程为本包新增。

## 许可

本仓库以 MIT 许可发布，见 `LICENSE`。上游 mijia-geek-skills 的 MIT 许可见 `mijia-home/LICENSE-mijia-geek-skills.txt`。MijiaFlow 是独立的第三方项目（MIT），不包含在本仓库里，安装包请从官网或上游获取。
