"""Structured JSON logging with request ids (Engineering pack 10.4).

Never log access tokens, push tokens, OTPs, raw evidence or exact coordinates.
"""
import json
import logging
import sys
from datetime import UTC, datetime

from app.core.errors import request_id_var


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        rid = getattr(record, "request_id", None) or request_id_var.get()
        if rid:
            entry["request_id"] = rid
        for key in ("event_id", "event_type", "report_id", "incident_id", "outcome", "worker_id"):
            if hasattr(record, key):
                entry[key] = str(getattr(record, key))
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
