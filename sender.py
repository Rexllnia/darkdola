import asyncio
from abc import ABC, abstractmethod


llm_request_queue = asyncio.Queue()
class Sender(ABC):
    """通用发送器：构造即启动后台队列消费，子类只实现 send(text)。"""

    def __init__(self, page, queue: asyncio.Queue):
        self.page = page
        self.queue = queue
        self.task = asyncio.create_task(self._run())
        

    @abstractmethod
    async def send(self, item: dict) -> None:
        ...

    async def _run(self):

        current = None
        while True:
            current = await llm_request_queue.get()
            print("worker_recv:", current)
            await self.send(current)
            await asyncio.sleep(3)
 