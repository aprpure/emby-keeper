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
        async def get():
            raise RuntimeError("unused in this test")

    ocr_module.OCRService = OCRService
    sys.modules["embykeeper.ocr"] = ocr_module

    utils_module = types.ModuleType("embykeeper.utils")
    utils_module.get_proxy_str = lambda proxy: None
    sys.modules["embykeeper.utils"] = utils_module


_install_test_stubs()

link_local_module = importlib.import_module("embykeeper.telegram.link_local")
config_module = importlib.import_module("embykeeper.config")

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
