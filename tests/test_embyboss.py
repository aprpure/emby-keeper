import asyncio
from contextlib import asynccontextmanager
import sys
from types import SimpleNamespace
import types
from typing import Any, cast

try:
    from embykeeper.telegram.embyboss import EmbybossRegister
except ModuleNotFoundError as exc:
    if exc.name != "pyrogram":
        raise

    pyrogram_module = types.ModuleType("pyrogram")
    pyrogram_errors_module = types.ModuleType("pyrogram.errors")
    pyrogram_types_module = types.ModuleType("pyrogram.types")
    pyrogram_raw_module = types.ModuleType("pyrogram.raw")
    pyrogram_raw_types_module = types.ModuleType("pyrogram.raw.types")
    pyrogram_raw_messages_module = types.ModuleType("pyrogram.raw.types.messages")
    telegram_pyrogram_module = types.ModuleType("embykeeper.telegram.pyrogram")

    class MessageIdInvalid(Exception):
        pass

    class Message:
        pass

    class BotCallbackAnswer:
        pass

    class Client:
        pass

    setattr(pyrogram_errors_module, "MessageIdInvalid", MessageIdInvalid)
    setattr(pyrogram_types_module, "Message", Message)
    setattr(pyrogram_raw_messages_module, "BotCallbackAnswer", BotCallbackAnswer)
    setattr(telegram_pyrogram_module, "Client", Client)

    sys.modules.setdefault("pyrogram", pyrogram_module)
    sys.modules["pyrogram.errors"] = pyrogram_errors_module
    sys.modules["pyrogram.types"] = pyrogram_types_module
    sys.modules["pyrogram.raw"] = pyrogram_raw_module
    sys.modules["pyrogram.raw.types"] = pyrogram_raw_types_module
    sys.modules["pyrogram.raw.types.messages"] = pyrogram_raw_messages_module
    sys.modules["embykeeper.telegram.pyrogram"] = telegram_pyrogram_module

    from embykeeper.telegram.embyboss import EmbybossRegister


def make_message(text: str, chat_id: int = 1000):
    return SimpleNamespace(text=text, caption=None, chat=SimpleNamespace(id=chat_id))


REGISTRATION_PROMPT = (
    "🤖注意：您已进入注册状态:\n\n"
    "• 请在2min内输入 [用户名][空格][安全码]\n"
    "• 举个例子🌰：苏苏 1234\n\n"
    "• 用户名中不限制中/英文/emoji，🚫特殊字符\n"
    "• 安全码为敏感操作时附加验证，请填入最熟悉的数字4~6位；退出请点 /cancel"
)


class FakeLogger:
    def __init__(self):
        self.records = []

    def debug(self, message):
        self.records.append(("debug", message))

    def warning(self, message):
        self.records.append(("warning", message))

    def info(self, message):
        self.records.append(("info", message))


class FakeClient:
    def __init__(self, reply_message=None, wait_reply_result=None, wait_edit_result=None, catch_reply_results=None):
        self.reply_message = reply_message
        self.wait_reply_result = wait_reply_result
        self.wait_edit_result = wait_edit_result
        self.wait_reply_calls = []
        self.wait_edit_calls = []
        self.send_message_calls = []
        self.send_message_times = []
        self.catch_reply_results = list(catch_reply_results or [])

    @asynccontextmanager
    async def catch_reply(self, chat_id):
        future = asyncio.Future()
        if self.catch_reply_results:
            result = self.catch_reply_results.pop(0)
            if isinstance(result, DelayedReply):
                result.schedule(future)
            elif result is not None:
                future.set_result(result)
        elif self.reply_message is not None:
            future.set_result(self.reply_message)
        yield future

    async def send_message(self, chat_id, text):
        self.send_message_times.append(asyncio.get_running_loop().time())
        self.send_message_calls.append((chat_id, text))

    async def wait_reply(self, chat_id, send, timeout=10):
        self.wait_reply_calls.append((chat_id, send, timeout))
        if isinstance(self.wait_reply_result, Exception):
            raise self.wait_reply_result
        return self.wait_reply_result

    async def wait_edit(self, message, timeout=10):
        self.wait_edit_calls.append((message, timeout))
        if isinstance(self.wait_edit_result, list):
            result = self.wait_edit_result.pop(0)
        else:
            result = self.wait_edit_result

        if isinstance(result, Exception):
            raise result
        return result


