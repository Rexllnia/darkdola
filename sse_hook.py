import asyncio
import re
import json
import inspect


async def _maybe_await(value):
    if inspect.isawaitable(value):
        return await value
    return value


class SSEHook:
    def __init__(self):
        self.buffer = ""

    def on_stream_msg_notify(self, data):
        return

    def on_chunk_delta(self, data):
        return

    def on_stream_chunk(self, data):
        return

    def on_AI_msg_end(self, data):
        return

    def on_sse_end(self, data):
        return

    def _parse_event(self, block: str):

        event_name = ""
        event_id = ""
        data_lines = []

        for line in block.splitlines():

            if line.startswith("event:"):
                event_name = line[6:].strip()

            elif line.startswith("id:"):
                event_id = line[3:].strip()

            elif line.startswith("data:"):
                data_lines.append(
                    line[5:].lstrip()
                )

        if not event_name and not data_lines:
            return None

        data_raw = "\n".join(data_lines)

        data = None

        if data_raw:

            try:
                data = json.loads(data_raw)

            except Exception:
                data = data_raw

        return {
            "event": event_name,
            "id": event_id,
            "data": data,
            "raw": block,
        }

    def parse(self, text: str):

        self.buffer += text

        events = []

        while True:

            match = re.search(
                r"\r\n\r\n|\n\n|\r\r",
                self.buffer
            )

            if not match:
                break

            block = self.buffer[:match.start()]

            self.buffer = self.buffer[match.end():]

            event = self._parse_event(block)

            if event:
                events.append(event)

        return events

    async def event_poll(self, events):
        for event in events:
                event_name = event["event"]
                event_id = event["id"]
                event_data = event["data"]

                # ============================================
                # HEARTBEAT
                # ============================================

                if event_name == "SSE_HEARTBEAT":
                    continue

                # ============================================
                # ACK
                # ============================================

                if event_name == "SSE_ACK":
                    continue

                # ============================================
                # FULL_MSG_NOTIFY
                #
                # 用户自己的消息
                # ============================================

                if event_name == "FULL_MSG_NOTIFY":
                    continue

                # ============================================
                # AI 输出
                # ============================================
                if event_name == "STREAM_MSG_NOTIFY":
                    await _maybe_await(self.on_stream_msg_notify(event_data))
                elif event_name == "CHUNK_DELTA":
                    await _maybe_await(self.on_chunk_delta(event_data))
                elif event_name == "STREAM_CHUNK":
                    await _maybe_await(self.on_stream_chunk(event_data))

                # ============================================
                # 当前消息结束
                # ============================================

                elif (
                    event_name == "SSE_REPLY_END"
                    and isinstance(event_data, dict)
                ):

                    end_type = event_data.get(
                        "end_type"
                    )
                    if end_type == 1:
                        await _maybe_await(self.on_AI_msg_end(event_data))
                    elif end_type == 3:
                        await _maybe_await(self.on_sse_end(event_data))

        return