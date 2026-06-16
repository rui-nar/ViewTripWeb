"""Unit tests for logging utilities."""

import logging
import tempfile
from pathlib import Path

import pytest

from src.utils.logging import (
    _APP_HANDLER_MARK,
    _APP_LOGGER_NAMES,
    configure_logging,
    get_logger,
    setup_logging,
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