class FakePanel:
    def __init__(self, answer, chat_id: int = 1000):
        self.chat = SimpleNamespace(id=chat_id)
        self.reply_markup = SimpleNamespace(
            inline_keyboard=[[SimpleNamespace(text="👑 创建账户")]],
        )
        self.answer = answer
        self.click_calls = []

    async def click(self, button_text):
        self.click_calls.append(button_text)
        return self.answer


class DelayedReply:
    def __init__(self, delay: float, message):
        self.delay = delay
        self.message = message

    def schedule(self, future):
        loop = asyncio.get_running_loop()

        def resolve():
            if not future.done():
                future.set_result(self.message)

        loop.call_later(self.delay, resolve)


def make_waiting_message(chat_id: int = 1000):
    return make_message(
        "🆗 会话结束，收到设置\n\n用户名：**purejam**  安全码：**1234** \n\n__正在加入注册队列__......",
        chat_id=chat_id,
    )


def configure_fast_credential_retries(register):
    register.credential_reply_timeout = 0.02
    register.credential_burst_reply_timeout = 0.005
    register.credential_resend_delay = 0


def test_attempt_accepts_registration_alert_with_followup_message():
    client = FakeClient(
        catch_reply_results=[
            make_message(REGISTRATION_PROMPT),
            make_message("🆗 已进入处理\n\n用户名：**purejam**  安全码：**1234** \n\n__正在为您初始化账户，更新用户策略__......"),
        ],
        wait_edit_result=make_message("创建用户成功"),
    )
    register = EmbybossRegister(cast(Any, client), FakeLogger(), "purejam", "1234", click_delay=(0, 0))
    panel = FakePanel(SimpleNamespace(message="您已进入注册状态", alert=True))

    result = asyncio.run(register._attempt_with_panel(panel))

    assert result is True
    assert client.send_message_calls == [(1000, "purejam 1234")] * 3


def test_attempt_accepts_open_alert_with_followup_message():
    client = FakeClient(
        catch_reply_results=[
            make_message(REGISTRATION_PROMPT),
            make_message("🆗 已进入处理\n\n用户名：**purejam**  安全码：**1234** \n\n__正在为您初始化账户，更新用户策略__......"),
        ],
        wait_edit_result=make_message("创建用户成功"),
    )
    register = EmbybossRegister(cast(Any, client), FakeLogger(), "purejam", "1234", click_delay=(0, 0))
    panel = FakePanel(SimpleNamespace(message="🪙 开放注册中，免除资质核验。", alert=True))

    result = asyncio.run(register._attempt_with_panel(panel))

    assert result is True
    assert client.send_message_calls == [(1000, "purejam 1234")] * 3


def test_attempt_accepts_verified_alert_with_followup_message():
    client = FakeClient(
        catch_reply_results=[
            make_message(REGISTRATION_PROMPT),
            make_message("🆗 已进入处理\n\n用户名：**purejam**  安全码：**1234** \n\n__正在为您初始化账户，更新用户策略__......"),
        ],
        wait_edit_result=make_message("创建用户成功"),
    )
    register = EmbybossRegister(cast(Any, client), FakeLogger(), "purejam", "1234", click_delay=(0, 0))
    panel = FakePanel(SimpleNamespace(message="🪙 资质核验成功，请稍后。", alert=True))

    result = asyncio.run(register._attempt_with_panel(panel))

    assert result is True
    assert client.send_message_calls == [(1000, "purejam 1234")] * 3


def test_attempt_stops_when_callback_explicitly_says_closed():
    client = FakeClient()
    register = EmbybossRegister(cast(Any, client), FakeLogger(), "purejam", "1234", click_delay=(0, 0))
    panel = FakePanel(SimpleNamespace(message="🤖 自助注册已关闭，等待开启或使用注册码注册。", alert=True))

    result = asyncio.run(register._attempt_with_panel(panel))

    assert result is False
    assert client.wait_reply_calls == []


def test_attempt_stops_when_reply_message_explicitly_says_closed():
    client = FakeClient(catch_reply_results=[make_message("🤖 自助注册已关闭，等待开启或使用注册码注册。")])
    register = EmbybossRegister(cast(Any, client), FakeLogger(), "purejam", "1234", click_delay=(0, 0))
    panel = FakePanel(SimpleNamespace(message="", alert=False))

    result = asyncio.run(register._attempt_with_panel(panel))

    assert result is False
    assert client.wait_reply_calls == []


