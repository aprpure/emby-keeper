import asyncio
import io

from rich.text import Text
from loguru import logger

from embykeeper.schema import TelegramAccount
from embykeeper.utils import show_exception

from .link import Link
from .session import ClientsSession

logger = logger.bind(scheme="telenotifier", nonotify=True)


class TelegramStream(io.TextIOWrapper):
    """消息推送处理器类"""

    MAX_CONSECUTIVE_FAILURES = 3  # 连续失败次数阈值, 超过后暂停推送
    COOLDOWN_SECONDS = 300  # 暂停推送后冷却时间 (秒)

    def __init__(self, account: TelegramAccount, instant=False):
        super().__init__(io.BytesIO(), line_buffering=True)
        self.account = account
        self.instant = instant

        self.queue = asyncio.Queue()
        self._consecutive_failures = 0
        self._disabled = False
        self._disabled_time = None
        self.watch = asyncio.create_task(self.watchdog())

    async def watchdog(self):
        while True:
            message = await self.queue.get()
            if self._disabled:
                # 冷却期后自动恢复
                if (
                    self._disabled_time
                    and (asyncio.get_event_loop().time() - self._disabled_time) > self.COOLDOWN_SECONDS
                ):
                    self._disabled = False
                    self._consecutive_failures = 0
                    logger.debug("Telegram 推送冷却期结束, 恢复推送.")
                else:
                    self.queue.task_done()
                    continue
            try:
                result = await asyncio.wait_for(self.send(message), 20)
            except asyncio.TimeoutError:
                self._consecutive_failures += 1
                if self._consecutive_failures >= self.MAX_CONSECUTIVE_FAILURES:
                    self._disabled = True
                    self._disabled_time = asyncio.get_event_loop().time()
                    logger.warning(
                        f"推送消息到 Telegram 连续超时 {self._consecutive_failures} 次, "
                        f"暂停推送 {self.COOLDOWN_SECONDS} 秒. 如认证机器人已失效, "
                        f"请在配置中设置 skip_auth = true."
                    )
                else:
                    logger.warning("推送消息到 Telegram 超时.")
            except Exception as e:
                self._consecutive_failures += 1
                logger.warning("推送消息到 Telegram 失败.")
                show_exception(e)
            else:
                if not result:
                    self._consecutive_failures += 1
                    logger.warning("推送消息到 Telegram 失败.")
                else:
                    self._consecutive_failures = 0
            finally:
                self.queue.task_done()

    async def send(self, message):
        async with ClientsSession([self.account]) as clients:
            async for _, tg in clients:
                if self.instant:
                    return await Link(tg).send_msg(message)
                else:
                    return await Link(tg).send_log(message)
            else:
                return False

    def write(self, message):
        message = Text.from_markup(message).plain
        if message.endswith("\n"):
            message = message[:-1]
        if message:
            self.queue.put_nowait(message)

    async def join(self):
        await self.queue.join()
        self.watch.cancel()
