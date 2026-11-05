import asyncio
import json
import os
import re
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse
from playwright.async_api import async_playwright, Playwright
from pathlib import Path
from doubao.doubao_sse_hook import DoubaoSseHook
from doubao.doubao_sender import DoubaoSender
from sender import llm_request_queue
from mcp_client import mcp_client_task
from worker import worker_init,worker_recv

SAVE_FILE = Path("save.json")
RAW_LOG = "raw_log.json"
TARGET_URL = "https://www.doubao.com/"
raw_file = open(
    RAW_LOG,
    "a",
    encoding="utf-8"
)

sse_hook = DoubaoSseHook()

async def on_sse_push(text: str):
    raw_file.write(text)
    raw_file.flush()
    events = sse_hook.parse(text)
    await sse_hook.event_poll(events)

async def page_init(playwright: Playwright):
    browser = await playwright.chromium.launch(
        channel="chrome",
        headless=False,

        args=[
            "--disable-blink-features=AutomationControlled",
            # "--headless=new"
        ],
    )
    if SAVE_FILE.exists():
        context = await browser.new_context(storage_state=str(SAVE_FILE))
        print("找到 save.json")
    else:
        print(f"未找到 {SAVE_FILE}，第一次请先手动运行命令登录并保存状态：")
        print(f"    playwright codegen {TARGET_URL} --save-storage={SAVE_FILE}")
        print("登录完成后关闭浏览器窗口，状态会自动保存。")
        raise SystemExit(1)  # 或者 return 让上层处理

    await context.add_init_script(
        path=os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "data",
            "fetch_hook.js",
        )
    )
    page = await context.new_page()

    await context.expose_function("__doubao_sse_push", on_sse_push)

    await page.goto(TARGET_URL)

    return page , browser , context



async def recv_task(browser,context):
    
    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        await context.storage_state(path=str(SAVE_FILE))
        await browser.close()
    

async def playwright_task():
    async with async_playwright() as playwright:
        (page ,browser, context) = await page_init(playwright)
        sender = DoubaoSender(page = page,queue=llm_request_queue)
        await recv_task(browser,context)

async def main():
    await worker_init()
    await asyncio.gather(
        playwright_task(),
        mcp_client_task(),
        worker_recv(),
    )



if __name__ == "__main__":
    asyncio.run(main())