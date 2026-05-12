from enum import IntEnum
from typing import Optional, Union
from io import BytesIO
import asyncio
import time


class CharRange(IntEnum):
    NUMBER = 0
    LLETTER = 1
    ULETTER = 2
    LLETTER_ULETTER = 3
    NUMBER_LLETTER = 4
    NUMBER_ULETTER = 5
    NUMBER_LLETTER_ULETTER = 6
    NOT_NUMBER_LLETTER_ULETTER = 7


class OCRService:
    _pool = {}
    _pool_lock = asyncio.Lock()

    @classmethod
    async def get(
        cls,
        ocr_name: str = None,
        char_range: Optional[Union[CharRange, str]] = None,
    ):
        # 创建用于标识唯一实例的键
        key = (ocr_name, char_range)
        async with cls._pool_lock:
            # 检查池中是否存在相同配置的实例
            if key in cls._pool:
                return cls._pool[key]
            instance = cls(ocr_name, char_range)
            cls._pool[key] = instance
            return instance

    def __init__(
        self,
        ocr_name: str = None,
        char_range: Optional[Union[CharRange, str]] = None,
    ) -> None:
        self.ocr_name = ocr_name
        self.char_range = char_range

        self._subscribers = 0
        self._last_active = time.time()

    async def run(self, image_data: BytesIO, timeout: int = 60, gif: bool = False) -> str:
        """使用LLM进行OCR识别"""
        from . import llm

        photo_bytes = image_data.getvalue()
        result = await llm.ocr(photo_bytes)
        if result:
            return result.strip()
        raise Exception("LLM OCR识别返回空结果, 请检查 LLM 配置")

    def subscribe(self):
        """增加使用者计数"""
        self._subscribers += 1
        self._last_active = time.time()

    def unsubscribe(self):
        """减少使用者计数"""
        self._subscribers = max(0, self._subscribers - 1)
        self._last_active = time.time()

    def __enter__(self):
        """上下文管理器入口"""
        self.subscribe()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器出口"""
        self.unsubscribe()
        return False  # 返回False允许异常正常传播
