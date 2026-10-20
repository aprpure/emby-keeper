import random
from typing import Iterable, List, Optional, Union

from loguru import logger
from pydantic import BaseModel, ValidationError

from embykeeper.ocr import CharRange
from embykeeper.utils import to_iterable

from . import BotCheckin

__ignore__ = True


class TemplateBCheckinConfig(BaseModel):
    # fmt: off
    name: Optional[str] = None  # 签到器的名称
    bot_checkin_cmd: Union[str, List[str]] = ["/checkin"]  # Bot 依次执行的签到命令
    bot_send_interval: int = 3  # 签到命令间等待的秒数
    bot_use_captcha: bool = True  # 当 Bot 返回图片时, 识别验证码并调用 on_captcha
    bot_checkin_caption_pat: Optional[str] = None  # 当 Bot 返回图片时, 仅当符合该 regex 才识别为验证码, 置空不限制
    bot_text_ignore: Union[str, List[str]] = []  # 当含有列表中的关键词, 即忽略该消息, 置空不限制
    ocr: Optional[str] = None  # OCR 模型, None = 默认模型, str = 自定义模型
    bot_captcha_char_range: Optional[Union[CharRange, str]] = None  # OCR 字符范围 (正则字符类, 如 "0-9" / "0-9A-Za-z"), None = 不限制
    bot_captcha_len: Union[int, Iterable[int]] = []  # 验证码长度的可能范围, 例如 [1, 2, 3], 置空不限制
    bot_success_pat: str = r"(\d+)[^\d]*(\d+)"  # 当接收到成功消息后, 从消息中提取数字的模式
    bot_retry_wait: int = 2  # 失败时等待的秒数
    bot_use_history: Optional[int] = None  # 首先尝试识别历史记录中最后一个验证码图片, 最多识别 N 条, 置空禁用
    bot_allow_from_scratch: bool = False  # 允许从未聊天情况下启动
    bot_success_keywords: Union[str, List[str]] = ([])  # 成功时检测的关键词 (暂不支持regex), 置空使用内置关键词表
    bot_checked_keywords: Union[str, List[str]] = []  # 今日已签到时检测的关键词, 置空使用内置关键词表
    bot_account_fail_keywords: Union[str, List[str]] = ([])  # 账户错误将退出时检测的关键词 (暂不支持regex), 置空使用内置关键词表
    bot_too_many_tries_fail_keywords: Union[str, List[str]] = ([])  # 过多尝试将退出时检测的关键词 (暂不支持regex), 置空使用内置关键词表
    bot_fail_keywords: Union[str, List[str]] = ([])  # 签到错误将重试时检测的关键词 (暂不支持regex), 置空使用内置关键词表
    is_chat: bool = False  # 指定的用户名为群组用户名或 ID, 而非机器人
    max_retries: Optional[int] = None  # 验证码错误或网络错误时最高重试次数 (默认无限)
    checked_retries: Optional[int] = None  # 今日已签到时最高重试次数 (默认不重试)
    wait_response: bool = True  # 是否需要等待相关回复, 以确认签到完成
    # fmt: on


class TemplateBCheckin(BotCheckin):
    init_first = True
    additional_auth = ["prime"]

    async def init(self):
        try:
            self.t_config = TemplateBCheckinConfig.model_validate(self.config)
        except ValidationError as e:
            self.log.warning(f"初始化失败: 签到自定义模板 B 的配置错误:\n{e}")
            return False
        self.name = self.t_config.name or "自定义"

        if self.t_config.is_chat:
            self.chat_name = self.bot_username
            self.bot_username = None
        self.bot_checkin_cmd = self.t_config.bot_checkin_cmd
        self.bot_send_interval = self.t_config.bot_send_interval
        self.bot_use_captcha = self.t_config.bot_use_captcha
        self.bot_checkin_caption_pat = self.t_config.bot_checkin_caption_pat
        self.bot_text_ignore = self.t_config.bot_text_ignore
        self.ocr = self.t_config.ocr
        self.bot_captcha_char_range = self.t_config.bot_captcha_char_range
        self.bot_captcha_len = self.t_config.bot_captcha_len
        self.bot_success_pat = self.t_config.bot_success_pat
        self.bot_retry_wait = self.t_config.bot_retry_wait
        self.bot_use_history = self.t_config.bot_use_history
        self.bot_allow_from_scratch = self.t_config.bot_allow_from_scratch
        self.bot_success_keywords = self.t_config.bot_success_keywords
        self.bot_checked_keywords = self.t_config.bot_checked_keywords
        self.bot_account_fail_keywords = self.t_config.bot_account_fail_keywords
        self.bot_too_many_tries_fail_keywords = self.t_config.bot_too_many_tries_fail_keywords
        self.bot_fail_keywords = self.t_config.bot_fail_keywords
        self.max_retries = self.t_config.max_retries
        self.checked_retries = self.t_config.checked_retries

        self.log = logger.bind(scheme="telechecker", name=self.name, username=self.client.me.full_name)
        return True

    async def send_checkin(self, **kw):
        if self.chat_name:
            cmd = random.choice(to_iterable(self.bot_checkin_cmd))
            await self.send(cmd)
            if not self.t_config.wait_response:
                await self.finish(message="群组发言已发送")
        else:
            await super().send_checkin(**kw)
            if not self.t_config.wait_response:
                await self.finish(message="签到命令已发送")


def use(**kw):
    return type("TemplatedClass", (TemplateBCheckin,), kw)
