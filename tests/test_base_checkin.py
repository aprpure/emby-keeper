import asyncio
from types import SimpleNamespace
from unittest.mock import patch

from embykeeper.telegram.checkiner._base import BotCheckin


def make_checkin() -> BotCheckin:
    context = SimpleNamespace(bind_logger=lambda log: log)
    client = SimpleNamespace(me=SimpleNamespace(full_name="tester"))
    return BotCheckin(client=client, context=context, config={})


def test_on_photo_submits_recognized_captcha():
    checkin = make_checkin()
    checkin.bot_captcha_len = 4
    submitted = []
    retried = []

    async def fake_on_captcha(message, captcha):
        submitted.append(captcha)

    async def fake_retry():
        retried.append(True)

    async def fake_download(message, in_memory=False):
        return b"img"

    class FakeOCR:
        async def run(self, data, expected_len=None):
            assert expected_len == 4
            return "AB12"

    checkin.on_captcha = fake_on_captcha
    checkin.retry = fake_retry
    checkin.client = SimpleNamespace(
        download_media=fake_download,
        me=SimpleNamespace(full_name="tester"),
    )

    with patch("embykeeper.telegram.checkiner._base.OCRService.get", return_value=FakeOCR()):
        with patch("embykeeper.telegram.checkiner._base.random.uniform", return_value=0):
            asyncio.run(checkin.on_photo(SimpleNamespace()))

    assert submitted == ["AB12"]
    assert retried == []


def test_on_photo_retries_when_ocr_returns_empty():
    checkin = make_checkin()
    checkin.bot_captcha_len = 4
    submitted = []
    retried = []

    async def fake_on_captcha(message, captcha):
        submitted.append(captcha)

    async def fake_retry():
        retried.append(True)

    async def fake_download(message, in_memory=False):
        return b"img"

    class FakeOCR:
        async def run(self, data, expected_len=None):
            return ""

    checkin.on_captcha = fake_on_captcha
    checkin.retry = fake_retry
    checkin.client = SimpleNamespace(
        download_media=fake_download,
        me=SimpleNamespace(full_name="tester"),
    )

    with patch("embykeeper.telegram.checkiner._base.OCRService.get", return_value=FakeOCR()):
        asyncio.run(checkin.on_photo(SimpleNamespace()))

    assert submitted == []
    assert retried == [True]


def test_on_text_captcha_error_hook_short_circuits():
    checkin = make_checkin()
    checkin.bot_captcha_error_keywords = ["验证码错误"]
    handled = []
    retried = []

    async def fake_on_captcha_error(message, text):
        handled.append(text)
        return True

    async def fake_retry():
        retried.append(True)

    checkin.on_captcha_error = fake_on_captcha_error
    checkin.retry = fake_retry

    asyncio.run(checkin.on_text(SimpleNamespace(), "验证码错误!"))

    assert handled == ["验证码错误!"]
    assert retried == []


def test_on_text_captcha_error_hook_can_fall_through_to_retry():
    checkin = make_checkin()
    checkin.bot_captcha_error_keywords = ["验证码错误"]
    retried = []

    async def fake_on_captcha_error(message, text):
        return False

    async def fake_retry():
        retried.append(True)

    checkin.on_captcha_error = fake_on_captcha_error
    checkin.retry = fake_retry

    asyncio.run(checkin.on_text(SimpleNamespace(), "验证码错误!"))

    assert retried == [True]
