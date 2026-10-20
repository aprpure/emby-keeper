import asyncio
from io import BytesIO

from embykeeper import llm
from embykeeper.ocr import (
    CharRange,
    OCRService,
    build_captcha_prompt,
    normalize_captcha,
)


def test_normalize_captcha_digits_and_letters():
    assert normalize_captcha("1234", expected_len=4) == "1234"
    assert normalize_captcha("12 34", expected_len=4) == "1234"
    assert normalize_captcha("K7m2", expected_len=4) == "K7m2"
    assert normalize_captcha("验证码: K7M2", expected_len=4) == "K7M2"


def test_normalize_captcha_no_assumptions():
    # 不传 expected_len 时拼接所有合法片段
    assert normalize_captcha("AB12") == "AB12"
    assert normalize_captcha("验证码: AB12") == "AB12"
    assert normalize_captcha("") == ""
    assert normalize_captcha("请输入验证码") == ""
    assert normalize_captcha("A B 1 2", expected_len=4) == "AB12"


def test_normalize_captcha_truncates_longer_candidates():
    # 兼容旧 Peach 行为: 超长时截断到期望长度
    assert normalize_captcha("12345", expected_len=4) == "1234"
    assert normalize_captcha("AB12CD", expected_len=4) == "AB12"
    assert normalize_captcha("123", expected_len=4) == ""
    assert normalize_captcha("1234", expected_len=[3, 4]) == "1234"


def test_normalize_captcha_respects_char_range():
    assert normalize_captcha("A1b2", char_range=CharRange.NUMBER) == "12"
    assert normalize_captcha("A1b2", char_range="0-9") == "12"
    assert normalize_captcha("A1b2", expected_len=2, char_range=CharRange.NUMBER) == "12"
    # 非法字符范围回退为默认字母数字
    assert normalize_captcha("AB12", char_range="[") == "AB12"


def test_build_captcha_prompt_is_optional():
    prompt = build_captcha_prompt()
    assert "字母" in prompt and "数字" in prompt
    assert "4 位" not in prompt
    prompt = build_captcha_prompt(expected_len=4)
    assert "4 个字符" in prompt
    prompt = build_captcha_prompt(char_range=CharRange.NUMBER)
    assert "数字" in prompt
    prompt = build_captcha_prompt(char_range="0-9")
    assert "0-9" in prompt


def test_ocr_service_forwards_prompt_and_normalizes():
    captured = {}
    original = llm.ocr

    async def fake_ocr(photo_bytes, prompt=None, model=None, timeout=None):
        captured.update(bytes=photo_bytes, prompt=prompt, model=model, timeout=timeout)
        return "验证码: A B 1 2"

    llm.ocr = fake_ocr
    try:
        result = asyncio.run(OCRService(ocr_name="my-vl").run(BytesIO(b"img"), expected_len=4))
    finally:
        llm.ocr = original

    assert result == "AB12"
    assert captured["bytes"] == b"img"
    assert captured["model"] == "my-vl"
    assert "4 个字符" in captured["prompt"]


def test_ocr_service_returns_empty_on_ocr_failure():
    original = llm.ocr

    async def fake_ocr(*args, **kwargs):
        return None

    llm.ocr = fake_ocr
    try:
        result = asyncio.run(OCRService().run(b"img"))
    finally:
        llm.ocr = original

    assert result == ""
