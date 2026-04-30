import asyncio
from abc import ABC, abstractmethod

from loguru import logger

from embykeeper.runinfo import RunContext, RunStatus
from embykeeper.utils import show_exception
from embykeeper.config import config
from embykeeper.telegram.pyrogram import Client

__ignore__ = True

logger = logger.bind(scheme="teleregistrar")


class BaseBotRegister(ABC):
    """基础注册类."""

    name: str = None

    def __init__(
        self,
        client: Client,
        context: RunContext = None,
        retries=None,
        timeout=None,
        config=None,
    ):
        self.client = client
        self.ctx = context or RunContext.prepare()

        self._retries = retries
        self._timeout = timeout

        self.config = {} if config is None else config
        self.finished = asyncio.Event()  # 注册完成事件
        self.log = self.ctx.bind_logger(logger.bind(name=self.name, username=client.me.full_name))  # 日志组件

        self._task = None  # 主任务

    @staticmethod
    def _get_registrar_option(name: str, default):
        registrar_config = getattr(config, "registrar", None)
        if registrar_config is None:
            return default
        if isinstance(registrar_config, dict):
            return registrar_config.get(name, default)
        return getattr(registrar_config, name, default)

    @property
    def retries(self):
        if self._retries is not None:
            return self._retries
        return self._get_registrar_option("retries", 1)

    @property
    def timeout(self):
        if self._timeout is not None:
            return self._timeout
        return self._get_registrar_option("timeout", 120)

    async def _start(self):
        """注册器的入口函数的错误处理外壳."""
        try:
            self.client.stop_handlers.append(self.stop)
            self._task = asyncio.create_task(self.start())
            return await self._task
        except Exception as e:
            if config.nofail:
                self.log.warning(f"初始化异常错误, 注册器将停止.")
                show_exception(e, regular=False)
                return self.ctx.finish(RunStatus.ERROR, "异常错误")
            else:
                raise
        finally:
            if hasattr(self.client, "stop_handlers") and self.stop in self.client.stop_handlers:
                self.client.stop_handlers.remove(self.stop)
            self._task = None

    @abstractmethod
    async def start(self) -> RunContext:
        pass

    async def stop(self):
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