def test_attempt_waits_for_queue_edits_until_success():
    client = FakeClient(
        catch_reply_results=[make_message(REGISTRATION_PROMPT), make_waiting_message()],
        wait_edit_result=[
            make_message(
                "🆗 会话结束，收到设置\n\n用户名：**purejam**  安全码：**1234** \n\n"
                "__已进入注册队列，当前排队序号：2__\n请耐心等待，创建完成后我会在这里直接通知你。"
            ),
            make_message("🆗 已进入处理\n\n用户名：**purejam**  安全码：**1234** \n\n__正在为您初始化账户，更新用户策略__......"),
            make_message("**▎创建用户成功🎉**\n\n· 用户名称 | `purejam`"),
        ],
    )
    register = EmbybossRegister(cast(Any, client), FakeLogger(), "purejam", "1234", click_delay=(0, 0))
    panel = FakePanel(SimpleNamespace(message="🪙 开放注册中，免除资质核验。", alert=True))

    result = asyncio.run(register._attempt_with_panel(panel))

    assert result is True
    assert len(client.wait_edit_calls) == 3
    assert client.send_message_calls == [(1000, "purejam 1234")] * 3


def test_attempt_stops_when_queue_edit_reports_failure():
    client = FakeClient(
        catch_reply_results=[make_message(REGISTRATION_PROMPT), make_waiting_message()],
        wait_edit_result=make_message(
            "**- ❎ 已有此账户名，请重新输入注册\n- ❎ 或检查有无特殊字符\n- ❎ 或emby服务器连接不通，会话已结束！**"
        ),
    )
    register = EmbybossRegister(cast(Any, client), FakeLogger(), "purejam", "1234", click_delay=(0, 0))
    panel = FakePanel(SimpleNamespace(message="🪙 资质核验成功，请稍后。", alert=True))

    result = asyncio.run(register._attempt_with_panel(panel))

    assert result is False


def test_attempt_resends_credential_bursts_until_queue_message_arrives():
    client = FakeClient(
        catch_reply_results=[make_message(REGISTRATION_PROMPT), None, make_waiting_message()],
        wait_edit_result=make_message("创建用户成功"),
    )
    register = EmbybossRegister(cast(Any, client), FakeLogger(), "purejam", "1234", click_delay=(0, 0))
    configure_fast_credential_retries(register)
    panel = FakePanel(SimpleNamespace(message="🪙 开放注册中，免除资质核验。", alert=True))

    result = asyncio.run(register._attempt_with_panel(panel))

    assert result is True
    assert client.send_message_calls == [(1000, "purejam 1234")] * 6


def test_attempt_resends_credentials_on_three_second_round_cadence():
    client = FakeClient(
        catch_reply_results=[
            make_message(REGISTRATION_PROMPT),
            DelayedReply(0.08, make_message("still waiting for the real registration status")),
            make_waiting_message(),
        ],
        wait_edit_result=make_message("创建用户成功"),
    )
    register = EmbybossRegister(cast(Any, client), FakeLogger(), "purejam", "1234", click_delay=(0, 0))
    register.credential_reply_timeout = 1
    register.credential_burst_reply_timeout = 0.2
    register.credential_resend_delay = 0.15
    panel = FakePanel(SimpleNamespace(message="🪙 开放注册中，免除资质核验。", alert=True))

    result = asyncio.run(register._attempt_with_panel(panel))

    assert result is True
    assert client.send_message_calls == [(1000, "purejam 1234")] * 6
    round_gap = client.send_message_times[3] - client.send_message_times[0]
    assert 0.12 <= round_gap < 0.2


def test_attempt_uses_callback_prompt_when_no_followup_message():
    import embykeeper.telegram.embyboss as embyboss_module

    original_wait_for = embyboss_module.asyncio.wait_for
    call_count = 0

    async def first_timeout_then_continue(awaitable, timeout):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise asyncio.TimeoutError
        return await original_wait_for(awaitable, timeout)

    embyboss_module.asyncio.wait_for = first_timeout_then_continue
    try:
        client = FakeClient(
            catch_reply_results=[None, make_message("🆗 已进入处理\n\n用户名：**purejam**  安全码：**1234** \n\n__正在为您初始化账户，更新用户策略__......")],
            wait_edit_result=make_message("创建用户成功"),
        )
        register = EmbybossRegister(cast(Any, client), FakeLogger(), "purejam", "1234", click_delay=(0, 0))
        panel = FakePanel(SimpleNamespace(message="您已进入注册状态", alert=True), chat_id=2468)

        result = asyncio.run(register._attempt_with_panel(panel))

        assert result is True
        assert client.send_message_calls == [(2468, "purejam 1234")] * 3
    finally:
        embyboss_module.asyncio.wait_for = original_wait_for
