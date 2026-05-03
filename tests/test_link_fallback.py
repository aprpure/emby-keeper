import asyncio
import importlib
import sys
from types import SimpleNamespace
import types


def _install_test_stubs():
    tomli_module = types.ModuleType("tomli")
    tomli_module.loads = lambda text: {}
    sys.modules["tomli"] = tomli_module

    loguru_module = types.ModuleType("loguru")

    class DummyLogger:
        def bind(self, **kwargs):
            return self

        def info(self, *args, **kwargs):
            return None

        def warning(self, *args, **kwargs):
            return None

        def debug(self, *args, **kwargs):
            return None

        def error(self, *args, **kwargs):
            return None

    loguru_module.logger = DummyLogger()
    sys.modules["loguru"] = loguru_module

    pyrogram_module = types.ModuleType("pyrogram")

    class DummyFilter:
        def __and__(self, other):
            return self

    pyrogram_module.filters = SimpleNamespace(text=DummyFilter(), bot=DummyFilter(), user=lambda _: DummyFilter())
    sys.modules["pyrogram"] = pyrogram_module

    handlers_module = types.ModuleType("pyrogram.handlers")

    class MessageHandler:
        def __init__(self, *args, **kwargs):
            pass

    handlers_module.MessageHandler = MessageHandler
    sys.modules["pyrogram.handlers"] = handlers_module

    enums_module = types.ModuleType("pyrogram.enums")
    enums_module.ParseMode = SimpleNamespace(DISABLED="disabled")
    sys.modules["pyrogram.enums"] = enums_module

    types_module = types.ModuleType("pyrogram.types")

    class Message:
        pass

    types_module.Message = Message
    sys.modules["pyrogram.types"] = types_module

    errors_module = types.ModuleType("pyrogram.errors")

    class FloodWait(Exception):
        pass

    errors_module.FloodWait = FloodWait
    sys.modules["pyrogram.errors"] = errors_module

    bad_request_module = types.ModuleType("pyrogram.errors.exceptions.bad_request_400")

    class YouBlockedUser(Exception):
        pass

    bad_request_module.YouBlockedUser = YouBlockedUser
    sys.modules["pyrogram.errors.exceptions.bad_request_400"] = bad_request_module

    utils_module = types.ModuleType("embykeeper.utils")

    def async_partial(func, *args, **kwargs):
        async def wrapped(*call_args, **call_kwargs):
            return await func(*args, *call_args, **kwargs, **call_kwargs)

        return wrapped

    utils_module.async_partial = async_partial
    utils_module.truncate_str = lambda text, length: text[:length]
    sys.modules["embykeeper.utils"] = utils_module

    lock_module = types.ModuleType("embykeeper.telegram.lock")
    lock_module.super_ad_shown = {}
    lock_module.authed_services = {}
    lock_module.super_ad_shown_lock = asyncio.Lock()
    lock_module.authed_services_lock = asyncio.Lock()
    sys.modules["embykeeper.telegram.lock"] = lock_module

    link_local_module = types.ModuleType("embykeeper.telegram.link_local")

    class LocalLink:
        allow_remote_fallback_value = True
        wssocks_result = (None, None)
        captcha_wssocks_result = (None, None)
        visual_result = (None, None)
        ocr_result = None

        def __init__(self, client):
            self.client = client

        @property
        def allow_remote_fallback(self):
            return type(self).allow_remote_fallback_value

        async def auth(self, service, log_func=None):
            return True

        async def wssocks(self):
            return type(self).wssocks_result

        async def captcha_wssocks(self, token, url, user_agent=None):
            return type(self).captcha_wssocks_result

        async def visual(self, photo_bytes, options, question=None):
            return type(self).visual_result

        async def ocr(self, photo_bytes):
            return type(self).ocr_result

    link_local_module.LocalLink = LocalLink
    sys.modules["embykeeper.telegram.link_local"] = link_local_module

    telegram_pyrogram_module = types.ModuleType("embykeeper.telegram.pyrogram")

    class Client:
        pass

    telegram_pyrogram_module.Client = Client
    sys.modules["embykeeper.telegram.pyrogram"] = telegram_pyrogram_module


