import asyncio
import importlib
import sys
from enum import Enum, auto
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

        def exception(self, *args, **kwargs):
            return None

        def add(self, *args, **kwargs):
            return 1

        def remove(self, *args, **kwargs):
            return None

    loguru_module.logger = DummyLogger()
    sys.modules["loguru"] = loguru_module

    runinfo_module = types.ModuleType("embykeeper.runinfo")

    class RunStatus(Enum):
        SUCCESS = auto()
        FAIL = auto()
        ERROR = auto()
        IGNORE = auto()
        CANCELLED = auto()

    class RunContext:
        _counter = 0

        def __init__(self, description=None, parent_ids=None):
            type(self)._counter += 1
            self.id = f"ctx-{type(self)._counter}"
            self.description = description
            self.parent_ids = list(parent_ids or [])
            self.status = None
            self.status_info = None

        def bind_logger(self, logger):
            return logger

        def finish(self, status=None, status_info=None):
            self.status = status
            self.status_info = status_info
            return self

        @classmethod
        def prepare(cls, description=None, parent_ids=None):
            return cls(description=description, parent_ids=parent_ids)

        @classmethod
        def get_or_create(cls, run_id=None, description=None, parent_ids=None, status=None):
            ctx = cls.prepare(description=description, parent_ids=parent_ids)
            if run_id:
                ctx.id = run_id
            ctx.status = status
            return ctx

        @classmethod
        def run(cls, func, description=None, parent_ids=None):
            async def runner():
                ctx = cls.prepare(description=description, parent_ids=parent_ids)
                return await func(ctx)

            return runner()

    runinfo_module.RunStatus = RunStatus
    runinfo_module.RunContext = RunContext
    sys.modules["embykeeper.runinfo"] = runinfo_module

    schema_module = types.ModuleType("embykeeper.schema")

    class TelegramAccount:
        @staticmethod
        def get_phone_masked(phone):
            phone = str(phone)
            if len(phone) <= 2:
                return phone
            return phone[:1] + "*" * max(0, len(phone) - 2) + phone[-1:]

    class ProxyConfig:
        pass

    schema_module.TelegramAccount = TelegramAccount
    schema_module.ProxyConfig = ProxyConfig
    sys.modules["embykeeper.schema"] = schema_module

    config_module = types.ModuleType("embykeeper.config")

    class BootstrapConfig:
        def __init__(self):
            self.debug_cron = False
            self.nofail = True
            self.telegram = SimpleNamespace(account=[])
            self.registrar = SimpleNamespace()
            self.site = None

        def on_change(self, key, callback):
            return SimpleNamespace()

        def on_list_change(self, key, callback):
            return SimpleNamespace()

    config_module.config = BootstrapConfig()
    sys.modules["embykeeper.config"] = config_module

    pyrogram_module = types.ModuleType("embykeeper.telegram.pyrogram")

    class Client:
        pass

    pyrogram_module.Client = Client
    sys.modules["embykeeper.telegram.pyrogram"] = pyrogram_module

    embyboss_module = types.ModuleType("embykeeper.telegram.embyboss")

    class EmbybossRegister:
        def __init__(self, *args, **kwargs):
            pass

        async def run(self, *args, **kwargs):
            return True

        async def run_continuous(self, *args, **kwargs):
            return True

    embyboss_module.EmbybossRegister = EmbybossRegister
    sys.modules["embykeeper.telegram.embyboss"] = embyboss_module

    link_module = types.ModuleType("embykeeper.telegram.link")

    class Link:
        def __init__(self, client):
            self.client = client

        async def auth(self, *args, **kwargs):
            return True

    link_module.Link = Link
    sys.modules["embykeeper.telegram.link"] = link_module

    session_module = types.ModuleType("embykeeper.telegram.session")

    class ClientsSession:
        def __init__(self, accounts):
            self.accounts = accounts

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def __aiter__(self):
            async def iterator():
                if False:
                    yield None

            return iterator()

    session_module.ClientsSession = ClientsSession
    sys.modules["embykeeper.telegram.session"] = session_module


