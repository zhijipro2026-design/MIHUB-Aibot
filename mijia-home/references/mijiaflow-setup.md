# 连接网关：MijiaFlow 安装与替代办法

本技能读取设备和写入规则，首选 **MijiaFlow**：一个开源、非官方的米家中枢网关 MCP 服务器（MIT 许可，上游 https://github.com/xmx-emm/mijiaflow ，作者 xmx-emm，许可证随安装包附带）。任何支持 MCP（stdio）的 AI 客户端都能用。

> ⚠️ MijiaFlow **没有发布到 npm**。`npx -y mijiaflow`、`claude mcp add mijiaflow -- npx -y mijiaflow` 这类写法都会失败（404）。MijiaFlow 自带的 README 和 MCP 资源里还写着这些旧写法，不要照着把配置改回去。一律用 zhijipro.cn 提供的安装包和下面带 `--package=` 的写法。

## 先判断能不能用

1. 看自己的工具列表里有没有 `mijia_probe`、`mijia_begin_session`、`mijia_read`。有就直接跳到「读取设备」。
2. 没有，就照实告诉用户还没有连接网关的工具，让用户选：装 MijiaFlow，或用备用办法。不要假装已经读到设备。

## 安装 MijiaFlow

**前提**（缺一条就装不上，先和用户确认）：
- AI 运行在**和中枢网关同一个局域网**的电脑上。运行在云端、连不到家里局域网的 AI 用不了，只能走备用办法。
- 这台电脑装有 Node.js v22 或更高（`node -v`）。没有就请用户到 https://nodejs.org/ 装 LTS 版（Windows 也可以 `winget install OpenJS.NodeJS.LTS`），装完重启 AI 客户端。
- 用户能在米家 App 里拿到中枢网关的六位登录码。

**第一步：下载安装包并核对**
1. 读 https://zhijipro.cn/skills/index.json 的 `mcp.mijiaflow`，取 `url`、`sha256`、`file`。
2. 下载到用户主目录下的 `.mijiaflow` 文件夹（没有就新建），原样保存，算 sha256，和清单不一致就停止并告诉用户：
   - Windows PowerShell：
     ```
     New-Item -ItemType Directory -Force "$HOME\.mijiaflow"
     Invoke-WebRequest "<url>" -OutFile "$HOME\.mijiaflow\<file>"
     Get-FileHash "$HOME\.mijiaflow\<file>" -Algorithm SHA256
     ```
   - macOS / Linux：
     ```
     mkdir -p ~/.mijiaflow && curl -fsSL "<url>" -o ~/.mijiaflow/<file>
     shasum -a 256 ~/.mijiaflow/<file>
     ```
3. **必须先试运行一次**，成功再改配置：`npx -y --package="<安装包完整路径>" mijiaflow --version`，应输出版本号（如 `0.2.0`）。第一次会从 npm 下载几个依赖包。
   - 很慢或超时（国内网络常见）：先运行 `npm config set registry https://registry.npmmirror.com`，再试一次。

**第二步：加进 AI 客户端的 MCP 设置**

把 `<安装包完整路径>` 换成上面文件的绝对路径。Windows 路径在 JSON 里用 `/`，例如 `C:/Users/zhangsan/.mijiaflow/mijiaflow-0.2.0.tgz`。改哪个文件先告诉用户；文件里已有其他 MCP 服务器时，只加 `mijiaflow` 这一项，不要删别的。

多数客户端用这一段（键名 `mcpServers`）：

```json
{
  "mcpServers": {
    "mijiaflow": { "command": "npx", "args": ["-y", "--package=<安装包完整路径>", "mijiaflow"] }
  }
}
```