_install_test_stubs()

link_module = importlib.import_module("embykeeper.telegram.link")

Link = link_module.Link
LocalLink = importlib.import_module("embykeeper.telegram.link_local").LocalLink


def make_client(skip_auth=True):
    return SimpleNamespace(me=SimpleNamespace(id=1, full_name="tester"), _skip_auth=skip_auth, stop_handlers=[])


def test_wssocks_falls_back_to_remote_when_local_backend_returns_no_token():
    LocalLink.allow_remote_fallback_value = True
    LocalLink.wssocks_result = (None, None)
    link = Link(make_client())
    calls = []

    async def fake_post(cmd, timeout=0, name=None):
        calls.append((cmd, timeout, name))
        return {"url": "ws://remote", "token": "remote-token"}

    link.post = fake_post

    assert asyncio.run(link.wssocks()) == ("ws://remote", "remote-token")
    assert len(calls) == 1


def test_captcha_wssocks_falls_back_to_remote_when_local_backend_returns_no_clearance():
    LocalLink.allow_remote_fallback_value = True
    LocalLink.captcha_wssocks_result = (None, None)
    link = Link(make_client())
    calls = []

    async def fake_post(cmd, timeout=0, name=None):
        calls.append((cmd, timeout, name))
        return {"cf_clearance": "cf-token", "useragent": "ua"}

    link.post = fake_post

    assert asyncio.run(link.captcha_wssocks("connector", "https://example.com")) == ("cf-token", "ua")
    assert len(calls) == 1


def test_wssocks_does_not_fall_back_when_local_backend_succeeds():
    LocalLink.allow_remote_fallback_value = True
    LocalLink.wssocks_result = ("ws://local", "local-token")
    link = Link(make_client())

    async def fake_post(cmd, timeout=0, name=None):
        raise AssertionError("remote fallback should not be called")

    link.post = fake_post

    assert asyncio.run(link.wssocks()) == ("ws://local", "local-token")


def test_download_photo_supports_in_memory_result_for_file_id_inputs():
    client = make_client()

    async def fake_download_media(photo, in_memory=False):
        assert photo == "file-id"
        assert in_memory is True
        return SimpleNamespace(getvalue=lambda: b"image-bytes")

    client.download_media = fake_download_media
    link = Link(client)

    assert asyncio.run(link._download_photo("file-id")) == b"image-bytes"


def test_visual_falls_back_to_remote_when_local_backend_returns_no_answer():
    LocalLink.allow_remote_fallback_value = True
    LocalLink.visual_result = (None, None)
    client = make_client()

    async def fake_download_media(photo, in_memory=False):
        assert photo == "file-id"
        return SimpleNamespace(getvalue=lambda: b"image-bytes")

    client.download_media = fake_download_media
    link = Link(client)
    calls = []

    async def fake_post(cmd, photo=None, timeout=0, name=None):
        calls.append((cmd, photo, timeout, name))
        return {"answer": "美女", "by": "remote"}

    link.post = fake_post

    assert asyncio.run(link.visual("file-id", ["内衣", "美女"])) == ("美女", "remote")
    assert len(calls) == 1


def test_ocr_falls_back_to_remote_when_local_backend_returns_no_answer():
    LocalLink.allow_remote_fallback_value = True
    LocalLink.ocr_result = None
    client = make_client()

    async def fake_download_media(photo, in_memory=False):
        assert photo == "file-id"
        return SimpleNamespace(getvalue=lambda: b"image-bytes")

    client.download_media = fake_download_media
    link = Link(client)
    calls = []

    async def fake_post(cmd, photo=None, timeout=0, name=None):
        calls.append((cmd, photo, timeout, name))
        return {"answer": "1234"}

    link.post = fake_post

    assert asyncio.run(link.ocr("file-id")) == "1234"
    assert len(calls) == 1