_install_test_stubs()

from embykeeper.runinfo import RunStatus

registrar_main_module = importlib.import_module("embykeeper.telegram.registrar_main")
base_module = importlib.import_module("embykeeper.telegram.registrar._base")

RegisterManager = registrar_main_module.RegisterManager
BaseBotRegister = base_module.BaseBotRegister


class FakeRegistrarConfig:
    def __init__(self, site_configs=None, retries=None, timeout=None, concurrency=1):
        self._site_configs = site_configs or {}
        self.retries = retries
        self.timeout = timeout
        self.concurrency = concurrency

    def get_site_config(self, site_name):
        return self._site_configs.get(site_name, {})


class FakeConfig:
    def __init__(self, accounts=None, registrar=None, site=None, nofail=True):
        self.telegram = SimpleNamespace(account=list(accounts or []))
        self.registrar = registrar or FakeRegistrarConfig()
        self.site = site
        self.nofail = nofail
        self._change_callbacks = []
        self._list_change_callbacks = []

    def on_change(self, key, callback):
        self._change_callbacks.append((key, callback))
        return SimpleNamespace()

    def on_list_change(self, key, callback):
        self._list_change_callbacks.append((key, callback))
        return SimpleNamespace()


class RecordingPool:
    def __init__(self):
        self.added = []

    def add(self, awaitable, name=None):
        self.added.append((awaitable, name))
        return awaitable

    def close(self):
        for awaitable, _ in self.added:
            if asyncio.iscoroutine(awaitable):
                awaitable.close()


class FakeTask:
    def __init__(self, name="task"):
        self.cancel_called = False
        self._name = name

    def cancel(self):
        self.cancel_called = True

    def get_name(self):
        return self._name


class FakeScheduler:
    def __init__(self, result="scheduled", register_key="1000.fake"):
        self.result = result
        self.calls = 0
        self._register_key = register_key

    def schedule(self):
        self.calls += 1

        async def runner():
            return self.result

        return runner()


class PendingScheduler:
    def __init__(self):
        self.cancelled = False
        self._register_key = None

    def schedule(self):
        async def runner():
            try:
                await asyncio.Future()
            except asyncio.CancelledError:
                self.cancelled = True
                raise

        return runner()


class DummyRegister(BaseBotRegister):
    name = "dummy"

    async def start(self):
        return self.ctx.finish(RunStatus.SUCCESS, "ok")


class FailingRegister(BaseBotRegister):
    name = "failing"

    async def start(self):
        raise RuntimeError("boom")


def make_account(phone="1000", site_names=None, registrar=True, enabled=True, registrar_config=None):
    return SimpleNamespace(
        phone=phone,
        enabled=enabled,
        registrar=registrar,
        registrar_config=registrar_config,
        site=SimpleNamespace(registrar=site_names) if site_names is not None else None,
    )


def make_client():
    return SimpleNamespace(me=SimpleNamespace(full_name="Tester"), stop_handlers=[])


def test_handle_config_change_accepts_schedule_account_tuple():
    account = make_account()
    fake_config = FakeConfig(accounts=[account])
    original_config = registrar_main_module.config
    registrar_main_module.config = fake_config
    try:

        async def scenario():
            manager = RegisterManager()
            manager._pool = RecordingPool()
            scheduler = FakeScheduler(register_key="1000.templ_a<Bot>.timed.0")
            task = FakeTask("interval-task")
            manager.schedule_account = lambda _: ([scheduler], [task])

            manager._handle_config_change(None, None)
            await asyncio.sleep(0)

            assert scheduler.calls == 1
            assert len(manager._pool.added) == 2
            assert manager._pool.added[1][1] == "interval-task"
            manager._pool.close()

        asyncio.run(scenario())
    finally:
        registrar_main_module.config = original_config