- Windows 上客户端启动不了 `npx` 时，改成 `"command": "cmd", "args": ["/c", "npx", "-y", "--package=<安装包完整路径>", "mijiaflow"]`。
- 常见客户端的配置位置（按字母排序，仅供参考，以你自己的文档为准）：
  - Claude Code：命令 `claude mcp add mijiaflow -- npx -y --package=<安装包完整路径> mijiaflow`
  - Claude Desktop：`claude_desktop_config.json`（Windows `%APPDATA%\Claude\`，macOS `~/Library/Application Support/Claude/`）
  - Cline：它的 MCP 服务器设置文件，结构同上
  - Codex CLI：`~/.codex/config.toml`，写成：
    ```toml
    [mcp_servers.mijiaflow]
    command = "npx"
    args = ["-y", "--package=<安装包完整路径>", "mijiaflow"]
    ```
  - Cursor：全局 `~/.cursor/mcp.json`，或项目内 `.cursor/mcp.json`
  - Gemini CLI：`~/.gemini/settings.json`
  - VS Code：`.vscode/mcp.json`，外层键名是 `servers` 而不是 `mcpServers`
  - Windsurf：`~/.codeium/windsurf/mcp_config.json`
  - 其他客户端：有「添加 MCP 服务器」的设置页或命令就用它，命令和参数同上；找不到就问用户。

**第三步：让工具出现**

改完配置要重新加载，告诉用户怎么做：
- 命令行类 AI（终端里运行的）：退出后重新启动。
- 编辑器插件类（Cursor、VS Code、Cline 等）：在 MCP 设置里点刷新/重新加载，或重启编辑器。
- 桌面 App 类：完全退出 App（包括托盘图标）再打开。
- 其他：新开一个对话；还不行就重启客户端。

重新加载后，用户对你说「继续米家调试」，你按 `references/quickstart.md` 读 `进度.md` 接着做。

## 读取设备（只读）

具体步骤和要对用户说的话见 `references/quickstart.md` 第 2 步。要点：
1. `mijia_probe("http://<网关IP>/")`：记下能力模式。版本不匹配时 MijiaFlow 只读，只能读取，写规则要走控制台整包导入。
2. `mijia_begin_session(同一地址)`：给用户本机 `127.0.0.1` 页面，用户**自己**在页面输入登录码。每个页面只能提交一次；失败了就重新调用 `mijia_begin_session` 拿新页面。
3. `mijia_session_status()` 到 `ready` 后，`mijia_read("devices")`，把返回的 JSON 文本原样存成 `mijia-home-work/devices.json`。
4. `mijia_create_backup({"fileName": "备份-<日期>.bak", "outputDir": "<mijia-home-work 完整路径>", "cloud": false})`。
5. 用 `scripts/device_registry.py` 建台账，用 `scripts/home_report.py` 出体检报告。
6. 结束时 `mijia_end_session()`。

## 常见失败

- **重启后工具不出现**：配置文件改错了位置或 JSON 格式错（多了逗号、路径里用了 `\`）；路径不对；Node 版本低于 22；客户端不支持 MCP。先在终端手动跑一遍试运行命令，能输出版本号，再查配置。
- **试运行报 404 或找不到 mijiaflow**：用了旧写法 `npx -y mijiaflow`，改成带 `--package=` 的写法。
- **试运行卡住或超时**：换国内 npm 源（见上），再试。
- **probe 连不上**：IP 写错；电脑和网关不在同一网段（比如电脑连的是访客 Wi-Fi）；AI 跑在云端。
- **配对失败或一直不 ready**：登录码过期或输错。重新 `mijia_begin_session`，请用户拿新码在新页面输入。
- **probe 显示只读**：网关极客版版本和 MijiaFlow 不匹配。读取照常；写入改用控制台整包导入（`references/console.md`）。

## 备用办法（没有 MijiaFlow 时）

能做的事少一些、手工多一些，要先跟用户说清楚。`.bak` 只含**已经在规则里出现过**的设备，而且没有设备名和房间，所以要多做一步「台账采集」：

1. 请用户打开极客版控制台（浏览器打开 `http://<网关IP>/`，用米家 App 里的登录码登录），先「恢复与备份 → 备份至本地」导出一份备份，作为采集前的退路。
2. 请用户新建一条规则，命名为 `_台账采集`，**保持停用**。把每台要用的设备拖一张卡片进去（多键开关每个键各一张），**不要连线**，保存。具体做法见 `references/console.md`「从零建立设备台账」。
3. 请用户再导出一份完整备份发给你，同时发一张画布截图（卡片上会显示设备名和房间）。
4. 运行 `<python> "<技能目录>/scripts/device_registry.py" "<新备份.bak>" --out "设备台账.json"`：台账里会列出每张卡片对应的 did。
5. 用备份里每个节点的 `cfg.pos` 坐标对照截图上的卡片位置，确认每个 did 是哪台设备，再逐个用 `--set "did=设备名|房间|键1,键2"` 写进台账。对不上的设备不要写。
6. 运行 `home_report.py` 出体检报告，然后回到 `references/quickstart.md` 第 4 步。

这条路上：
- 改了设备名以后，要重新做第 2–5 步才能更新台账。
- 生成的规则只能在控制台整包导入，会覆盖网关上全部规则和变量。导入前按 `references/console.md` 重新导出核对，并给用户看差异。
- 台账确认后，可以请用户删掉 `_台账采集` 这条规则。
