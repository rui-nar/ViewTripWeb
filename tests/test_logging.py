"""Unit tests for logging utilities."""

import logging
import tempfile
import time
from pathlib import Path

import pytest

import src.utils.logging as logging_mod
from src.utils.logging import (
    _APP_HANDLER_MARK,
    _APP_LOGGER_NAMES,
    LEVEL_NAMES,
    _context_filter,
    apply_level,
    clear_level_override,
    configure_logging,
    current_level_info,
    env_level,
    get_logger,
    publish_level_override,
    refresh_level_from_store,
    request_id_var,
    set_level_override,
    setup_logging,
    user_id_var,
)


def _app_handlers(logger):
    return [h for h in logger.handlers if getattr(h, _APP_HANDLER_MARK, False)]


class TestConfigureLogging:
    """configure_logging wires app namespaces to a console handler."""

    def setup_method(self):
        # Start each test from a clean slate on the app namespaces.
        for name in _APP_LOGGER_NAMES:
            logger = logging.getLogger(name)
            for h in _app_handlers(logger):
                logger.removeHandler(h)

    teardown_method = setup_method

    def test_attaches_handler_to_each_app_namespace(self):
        configure_logging()
        for name in _APP_LOGGER_NAMES:
            assert len(_app_handlers(logging.getLogger(name))) == 1

    def test_is_idempotent(self):
        configure_logging()
        configure_logging()
        configure_logging()
        for name in _APP_LOGGER_NAMES:
            assert len(_app_handlers(logging.getLogger(name))) == 1

    def test_app_logger_emits_info(self, caplog):
        configure_logging()
        with caplog.at_level(logging.INFO, logger="api"):
            get_logger("api.test").info("hello-info")
        assert "hello-info" in caplog.text

    def test_does_not_touch_uvicorn_loggers(self):
        configure_logging()
        uvicorn_logger = logging.getLogger("uvicorn.access")
        assert _app_handlers(uvicorn_logger) == []

    def test_restyles_existing_uvicorn_handler_with_timestamp(self):
        """Issue #45 investigation needed exact request timing to tell a slow
        request apart from a stuck one, but uvicorn's access/error loggers
        print no timestamp by default. configure_logging() must restyle
        whatever handler uvicorn already attached (not add a second one, which
        would duplicate every access/error line) so its output carries the
        same %(asctime)s (millisecond-resolution) prefix as app logs."""
        uvicorn_logger = logging.getLogger("uvicorn.access")
        stub_handler = logging.StreamHandler()
        stub_handler.setFormatter(logging.Formatter("%(message)s"))  # mimics uvicorn's own, no timestamp
        uvicorn_logger.handlers = [stub_handler]
        try:
            configure_logging()
            assert len(uvicorn_logger.handlers) == 1
            assert "%(asctime)s" in uvicorn_logger.handlers[0].formatter._fmt
        finally:
            uvicorn_logger.handlers = []

    def test_formatter_carries_request_id_and_user_id_fields(self):
        """issue #205: the logfmt preamble must be parseable at query time via
        ``| logfmt`` (request_id/user_id are never Loki labels — unbounded
        cardinality), so both field names have to appear literally in the
        format string, not just render correctly."""
        configure_logging()
        fmt = _app_handlers(logging.getLogger("api"))[0].formatter._fmt
        assert "request_id=%(request_id)s" in fmt
        assert "user_id=%(user_id)s" in fmt

    def test_uvicorn_handler_gets_context_filter(self):
        """The restyled uvicorn handler must also inject request_id/user_id —
        access lines uvicorn itself emits (not our own access-log middleware)
        need the same correlation fields or they're unparseable by the same
        ``| logfmt`` query as everything else."""
        uvicorn_logger = logging.getLogger("uvicorn.access")
        stub_handler = logging.StreamHandler()
        stub_handler.setFormatter(logging.Formatter("%(message)s"))
        uvicorn_logger.handlers = [stub_handler]
        try:
            configure_logging()
            configure_logging()  # idempotent: must not attach the filter twice
            handler = uvicorn_logger.handlers[0]
            assert sum(1 for f in handler.filters if f is _context_filter) == 1
        finally:
            uvicorn_logger.handlers = []

    def test_alembic_fileconfig_keeps_app_loggers_enabled(self):
        """Regression for the "no logs in production" bug. `alembic upgrade head`
        runs inside the live API process (lifespan) and loads alembic/env.py,
        which calls fileConfig. With the default disable_existing_loggers=True it
        DISABLED the app's api.*/src.* loggers (configured at import) — silently
        killing every app log on the NAS. env.py now passes
        disable_existing_loggers=False, and alembic.ini puts no handler on root
        (so app logs don't double via propagation)."""
        import os
        from logging.config import fileConfig

        configure_logging()
        ini = os.path.join(os.path.dirname(os.path.dirname(__file__)), "alembic.ini")
        root = logging.getLogger()
        saved_root = root.handlers[:]
        try:
            fileConfig(ini, disable_existing_loggers=False)  # mirrors alembic/env.py
            # App loggers survive alembic's reconfiguration.
            assert logging.getLogger("src").disabled is False
            assert logging.getLogger("api").disabled is False
            assert len(_app_handlers(logging.getLogger("src"))) == 1
            # alembic.ini must not hang a handler on root, or every app log would
            # print twice (own handler + propagation to root).
            assert root.handlers == []
        finally:
            root.handlers[:] = saved_root


