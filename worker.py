import asyncio

from identity_agnostic_worker import WorkerClient
from sender import llm_request_queue
from reasoning_acting import maybe_add_periodic_reminder
from collections import deque

worker = None
user_question_queue = asyncio.Queue()


history = deque(maxlen=3)  # 保存最近的 3 条消息


async def worker_init():
    global worker
    worker = await WorkerClient.register()
async def worker_recv():
    round_index = 0
    global worker
    while True:
        text = await worker.recv()
        history.append(text)
        round_index += 1
        await user_question_queue.put("\n".join(history))
        text = maybe_add_periodic_reminder(round_index=round_index, user_message=text)
        await llm_request_queue.put({"text": text})
async def worker_send(text):
    global worker
    await worker.send(text)