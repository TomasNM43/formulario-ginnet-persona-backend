"""Logging JSON a archivo rotativo (un archivo por proceso: en Windows no se puede rotar un archivo compartido)."""
from __future__ import annotations

import json
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        data = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "pid": record.process,
            "msg": record.getMessage(),
        }
        extra = getattr(record, "ctx", None)
        if extra:
            data.update(extra)
        if record.exc_info:
            data["exc"] = self.formatException(record.exc_info)
        return json.dumps(data, ensure_ascii=False)


def setup_logging(log_dir: Path, name: str) -> None:
    root = logging.getLogger()
    if getattr(root, "_ginnet_configured", False):
        return
    root.setLevel(logging.INFO)
    fmt = JsonFormatter()
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stderr)]
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        handlers.append(
            RotatingFileHandler(
                log_dir / f"{name}-{os.getpid()}.log", maxBytes=10 * 1024 * 1024, backupCount=10, encoding="utf-8"
            )
        )
    except OSError as exc:
        sys.stderr.write(f"No se pudo crear el log en {log_dir}: {exc}\n")
    for h in handlers:
        h.setFormatter(fmt)
        root.addHandler(h)
    root._ginnet_configured = True  # type: ignore[attr-defined]
