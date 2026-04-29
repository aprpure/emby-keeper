"""LLM 大语言模型客户端, 用于视觉识别和智能回答, 作为 @embykeeper_auth_bot 的本地替代方案."""

import base64
from typing import List, Optional, Tuple

import httpx
from loguru import logger

from .config import config
from .utils import get_proxy_str

logger = logger.bind(scheme="llm")


async def _chat_completion(
    messages: list,
    model: Optional[str] = None,
    timeout: int = 60,
) -> Optional[str]:
    """调用 OpenAI 兼容 API 的 chat completion."""
    llm_cfg = getattr(config, "llm", None)
    if not llm_cfg or not llm_cfg.api_key:
        return None

    base_url = (llm_cfg.base_url or "https://api.openai.com/v1").rstrip("/")
    model = model or llm_cfg.model or "gpt-4o-mini"
    proxy_str = get_proxy_str(config.proxy) if config.proxy else None

    headers = {
        "Authorization": f"Bearer {llm_cfg.api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": 512,
        "temperature": 0.1,
    }

    try:
        async with httpx.AsyncClient(proxy=proxy_str, timeout=timeout) as client:
            resp = await client.post(
                f"{base_url}/chat/completions",
                headers=headers,
                json=payload,
            )
            if resp.status_code == 200:
                data = resp.json()
                return data["choices"][0]["message"]["content"].strip()
            else:
                logger.debug(f"LLM API 返回异常状态码 {resp.status_code}: {resp.text[:200]}")
                return None
    except Exception as e:
        err_msg = str(e) or type(e).__name__
        logger.debug(f"LLM API 请求失败: {err_msg}")
        return None


async def gpt(prompt: str) -> Optional[str]:
    """使用 LLM 进行智能回答."""
    llm_cfg = getattr(config, "llm", None)
    if not llm_cfg or not llm_cfg.api_key:
        return None
    model = llm_cfg.model or "gpt-4o-mini"
    messages = [{"role": "user", "content": prompt}]
    return await _chat_completion(messages, model=model, timeout=llm_cfg.timeout or 60)


async def visual(photo_bytes: bytes, options: List[str], question: Optional[str] = None) -> Optional[str]:
    """使用 LLM 视觉模型识别图片并从选项中选择答案."""
    llm_cfg = getattr(config, "llm", None)
    if not llm_cfg or not llm_cfg.api_key:
        return None
    model = llm_cfg.vision_model or llm_cfg.model or "gpt-4o-mini"

    b64_image = base64.b64encode(photo_bytes).decode("utf-8")

    text = (
        f"请从以下选项中选择与图片内容最匹配的一个: {', '.join(options)}\n"
        "只输出选项文本, 不要输出任何其他内容."
    )
    if question:
        text = f"{question}\n{text}"

    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": text},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{b64_image}"},
                },
            ],
        }
    ]
    return await _chat_completion(messages, model=model, timeout=llm_cfg.timeout or 60)


async def ocr(photo_bytes: bytes) -> Optional[str]:
    """使用 LLM 视觉模型进行 OCR 文字识别."""
    llm_cfg = getattr(config, "llm", None)
    if not llm_cfg or not llm_cfg.api_key:
        return None
    model = llm_cfg.vision_model or llm_cfg.model or "gpt-4o-mini"

    b64_image = base64.b64encode(photo_bytes).decode("utf-8")

    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "请识别图片中的所有文字, 只输出文字内容, 不要输出任何其他内容."},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{b64_image}"},
                },
            ],
        }
    ]
    return await _chat_completion(messages, model=model, timeout=llm_cfg.timeout or 60)
