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
    def __init__(self, reply_message=None, wait_reply_result=None, wait_edit_result=None):
        self.reply_message = reply_message
        self.wait_reply_result = wait_reply_result
        self.wait_edit_result = wait_edit_result
        self.wait_reply_calls = []
        self.wait_edit_calls = []

    @asynccontextmanager
    async def catch_reply(self, chat_id):
        future = asyncio.Future()
        if self.reply_message is not None:
            future.set_result(self.reply_message)
        yield future

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


def test_attempt_accepts_registration_alert_with_followup_message():
    prompt = "🤖注意：您已进入注册状态:\n\n• 请在2min内输入 [用户名][空格][安全码]"
    client = FakeClient(
        reply_message=make_message(prompt),
        wait_reply_result=make_message("🆗 已进入处理\n\n用户名：**purejam**  安全码：**1234** \n\n__正在为您初始化账户，更新用户策略__......"),
        wait_edit_result=make_message("创建用户成功"),
    )
    register = EmbybossRegister(cast(Any, client), FakeLogger(), "purejam", "1234", click_delay=(0, 0))
    panel = FakePanel(SimpleNamespace(message="您已进入注册状态", alert=True))

    result = asyncio.run(register._attempt_with_panel(panel))

    assert result is True
    assert client.wait_reply_calls == [(1000, "purejam 1234", 30)]


def test_attempt_accepts_open_alert_with_followup_message():
    prompt = "🤖注意：您已进入注册状态:\n\n• 请在2min内输入 [用户名][空格][安全码]"
    client = FakeClient(
        reply_message=make_message(prompt),
        wait_reply_result=make_message("🆗 已进入处理\n\n用户名：**purejam**  安全码：**1234** \n\n__正在为您初始化账户，更新用户策略__......"),
        wait_edit_result=make_message("创建用户成功"),
    )
    register = EmbybossRegister(cast(Any, client), FakeLogger(), "purejam", "1234", click_delay=(0, 0))
    panel = FakePanel(SimpleNamespace(message="🪙 开放注册中，免除资质核验。", alert=True))

    result = asyncio.run(register._attempt_with_panel(panel))

    assert result is True
    assert client.wait_reply_calls == [(1000, "purejam 1234", 30)]


def test_attempt_accepts_verified_alert_with_followup_message():
    prompt = "🤖注意：您已进入注册状态:\n\n• 请在2min内输入 [用户名][空格][安全码]"
    client = FakeClient(
        reply_message=make_message(prompt),
        wait_reply_result=make_message("🆗 已进入处理\n\n用户名：**purejam**  安全码：**1234** \n\n__正在为您初始化账户，更新用户策略__......"),
        wait_edit_result=make_message("创建用户成功"),
    )
    register = EmbybossRegister(cast(Any, client), FakeLogger(), "purejam", "1234", click_delay=(0, 0))
    panel = FakePanel(SimpleNamespace(message="🪙 资质核验成功，请稍后。", alert=True))

    result = asyncio.run(register._attempt_with_panel(panel))

    assert result is True
    assert client.wait_reply_calls == [(1000, "purejam 1234", 30)]


def test_attempt_stops_when_callback_explicitly_says_closed():
    client = FakeClient()
    register = EmbybossRegister(cast(Any, client), FakeLogger(), "purejam", "1234", click_delay=(0, 0))
    panel = FakePanel(SimpleNamespace(message="🤖 自助注册已关闭，等待开启或使用注册码注册。", alert=True))

    result = asyncio.run(register._attempt_with_panel(panel))

    assert result is False
    assert client.wait_reply_calls == []


def test_attempt_stops_when_reply_message_explicitly_says_closed():
    client = FakeClient(reply_message=make_message("🤖 自助注册已关闭，等待开启或使用注册码注册。"))
    register = EmbybossRegister(cast(Any, client), FakeLogger(), "purejam", "1234", click_delay=(0, 0))
    panel = FakePanel(SimpleNamespace(message="", alert=False))

    result = asyncio.run(register._attempt_with_panel(panel))

    assert result is False
    assert client.wait_reply_calls == []


def test_attempt_waits_for_queue_edits_until_success():
    prompt = "🤖注意：您已进入注册状态:\n\n• 请在2min内输入 [用户名][空格][安全码]"
    client = FakeClient(
        reply_message=make_message(prompt),
        wait_reply_result=make_message(
            "🆗 会话结束，收到设置\n\n用户名：**purejam**  安全码：**1234** \n\n__正在加入注册队列__......"
        ),
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


def test_attempt_stops_when_queue_edit_reports_failure():
    prompt = "🤖注意：您已进入注册状态:\n\n• 请在2min内输入 [用户名][空格][安全码]"
    client = FakeClient(
        reply_message=make_message(prompt),
        wait_reply_result=make_message(
            "🆗 会话结束，收到设置\n\n用户名：**purejam**  安全码：**1234** \n\n__正在加入注册队列__......"
        ),
        wait_edit_result=make_message(
            "**- ❎ 已有此账户名，请重新输入注册\n- ❎ 或检查有无特殊字符\n- ❎ 或emby服务器连接不通，会话已结束！**"
        ),
    )
    register = EmbybossRegister(cast(Any, client), FakeLogger(), "purejam", "1234", click_delay=(0, 0))
    panel = FakePanel(SimpleNamespace(message="🪙 资质核验成功，请稍后。", alert=True))

    result = asyncio.run(register._attempt_with_panel(panel))

    assert result is False


def test_attempt_uses_callback_prompt_when_no_followup_message():
    import embykeeper.telegram.embyboss as embyboss_module

    original_wait_for = embyboss_module.asyncio.wait_for

    async def immediate_timeout(awaitable, timeout):
        raise asyncio.TimeoutError

    embyboss_module.asyncio.wait_for = immediate_timeout
    try:
        client = FakeClient(
            wait_reply_result=make_message("🆗 已进入处理\n\n用户名：**purejam**  安全码：**1234** \n\n__正在为您初始化账户，更新用户策略__......"),
            wait_edit_result=make_message("创建用户成功"),
        )
        register = EmbybossRegister(cast(Any, client), FakeLogger(), "purejam", "1234", click_delay=(0, 0))
        panel = FakePanel(SimpleNamespace(message="您已进入注册状态", alert=True), chat_id=2468)

        result = asyncio.run(register._attempt_with_panel(panel))

        assert result is True
        assert client.wait_reply_calls == [(2468, "purejam 1234", 30)]
    finally:
        embyboss_module.asyncio.wait_for = original_wait_for
