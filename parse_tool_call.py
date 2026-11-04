import json
from dataclasses import dataclass


@dataclass
class ParsedToolCall:
    name: str
    args: dict


# ============================================================
# 1) 扫描顶层 {...} 块（原样保留）
# ============================================================
def _scan_json_blocks(text: str) -> list[str]:
    """按括号配对扫描所有顶层 {...} 块，正确处理字符串和转义。"""
    blocks = []
    i = 0
    n = len(text)
    while i < n:
        if text[i] != "{":
            i += 1
            continue
        start = i
        depth = 0
        in_str = False
        escape = False
        j = i
        found = False
        while j < n:
            ch = text[j]
            if in_str:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_str = False
            else:
                if ch == '"':
                    in_str = True
                elif ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        blocks.append(text[start:j + 1])
                        i = j + 1
                        found = True
                        break
            j += 1
        if not found:
            break
    return blocks


# ============================================================
# 2) 参数归一化：dict 或 JSON 字符串
# ============================================================
def _normalize_args(args) -> dict | None:
    """arguments 可能是 dict，也可能是 JSON 字符串（OpenAI 风格）。

    返回：
      - dict：解析成功（含空 dict）
      - None：类型不对或字符串解析失败
    """
    if isinstance(args, dict):
        return args
    if isinstance(args, str):
        s = args.strip()
        if not s:
            return None
        try:
            parsed = json.loads(s)
        except Exception:
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


# ============================================================
# 3) 单个对象的格式识别
# ============================================================
def _pick_args(fn: dict) -> dict | None:
    """从 {name, arguments|args|input} 里取参数。"""
    raw = fn.get("arguments")
    if raw is None:
        raw = fn.get("args")
    if raw is None:
        raw = fn.get("input")
    return _normalize_args(raw)


def _parse_one(obj) -> tuple[str, dict] | None:
    """从一个 dict 里抠出 (name, args)，命中任一格式返回元组，否则 None。

    支持的格式：
      1. MCP JSON-RPC
         {"method": "tools/call", "params": {"name": ..., "arguments": {...}}}
      2. Anthropic tool_use
         {"type": "tool_use", "name": ..., "input": {...}}
      3. OpenAI function / function_call 对象
         {"function": {"name": ..., "arguments": "{...}"}}
         {"function_call": {"name": ..., "arguments": "{...}"}}
      4. Gemini functionCall
         {"functionCall": {"name": ..., "args": {...}}}
      5. 通用简写
         {"tool"/"name": ..., "arguments"/"input"/"args": {...}}
    """
    if not isinstance(obj, dict):
        return None

    # 1) MCP JSON-RPC
    if obj.get("method") == "tools/call":
        params = obj.get("params")
        if isinstance(params, dict):
            name = params.get("name")
            args = _normalize_args(params.get("arguments"))
            if isinstance(name, str) and args is not None:
                return name, args

    # 2) Anthropic tool_use
    if obj.get("type") == "tool_use":
        name = obj.get("name")
        args = _normalize_args(obj.get("input"))
        if isinstance(name, str) and args is not None:
            return name, args

    # 3) & 4) 嵌套在已知字段里的 name/args（function / function_call / functionCall）
    for key in ("function", "function_call", "functionCall"):
        fn = obj.get(key)
        if isinstance(fn, dict):
            name = fn.get("name")
            args = _pick_args(fn)
            if isinstance(name, str) and args is not None:
                return name, args

    # 5) 通用简写
    name = obj.get("tool") or obj.get("name")
    if isinstance(name, str):
        for k in ("arguments", "input", "args"):
            if k in obj:
                args = _normalize_args(obj[k])
                if args is not None:
                    return name, args

    return None


# ============================================================
# 4) 对外入口
# ============================================================
def extract_tool_calls(answer: str) -> list[ParsedToolCall] | None:
    """从混合文本里抠出所有工具调用。

    返回：
      - list[ParsedToolCall]：解析到至少一个工具调用
      - None：没有解析到任何工具调用
    """
    if not answer:
        return None

    results: list[ParsedToolCall] = []
    seen = set()

    def add(name: str, args: dict):
        key = (name, json.dumps(args, sort_keys=True, ensure_ascii=False, default=str))
        if key in seen:
            return
        seen.add(key)
        results.append(ParsedToolCall(name=name, args=args))

    # 已知的"容器字段"：值本身是工具调用，或工具调用的数组
    CONTAINER_KEYS = (
        "tool_calls", "toolCalls",
        "function_call", "functionCall",
        "tool_use", "toolUse",
    )
    MAX_DEPTH = 4

    def handle(obj, depth=0):
        if depth > MAX_DEPTH:
            return
        if isinstance(obj, dict):
            r = _parse_one(obj)
            if r is not None:
                add(*r)
                return
            for k in CONTAINER_KEYS:
                if k in obj:
                    handle(obj[k], depth + 1)
        elif isinstance(obj, list):
            for item in obj:
                handle(item, depth + 1)

    for block in _scan_json_blocks(answer):
        try:
            obj = json.loads(block)
        except Exception:
            continue
        handle(obj)

    return results if results else None