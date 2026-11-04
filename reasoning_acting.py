import json
import os
import time

from tool_contract import ToolCallStatus


# ReAct 循环的最大工具调用轮数
MAX_ITERATIONS = 20


# ---------------------------------------------------------------------------
# 工具清单格式化
# ---------------------------------------------------------------------------

def _build_tools_block(tools: list[dict]) -> str:
    """按 server 分组，格式化工具清单。

    tools 格式（与 MCP 无关的中立结构）：
        [{"name": str, "server": str, "description": str, "schema": dict}, ...]
    """
    if not tools:
        return "（当前没有可用工具）"

    items = sorted(tools, key=lambda t: (t.get("server") or "", t["name"]))

    blocks: list[str] = []
    current_server = None
    for t in items:
        server = t.get("server") or "unknown"
        if server != current_server:
            blocks.append(f"\n## server: {server}")
            current_server = server
        desc = (t.get("description") or "").strip()
        blocks.append(f"- {t['name']}: {desc}".rstrip())
        blocks.append(
            f"  input_schema: {json.dumps(t.get('schema') or {}, ensure_ascii=False)}"
        )

    return "\n".join(blocks).strip()


# ---------------------------------------------------------------------------
# 初始化：构建 ReAct bootstrap 提示词
# ---------------------------------------------------------------------------

def build_react_bootstrap_prompt(tools: list[dict]) -> str:
    """构建 ReAct 初始化系统提示词。只在工具就绪后调用一次。"""
    tools_block = _build_tools_block(tools)
    return f"""# 角色
你是一个通过「思考 → 行动 → 观察」循环来可靠完成任务的智能体。

# 可用工具
以下工具已连接到运行环境。工具名必须精确匹配，禁止编造不存在的工具。
{tools_block}

每个工具的 input_schema 是 JSON Schema，调用时 arguments 必须符合对应 schema。

# 输出协议
每一轮只选择以下两种形式之一。

## 形式 A：需要调用工具
Thought: <用自然语言分析当前已知信息，说明下一步做什么、为什么>
<tool_call>
{{"name": "<工具名>", "arguments": {{<符合该工具 input_schema 的 JSON 对象>}}}}
</tool_call>

系统执行工具后，会以 Observation 的形式返回结果。收到 Observation 后，必须回到 Thought 重新分析，再决定下一次 Action 或给出 Final Answer。

## 形式 B：信息已足够，给出最终答案
Thought: <简要说明为什么现在可以回答>
Final Answer: <完整、准确的最终答案>

# 约束
2. 调用工具前必须先输出 Thought，禁止无思考直接调用。
3. <tool_call> 内必须是合法 JSON：双引号、无注释、无尾逗号。
4. name 必须精确等于上方工具列表中的名字。
5. arguments 必须是 JSON 对象，并符合该工具的 input_schema。
6. 工具返回错误或空结果时，在下一个 Thought 中分析原因，可调整参数重试或换工具，不要直接放弃。
7. 仅凭已有信息就能可靠回答时，直接输出 Final Answer，无需调用工具。
8. 最多进行 {MAX_ITERATIONS} 轮工具调用；达到上限仍未完成时，输出 Final Answer 并如实说明未解决的部分。
9. 如果需要用户确认、补充信息，或对任务目标存在犹豫，直接用自然语言向用户提问，禁止输出 <tool_call>，禁止输出 JSON。
10. 禁止输出任何表情包，整个对话中不要使用表情。

# 停止条件
输出 Final Answer 时循环结束。不要在 <tool_call> 之后追加确认性问题或额外说明。

# 示例
User: 请计算 2 的 10 次方。
Thought: 这是纯计算任务，应调用 Python 解释器工具。
<tool_call>
{{"name": "python_execute", "arguments": {{"code": "print(2 ** 10)"}}}}
</tool_call>
Observation: 1024
Thought: 工具返回 1024，已经得到答案。
Final Answer: 2 的 10 次方等于 1024。

（示例中的工具名与参数仅用于展示格式，实际以工具列表与 input_schema 为准。）
"""


async def init_react_agent(tools: list[dict], send_fn) -> None:
    """工具就绪后由编排层调用：构建初始化提示词并发送。

    send_fn: 接收 dict 的 async 发送函数（如 llm_request_queue.put）
    """
    prompt = build_react_bootstrap_prompt(tools)
    await send_fn({
        "text": prompt,
        "timestamp": time.time(),
    })


# ---------------------------------------------------------------------------
# Observation：工具结果回流
# ---------------------------------------------------------------------------

async def build_react_obervation_prompt(
    tool_calls,          # try_parse_tool_calls(self.answer) 的返回值
    user_question: str,  # 当前用户的问题/任务
    toolcall_fn,         # 调用工具的函数 async (name, args) -> (text, status)
) -> tuple[str, str]:
    """
    输入：
      - tool_calls: 模型本轮解析出的工具调用列表，元素需有 .name 和 .args
      - user_question: 当前用户的问题/任务
      - toolcall_fn: 工具执行函数 async (name, args) -> (text, status)
    输出：
      - prompt: 发给模型的 JSON 格式系统消息
      - results_text: 工具结果的完整 JSON，作为附件
    """
    tool_list = []
    results = []
    all_success = True

    for call in tool_calls:
        print(f"要调用的工具: {call.name}")
        print(f"参数: {call.args}")

        text, result = await toolcall_fn(call.name, call.args)
        os.makedirs("./log", exist_ok=True)
        with open("./log/调用结果.txt", "w", encoding="utf-8") as f:
            f.write(text)
        print(f"调用结果: result={result}")

        if result == ToolCallStatus.NOT_FOUND:
            print(f"工具 {call.name} 未注册，忽略调用")
            tool_list.append({"tool": call.name, "status": "not_found"})
            all_success = False
        elif result == ToolCallStatus.FAILED:
            tool_list.append({"tool": call.name, "status": "failed"})
            all_success = False
        else:
            tool_list.append({"tool": call.name, "status": "success"})

        results.append({
            "tool": call.name,
            "arguments": call.args,
            "result": text,
        })

    print("所有工具调用完成，准备发送给 AI 进行下一轮调用或回复用户")
    results_text = json.dumps(results, ensure_ascii=False, default=str)

    payload = {
        "message_type": "system",
        "user_history_question": user_question,
        "tool_calls": tool_list,
        "all_success": all_success,
        "results_attachment": "附件包含这些 mcp 工具调用的完整返回结果；每个工具的具体返回见附件中对应 tool 的 result 字段",
    }
    if all_success:
        payload["instruction"] = (
            "所有工具调用成功。根据 tool_calls 与附件结果继续下一步；"
            "若信息已足够，给出最终回复。"
        )
    else:
        payload["instruction"] = (
            "存在失败的调用。必须根据附件中对应 tool 的失败原因修正参数，"
            "重新调用失败的工具；在所有失败工具都调用成功之前，不得直接给用户最终回复。"
        )
    prompt = json.dumps(payload, ensure_ascii=False)

    return prompt, results_text
def build_react_user_prompt(text: str) -> str:
    """把用户输入包装成 ReAct user 消息的 payload。

    输入：
      - text: 用户原话/任务描述
    输出：
      - prompt: JSON 字符串，作为消息 text 发送
    """
    payload = {
        "message_type": "user",
        "task": text,
    }
    return json.dumps(payload, ensure_ascii=False)