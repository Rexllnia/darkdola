import asyncio
import json
import os
import time

from sse_hook import SSEHook
from mcp_client import ToolCallStatus, toolcall
from sender import llm_request_queue
from parse_tool_call import ParsedToolCall, extract_tool_calls

from worker import worker_send, worker_recv,user_question_queue
from agent_tool_parser import try_parse_tool_calls
from reasoning_acting import build_react_obervation_prompt
MAX_MCP_CALL_TIMES = 30  # 最大调用轮次，超过后不再调用工具
class DoubaoSseHook(SSEHook):

    def __init__(self):
        # 先调用父类构造（新版父类无参数）
        super().__init__()

        # 业务状态
        self.answer = ""
        self.message_id = None
        self.is_inited = False
        self.finished = True
        self.user_question =""

    # --------------------------------------------------------
    # 提取函数（原样保留）
    # --------------------------------------------------------

    def extract_stream_msg_notify(self, data):
        if not isinstance(data, dict):
            return []
        content = data.get("content")
        if not isinstance(content, dict):
            return []
        content_blocks = content.get("content_block")
        if not isinstance(content_blocks, list):
            return []
        result = []
        for block in content_blocks:
            if not isinstance(block, dict):
                continue
            block_content = block.get("content")
            if not isinstance(block_content, dict):
                continue
            text_block = block_content.get("text_block")
            if not isinstance(text_block, dict):
                continue
            text = text_block.get("text")
            if isinstance(text, str) and text:
                result.append(text)
        return result

    def extract_stream_chunk(self, data):
        if not isinstance(data, dict):
            return []
        patch_ops = data.get("patch_op")
        if not isinstance(patch_ops, list):
            return []
        result = []
        for op in patch_ops:
            if not isinstance(op, dict):
                continue
            patch_value = op.get("patch_value")
            if not isinstance(patch_value, dict):
                continue
            content_blocks = patch_value.get("content_block")
            if isinstance(content_blocks, list):
                for block in content_blocks:
                    if not isinstance(block, dict):
                        continue
                    block_content = block.get("content")
                    if not isinstance(block_content, dict):
                        continue
                    text_block = block_content.get("text_block")
                    if not isinstance(text_block, dict):
                        continue
                    text = text_block.get("text")
                    if isinstance(text, str) and text:
                        result.append(text)
        return result

    def extract_chunk_delta(self, data):
        if not isinstance(data, dict):
            return []
        text = data.get("text")
        if isinstance(text, str) and text:
            return [text]
        return []


    async def _delta_msg_hanle(self, text):
        if not text:
            return
        if self.is_inited == False:
            return
        self.answer += text
        await worker_send(text)
        return


        
    async def on_stream_msg_notify(self, data):
        for text in self.extract_stream_msg_notify(data):
            print("delta:", text)
            await self._delta_msg_hanle(text)            

    async def on_chunk_delta(self, data):
        for text in self.extract_chunk_delta(data):
            await self._delta_msg_hanle(text)

    async def on_stream_chunk(self, data):
        for text in self.extract_stream_chunk(data):
            print("on_stream_chunk delta:", text)
            await self._delta_msg_hanle(text)


    def on_AI_msg_end(self, data):
        # end_type == 1：当前 AI 消息完成
        print("当前 AI 消息完成")
        attr = data.get("msg_finish_attr", {}) if isinstance(data, dict) else {}
        if isinstance(attr, dict):
            msgid = attr.get("msgid")
            if msgid:
                self.message_id = msgid

    async def on_sse_end(self, data):
        # end_type == 3：整个 completion 流结束
        self.is_inited = True
        print("整个 completion 流结束 ")
        os.makedirs("./log", exist_ok=True)
        with open("./log/answer.txt", "w", encoding="utf-8") as f:
            f.write(self.answer)       
        tool_calls = try_parse_tool_calls(self.answer)
        print(f"解析到的工具调用: {tool_calls}")
        if not tool_calls:
            print("模型没有调用工具，正常回复")
            self.finished = True
            self.user_question = ""
            await worker_send(None)
        else:
            if self.finished == True:
                self.user_question = await user_question_queue.get()
                self.finished = False

            prompt, results_text = await build_react_obervation_prompt(
                tool_calls,
                self.user_question,
                toolcall,
            )
            print("发送给 AI 的 JSON 系统消息:", prompt)

            await llm_request_queue.put ({
                "text": prompt,
                "file": results_text,
                "timestamp": time.time(),
            })
        self.answer = ""