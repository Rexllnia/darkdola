# darkdola

> 把你的浏览器变成 AI Agent 的推理引擎。

darkdola 是一个基于 **Model Context Protocol (MCP)** 的轻量级 AI Agent 运行时。它最特别的地方在于：不调用付费 LLM API，而是通过 Playwright 操控已经登录的**豆包（Doubao）网页版**来充当推理后端，同时把 MCP 工具生态完整接入 **ReAct（Think → Act → Observe）** 循环。

---

## 为什么是 darkdola

大多数 Agent 框架要求你持有 OpenAI / Anthropic 的 API Key，按 token 付费。darkdola 走了一条完全不同的路：

- **零 API 成本**：推理直接复用你浏览器里已登录的豆包会话，不需要额外购买 LLM 额度。
- **完整 MCP 工具支持**：通过 stdio 启动任意 MCP Server，自动把工具清单注入 ReAct 提示词，模型在"思考"后可以主动调用工具。
- **ReAct 循环原生实现**：每一轮强制输出 `Thought → Action(JSON) → 等待 Observation`，最多 20 轮工具调用，防止无限循环。
- **SSE 流式输出**：豆包返回的增量内容会经过 SSE 解析器逐块推送给下游，而不是等完整回复再处理。
- **多实例编排**：一条命令拉起 N 个 worker，配合信号清理，`Ctrl+C` 时干净退出。

---

# 快速开始

> 5 分钟把 darkdola 跑起来。不需要 `pip install` 本体，clone 下来直接跑。

## 前置条件

