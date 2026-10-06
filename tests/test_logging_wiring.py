"""Tests for the logging-system SDK integration."""

from __future__ import annotations

import builtins
import logging

import pytest

from app import logging_setup as logging_pkg
from app.config import settings as settings_pkg
from app.logging_setup import client as get_log_client
from app.logging_setup import correlation_id, setup_logging, shutdown_logging

log_id_var = logging_pkg.log_id_var


@pytest.fixture(autouse=True)
def disable_logging_sdk(monkeypatch):
    monkeypatch.setenv("LOG_DISABLED", "1")


@pytest.fixture(autouse=True)
def required_settings(monkeypatch):
    """Settings has required fields; supply throwaway values so the
    logging tests don't depend on a real .env."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("IMAP_USERNAME", "test@example.com")
    monkeypatch.setenv("IMAP_PASSWORD", "test-password")


def _reset_settings_cache():
    settings_pkg.get_settings.cache_clear()


def test_setup_logging_installs_stderr_handler():
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    setup_logging()
    setup_logging()  # idempotent

    kinds = {type(h).__name__ for h in root.handlers}
    assert "StreamHandler" in kinds


def test_setup_logging_constructs_client_when_enabled(monkeypatch):
    monkeypatch.setenv("LOG_DISABLED", "0")
    monkeypatch.setenv("LOG_KAFKA_BROKERS", "127.0.0.1:1")
    monkeypatch.setenv("LOG_PROJECT", "expense_tracker")

    _reset_settings_cache()

    logging_pkg._client_instance = None
    try:
        c = logging_pkg.setup_logging()
        assert c is not None
        assert c.project == "expense_tracker"
    finally:
        shutdown_logging()
        _reset_settings_cache()


def test_setup_logging_attaches_sdk_handler_to_root(monkeypatch):
    """Records logged through stdlib ``logging`` must also reach Kafka."""
    monkeypatch.setenv("LOG_DISABLED", "0")
    monkeypatch.setenv("LOG_KAFKA_BROKERS", "127.0.0.1:1")

    _reset_settings_cache()

    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)

    logging_pkg._client_instance = None
    try:
        c = logging_pkg.setup_logging()
        assert c is not None
        assert any(type(h).__name__ == "LoggingHandler" for h in root.handlers)
    finally:
        shutdown_logging()
        _reset_settings_cache()


def test_setup_logging_noop_when_sdk_unavailable(monkeypatch):
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "loggingsdk" or name.startswith("loggingsdk."):
            raise ImportError("simulated sdk missing")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    monkeypatch.setattr(logging_pkg, "loggingsdk", None)
    monkeypatch.setattr(logging_pkg, "Client", None)
    monkeypatch.setattr(logging_pkg, "LoggingHandler", None)
    monkeypatch.setattr(logging_pkg, "ParseLevel", None)

    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    result = setup_logging()

    assert result is None
    assert any(type(h).__name__ == "StreamHandler" for h in root.handlers)


def test_client_accessor_returns_null_when_disabled():
    log = get_log_client()
    log.info("hi")
    log.error("oops")
    assert hasattr(log, "project")


def test_client_facade_supports_every_level(monkeypatch):
    """Call sites use warn() (not stdlib's warning()); make sure the
    facade exposes the full set the modules rely on."""
    calls: list[str] = []

    class FakeClient:
        def debug(self, *_a, **_k): calls.append("debug")
        def info(self, *_a, **_k): calls.append("info")
        def warn(self, *_a, **_k): calls.append("warn")
        def error(self, *_a, **_k): calls.append("error")
        def fatal(self, *_a, **_k): calls.append("fatal")

    monkeypatch.setattr(logging_pkg, "_client_instance", FakeClient())

    log = get_log_client()
    log.debug("d")
    log.info("i")
    log.warn("w")
    log.error("e")
    log.fatal("f")

    assert calls == ["debug", "info", "warn", "error", "fatal"]


def test_repeated_setup_keeps_sdk_handler_installed(monkeypatch):
    """Modules call ``client()`` at import time, which triggers
    ``setup_logging()`` before ``app.main`` calls it again. The second
    call clears root.handlers, so it must re-attach the SDK handler."""
    monkeypatch.setenv("LOG_DISABLED", "0")
    monkeypatch.setenv("LOG_KAFKA_BROKERS", "127.0.0.1:1")

    _reset_settings_cache()

    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)

    logging_pkg._client_instance = None
    try:
        first = logging_pkg.setup_logging()
        second = logging_pkg.setup_logging()

        assert first is not None
        assert first is second, "client should be reused, not rebuilt"
        handlers = [type(h).__name__ for h in root.handlers]
        assert handlers.count("LoggingHandler") == 1, handlers
        assert "StreamHandler" in handlers, handlers
    finally:
        shutdown_logging()
        _reset_settings_cache()


def test_shutdown_logging_is_safe_when_disabled():
    shutdown_logging()
    shutdown_logging()


def test_correlation_id_mints_a_fresh_id_per_block():
    with correlation_id() as first:
        pass
    with correlation_id() as second:
        pass
    assert first != second
    assert first and second


def test_correlation_id_reuses_supplied_id():
    with correlation_id("fixed-id") as a:
        assert a == "fixed-id"
        with correlation_id() as b:
            assert b != "fixed-id"


def test_correlation_id_restores_the_enclosing_id():
    """Nested blocks must restore the outer id on exit, otherwise the
    per-email scope would leak into the next poll cycle's logs."""
    with correlation_id() as outer:
        with correlation_id() as inner:
            assert inner != outer
        assert log_id_var.get() == outer

    assert log_id_var.get() is None


def test_correlation_id_restores_on_exception():
    with pytest.raises(RuntimeError):
        with correlation_id():
            raise RuntimeError("boom")
    assert log_id_var.get() is None


def test_correlation_id_is_a_noop_when_sdk_unavailable(monkeypatch):
    """Callers must not need None-checks, so the block still yields a
    usable id when log_id_var is missing."""
    monkeypatch.setattr(logging_pkg, "log_id_var", None)
    monkeypatch.setattr(logging_pkg, "new_log_id", None)

    with correlation_id() as generated:
        assert generated == "unknown"

    with correlation_id("explicit") as supplied:
        assert supplied == "explicit"


async def test_correlation_id_isolated_per_task():
    """Each poll email runs as its own task, so a contextvar set in one
    must not leak into a sibling."""
    import asyncio

    seen: dict[str, str] = {}

    async def worker(name: str) -> None:
        with correlation_id():
            await asyncio.sleep(0)
            seen[name] = log_id_var.get()

    await asyncio.gather(worker("a"), worker("b"))

    assert seen["a"] != seen["b"]
    assert log_id_var.get() is None


def test_modules_import_the_sdk_facade():
    """Guard against a call site creeping back to structlog or
    ``logging.getLogger(__name__)``, which would bypass the SDK."""
    import app.cli.healthcheck
    import app.health.server
    import app.poller.gmail
    import app.services.categorizer
    import app.services.notification
    import app.services.tags_config_builders
    import app.services.tags_provider
    import app.services.tools.base
    import app.telegram.bot
    import app.telegram.handlers.queries

    modules = [
        app.cli.healthcheck,
        app.health.server,
        app.poller.gmail,
        app.services.categorizer,
        app.services.notification,
        app.services.tags_config_builders,
        app.services.tags_provider,
        app.services.tools.base,
        app.telegram.bot,
        app.telegram.handlers.queries,
    ]
    for mod in modules:
        assert hasattr(mod, "log"), f"{mod.__name__} has no `log` client"
        assert not hasattr(mod, "logger"), (
            f"{mod.__name__} still binds a stdlib/structlog `logger`"
        )
