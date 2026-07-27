"""Minimal structured JSON logging without response bodies or environment dumps."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any, ClassVar


class JsonFormatter(logging.Formatter):
    """Render a stable JSON object per log event."""

    RESERVED: ClassVar[set[str]] = set(logging.makeLogRecord({}).__dict__)

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        payload.update(
            {
                key: value
                for key, value in record.__dict__.items()
                if key not in self.RESERVED
                and key not in {"message", "asctime"}
                and isinstance(value, (str, int, float, bool, type(None)))
            }
        )
        return json.dumps(payload, sort_keys=True)


def configure_logging(verbose: bool = False) -> None:
    """Configure application logging exactly once."""

    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
