import asyncio
import re

from pyrogram.types import Message
from pyrogram import filters
from pyrogram.errors import MessageIdInvalid

from embykeeper.utils import async_partial

from . import Monitor

__ignore__ = True


class CcMonitor(Monitor):
    name = "Cc"
    chat_name = "EmbyCc"
    chat_keyword = r"Cc-register-[\w]+-[\w]+-[\w]+-[\w]+"
    bot_username = "EmbyCc_bot"
    notify_create_name = True
    additional_auth = ["prime"]
    register_username = "purejam"
    register_code = "1998"

    async def init(self):
        """启动时先检查历史记录中的邀请码"""
        self.log.info("正在检查历史记录...")
        try:
            async for message in self.client.get_chat_history(self.chat_name[0] if isinstance(self.chat_name, list) else self.chat_name, limit=100):
                text = message.text or message.caption
                if text:
                    keys = re.findall(r"Cc-register-[\w]+-[\w]+-[\w]+-[\w]+", text)
                    if keys:
                        self.log.info(f"发现历史邀请码: {keys}")
                        await self._try_invite_codes(keys)
                        return True
        except Exception as e:
            self.log.warning(f"检查历史记录失败: {e}")
        return True

    async def _try_invite_codes(self, keys):
        """尝试使用邀请码列表"""
        wr = async_partial(self.client.wait_reply, self.bot_username)
        
        for invite_code in keys:
            success = False
            for _ in range(3):
                try:
                    msg = None
                    async for m in self.client.get_chat_history(self.bot_username, limit=1):
                        msg = m
                    if msg and msg.reply_markup and any(
                        "兑换注册码" in k.text for r in msg.reply_markup.inline_keyboard for k in r
                    ):
                        pass
                    else:
                        msg = await wr("/start")
                    
                    if "请确认好重试" in (msg.text or msg.caption):
                        continue
                    elif "欢迎使用" in (msg.text or msg.caption) and msg.reply_markup:
                        keys_btn = [k.text for r in msg.reply_markup.inline_keyboard for k in r]
                        for k in keys_btn:
                            if "兑换注册码" in k:
                                async with self.client.catch_reply(
                                    self.bot_username, filter=filters.regex(".*请把注册码发给我.*")
                                ) as f:
                                    try:
                                        await msg.click(k)
                                    except (TimeoutError, MessageIdInvalid):
                                        pass
                                    try:
                                        await asyncio.wait_for(f, 10)
                                    except asyncio.TimeoutError:
                                        continue
                                    else:
                                        break
                        else:
                            continue
                        
                        msg = await wr(invite_code)
                        
                        if "已被使用" in (msg.text or msg.caption) or "无效" in (msg.text or msg.caption):
                            self.log.info(f'邀请码 "{invite_code}" 已被使用或无效，尝试下一个...')
                            break
                        elif "注册成功" in (msg.text or msg.caption) or "成功" in (msg.text or msg.caption):
                            self.log.bind(msg=True).info(
                                f'注册成功！邀请码: "{invite_code}"'
                            )
                            success = True
                            break
                        else:
                            self.log.bind(msg=True).info(
                                f'已发送邀请码 "{invite_code}"，请查看结果.'
                            )
                            success = True
                            break
                    else:
                        continue
                except asyncio.TimeoutError:
                    pass
            
            if success:
                return True
        
        self.log.bind(msg=True).warning(f"共 {len(keys)} 个邀请码，但全部失败.")
        return False

    async def on_trigger(self, message: Message, key, reply):
        """监控到新消息时触发"""
        keys = re.findall(r"Cc-register-[\w]+-[\w]+-[\w]+-[\w]+", message.text or message.caption)
        if not keys:
            return
        await self._try_invite_codes(keys)
