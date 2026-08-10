import asyncio
import random
import re
import string
from io import BytesIO

from pyrogram.types import Message
from pyrogram.errors import MessageIdInvalid

from embykeeper.ocr import OCRService

from . import BotCheckin


class PeachCheckin(BotCheckin):
    name = "Peach"
    bot_username = "peach_emby_bot"
    bot_checkin_cmd = "/start"
    bot_captcha_len = 4
    bot_checkin_caption_pat = "请输入验证码"
    max_retries = 4

    # 点击签到: 超时就重试; 同一张验证码: 非 4 位就重新识别; 4 位但机器人判错: 父类会 retry → /start 换新图
    click_max_attempts = 5
    ocr_max_attempts = 3

    async def _click_checkin(self, message: Message, button_text: str) -> bool:
        """点签到按钮; 超时则循环重试一段时间, 不要立刻整轮 /start.

        使用消息里实际的按钮文本点击, 避免硬编码 "签到" 与界面文本不一致.
        """
        for i in range(self.click_max_attempts):
            try:
                await message.click(button_text)
                self.log.debug(f"已点击签到按钮 ({i + 1}/{self.click_max_attempts}).")
                return True
            except TimeoutError:
                self.log.debug(
                    f"点击签到按钮超时 ({i + 1}/{self.click_max_attempts}), 稍后重试."
                )
                await asyncio.sleep(2 + i * 0.5)
            except MessageIdInvalid:
                self.log.debug("签到按钮已失效 (MessageIdInvalid).")
                return False
            except Exception as e:
                self.log.debug(f"点击签到异常 ({e.__class__.__name__}: {e}), 稍后重试.")
                await asyncio.sleep(2)
        self.log.warning("点击签到按钮多次超时, 将重新发送签到命令.")
        return False

    async def message_handler(self, client, message: Message):
        if message.caption and "欢迎使用" in message.caption and message.reply_markup:
            keys = [k.text for r in message.reply_markup.inline_keyboard for k in r]
            match = next((k for k in keys if "签到" in (k or "")), None)
            if match:
                await asyncio.sleep(random.uniform(0.5, 1.5))
                ok = await self._click_checkin(message, match)
                if not ok:
                    # 多次点不动 → 整轮重来 (/start 换流程)
                    await self.retry()
                return
            self.log.warning("签到失败: 账户错误.")
            return await self.fail()
        await super().message_handler(client, message)

    def _normalize_captcha(self, raw: str) -> str:
        """清洗 OCR 结果, 尽量抽出 4 位数字."""
        if not raw:
            return ""
        cleaned = raw.translate(str.maketrans("", "", string.punctuation)).replace(" ", "")
        digits = re.sub(r"[^0-9A-Za-z]", "", cleaned)
        # Peach 验证码以数字为主; 若混入字母, 优先取连续数字
        m = re.search(r"\d{4}", digits)
        if m:
            return m.group(0)
        only_digits = re.sub(r"[^0-9]", "", digits)
        return only_digits or digits

    async def on_photo(self, message: Message):
        """同一张图: 非 4 位就重新识别; 识别出 4 位再提交.
        若提交后机器人判错, 父类 on_text 会 retry → /start 换新图.
        """
        data = await self.client.download_media(message, in_memory=True)
        if not isinstance(data, BytesIO):
            # pyrogram 有时返回文件类对象
            raw = data.read() if hasattr(data, "read") else bytes(data)
            data = BytesIO(raw)

        ocr = await OCRService.get(
            ocr_name=self.ocr,
            char_range=self.bot_captcha_char_range,
        )
        is_gif = getattr(data, "name", "").endswith(".gif") if hasattr(data, "name") else False
        expected = self.bot_captcha_len if isinstance(self.bot_captcha_len, int) else 4

        for attempt in range(1, self.ocr_max_attempts + 1):
            try:
                data.seek(0)
                with ocr:
                    ocr_text = await ocr.run(data, gif=is_gif)
                captcha = self._normalize_captcha(ocr_text or "")
                self.log.debug(f"[gray50]OCR 原始={ocr_text!r} → 清洗={captcha!r} ({attempt}/{self.ocr_max_attempts}).[/]")
                if len(captcha) == expected:
                    self.log.debug(f"[gray50]接收验证码: {captcha}.[/]")
                    await asyncio.sleep(random.uniform(1.5, 3.0))
                    await self.on_captcha(message, captcha)
                    return
                self.log.info(
                    f"验证码 {captcha!r} 不是 {expected} 位, 重新识别同一张图 ({attempt}/{self.ocr_max_attempts})."
                )
            except Exception as e:
                self.log.info(
                    f"验证码识别失败 ({e.__class__.__name__}: {e}), "
                    f"重新识别 ({attempt}/{self.ocr_max_attempts})."
                )
            await asyncio.sleep(1.0)

        # 同一张图多次识别仍不是 4 位 → 整轮 /start 换新图
        self.log.warning("同一验证码多次识别仍非 4 位, 重新签到换新图.")
        await self.retry()