class TestLevelOverride:
    """Live, process-memory override on top of the LOG_LEVEL baseline (#208)."""

    def setup_method(self):
        for name in _APP_LOGGER_NAMES:
            logger = logging.getLogger(name)
            for h in _app_handlers(logger):
                logger.removeHandler(h)
        logging_mod._env_level = logging.INFO
        clear_level_override()

    teardown_method = setup_method

    def test_env_level_defaults_to_info(self, monkeypatch):
        monkeypatch.delenv("LOG_LEVEL", raising=False)
        assert env_level() == logging.INFO

    def test_env_level_reads_valid_value(self, monkeypatch):
        monkeypatch.setenv("LOG_LEVEL", "debug")
        assert env_level() == logging.DEBUG

    def test_env_level_falls_back_on_unrecognized_value(self, monkeypatch):
        """A typo'd env var must not crash boot — silently default to INFO."""
        monkeypatch.setenv("LOG_LEVEL", "not-a-level")
        assert env_level() == logging.INFO

    def test_apply_level_sets_logger_and_handler_levels(self):
        configure_logging(level=logging.INFO)
        apply_level(logging.DEBUG)
        for name in _APP_LOGGER_NAMES:
            logger = logging.getLogger(name)
            assert logger.level == logging.DEBUG
            for h in _app_handlers(logger):
                assert h.level == logging.DEBUG

    def test_current_level_info_defaults_to_env(self):
        configure_logging(level=logging.WARNING)
        info = current_level_info()
        assert info.effective_level == logging.WARNING
        assert info.source == "env"
        assert info.override_level is None

    def test_set_level_override_takes_effect_immediately(self):
        configure_logging(level=logging.INFO)
        set_level_override(logging.DEBUG, expires_at=None)
        info = current_level_info()
        assert info.effective_level == logging.DEBUG
        assert info.source == "override"
        for name in _APP_LOGGER_NAMES:
            assert logging.getLogger(name).level == logging.DEBUG

    def test_clear_level_override_reverts_to_env(self):
        configure_logging(level=logging.INFO)
        set_level_override(logging.DEBUG, expires_at=None)
        clear_level_override()
        info = current_level_info()
        assert info.effective_level == logging.INFO
        assert info.source == "env"

    def test_expired_override_is_treated_as_absent(self):
        """Belt-and-suspenders in case the scheduled revert job hasn't fired
        yet — an expiry in the past must never be reported as still live."""
        configure_logging(level=logging.INFO)
        set_level_override(logging.DEBUG, expires_at=time.time() - 1)
        info = current_level_info()
        assert info.source == "env"
        assert info.effective_level == logging.INFO

    def test_publish_level_override_writes_to_the_shared_store(self, monkeypatch):
        written = {}
        monkeypatch.setattr(
            "src.utils.log_level_store.write",
            lambda level, expires_at: written.update(
                level=level, expires_at=expires_at
            ),
        )
        expires_at = time.time() + 3600
        publish_level_override(logging.DEBUG, expires_at)
        assert written == {"level": logging.DEBUG, "expires_at": expires_at}
        assert current_level_info().effective_level == logging.DEBUG

    def test_refresh_level_from_store_applies_a_pending_override(self, monkeypatch):
        configure_logging(level=logging.INFO)
        monkeypatch.setattr(
            "src.utils.log_level_store.read", lambda: (logging.DEBUG, None)
        )
        refresh_level_from_store()
        assert current_level_info().effective_level == logging.DEBUG

    def test_refresh_level_from_store_clears_a_reverted_override(self, monkeypatch):
        """A worker process picks up an admin's DELETE the same way it picks
        up a PUT — by re-reading the store, not by being told directly."""
        configure_logging(level=logging.INFO)
        set_level_override(logging.DEBUG, expires_at=None)
        monkeypatch.setattr("src.utils.log_level_store.read", lambda: None)
        refresh_level_from_store()
        assert current_level_info().source == "env"

    def test_refresh_level_from_store_treats_an_expired_entry_as_reverted(
        self, monkeypatch
    ):
        configure_logging(level=logging.INFO)
        monkeypatch.setattr(
            "src.utils.log_level_store.read",
            lambda: (logging.DEBUG, time.time() - 1),
        )
        refresh_level_from_store()
        assert current_level_info().source == "env"

    def test_level_names_cover_the_admin_endpoint_choices(self):
        assert LEVEL_NAMES == ("DEBUG", "INFO", "WARNING", "ERROR")


