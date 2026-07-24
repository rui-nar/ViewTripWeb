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
# ``apscheduler`` (background jobs — WAL checkpoint, daily backup) has no
# handler of its own either, so it gets the same treatment.
_APP_LOGGER_NAMES = ("api", "src", "apscheduler")
_APP_HANDLER_MARK = "_viewtrip_app_handler"

# uvicorn wires its own handlers onto these before the app module is imported
# (Config.__init__ calls configure_logging() ahead of Config.load()), but its
# default formatters omit the timestamp entirely — restyled in place below
# rather than replaced, so the record's %(message)s (built by uvicorn's
# ColourizedFormatter subclasses from client_addr/request_line/status_code)
# still renders correctly.
_UVICORN_LOGGER_NAMES = ("uvicorn", "uvicorn.error", "uvicorn.access")


def configure_logging(level: int = logging.INFO) -> None:
    """Attach a millisecond-timestamped console handler across every logger
    this process emits through (idempotent).

    App modules obtain loggers via ``get_logger(__name__)`` under the ``api.*``
    and ``src.*`` namespaces, and APScheduler logs under ``apscheduler``. Those
    loggers have no handlers of their own, so without this their records
    propagate to an unconfigured root and are dropped (only WARNING+ survives,
    via logging's last-resort handler) — which is why early auth diagnostics
    were invisible when running under uvicorn, and why APScheduler's "job
    missed" warnings showed up with no timestamp at all (issue #45 investigation
    needed exact timing to distinguish a slow request from a stuck one).

    uvicorn's own ``uvicorn``/``uvicorn.error``/``uvicorn.access`` loggers do
    have handlers (uvicorn wires those up before this app module is even
    imported), but uvicorn's default formatters print no timestamp either —
    those get their existing handler's formatter swapped in place instead of a
    second handler added, so access/error lines aren't duplicated.

    ``%(asctime)s`` includes milliseconds by default (``,mmm``) with no
    ``datefmt`` override, which is what every one of these needed to correlate
    a request's actual server-side duration against the client's own timeout.

    Safe to call more than once (e.g. on module reload): a handler is added
    only if one isn't already there.
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

    for name in _UVICORN_LOGGER_NAMES:
        for h in logging.getLogger(name).handlers:
            h.setFormatter(formatter)