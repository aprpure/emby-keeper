import re
from enum import IntEnum
from io import BytesIO
from typing import Iterable, Optional, Union

from loguru import logger

logger = logger.bind(scheme="ocr")


class CharRange(IntEnum):
    NUMBER = 0
    LLETTER = 1
    ULETTER = 2
    LLETTER_ULETTER = 3
    NUMBER_LLETTER = 4
    NUMBER_ULETTER = 5
    NUMBER_LLETTER_ULETTER = 6
    NOT_NUMBER_LLETTER_ULETTER = 7


# CharRange 对应的正则字符范围 (用于提示词与结果过滤, 不再兼容 ddddocr 语义)
CHAR_RANGE_PATTERNS = {
    CharRange.NUMBER: "0-9",
    CharRange.LLETTER: "a-z",
    CharRange.ULETTER: "A-Z",
    CharRange.LLETTER_ULETTER: "a-zA-Z",
    CharRange.NUMBER_LLETTER: "0-9a-z",
    CharRange.NUMBER_ULETTER: "0-9A-Z",
    CharRange.NUMBER_LLETTER_ULETTER: "0-9A-Za-z",
    CharRange.NOT_NUMBER_LLETTER_ULETTER: "A-Za-z",
}

CHAR_RANGE_HINTS = {
    CharRange.NUMBER: "只包含数字 0-9",
    CharRange.LLETTER: "只包含小写字母 a-z",
    CharRange.ULETTER: "只包含大写字母 A-Z",
    CharRange.LLETTER_ULETTER: "只包含字母, 大小写均可",
    CharRange.NUMBER_LLETTER: "只包含数字和小写字母",
    CharRange.NUMBER_ULETTER: "只包含数字和大写字母",
    CharRange.NUMBER_LLETTER_ULETTER: "只包含数字和字母, 大小写均可",
    CharRange.NOT_NUMBER_LLETTER_ULETTER: "只包含字母, 大小写均可, 不含数字",
}


# 验证码 OCR 默认提示词: 不预设位数, 也不预设是纯数字, 只要求输出验证码字符本身.
CAPTCHA_OCR_PROMPT = (
    "这是一张验证码图片，图片中可能包含干扰线、噪点、字符扭曲、背景图案、水印或其它装饰文字。\n"
    "请逐字符识别图片中的验证码（由字母和/或数字组成），按图片原样输出，大小写均可。\n"
    "要求：\n"
    "1. 只输出验证码本身：一行、连续，不要加空格、标点、引号、代码块或任何解释；\n"
    "2. 忽略图片中的其它文字、水印、边框和装饰，不要输出它们；\n"
    "3. 不要猜测或补全看不清的字符；如果确实无法辨认，直接输出空内容，不要输出任何占位词或说明。\n"
    "示例：验证码为 AB12 时，只输出 AB12。"
)


def _as_list(value) -> list:
    """把 int / str / iterable 统一成 list, 便于处理 expected_len."""
    if value is None:
        return []
    if isinstance(value, (int, str, bytes)):
        return [value]
    try:
        return list(value)
    except TypeError:
        return [value]


def _char_range_pattern(char_range: Optional[Union[CharRange, str]]) -> Optional[str]:
    """把 CharRange / int / str 统一成正则字符范围内容, 如 "0-9A-Za-z"."""
    if char_range is None:
        return None
    if isinstance(char_range, CharRange):
        return CHAR_RANGE_PATTERNS.get(char_range)
    if isinstance(char_range, int):
        try:
            return CHAR_RANGE_PATTERNS.get(CharRange(char_range))
        except ValueError:
            return None
    if isinstance(char_range, str):
        pattern = char_range.strip()
        if not pattern:
            return None
        if "[" in pattern or "]" in pattern:
            logger.warning(f"无效的字符范围 {char_range!r}, 将不限制字符集.")
            return None
        try:
            re.compile(f"[{pattern}]")
        except re.error:
            logger.warning(f"无效的字符范围 {char_range!r}, 将不限制字符集.")
            return None
        return pattern
    return None


def _char_range_hint(char_range: Optional[Union[CharRange, str]]) -> Optional[str]:
    """把字符集转换成提示词里的一句描述."""
    if isinstance(char_range, CharRange):
        return CHAR_RANGE_HINTS.get(char_range)
    if isinstance(char_range, int):
        try:
            return CHAR_RANGE_HINTS.get(CharRange(char_range))
        except ValueError:
            return None
    if isinstance(char_range, str):
        return f"只包含字符范围 {char_range}"
    return None


