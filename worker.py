import asyncio

from identity_agnostic_worker import WorkerClient
from sender import llm_request_queue
from reasoning_acting import build_react_user_prompt
from collections import deque

worker = None
user_question_queue = asyncio.Queue()


history = deque(maxlen=3)  # 保存最近的 3 条消息


async def worker_init():
    global worker
    worker = await WorkerClient.register()
async def worker_recv():
    global worker
    while True:
        text = await worker.recv()
        history.append(text)
        await user_question_queue.put("\n".join(history))
        await llm_request_queue.put({"text": text})
async def worker_send(text):
    global worker
    await worker.send(text)