class TestSetupLogging:
    """Test logging setup functions."""

    def test_setup_logging_basic(self):
        """Test basic logger setup."""
        logger = setup_logging("test_logger")
        assert isinstance(logger, logging.Logger)
        assert logger.name == "test_logger"

    def test_setup_logging_level(self):
        """Test logger setup with custom level."""
        logger = setup_logging("test_logger", level=logging.DEBUG)
        assert logger.level == logging.DEBUG

    def test_setup_logging_with_file(self):
        """Test logger setup with file handler."""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger_name = f"test_file_logger_{id(tmpdir)}"
            logger = setup_logging(
                logger_name,
                log_file="test.log",
                log_dir=tmpdir,
            )
            assert isinstance(logger, logging.Logger)

            # Verify log directory was created
            log_dir = Path(tmpdir)
            assert log_dir.exists()

            # Test logging to file
            logger.info("Test message")
            log_file = log_dir / "test.log"
            assert log_file.exists()
            
            # Clean up handlers to allow temp directory deletion
            for handler in list(logger.handlers):
                handler.close()
                logger.removeHandler(handler)
            
            # Remove logger from registry
            if logger_name in logging.Logger.manager.loggerDict:
                del logging.Logger.manager.loggerDict[logger_name]
            # Shutdown logging to release file handles
            logging.shutdown()

    def test_setup_logging_creates_log_directory(self):
        """Test that log directory is created if it doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_dir = Path(tmpdir) / "new_logs"
            assert not log_dir.exists()

            logger_name = f"test_dir_logger_{id(tmpdir)}"
            logger = setup_logging(
                logger_name,
                log_file="test.log",
                log_dir=str(log_dir),
            )

            assert log_dir.exists()
            
            # Clean up handlers to allow temp directory deletion
            for handler in list(logger.handlers):
                handler.close()
                logger.removeHandler(handler)
            
            # Remove logger from registry
            if logger_name in logging.Logger.manager.loggerDict:
                del logging.Logger.manager.loggerDict[logger_name]
            # Shutdown logging to release file handles
            logging.shutdown()

    def test_setup_logging_console_handler(self):
        """Test that console handler is added."""
        logger = setup_logging("test_console_logger")
        handlers = logger.handlers
        assert len(handlers) >= 1
        assert isinstance(handlers[0], logging.StreamHandler)

    def test_get_logger(self):
        """Test getting existing logger."""
        # First setup a logger
        setup_logging("test_get_logger")
        # Then get it
        logger = get_logger("test_get_logger")
        assert isinstance(logger, logging.Logger)
        assert logger.name == "test_get_logger"

    def test_get_logger_nonexistent(self):
        """Test getting a logger that doesn't exist yet."""
        logger = get_logger("nonexistent_logger")
        assert isinstance(logger, logging.Logger)
        assert logger.name == "nonexistent_logger"

    def test_multiple_loggers(self):
        """Test setting up multiple loggers."""
        logger1 = setup_logging("logger1")
        logger2 = setup_logging("logger2")

        assert logger1.name == "logger1"
        assert logger2.name == "logger2"
        assert logger1 is not logger2


class TestRequestContextFilter:
    """request_id_var/user_id_var + the filter that stamps them onto records."""

    def test_defaults_outside_any_request_context(self):
        """APScheduler jobs, the import-time startup line, a worker process —
        none of them ever call .set(), so LookupError must never surface and
        the record must show the documented "-" placeholder."""
        record = logging.LogRecord(
            "test", logging.INFO, __file__, 1, "msg", None, None
        )
        assert _context_filter.filter(record) is True
        assert record.request_id == "-"
        assert record.user_id == "-"

    def test_stamps_bound_context_values(self):
        req_token = request_id_var.set("abc12345")
        user_token = user_id_var.set("42")
        try:
            record = logging.LogRecord(
                "test", logging.INFO, __file__, 1, "msg", None, None
            )
            _context_filter.filter(record)
            assert record.request_id == "abc12345"
            assert record.user_id == "42"
        finally:
            request_id_var.reset(req_token)
            user_id_var.reset(user_token)