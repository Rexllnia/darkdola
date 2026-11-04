darkdola
把你的浏览器变成 AI Agent 的推理引擎。

darkdola 是一个基于 Model Context Protocol (MCP) 的轻量级 AI Agent 运行时。它最特别的地方在于：不调用付费 LLM API，而是通过 Playwright 操控已经登录的豆包（Doubao）网页版来充当推理后端，同时把 MCP 工具生态完整接入 ReAct（Think → Act → Observe）循环。

为什么是 darkdola
大多数 Agent 框架要求你持有 OpenAI / Anthropic 的 API Key，按 token 付费。darkdola 走了一条完全不同的路：

零 API 成本：推理直接复用你浏览器里已登录的豆包会话，不需要额外购买 LLM 额度。

完整 MCP 工具支持：通过 stdio 启动任意 MCP Server，自动把工具清单注入 ReAct 提示词，模型在“思考”后可以主动调用工具。

ReAct 循环原生实现：每一轮强制输出 Thought → Action(JSON) → 等待 Observation，最多 20 轮工具调用，防止无限循环。

SSE 流式输出：豆包返回的增量内容会经过 SSE 解析器逐块推送给下游，而不是等完整回复再处理。

多实例编排：一条命令拉起 N 个 worker，配合信号清理，Ctrl+C 时干净退出。


#快速开始
5 分钟把 darkdola 跑起来。

##前置条件
依赖	要求	检查命令
Python	≥ 3.10	python3 --version
Google Chrome	任意稳定版	google-chrome --version
豆包账号	已注册，能正常登录网页版	浏览器打开 doubao.com
Node.js	≥ 18（可选，用 npx 启动 MCP Server 时需要）	node --version
没有 Node.js 也能跑：只要你的 MCP Server 是用 Python、二进制或其他方式启动的，就不需要 npx。

##第 1 步：安装
bash
git clone https://github.com/Rexllnia/darkdola.git
cd darkdola
chmod +x install.sh
./install.sh
脚本会自动完成：创建 .venv → 安装 darkdola 和 Playwright → 检查系统 Chrome → 生成 data/mcp_servers.json → 创建 ~/.darkdola/ → 验证 darkdola 命令。

看到下面这段就成功了：

text
========================================
  darkdola 安装完成
========================================
每次开新终端都需要激活环境：

bash
source .venv/bin/activate
##第 2 步：首次登录豆包
bash
python main.py
会发生三件事：

弹出一个 Chrome 窗口，打开 https://www.doubao.com/。

在窗口里手动完成豆包登录（扫码或账号密码都行）。

登录成功后，回到终端按回车。

终端会打印：

text
状态已保存到 ~/.darkdola/save.json
登录态只保存这一次，后续启动自动复用。如果以后失效（豆包强制重新登录），删掉 ~/.darkdola/save.json 再跑一次 python main.py 即可。

##第 3 步：配置 MCP 工具（可选）
如果暂时不需要工具，跳过这步，直接看第 4 步。darkdola 在没有工具时仍然能纯对话。

编辑 data/mcp_servers.json，加一个 MCP Server。以官方 filesystem server 为例（需要 Node.js）：

json
{
  "servers": {
    "filesystem": {
      "command": "npx",
      "args": [
        "-y",
        "@modelcontextprotocol/server-filesystem",
        "/home/你的用户名/workspace"
      ]
    }
  }
}
把 /home/你的用户名/workspace 换成你希望模型能读写的真实目录。不要直接指向 ~ 或 /。

启动时 darkdola 会通过 stdio_client 拉起这个 Server，list_tools() 拿到工具清单后注入 ReAct 提示词。

##第 4 步：启动
bash
darkdola 1
1 是 worker 实例数。想并发跑多路任务就写 darkdola 2、darkdola 4，每个 worker 独占一个浏览器上下文。

启动过程会依次打印：

text
[1] 启动 brewer-nash-dispatcher (后台)
brewer-nash-dispatcher pid: 12345
[2] 启动 brewer-nash-dispatcher-openai-apikey-server (后台)
brewer-nash-dispatcher-openai-apikey-server pid: 12346
[3] 启动 1 份 darkdola main 实例
启动 darkdola #0
darkdola #0 pid: 12347
=====================================
全部服务已启动。按 Ctrl+C 停止全部进程
=====================================

