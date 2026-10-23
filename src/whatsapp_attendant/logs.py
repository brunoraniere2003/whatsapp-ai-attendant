"""Structured JSON logs to a rotating file, never to stdout (RQ-22)."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .config import LoggingSettings

LOGGER_NAME = "whatsapp_attendant"
_HANDLER_TAG = "_attendant_handler"
# Library default: silent until setup_logging() attaches the file handler.
logging.getLogger(LOGGER_NAME).addHandler(logging.NullHandler())


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "event": record.getMessage(),
        }
        entry.update(getattr(record, "fields", {}))
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False, default=str)


def mask_phone(phone: str) -> str:
    """Keep the country and area code and the last 2 digits: 5511*******01."""
    digits = "".join(c for c in phone if c.isdigit())
    if len(digits) <= 6:
        return "*" * len(digits)
    return digits[:4] + "*" * (len(digits) - 6) + digits[-2:]


def setup_logging(settings: LoggingSettings) -> logging.Logger:
    """Attach one rotating JSON file handler to the package logger (idempotent)."""
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(settings.level)
    logger.propagate = False
    target = Path(settings.file).resolve()
    for handler in list(logger.handlers):
        if getattr(handler, _HANDLER_TAG, False):
            logger.removeHandler(handler)
            handler.close()
    target.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        target, maxBytes=settings.max_bytes, backupCount=settings.backup_count, encoding="utf-8"
    )
    handler.setFormatter(JsonFormatter())
    setattr(handler, _HANDLER_TAG, True)
    logger.addHandler(handler)
    return logger


def get_logger() -> logging.Logger:
    return logging.getLogger(LOGGER_NAME)


def log_event(event: str, level: int = logging.INFO, **fields: object) -> None:
    get_logger().log(level, event, extra={"fields": fields})
