from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import random
import re
from typing import Optional, TYPE_CHECKING

from pyrogram import filters
from pyrogram.errors import MessageIdInvalid
from pyrogram.handlers import MessageHandler
from pyrogram.types import Message
from pyrogram.raw.types.messages import BotCallbackAnswer

from .pyrogram import Client

if TYPE_CHECKING:
    from loguru import Logger


class EmbybossRegister:
    # 阶段 1: 抢开注.
    # 在同一张面板上持续点击“创建账户”, 直到收到进入注册状态的信号,
    # 或者本轮窗口超时后立刻进入下一轮.
    create_button_reply_timeout = 5
    create_button_callback_timeout = 0.5
    create_button_max_inflight = 5

    # 阶段 2: 已进入注册状态.
    # 连续发送“用户名 安全码”, 并在限定时间内等待机器人进入处理流程.
    credential_reply_timeout = 30
    credential_burst_count = 3
    credential_burst_reply_timeout = 3
    credential_resend_delay = 3

    # 阶段 3: 已进入处理队列.
    # 机器人已经开始创建账户, 此时等待最终成功或失败结果.
    registration_result_timeout = 60

    # 文案分类.
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
    registration_success_keywords = ("创建用户成功",)
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

    @staticmethod
    def _preview_text(text: str, limit: int = 80):
        text = re.sub(r"\s+", " ", (text or "")).strip()
        if len(text) > limit:
            return text[: limit - 3] + "..."
        return text

    @asynccontextmanager
    async def _catch_reply_queue(self, chat_id: int):
        queue = asyncio.Queue()

        async def handler_func(client, message: Message):
            queue.put_nowait(message)

        handler = MessageHandler(handler_func, filters.chat(chat_id) & (~filters.outgoing))
        await self.client.add_handler(handler, group=0)
        try:
            yield queue
        finally:
            try:
                await self.client.remove_handler(handler, group=0)
            except ValueError:
                pass

    @staticmethod
    def _set_outcome(
        outcome: asyncio.Future,
        status: str,
        chat_id: Optional[int] = None,
        source: Optional[str] = None,
        signal_text: Optional[str] = None,
    ):
        if not outcome.done():
            outcome.set_result((status, chat_id, source, signal_text))

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

    async def _watch_registration_replies(
        self,
        replies: asyncio.Queue,
        outcome: asyncio.Future,
        deadline: float,
        metrics: dict,
    ):
        while not outcome.done():
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                return
            try:
                msg: Message = await asyncio.wait_for(replies.get(), timeout=remaining)
            except asyncio.TimeoutError:
                return

            text = self._message_text(msg)
            metrics["reply_messages"] += 1
            if self._is_registration_prompt(text):
                self._set_outcome(outcome, "prompt", msg.chat.id, "reply_prompt", text)
                return
            if self._is_registration_failure(text):
                self._set_outcome(outcome, "failure", None, "reply_failure", text)
                return

    async def _spam_create_button(
        self,
        panel: Message,
        create_button: str,
        outcome: asyncio.Future,
        deadline: float,
        metrics: dict,
    ):
        window_clicks = 0
        next_report_at = asyncio.get_running_loop().time() + 1
        inflight_clicks = set()

        async def click_once():
            try:
                answer: BotCallbackAnswer = await panel.click(
                    create_button,
                    timeout=min(self.create_button_callback_timeout, max(deadline - asyncio.get_running_loop().time(), 0.1)),
                )
            except (TimeoutError, MessageIdInvalid):
                metrics["callback_timeouts"] += 1
                return

            answer_text = (getattr(answer, "message", None) or "").strip()
            metrics["callback_answers"] += 1
            if self._is_registration_prompt(answer_text):
                self._set_outcome(outcome, "prompt", panel.chat.id, "callback_prompt", answer_text)
            elif self._is_registration_failure(answer_text):
                self._set_outcome(outcome, "failure", None, "callback_failure", answer_text)

        try:
            while not outcome.done():
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    return

                inflight_clicks = {task for task in inflight_clicks if not task.done()}
                if len(inflight_clicks) >= self.create_button_max_inflight:
                    await asyncio.sleep(min(0.02, remaining))
                    continue

                await asyncio.sleep(min(random.uniform(*self.click_delay), remaining))
                if outcome.done():
                    return

                metrics["clicks_total"] += 1
                window_clicks += 1

                task = asyncio.create_task(click_once())
                inflight_clicks.add(task)

                now = asyncio.get_running_loop().time()
                if now >= next_report_at:
                    self.log.debug(
                        f"创建账户点击速率: {window_clicks}/s, 累计点击 {metrics['clicks_total']} 次, "
                        f"进行中回调 {len(inflight_clicks)} 个, 收到回调 {metrics['callback_answers']} 次, "
                        f"回调超时 {metrics['callback_timeouts']} 次, 收到回复 {metrics['reply_messages']} 条."
                    )
                    window_clicks = 0
                    next_report_at = now + 1
        finally:
            for task in inflight_clicks:
                task.cancel()
            if inflight_clicks:
                await asyncio.gather(*inflight_clicks, return_exceptions=True)

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
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.credential_reply_timeout

        while True:
            round_started_at = loop.time()
            remaining = deadline - round_started_at
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

            remaining = deadline - loop.time()
            if remaining <= 0:
                self.log.warning("发送凭据后无响应, 无法注册.")
                return False

            next_round_delay = max(0, self.credential_resend_delay - (loop.time() - round_started_at))
            if next_round_delay > 0:
                await asyncio.sleep(min(next_round_delay, remaining))

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

                if interval_seconds and interval_seconds > 0:
                    self.log.debug(f"注册失败, {interval_seconds} 秒后重试.")
                    await asyncio.sleep(interval_seconds)
                else:
                    self.log.debug(f"注册失败, 即将重试.")
                    await asyncio.sleep(0)
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
            if current_status_match is None or register_status_match is None or available_slots_match is None:
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

        started_at = asyncio.get_running_loop().time()
        deadline = asyncio.get_running_loop().time() + self.create_button_reply_timeout
        outcome = asyncio.get_running_loop().create_future()
        metrics = {
            "clicks_total": 0,
            "callback_answers": 0,
            "callback_timeouts": 0,
            "reply_messages": 0,
        }

        async with self._catch_reply_queue(panel.chat.id) as replies:
            click_task = asyncio.create_task(
                self._spam_create_button(panel, create_button, outcome, deadline, metrics)
            )
            reply_task = asyncio.create_task(
                self._watch_registration_replies(replies, outcome, deadline, metrics)
            )
            try:
                status, chat_id, source, signal_text = await asyncio.wait_for(
                    outcome, timeout=self.create_button_reply_timeout
                )
            except asyncio.TimeoutError:
                elapsed = asyncio.get_running_loop().time() - started_at
                self.log.debug(
                    f"未开注, {elapsed:.2f} 秒内累计点击 {metrics['clicks_total']} 次, "
                    f"收到回调 {metrics['callback_answers']} 次, 回调超时 {metrics['callback_timeouts']} 次, "
                    f"收到回复 {metrics['reply_messages']} 条."
                )
                return False
            finally:
                click_task.cancel()
                reply_task.cancel()
                await asyncio.gather(click_task, reply_task, return_exceptions=True)

        if status == "failure":
            self.log.warning(
                f"创建账户按钮点击后注册失败: 来源={source or 'unknown'}, "
                f"信号={self._preview_text(signal_text)}, 累计点击 {metrics['clicks_total']} 次."
            )
            return False

        elapsed = asyncio.get_running_loop().time() - started_at
        self.log.debug(
            f"进入注册状态: 来源={source or 'unknown'}, 耗时 {elapsed:.2f} 秒, "
            f"累计点击 {metrics['clicks_total']} 次, 收到回调 {metrics['callback_answers']} 次, "
            f"回调超时 {metrics['callback_timeouts']} 次, 收到回复 {metrics['reply_messages']} 条, "
            f"信号={self._preview_text(signal_text)}."
        )

        return await self._submit_credentials(chat_id)
