import asyncio
import importlib
import sys
from types import SimpleNamespace
import types


def _install_test_stubs():
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

    curl_cffi_module = types.ModuleType("curl_cffi")
    curl_cffi_requests_module = types.ModuleType("curl_cffi.requests")

    class AsyncSession:
        pass

    curl_cffi_requests_module.AsyncSession = AsyncSession
    sys.modules["curl_cffi"] = curl_cffi_module
    sys.modules["curl_cffi.requests"] = curl_cffi_requests_module

    llm_module = types.ModuleType("embykeeper.llm")

    async def _noop(*args, **kwargs):
        return None

    llm_module.gpt = _noop
    llm_module.visual = _noop
    llm_module.ocr = _noop
    sys.modules["embykeeper.llm"] = llm_module

    config_module = types.ModuleType("embykeeper.config")
    config_module.config = SimpleNamespace(llm=None, proxy=None)
    sys.modules["embykeeper.config"] = config_module

    ocr_module = types.ModuleType("embykeeper.ocr")

    class OCRService:
        @staticmethod
        def get():
            raise RuntimeError("unused in this test")

    ocr_module.OCRService = OCRService
    sys.modules["embykeeper.ocr"] = ocr_module

    utils_module = types.ModuleType("embykeeper.utils")
    utils_module.get_proxy_str = lambda proxy: None
    sys.modules["embykeeper.utils"] = utils_module


_STUB_MODULES = [
    "loguru",
    "curl_cffi",
    "curl_cffi.requests",
    "embykeeper.llm",
    "embykeeper.config",
    "embykeeper.ocr",
    "embykeeper.utils",
]
_original_modules = {name: sys.modules.get(name) for name in _STUB_MODULES}

_install_test_stubs()
sys.modules.pop("embykeeper.telegram.link_local", None)

link_local_module = importlib.import_module("embykeeper.telegram.link_local")
config_module = importlib.import_module("embykeeper.config")

# 恢复被替换的模块并移除测试用模块, 避免污染后续测试模块的收集
for _name in _STUB_MODULES:
    _original = _original_modules.get(_name)
    if _original is None:
        sys.modules.pop(_name, None)
    else:
        sys.modules[_name] = _original
sys.modules.pop("embykeeper.telegram.link_local", None)

LocalLink = link_local_module.LocalLink


def make_client():
    return SimpleNamespace(me=SimpleNamespace(id=1, full_name="tester"))


def test_local_link_allows_component_entry_services_without_llm_config():
    config_module.config.llm = None
    local = LocalLink(make_client())

    assert local.supports_service("checkiner") is True
    assert local.supports_service("monitor") is True
    assert local.supports_service("messager") is True
    assert local.supports_service("registrar") is True
    assert asyncio.run(local.auth("checkiner")) is True


def test_local_link_still_rejects_capability_services_without_backend():
    config_module.config.llm = None
    local = LocalLink(make_client())

    assert local.supports_service("captcha") is False
    assert asyncio.run(local.auth("captcha")) is False


def _make_ocr_service(result):
    class FakeOCR:
        async def run(self, photo_bytes):
            if isinstance(result, Exception):
                raise result
            return result

    class FakeOCRService:
        @classmethod
        def get(cls):
            return FakeOCR()

    return FakeOCRService


def test_local_link_ocr_uses_llm_result():
    config_module.config.llm = SimpleNamespace(api_key="test")
    local = LocalLink(make_client())
    original = link_local_module.OCRService
    link_local_module.OCRService = _make_ocr_service("AB12")
    try:
        assert asyncio.run(local.ocr(b"img")) == "AB12"
    finally:
        link_local_module.OCRService = original


def test_local_link_ocr_falls_back_to_helper_when_llm_returns_empty():
    config_module.config.llm = SimpleNamespace(api_key="test")
    local = LocalLink(make_client())
    original = link_local_module.OCRService
    link_local_module.OCRService = _make_ocr_service("")

    async def fake_helper(method, payload):
        return {"answer": "HELP"}

    local._run_helper = fake_helper
    try:
        assert asyncio.run(local.ocr(b"img")) == "HELP"
    finally:
        link_local_module.OCRService = original


def test_local_link_ocr_falls_back_to_helper_when_llm_raises():
    config_module.config.llm = SimpleNamespace(api_key="test")
    local = LocalLink(make_client())
    original = link_local_module.OCRService
    link_local_module.OCRService = _make_ocr_service(RuntimeError("boom"))

    async def fake_helper(method, payload):
        return "HELP"

    local._run_helper = fake_helper
    try:
        assert asyncio.run(local.ocr(b"img")) == "HELP"
    finally:
        link_local_module.OCRService = original