def test_handle_config_change_stops_accounts_found_in_task_keys():
    fake_config = FakeConfig(accounts=[])
    original_config = registrar_main_module.config
    registrar_main_module.config = fake_config
    try:
        manager = RegisterManager()
        stopped = []
        manager.stop_account = lambda phone: stopped.append(phone)
        manager._tasks = {"1000.templ_a<Bot>": FakeTask()}
        manager._schedulers = {}

        manager._handle_config_change(None, None)

        assert stopped == ["1000"]
    finally:
        registrar_main_module.config = original_config


def test_handle_account_change_accepts_schedule_account_tuple():
    added_account = make_account(phone="1001")
    removed_account = make_account(phone="2002")
    fake_config = FakeConfig(accounts=[])
    original_config = registrar_main_module.config
    registrar_main_module.config = fake_config
    try:

        async def scenario():
            manager = RegisterManager()
            manager._pool = RecordingPool()
            scheduler = FakeScheduler(register_key="1001.templ_a<Bot>.timed.0")
            task = FakeTask("added-task")
            stopped = []
            manager.stop_account = lambda phone: stopped.append(phone)
            manager.schedule_account = lambda _: ([scheduler], [task])

            manager._handle_account_change([added_account], [removed_account])
            await asyncio.sleep(0)

            assert stopped == ["2002"]
            assert scheduler.calls == 1
            assert len(manager._pool.added) == 2
            assert manager._pool.added[1][1] == "added-task"
            manager._pool.close()

        asyncio.run(scenario())
    finally:
        registrar_main_module.config = original_config


def test_schedule_account_clears_existing_site_tasks_before_rescheduling():
    fake_config = FakeConfig(accounts=[], registrar=FakeRegistrarConfig())
    original_config = registrar_main_module.config
    registrar_main_module.config = fake_config
    try:
        manager = RegisterManager()
        stale_task = FakeTask()
        manager._tasks["1000.templ_a<Bot>"] = stale_task
        manager.get_sites_for_account = lambda _: []

        schedulers, tasks = manager.schedule_account(make_account(phone="1000"))

        assert schedulers == []
        assert tasks == []
        assert stale_task.cancel_called is True
        assert manager._tasks == {}
    finally:
        registrar_main_module.config = original_config


def test_schedule_account_uses_account_specific_registrar_config():
    account_registrar_config = FakeRegistrarConfig({"templ_a<Bot>": {"interval_minutes": 5}})
    fake_config = FakeConfig(accounts=[], registrar=FakeRegistrarConfig({}))
    original_config = registrar_main_module.config
    original_extract = registrar_main_module.extract
    original_get_cls = registrar_main_module.get_cls
    registrar_main_module.config = fake_config
    try:
        manager = RegisterManager()
        manager.get_sites_for_account = lambda _: ["templ_a<Bot>"]
        captured_site_configs = []

        class FakeRegistrar:
            templ_name = "templ_a<Bot>"

        registrar_main_module.extract = lambda classes: [FakeRegistrar]
        registrar_main_module.get_cls = lambda *args, **kwargs: [FakeRegistrar]
        manager._schedule_site_interval = (
            lambda account, site_name, site_config: captured_site_configs.append(site_config) or FakeTask()
        )

        _, tasks = manager.schedule_account(
            make_account(phone="1000", registrar_config=account_registrar_config)
        )

        assert len(tasks) == 1
        assert captured_site_configs == [{"interval_minutes": 5}]
    finally:
        registrar_main_module.config = original_config
        registrar_main_module.extract = original_extract
        registrar_main_module.get_cls = original_get_cls