def build_captcha_prompt(
    char_range: Optional[Union[CharRange, str]] = None,
    expected_len: Optional[Union[int, Iterable[int]]] = None,
    extra: Optional[str] = None,
) -> str:
    """在基础验证码提示词上追加字符集 / 长度等可选提示."""
    prompt = CAPTCHA_OCR_PROMPT
    hints = []
    range_hint = _char_range_hint(char_range)
    if range_hint:
        hints.append(range_hint)
    lengths = sorted({int(n) for n in _as_list(expected_len)})
    if lengths:
        if len(lengths) == 1:
            hints.append(f"验证码长度为 {lengths[0]} 个字符")
        else:
            hints.append("验证码长度为 " + " / ".join(str(n) for n in lengths) + " 个字符")
    if hints:
        prompt += "\n补充：" + "；".join(hints) + "。"
    if extra:
        prompt += "\n" + extra.strip()
    return prompt


def normalize_captcha(
    raw: str,
    expected_len: Optional[Union[int, Iterable[int]]] = None,
    char_range: Optional[Union[CharRange, str]] = None,
) -> str:
    """从 OCR 原文中提取验证码候选, 无法确定时返回空字符串.

    - 不预设字符集和位数; char_range / expected_len 只在调用方显式传入时作为约束.
    - 有 expected_len 时: 优先返回长度匹配的片段; 没有精确匹配但候选更长时按旧
      Peach 行为截断到期望长度; 候选比期望长度还短则返回空.
    - 无 expected_len 时: 拼接所有合法片段 (与旧版去标点/空格的行为一致).
    """
    if not raw:
        return ""
    chars = _char_range_pattern(char_range)
    pattern = f"[{chars}]" if chars else "[0-9A-Za-z]"
    runs = re.findall(f"{pattern}+", raw)
    if not runs:
        return ""
    lengths = sorted({int(n) for n in _as_list(expected_len)})
    if lengths:
        # 1) 精确长度匹配
        for run in runs:
            if len(run) in lengths:
                return run
        joined = "".join(runs)
        if len(joined) in lengths:
            return joined
        # 2) 超长时截断 (兼容旧 Peach 行为)
        longest = max(runs, key=len)
        for candidate in (longest, joined):
            if len(candidate) >= min(lengths):
                fitting = [n for n in lengths if n <= len(candidate)]
                return candidate[: max(fitting)]
        return ""
    return "".join(runs)


class OCRService:
    """验证码 OCR 服务: 组装提示词、调用 LLM、清洗结果.

    站点相关的长度 / 字符集只作为提示传入, 不在这里硬编码.
    """

    @classmethod
    def get(
        cls,
        ocr_name: str = None,
        char_range: Optional[Union[CharRange, str]] = None,
    ):
        return cls(ocr_name, char_range)

    def __init__(
        self,
        ocr_name: str = None,
        char_range: Optional[Union[CharRange, str]] = None,
    ) -> None:
        self.ocr_name = ocr_name
        self.char_range = char_range

    async def run(
        self,
        image_data: Union[BytesIO, bytes],
        *,
        expected_len: Optional[Union[int, Iterable[int]]] = None,
        char_range: Optional[Union[CharRange, str]] = None,
        prompt: Optional[str] = None,
        model: Optional[str] = None,
        timeout: Optional[int] = None,
    ) -> str:
        """识别验证码, 返回清洗后的候选; 无法识别返回空字符串.

        - expected_len / char_range 只作为提示, 不传则不限制;
        - prompt 可整体覆盖默认验证码提示词;
        - model 不传时使用 ocr_name (站点配置的 OCR 模型名).
        """
        from . import llm

        if isinstance(image_data, (bytes, bytearray)):
            photo_bytes = bytes(image_data)
        elif hasattr(image_data, "getvalue"):
            photo_bytes = image_data.getvalue()
        else:
            image_data.seek(0)
            photo_bytes = image_data.read()

        effective_range = char_range if char_range is not None else self.char_range
        effective_prompt = prompt or build_captcha_prompt(effective_range, expected_len)
        result = await llm.ocr(
            photo_bytes,
            prompt=effective_prompt,
            model=model or self.ocr_name,
            timeout=timeout,
        )
        if not result:
            logger.debug("OCR 未返回结果.")
            return ""
        captcha = normalize_captcha(result, expected_len=expected_len, char_range=effective_range)
        logger.debug(f"OCR 原始={result!r} → 清洗={captcha!r}.")
        return captcha
