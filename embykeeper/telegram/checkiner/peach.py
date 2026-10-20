import asyncio
import random
import time

from pyrogram.types import InlineKeyboardMarkup, Message, ReplyKeyboardMarkup
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

    # 点击签到: 异常时重试; 同一张验证码: 识别失败就重新识别; 判错后等机器人补发新图.
    click_max_attempts = 5
    ocr_max_attempts = 3
    captcha_resend_wait = 15  # 验证码错误后等待机器人补发新验证码的秒数
    bot_captcha_error_keywords = ["验证码错误", "验证码不正确", "验证码有误"]

    def __init__(self, *args, **kw):
        super().__init__(*args, **kw)
        self._last_captcha_at = 0.0

    async def _click_checkin(self, message: Message, button_text: str) -> bool:
        """点签到按钮.

        使用消息里实际的按钮文本点击, 避免硬编码 "签到" 与界面文本不一致.
        callback 等待超时视为点击成功, 只有按钮失效或其它异常才重试.
        """
        for i in range(self.click_max_attempts):
            try:
                await message.click(button_text)
                self.log.debug(f"已点击签到按钮 ({i + 1}/{self.click_max_attempts}).")
                return True
            except TimeoutError:
                # pyrogram 的 click 超时只代表机器人没有在时限内回应 callback, 点击本身通常已送达;
                # 继续点击会重复触发机器人 (可能连发验证码), 因此这里视为点击成功.
                self.log.debug(
                    f"点击签到按钮等待回调超时 ({i + 1}/{self.click_max_attempts}), 视为已点击."
                )
                return True
            except MessageIdInvalid:
                self.log.debug("签到按钮已失效 (MessageIdInvalid).")
                return False
            except Exception as e:
                self.log.debug(f"点击签到异常 ({e.__class__.__name__}: {e}), 稍后重试.")
                await asyncio.sleep(2)
        self.log.warning("点击签到按钮多次失败, 将重新发送签到命令.")
        return False

    @staticmethod
    def _get_button_texts(message: Message):
        """取消息上所有按钮文本, 同时兼容 inline 键盘和 reply 键盘."""
        rm = message.reply_markup
        if isinstance(rm, InlineKeyboardMarkup):
            return [k.text for r in rm.inline_keyboard for k in r]
        if isinstance(rm, ReplyKeyboardMarkup):
            return [k.text for r in rm.keyboard for k in r]
        return []

    async def message_handler(self, client, message: Message):
        if message.caption and "欢迎使用" in message.caption:
            keys = self._get_button_texts(message)
            if keys:
                match = next((k for k in keys if "签到" in (k or "")), None)
                if match:
                    await asyncio.sleep(random.uniform(0.5, 1.5))
                    ok = await self._click_checkin(message, match)
                    if not ok:
                        # 按钮失效或点击异常 → 整轮重来 (/start 换流程)
                        await self.retry()
                    return
                self.log.warning("签到失败: 账户错误.")
                return await self.fail()
        await super().message_handler(client, message)

    async def on_captcha_error(self, message: Message, text: str) -> bool:
        """机器人判错验证码后会自行补发新图, 此时不要立刻回 /start.

        回 /start 会被机器人当成一次错误答案, 白白消耗刚补发的新验证码;
        先等一会儿, 等到新验证码就继续识别, 等不到再重新发送签到命令.
        """
        self.log.info("验证码错误, 等待机器人补发新验证码.")
        requested_at = time.time()
        await asyncio.sleep(self.captcha_resend_wait)
        if self.finished.is_set():
            return True
        if self._last_captcha_at > requested_at:
            self.log.debug("已收到新验证码, 无需重新发送签到命令.")
            return True
        self.log.info("等待超时仍未收到新验证码, 重新发送签到命令.")
        await self.retry()
        return True

    async def on_photo(self, message: Message):
        """同一张图识别失败就重新识别; 识别出结果再提交.

        提交后若机器人判错, 会走 on_captcha_error 等待补发新图.
        """
        self._last_captcha_at = time.time()
        data = await self.client.download_media(message, in_memory=True)
        ocr = OCRService.get(
            ocr_name=self.ocr,
            char_range=self.bot_captcha_char_range,
        )

        for attempt in range(1, self.ocr_max_attempts + 1):
            try:
                captcha = await ocr.run(data, expected_len=self.bot_captcha_len)
            except Exception as e:
                captcha = ""
                self.log.info(
                    f"验证码识别失败 ({e.__class__.__name__}: {e}), "
                    f"重新识别 ({attempt}/{self.ocr_max_attempts})."
                )
            else:
                if captcha:
                    self.log.debug(f"[gray50]接收验证码: {captcha}.[/]")
                    await asyncio.sleep(random.uniform(1.5, 3.0))
                    await self.on_captcha(message, captcha)
                    return
                self.log.info(
                    f"验证码识别失败或不是 {self.bot_captcha_len} 位, "
                    f"重新识别同一张图 ({attempt}/{self.ocr_max_attempts})."
                )
            await asyncio.sleep(1.0)

        self.log.warning("同一验证码多次识别仍失败, 重新签到换新图.")
        await self.retry()
