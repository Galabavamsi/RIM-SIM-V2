"""Centralized structured logging for the RIS emulator.

Uses Python's built-in :mod:`logging` with a console handler that renders
key-value pairs for easy parsing and optional file output.

Usage::

    from ris_sim.core.logging import get_logger
    logger = get_logger(__name__)
    logger.info("simulation_started", nodes=2, ris_panels=1, tau=0.002)
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path


class _StructuredFormatter(logging.Formatter):
    """Key=value formatter for machine-parseable logs."""

    def format(self, record: logging.LogRecord) -> str:
        base = f"{record.asctime} [{record.levelname}] {record.name} | {record.getMessage()}"
        if record.exc_info and record.exc_info[1]:
            base += f" | exception={record.exc_info[1]}"
        return base


_LOGGER_CACHE: dict[str, logging.Logger] = {}
_CONSOLE_HANDLER: logging.Handler | None = None
_FILE_HANDLER: logging.Handler | None = None


def setup_logging(
    level: int = logging.INFO,
    log_file: str | Path | None = None,
    *,
    force: bool = False,
) -> None:
    """Configure the root logger with console and optional file output.

    Args:
        level: Log level (e.g. logging.DEBUG, logging.INFO).
        log_file: Optional path for a rotating log file.
        force: If True, remove existing handlers before reconfiguring.
    """
    global _CONSOLE_HANDLER, _FILE_HANDLER

    root = logging.getLogger("ris_sim")
    root.setLevel(level)

    if force:
        root.handlers.clear()
        _CONSOLE_HANDLER = None
        _FILE_HANDLER = None

    if _CONSOLE_HANDLER is None:
        _CONSOLE_HANDLER = logging.StreamHandler(sys.stderr)
        _CONSOLE_HANDLER.setFormatter(_StructuredFormatter())
        _CONSOLE_HANDLER.setLevel(level)
        root.addHandler(_CONSOLE_HANDLER)

    if log_file is not None and _FILE_HANDLER is None:
        path = Path(log_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        _FILE_HANDLER = logging.FileHandler(str(path))
        _FILE_HANDLER.setFormatter(_StructuredFormatter())
        _FILE_HANDLER.setLevel(level)
        root.addHandler(_FILE_HANDLER)


def get_logger(name: str) -> logging.LoggerAdapter:
    """Return a logger that supports dict-style extra fields via ``kwargs``.

    Usage::

        logger = get_logger(__name__)
        logger.info("tx_request", node_id="node_1", fc=2.4e9, samples=2389)
    """
    if name in _LOGGER_CACHE:
        return _LOGGER_CACHE[name]  # type: ignore[return-value]

    base = logging.getLogger(f"ris_sim.{name}")

    class _Adapter(logging.LoggerAdapter):
        def process(self, msg, kwargs):
            extra_parts = " ".join(f"{k}={v}" for k, v in kwargs.items())
            full_msg = f"{msg} {extra_parts}".strip()
            return full_msg, {}

    adapter = _Adapter(base, {})
    _LOGGER_CACHE[name] = adapter  # type: ignore[assignment]
    return adapter


def set_level(level: int) -> None:
    """Change the log level at runtime."""
    logging.getLogger("ris_sim").setLevel(level)
    if _CONSOLE_HANDLER:
        _CONSOLE_HANDLER.setLevel(level)
