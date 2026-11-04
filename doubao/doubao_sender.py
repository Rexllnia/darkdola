import asyncio
import tempfile
import time
from pathlib import Path

from sender import Sender


class DoubaoSender(Sender):
    TEXTBOX_SELECTOR = 'div[contenteditable="true"].tiptap.ProseMirror'
    UPLOAD_BTN_SELECTOR = 'button[data-testid="upload_file_button"]'
    UPLOAD_OPTION_SELECTOR = '[role="option"]:has-text("上传文件或图片")'
    ATTACHMENT_SELECTOR = '[class*="attachment"]'
    SCREENSHOT_PREFIX = "doubao_headless"

    def __init__(self, page, queue: asyncio.Queue = None, screenshot: bool = False):
        self.screenshot = screenshot
        print("[DOUBAO SENDER] initialized")
        super().__init__(page, queue)

    async def _shot(self, idx: int):
        if not self.screenshot:
            return
        await self.page.screenshot(
            path=f"./{self.SCREENSHOT_PREFIX}_{idx:02d}.png",
            full_page=True,
        )

    # ============================================================
    # text 和 file 是并列的字符串，各自独立：
    #   - text 有值 -> 文本框输入
    #   - file 有值 -> 把 file 这个字符串写成文件上传
    #   - 两者都有 -> 先上传文件，再输入文本，一次回车一起发
    # ============================================================
    async def send(self, item: dict) -> None:
        text = str(item.get("text") or "")
        file_content = item.get("file")

        if not text and file_content is None:
            print("[DOUBAO] 空消息，跳过")
            return

        upload_path = None
        is_temp = False

        # 1. file 有值：把 file 字符串写成临时文件
        if file_content is not None:
            name = str(item.get("file_name") or self._default_name(item))
            tmpdir = tempfile.mkdtemp(prefix="doubao_")
            upload_path = Path(tmpdir) / name
            upload_path.write_text(str(file_content), encoding="utf-8")
            is_temp = True

        await self._shot(1)

        try:
            textbox = self.page.locator(self.TEXTBOX_SELECTOR)
            await textbox.wait_for(state="visible", timeout=15000)

            # 2. 先上传文件
            if upload_path:
                print(f"[DOUBAO FILE] 上传 {upload_path.name} ({len(str(file_content))} chars)")
                ok = await self._upload(upload_path)
                if not ok:
                    raise RuntimeError("上传失败")
                await self.page.wait_for_selector(self.ATTACHMENT_SELECTOR, timeout=15000)
                print("[DOUBAO FILE] attachment visible")
                await asyncio.sleep(2)

            await self._shot(2)

            # 3. 再输入文本（如果有）
            if text:
                await textbox.click()
                await textbox.fill(text)
                text_now = (await textbox.text_content() or "").strip()
                if not text_now:
                    raise RuntimeError("Doubao textbox is empty after fill()")
                print(f"[DOUBAO TEXT] filled ({len(text)} chars)")
                await asyncio.sleep(1)

            # 4. 一次回车，文本+附件一起发
            await textbox.click()
            await textbox.press("Enter")
            await self._shot(3)

            parts = []
            if upload_path:
                parts.append(f"file={upload_path.name}")
            if text:
                parts.append(f"text={len(text)}chars")
            print(f"[DOUBAO SENT] {' + '.join(parts)}")

        finally:
            if is_temp and upload_path:
                try:
                    upload_path.unlink()
                    upload_path.parent.rmdir()
                except OSError:
                    pass

    def _default_name(self, item: dict) -> str:
        sender = str(item.get("sender") or "unknown")
        ts = item.get("timestamp") or time.time()
        try:
            ts = float(ts)
        except (TypeError, ValueError):
            ts = time.time()
        stamp = time.strftime("%Y%m%d_%H%M%S", time.localtime(ts))
        safe_sender = "".join(
            c if c.isalnum() or c in "-_" else "_" for c in sender
        )[:32] or "unknown"
        return f"{stamp}_{safe_sender}.txt"

    async def _upload(self, file_path: Path) -> bool:
        """点 + -> 等菜单 -> 点『上传文件或图片』-> 拦截 FileChooser。"""
        upload_btn = self.page.locator(self.UPLOAD_BTN_SELECTOR)
        try:
            await upload_btn.wait_for(state="visible", timeout=10000)
        except Exception as e:
            print(f"[UPLOAD] + 按钮不可见: {e}")
            return False

        print("[UPLOAD] 点击 + 按钮...")
        try:
            await upload_btn.click(timeout=3000)
        except Exception as e:
            print(f"[UPLOAD] 普通点击失败，尝试 force: {e}")
            await upload_btn.click(force=True, timeout=3000)

        print("[UPLOAD] 等菜单出现...")
        option = self.page.locator(self.UPLOAD_OPTION_SELECTOR)
        try:
            await option.wait_for(state="visible", timeout=8000)
        except Exception as e:
            print(f"[UPLOAD] 菜单项没出现: {e}")
            try:
                opts = await self.page.evaluate("""
                () => Array.from(document.querySelectorAll('[role="option"]'))
                    .map(el => ({
                        text: (el.innerText || '').trim().slice(0, 40),
                        cls: (typeof el.className === 'string' ? el.className : '').slice(0, 60),
                    }))
                """)
                print(f"[UPLOAD] 当前 role=option 列表: {opts}")
            except Exception:
                pass
            return False

        print("[UPLOAD] 点『上传文件或图片』，等 FileChooser...")
        try:
            async with self.page.expect_file_chooser(timeout=10000) as fc_info:
                await option.first.click(timeout=5000)
            fc = await fc_info.value
            await fc.set_files(str(file_path))
            print("[UPLOAD] FileChooser 已设置文件")
            return True
        except Exception as e:
            print(f"[UPLOAD] FileChooser 失败: {e}")
            await asyncio.sleep(0.5)
            try:
                count = await self.page.locator('input[type="file"]').count()
                if count > 0:
                    for i in range(count):
                        el = self.page.locator('input[type="file"]').nth(i)
                        try:
                            await el.set_input_files(str(file_path), timeout=3000)
                            print(f"[UPLOAD] 兜底 set_input_files -> input[{i}]")
                            return True
                        except Exception:
                            continue
            except Exception:
                pass
            return False