def test_schedule_account_treats_times_as_one_random_daily_window():
    account_registrar_config = FakeRegistrarConfig({"templ_a<Bot>": {"times": ["9:00AM", "9:00PM"]}})
    fake_config = FakeConfig(accounts=[], registrar=FakeRegistrarConfig({}))
    original_config = registrar_main_module.config
    original_extract = registrar_main_module.extract
    original_get_cls = registrar_main_module.get_cls
    registrar_main_module.config = fake_config
    try:
        manager = RegisterManager()
        manager.get_sites_for_account = lambda _: ["templ_a<Bot>"]

        class FakeRegistrar:
            templ_name = "templ_a<Bot>"

        registrar_main_module.extract = lambda classes: [FakeRegistrar]
        registrar_main_module.get_cls = lambda *args, **kwargs: [FakeRegistrar]

        schedulers, tasks = manager.schedule_account(
            make_account(phone="1000", registrar_config=account_registrar_config)
        )

        assert tasks == []
        assert len(schedulers) == 1
        assert schedulers[0].start_time.strftime("%H:%M") == "09:00"
        assert schedulers[0].end_time.strftime("%H:%M") == "21:00"
        assert set(manager._schedulers.keys()) == {"1000.templ_a<Bot>"}
    finally:
        registrar_main_module.config = original_config
        registrar_main_module.extract = original_extract
        registrar_main_module.get_cls = original_get_cls


def test_stop_account_cancels_started_timed_scheduler_tasks():
    account_registrar_config = FakeRegistrarConfig({"templ_a<Bot>": {"times": ["9:00AM", "9:00PM"]}})
    fake_config = FakeConfig(accounts=[], registrar=FakeRegistrarConfig({}))
    original_config = registrar_main_module.config
    original_extract = registrar_main_module.extract
    original_get_cls = registrar_main_module.get_cls
    original_from_str = registrar_main_module.Scheduler.from_str
    registrar_main_module.config = fake_config
    pending_schedulers = []

    def fake_from_str(*args, **kwargs):
        scheduler = PendingScheduler()
        pending_schedulers.append(scheduler)
        return scheduler

    async def scenario():
        manager = RegisterManager()
        manager._pool = RecordingPool()
        manager.get_sites_for_account = lambda _: ["templ_a<Bot>"]

        class FakeRegistrar:
            templ_name = "templ_a<Bot>"

        registrar_main_module.extract = lambda classes: [FakeRegistrar]
        registrar_main_module.get_cls = lambda *args, **kwargs: [FakeRegistrar]
        registrar_main_module.Scheduler.from_str = fake_from_str

        manager._register_account_schedule(
            make_account(phone="1000", registrar_config=account_registrar_config)
        )
        await asyncio.sleep(0)

        assert set(manager._tasks.keys()) == {"1000.templ_a<Bot>"}

        manager.stop_account("1000")
        await asyncio.sleep(0)

        assert manager._tasks == {}
        assert len(pending_schedulers) == 1
        assert pending_schedulers[0].cancelled is True
        manager._pool.close()

    try:
        asyncio.run(scenario())
    finally:
        registrar_main_module.config = original_config
        registrar_main_module.extract = original_extract
        registrar_main_module.get_cls = original_get_cls
        registrar_main_module.Scheduler.from_str = original_from_str


def test_base_register_uses_registrar_fallback_and_respects_explicit_zero():
    original_config = base_module.config
    base_module.config = SimpleNamespace(
        registrar=SimpleNamespace(retries=4, timeout=90),
        nofail=True,
    )
    try:
        register = DummyRegister(make_client())
        zero_override = DummyRegister(make_client(), retries=0, timeout=0)

        assert register.retries == 4
        assert register.timeout == 90
        assert zero_override.retries == 0
        assert zero_override.timeout == 0
    finally:
        base_module.config = original_config


def test_base_register_default_config_is_not_shared_between_instances():
    original_config = base_module.config
    base_module.config = SimpleNamespace(registrar=None, nofail=True)
    try:
        left = DummyRegister(make_client())
        right = DummyRegister(make_client())

        left.config["left_only"] = True

        assert right.config == {}
    finally:
        base_module.config = original_config


def test_base_register_start_wraps_errors_when_nofail_enabled():
    original_config = base_module.config
    original_show_exception = base_module.show_exception
    base_module.config = SimpleNamespace(registrar=None, nofail=True)
    base_module.show_exception = lambda *args, **kwargs: None
    try:
        client = make_client()
        result = asyncio.run(FailingRegister(client)._start())

        assert result.status == RunStatus.ERROR
        assert client.stop_handlers == []
    finally:
        base_module.config = original_config
        base_module.show_exception = original_show_exception
