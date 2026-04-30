from __future__ import annotations

import asyncio
import random
import re
from typing import Optional, TYPE_CHECKING

from pyrogram.errors import MessageIdInvalid
from pyrogram.types import Message
from pyrogram.raw.types.messages import BotCallbackAnswer

from .pyrogram import Client

if TYPE_CHECKING:
    from loguru import Logger


class EmbybossRegister:
    credential_reply_timeout = 30
    credential_burst_count = 3
    credential_burst_reply_timeout = 3
    credential_resend_delay = 3
    registration_result_timeout = 180
    registration_ready_keywords = (
        "开放注册中",
        "资质核验成功",
    )
    registration_prompt_keywords = (
        "进入注册状态",
        "请输入 [用户名][空格][安全码]",
        "请在2min内输入 [用户名][空格][安全码]",
    )
    registration_closed_keywords = (
        "已关闭",
        "未开放",
        "暂未开放",
        "暂未开启",
        "名额不足",
        "席位不足",
        "自助注册已关闭",
    )
    registration_waiting_keywords = (
        "正在加入注册队列",
        "已进入注册队列",
        "请耐心等待",
        "已进入处理",
        "正在为您初始化账户",
        "正在创建用户",
    )
    registration_success_keywords = (
        "创建用户成功",
    )
    registration_failure_keywords = (
        "已有此账户名",
        "检查有无特殊字符",
        "服务器连接不通",
        "当前没有可用注册资格",
        "你已经有账户啦",
        "账户状态已变化",
        "已达总注册限制",
        "剩余可注册总数",
        "数据库没有你",
        "账户初始化失败",
    )

    def __init__(self, client: Client, logger: Logger, username: str, password: str, click_delay=(0.5, 1.5)):
        self.client = client
        self.log = logger
        self.username = username
        self.password = password
        self.click_delay = click_delay

    @staticmethod
    def _message_text(message: Optional[Message]):
        if not message:
            return ""
        return (message.text or message.caption or "").strip()

    @classmethod
    def _is_registration_prompt(cls, text: str):
        return any(keyword in text for keyword in cls.registration_prompt_keywords)

    @classmethod
    def _is_registration_ready(cls, text: str):
        return any(keyword in text for keyword in cls.registration_ready_keywords)

    @classmethod
    def _is_registration_closed(cls, text: str):
        return any(keyword in text for keyword in cls.registration_closed_keywords)

    @classmethod
    def _is_registration_waiting(cls, text: str):
        return any(keyword in text for keyword in cls.registration_waiting_keywords)

    @classmethod
    def _is_registration_success(cls, text: str):
        return any(keyword in text for keyword in cls.registration_success_keywords)

    @classmethod
    def _is_registration_failure(cls, text: str):
        return any(keyword in text for keyword in cls.registration_failure_keywords)

    async def _handle_credential_response(self, message: Message):
        text = self._message_text(message)
        if self._is_registration_success(text):
            self.log.info("注册成功!")
            return True
        if self._is_registration_waiting(text):
            return await self._wait_registration_result(message)
        if self._is_registration_failure(text):
            self.log.warning("发送凭据后注册失败.")
            return False
        if self._is_registration_closed(text):
            self.log.warning("发送凭据后注册失败.")
            return False
        return None

    async def _submit_credentials(self, chat_id: int):
        credential_text = f"{self.username} {self.password}"
        deadline = asyncio.get_running_loop().time() + self.credential_reply_timeout

        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                self.log.warning("发送凭据后无响应, 无法注册.")
                return False

            response_timeout = min(self.credential_burst_reply_timeout, remaining)
            async with self.client.catch_reply(chat_id) as f:
                for _ in range(self.credential_burst_count):
                    await self.client.send_message(chat_id, credential_text)

                try:
                    msg: Message = await asyncio.wait_for(f, response_timeout)
                except asyncio.TimeoutError:
                    msg = None

            if msg is not None:
                result = await self._handle_credential_response(msg)
                if result is not None:
                    return result

            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                self.log.warning("发送凭据后无响应, 无法注册.")
                return False

            await asyncio.sleep(min(self.credential_resend_delay, remaining))

    async def _wait_registration_result(self, message: Message):
        current_message = message
        deadline = asyncio.get_running_loop().time() + self.registration_result_timeout

        while True:
            text = self._message_text(current_message)
            if self._is_registration_success(text):
                self.log.info("注册成功!")
                return True
            if self._is_registration_failure(text):
                self.log.warning("发送凭据后注册失败.")
                return False
            if not self._is_registration_waiting(text):
                self.log.warning("发送凭据后注册失败.")
                return False

            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                self.log.warning("等待注册结果超时, 无法注册.")
                return False

            try:
                current_message = await self.client.wait_edit(current_message, timeout=remaining)
            except asyncio.TimeoutError:
                self.log.warning("等待注册结果超时, 无法注册.")
                return False

    async def run(self, bot: str):
        """单次注册尝试"""
        return await self._register_once(bot)

    async def run_continuous(self, bot: str, interval_seconds: float = 1):
        try:
            panel = await self.client.wait_reply(bot, "/start")
        except asyncio.TimeoutError:
            self.log.warning("初始命令无响应, 无法注册.")
            return False

        while True:
            try:
                result = await self._attempt_with_panel(panel)
                if result:
                    self.log.info(f"注册成功")
                    return True

                if interval_seconds:
                    self.log.debug(f"注册失败, {interval_seconds} 秒后重试.")
                    await asyncio.sleep(interval_seconds)
                else:
                    self.log.debug(f"注册失败, 即将重试.")
                    return False
            except (MessageIdInvalid, ValueError, AttributeError):
                # 面板失效或结构变化, 重新获取
                self.log.debug("面板失效, 正在重新获取...")
                try:
                    panel = await self.client.wait_reply(bot, "/start")
                except asyncio.TimeoutError:
                    if interval_seconds:
                        self.log.warning("重新获取面板失败, 等待后重试.")
                        await asyncio.sleep(interval_seconds)
                        continue
                    else:
                        self.log.warning("重新获取面板失败, 无法注册.")
                        return False
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.log.error(f"注册异常: {e}")
                await asyncio.sleep(5)
        return False

    async def _register_once(self, bot: str):
        try:
            panel = await self.client.wait_reply(bot, "/start")
        except asyncio.TimeoutError:
            self.log.warning("初始命令无响应, 无法注册.")
            return False

        text = panel.text or panel.caption or ""
        try:
            current_status_match = re.search(r"当前状态 \| ([^\n]+)", text)
            register_status_match = re.search(r"注册状态 \| (True|False)", text)
            available_slots_match = re.search(r"可注册席位 \| (\d+)", text)
            if (
                current_status_match is None
                or register_status_match is None
                or available_slots_match is None
            ):
                raise ValueError

            current_status = current_status_match.group(1).strip()
            register_status = register_status_match.group(1) == "True"
            available_slots = int(available_slots_match.group(1))
        except (AttributeError, ValueError):
            self.log.warning("无法解析界面, 无法注册, 可能您已注册.")
            return False

        if current_status != "未注册":
            self.log.warning("当前状态不是未注册, 无法注册.")
            return False
        if not register_status:
            self.log.debug(f"未开注, 将继续监控.")
            return False
        if available_slots <= 0:
            self.log.debug("可注册席位不足, 将继续监控.")
            return False

        return await self._attempt_with_panel(panel)

    async def _attempt_with_panel(self, panel: Message):
        # 点击创建账户按钮
        buttons = panel.reply_markup.inline_keyboard
        create_button = None
        for row in buttons:
            for button in row:
                if "创建账户" in button.text:
                    create_button = button.text
                    break
            if create_button:
                break

        if not create_button:
            self.log.warning("找不到创建账户按钮, 无法注册.")
            return False

        await asyncio.sleep(random.uniform(*self.click_delay))

        answer_text = ""
        prompt_text = ""
        chat_id = panel.chat.id

        async with self.client.catch_reply(panel.chat.id) as f:
            try:
                answer: BotCallbackAnswer = await panel.click(create_button)
                answer_text = (getattr(answer, "message", None) or "").strip()
                if self._is_registration_closed(answer_text):
                    self.log.debug("未开注, 将继续监控.")
                    return False
                if self._is_registration_failure(answer_text):
                    self.log.warning("创建账户按钮点击后注册失败.")
                    return False
            except (TimeoutError, MessageIdInvalid):
                pass
            try:
                msg: Message = await asyncio.wait_for(f, 5)
            except asyncio.TimeoutError:
                if self._is_registration_prompt(answer_text):
                    prompt_text = answer_text
                elif self._is_registration_ready(answer_text):
                    self.log.warning("收到注册资格回调但未收到注册提示, 无法注册.")
                    return False
                else:
                    self.log.warning("创建账户按钮点击无响应, 无法注册.")
                    return False
            else:
                prompt_text = self._message_text(msg)
                chat_id = msg.chat.id
                if self._is_registration_closed(prompt_text):
                    self.log.debug("未开注, 将继续监控.")
                    return False
                if self._is_registration_failure(prompt_text):
                    self.log.warning("创建账户按钮点击后注册失败.")
                    return False

        if not self._is_registration_prompt(prompt_text):
            if self._is_registration_prompt(answer_text):
                prompt_text = answer_text
            else:
                self.log.warning("未能正常进入注册状态, 注册失败.")
                return False

        return await self._submit_credentials(chat_id)
