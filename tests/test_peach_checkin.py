import asyncio
from types import SimpleNamespace
from unittest.mock import patch

from pyrogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from embykeeper.telegram.checkiner.peach import PeachCheckin


def make_checkin() -> PeachCheckin:
    context = SimpleNamespace(bind_logger=lambda log: log)
    client = SimpleNamespace(me=SimpleNamespace(full_name="tester"))
    return PeachCheckin(client=client, context=context, config={})


def test_captcha_error_waits_for_new_captcha():
    checkin = make_checkin()
    checkin.captcha_resend_wait = 0
    checkin._last_captcha_at = 0.0
    retries = []

    async def fake_retry():
        retries.append(True)

    checkin.retry = fake_retry
    asyncio.run(checkin.on_captcha_error(SimpleNamespace(), "验证码错误!"))
    # 没有等到新验证码 -> 超时后重新发送签到命令
    assert retries == [True]


def test_captcha_error_skips_retry_when_new_captcha_arrives():
    checkin = make_checkin()
    checkin.captcha_resend_wait = 0
    checkin._last_captcha_at = 1000.5
    retries = []

    async def fake_retry():
        retries.append(True)

    checkin.retry = fake_retry
    with patch("embykeeper.telegram.checkiner.peach.time.time", return_value=1000.0):
        asyncio.run(checkin.on_captcha_error(SimpleNamespace(), "验证码错误!"))
    # 等待期间已收到新验证码 -> 不再重复发送 /start
    assert retries == []


def test_on_text_routes_captcha_error_to_hook():
    checkin = make_checkin()
    checkin.captcha_resend_wait = 0
    checkin._last_captcha_at = 1000.5
    retries = []

    async def fake_retry():
        retries.append(True)

    checkin.retry = fake_retry
    with patch("embykeeper.telegram.checkiner.peach.time.time", return_value=1000.0):
        asyncio.run(checkin.on_text(SimpleNamespace(), "验证码错误!"))
    # 已被 on_captcha_error 处理, 不应再走默认的 "错误" 重试
    assert retries == []


def test_fail_text_retries():
    checkin = make_checkin()
    retries = []

    async def fake_retry():
        retries.append(True)

    checkin.retry = fake_retry
    asyncio.run(checkin.on_text(SimpleNamespace(), "签到失败, 请重试"))
    assert retries == [True]


def test_click_timeout_is_treated_as_clicked():
    checkin = make_checkin()

    class FakeMessage:
        async def click(self, text):
            raise TimeoutError

    assert asyncio.run(checkin._click_checkin(FakeMessage(), "签到")) is True


def test_get_button_texts_supports_inline_keyboard():
    message = SimpleNamespace(
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("签到", callback_data="x")]])
    )
    assert PeachCheckin._get_button_texts(message) == ["签到"]


def test_get_button_texts_supports_reply_keyboard():
    message = SimpleNamespace(reply_markup=ReplyKeyboardMarkup([[KeyboardButton("签到")]]))
    assert PeachCheckin._get_button_texts(message) == ["签到"]


def test_get_button_texts_ignores_non_keyboard_markup():
    message = SimpleNamespace(reply_markup=SimpleNamespace())
    assert PeachCheckin._get_button_texts(message) == []