| 依赖 | 要求 | 检查命令 |
| :--- | :--- | :--- |
| Python | ≥ 3.10 | `python3 --version` |
| Google Chrome | 任意稳定版 | `google-chrome --version` |
| 豆包账号 | 已注册，能正常登录网页版 | 浏览器打开 [doubao.com](https://www.doubao.com/) |
| Node.js | ≥ 18（**可选**，用 `npx` 启动 MCP Server 时需要） | `node --version` |

> 没有 Node.js 也能跑：只要你的 MCP Server 是用 Python、二进制或其他方式启动的，就不需要 `npx`。

---

## 第 1 步：克隆并安装依赖

```bash
git clone https://github.com/Rexllnia/darkdola.git
cd darkdola

uv venv --python 3.13

# 激活并重新安装依赖
source .venv/bin/activate
uv pip install -r requirements.txt

python -m playwright install chromium
```

> 本项目**不需要** `pip install .`。所有模块通过工程根目录直接 import，`git clone` 后即可运行。

每次开新终端需要重新激活 venv：

```bash
source .venv/bin/activate
```

---

## 第 2 步：首次登录豆包

```bash
python darkdola.py 1
```

会发生三件事：

1. 弹出一个 Chrome 窗口，打开 `https://www.doubao.com/`。
2. 在窗口里**手动完成豆包登录**（扫码或账号密码都行）。
3. 登录成功后，**回到终端按回车**。

终端会打印：

```text
状态已保存到 ~/.darkdola/save.json
```

登录态只保存这一次，后续启动自动复用。如果以后失效（豆包强制重新登录），删掉 `~/.darkdola/save.json` 再跑一次 `python main.py` 即可。

---

## 第 3 步：配置 MCP 工具（可选）

如果暂时不需要工具，跳过这步，直接看第 4 步。darkdola 在没有工具时仍然能纯对话。

编辑 `data/mcp_servers.json`，加一个 MCP Server。以官方 filesystem server 为例（需要 Node.js）：

```json
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
```

> 把 `/home/你的用户名/workspace` 换成你希望模型能读写的真实目录。**不要**直接指向 `~` 或 `/`。

启动时 darkdola 会通过 `stdio_client` 拉起这个 Server，`list_tools()` 拿到工具清单后注入 ReAct 提示词。

---

## 第 4 步：启动

```bash
python darkdola.py 4
```

`4` 是 worker 实例数。想并发跑多路任务就写 `python darkdola.py 2`、`python darkdola.py 4`，每个 worker 独占一个浏览器上下文。

启动过程会依次打印：

```text
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
```

---

# 架构

```text
┌──────────────────────────────────────────────────────┐
│  darkdola.py  (launcher)                             │
│  拉起 brewer-nash-dispatcher + apikey-server + N×main│
└──────────────────────┬───────────────────────────────┘
                       │  python main.py
                       ▼
┌──────────────────────────────────────────────────────┐
│  main.py                                             │
│  asyncio.gather(playwright_task, mcp_client_task,   │
│                  worker_recv)                        │
└──────┬──────────────────────┬────────────────────────┘
       │                      │
       ▼                      ▼
┌──────────────┐      ┌──────────────────┐
│ Playwright   │      │ mcp_client.py    │
│ 打开豆包网页  │      │ stdio 启动 MCP   │
│ 注入 SSE Hook│      │ 注册工具清单      │
└──────┬───────┘      └────────┬─────────┘
       │                       │
       ▼                       ▼
┌──────────────┐      ┌──────────────────┐
│ DoubaoSender │      │ reasoning_acting │
│ 写入文本框   │      │ ReAct 提示词     │
│ 上传文件     │      │ Thought/Action   │
└──────────────┘      └──────────────────┘
```

**数据流**：用户问题 → `worker_recv` → 豆包页面 → SSE Hook 捕获回复 → `parse_tool_call` 提取工具调用 → `mcp_client.toolcall` 执行 → 结果作为 Observation 回注 → 豆包继续推理 → 最终答案。

---

# ReAct 循环

darkdola 的系统提示词要求模型**每一轮只输出两种形式之一**：

**需要调用工具时：**

```text
Thought: 这是纯计算任务，应调用 Python 解释器。
{"name": "python_execute", "arguments": {"code": "print(2 ** 10)"}}
```

**信息已足够时：**

```text
Thought: 工具返回 1024，已经得到答案。
Final Answer: 2 的 10 次方等于 1024。
```

关键约束：

- 调用工具前必须先输出 `Thought`。
- `name` 必须精确匹配工具清单中的名字。
- `arguments` 必须符合对应 `input_schema`。
- 工具报错时，下一个 `Thought` 必须分析原因，不能直接放弃。

---

# 工具调用解析

豆包网页版返回的是自然语言流，而不是结构化的 `tool_calls` 字段。`parse_tool_call.py` 从混合文本中按括号配对扫描 JSON 块，再逐个识别多种格式：

- **MCP JSON-RPC**：`{"method": "tools/call", "params": {"name": ..., "arguments": ...}}`
- **Anthropic**：`{"type": "tool_use", "name": ..., "input": ...}`
- **OpenAI**：`{"function": {"name": ..., "arguments": "{...}"}}`
- **Gemini**：`{"functionCall": {"name": ..., "args": ...}}`
- **通用简写**：`{"name": ..., "arguments": ...}`

即使模型"幻觉"出了别家格式，也能被归一化成统一的 `ParsedToolCall`。

---

# 验证是否正常

### 日志有没有动

```bash
tail -f ~/.darkdola/raw_log.json
```

有内容滚动说明 SSE Hook 正在捕获豆包的流式回复。

### worker 进程是否活着

```bash
ps aux | grep -E "main.py|brewer-nash" | grep -v grep
```

应该看到 3 类进程：`brewer-nash-dispatcher`、`brewer-nash-dispatcher-openai-apikey-server`、`main.py`。

### 工具调用日志

```bash
tail -f ~/.darkdola/log/调用结果.txt
```

模型触发工具时会写这里。如果一直为空，说明还没触发过工具调用（纯对话不写这个文件）。

### Ctrl+C 清理是否干净

在启动终端按 `Ctrl+C`，应该看到：

```text
收到终止信号，杀死所有后台子进程...
全部进程已清理完毕
```

再跑一次 `ps aux | grep -E "main.py|brewer-nash" | grep -v grep`，应该没有任何输出。

---

# 项目结构

```text
darkdola/
├── darkdola.py            # 编排入口：多进程 launcher
├── main.py                # 单 worker 入口：Playwright + MCP + Worker 并发
├── reasoning_acting.py    # ReAct 提示词构建（Thought / Action / Observation）
├── mcp_client.py          # MCP Server 生命周期 + 工具调用
├── parse_tool_call.py     # 多厂商工具调用格式提取
├── sender.py              # 抽象 Sender + 请求队列
├── sse_hook.py            # SSE 事件解析基类
├── tool_contract.py       # ToolCallStatus 枚举
├── worker.py              # WorkerClient 注册与收发
├── requirements.txt       # 依赖清单
├── doubao/
│   ├── doubao_sender.py   # 豆包页面操作：填文本框、上传文件、回车发送
│   └── doubao_sse_hook.py # 豆包 SSE 事件 → 文本增量 → 工具调用
└── data/
    ├── fetch_hook.js      # 注入页面的 fetch Hook
    └── mcp_servers.json   # MCP Server 配置
```

---

# 常见问题

**Q：`python darkdola.py` 报 `No module named darkdola.__main__`**

你运行的是旧版编排器（内部用了 `-m darkdola`）。确认 `darkdola.py` 里 worker 启动是 `[sys.executable, "main.py"]`，不是 `-m darkdola`。

**Q：`FileNotFoundError: fetch_hook.js`**

`main.py` 里 `add_init_script` 的路径没跟上文件搬迁。改成：

```python
from importlib.resources import files
hook_path = files("data") / "fetch_hook.js"
await context.add_init_script(path=str(hook_path))
```

或者用 `__file__` 定位：

```python
import os
hook_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "fetch_hook.js")
```

**Q：Chrome 没弹出来 / 秒退**

项目用 `channel="chrome"` 启动**系统 Chrome**，不是 Playwright 自带 chromium。确认：

```bash
google-chrome --version   # Linux
```

macOS 检查 `/Applications/Google Chrome.app` 是否存在。没装就去 [google.com/chrome](https://www.google.com/chrome/) 装一个。

**Q：豆包回复了但没触发工具**

检查 `data/mcp_servers.json` 是否配置正确，以及启动日志里有没有 `list_tools` 相关输出。工具清单为空时模型不会主动调用。

**Q：多实例时日志交错**

`raw_log.json` 目前是全局单文件，N 个 worker 同时写会混在一起。调试多实例时建议改成按 pid 分文件：

```python
RAW_LOG = USER_DIR / f"raw_log_{os.getpid()}.json"
```

**Q：`ImportError: cannot import name 'openai_server_main'`**

这是 `brewer-nash-dispatcher-openai-apikey-server` 这个依赖包自身的入口 bug，和 darkdola 无关。在它的 `openai_api_server.py` 里补一个同步 wrapper：

```python
def openai_server_main():
    import asyncio
    asyncio.run(openai_api_server_task())
```

---

# 停止与卸载

**停止**：在 `python darkdola.py N` 终端按 `Ctrl+C`，编排器会清理所有子进程。

**卸载**（因为没 `pip install` 本体，只需清理本地环境）：

```bash
deactivate 2>/dev/null || true
rm -rf .venv
rm -rf ~/.darkdola        # 会删除登录态和日志，谨慎
```

---

# 已知限制

- **豆包网页版 UI 变更**：`DoubaoSender` 依赖 `contenteditable` 文本框和上传按钮的 CSS 选择器，豆包改版可能导致发送失败。
- **串行 worker**：每个 worker 独占一个浏览器上下文和一条推理链路，N 个 worker 之间不共享对话历史。
- **工具调用轮数上限**：单次任务最多 20 轮 ReAct 工具调用，超过后强制输出 `Final Answer`。
- **登录态存储**：`save.json` 包含有效的豆包会话，请勿提交到版本库。

---

# 许可证

MIT License。详见 [LICENSE](LICENSE)。