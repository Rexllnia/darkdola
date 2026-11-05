import asyncio
import json
import os
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from sender import llm_request_queue
from tool_contract import ToolCallStatus
import reasoning_acting


# ---------------------------------------------------------------------------
# 全局状态
# ---------------------------------------------------------------------------

TOOL_SCHEMAS: dict[str, dict] = {}
TOOL_TO_SESSION: dict[str, ClientSession] = {}
TOOL_TO_SERVER: dict[str, str] = {}
TOOL_DESCRIPTIONS: dict[str, str] = {}

manual_mode = False

# 等待所有 MCP server 就绪的最长时间（秒）
SERVER_READY_TIMEOUT = 60

CONFIG_PATH = Path(__file__).parent / "data/mcp_servers.json"


# ---------------------------------------------------------------------------
# 工具调用
# ---------------------------------------------------------------------------

def _is_error(result) -> bool:
    """兼容 mcp 不同版本：内部字段可能是 is_error 或 isError。"""
    for attr in ("is_error", "isError"):
        if hasattr(result, attr):
            return bool(getattr(result, attr))
    return False


async def toolcall(name, arguments) -> tuple[str, ToolCallStatus]:
    sess = TOOL_TO_SESSION.get(name)
    if sess is None:
        return f"error: unknown tool `{name}`", ToolCallStatus.NOT_FOUND

    tool_result = await sess.call_tool(name, arguments)
    text = "\n".join(getattr(b, "text", str(b)) for b in tool_result.content)

    if _is_error(tool_result):
        schema = TOOL_SCHEMAS.get(name)
        if schema:
            text += "\ninput_schema: " + json.dumps(schema, ensure_ascii=False)
        return text, ToolCallStatus.FAILED

    return text, ToolCallStatus.SUCCESS


# ---------------------------------------------------------------------------
# 工具快照：把 MCP 注册表转成 ReAct 层需要的中立结构
# ---------------------------------------------------------------------------

def get_tools_snapshot() -> list[dict]:
    """只导出 name / server / description / schema。

    TOOL_TO_SESSION 是运行时连接对象，不进快照，也不进提示词。
    """
    return [
        {
            "name": name,
            "server": TOOL_TO_SERVER.get(name),
            "description": TOOL_DESCRIPTIONS.get(name) or "",
            "schema": schema,
        }
        for name, schema in TOOL_SCHEMAS.items()
    ]


# ---------------------------------------------------------------------------
# 配置加载
# ---------------------------------------------------------------------------

def _load_servers() -> dict[str, StdioServerParameters]:
    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    params: dict[str, StdioServerParameters] = {}
    for name, s in cfg["mcpServers"].items():
        params[name] = StdioServerParameters(
            command=s["command"],
            args=s.get("args", []),
            env=s.get("env") or None,
        )
    return params


# ---------------------------------------------------------------------------
# MCP server 生命周期
# ---------------------------------------------------------------------------

async def _run_server(
    name: str,
    server_params: StdioServerParameters,
    ready_event: asyncio.Event,
):
    try:
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as mcp_session:
                await mcp_session.initialize()

                result = await mcp_session.list_tools()
                for tool in result.tools:
                    desc = getattr(tool, "description", None) or ""
                    schema = (
                        getattr(tool, "input_schema", None)
                        or getattr(tool, "inputSchema", None)
                        or {}
                    )

                    print(f"[{name}] {tool.name}")
                    print(desc)
                    print(schema)
                    print("=" * 80)

                    TOOL_SCHEMAS[tool.name] = schema
                    TOOL_TO_SESSION[tool.name] = mcp_session
                    TOOL_TO_SERVER[tool.name] = name
                    TOOL_DESCRIPTIONS[tool.name] = desc

                ready_event.set()
                await asyncio.Event().wait()
    except Exception as e:
        # 单个 server 失败不应拖垮整体；标记就绪，避免主任务死等
        print(f"[{name}] MCP server 启动或运行失败: {e!r}")
        ready_event.set()
        return


async def mcp_client_task():
    servers = _load_servers()

    ready_events = {name: asyncio.Event() for name in servers}
    server_tasks = [
        asyncio.create_task(_run_server(name, params, ready_events[name]))
        for name, params in servers.items()
    ]

    # 等所有 server 完成 list_tools
    try:
        await asyncio.wait_for(
            asyncio.gather(*(ev.wait() for ev in ready_events.values())),
            timeout=SERVER_READY_TIMEOUT,
        )
    except asyncio.TimeoutError:
        missing = [n for n, ev in ready_events.items() if not ev.is_set()]
        print(f"[mcp_client] 等待 server 就绪超时，未就绪: {missing}")

    # 工具就绪，交给 ReAct 层构建并发送初始化提示词
    await reasoning_acting.init_react_agent(
        tools=get_tools_snapshot(),
        send_fn=llm_request_queue.put,
    )

    await asyncio.gather(*server_tasks)