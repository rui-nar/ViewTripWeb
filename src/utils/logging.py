"""Logging utilities for ViewTrip."""

import logging
import logging.handlers
from pathlib import Path
from typing import Optional


def setup_logging(
    name: str,
    level: int = logging.INFO,
    log_file: Optional[str] = None,
    log_dir: str = "logs",
) -> logging.Logger:
    """
    Set up logging for a module.

    Args:
        name: Logger name (typically __name__)
        level: Logging level (default: INFO)
        log_file: Optional log file name
        log_dir: Directory for log files (default: logs/)

    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_format = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    console_handler.setFormatter(console_format)
    logger.addHandler(console_handler)

    # File handler (optional)
    if log_file:
        log_path = Path(log_dir)
        log_path.mkdir(exist_ok=True)

        file_handler = logging.handlers.RotatingFileHandler(
            log_path / log_file, maxBytes=10485760, backupCount=5
        )
        file_handler.setLevel(level)
        file_format = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s"
        )
        file_handler.setFormatter(file_format)
        logger.addHandler(file_handler)

    return logger


def get_logger(name: str) -> logging.Logger:
    """
    Get an existing logger by name.

    Args:
        name: Logger name

    Returns:
        Logger instance
    """
    return logging.getLogger(name)


# Top-level logger namespaces used by app modules via get_logger(__name__):
# everything under `api.*` (routers) and `src.*` (business logic / services).
_APP_LOGGER_NAMES = ("api", "src")
_APP_HANDLER_MARK = "_viewtrip_app_handler"


def configure_logging(level: int = logging.INFO) -> None:
    """Attach a console handler to the app's top-level loggers (idempotent).

    App modules obtain loggers via ``get_logger(__name__)`` under the ``api.*``
    and ``src.*`` namespaces. Those loggers have no handlers of their own, so
    without this their records propagate to an unconfigured root and are dropped
    (only WARNING+ survives, via logging's last-resort handler) — which is why
    early auth diagnostics were invisible when running under uvicorn.

    Wiring a handler onto the two app namespaces makes INFO+ app logs appear on
    the console alongside uvicorn's own output. Uvicorn configures its own
    ``uvicorn``/``uvicorn.access`` loggers with ``propagate=False``, so they are
    untouched and access logs are never duplicated. Safe to call more than once
    (e.g. on module reload): a handler is added only if one isn't already there.
    """
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    handler = logging.StreamHandler()
    handler.setLevel(level)
    handler.setFormatter(formatter)
    setattr(handler, _APP_HANDLER_MARK, True)

    for name in _APP_LOGGER_NAMES:
        logger = logging.getLogger(name)
        logger.setLevel(level)
        already = any(
            getattr(h, _APP_HANDLER_MARK, False) for h in logger.handlers
        )
        if not already:
            logger.addHandler(handler)