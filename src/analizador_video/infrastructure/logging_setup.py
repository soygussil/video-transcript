"""Logging estructurado (JSON por línea), con rotación y sanitización.

No se registran por defecto: transcripción, OCR, secretos ni rutas personales completas.
"""

from __future__ import annotations

import json
import logging
import re
import traceback
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

CONTEXT_FIELDS = ("project_id", "run_id", "stage", "backend", "device", "event", "duration_ms", "result")
_SECRET_RE = re.compile(r"(?i)\b(api[_-]?key|token|secret|password|authorization)\b\s*[:=]\s*(?:bearer\s+)?\S+")
_BEARER_RE = re.compile(r"(?i)bearer\s+[a-z0-9._\-]+")


def sanitize(text: str) -> str:
    home = str(Path.home())
    result = text.replace(home, "~") if home not in ("/", "") else text
    result = _SECRET_RE.sub(lambda m: f"{m.group(1)}=***", result)
    return _BEARER_RE.sub("Bearer ***", result)


class SanitizingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = sanitize(record.getMessage())
        record.args = None
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for name in CONTEXT_FIELDS:
            value = getattr(record, name, None)
            if value is not None:
                payload[name] = value
        if record.exc_info and record.exc_info[0] is not None:
            payload["exception"] = sanitize("".join(traceback.format_exception(*record.exc_info))[-4000:])
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(log_dir: Path, level: str = "INFO", console: bool = False) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger("analizador_video")
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()
    file_handler = RotatingFileHandler(log_dir / "aplicacion.log", maxBytes=2_000_000, backupCount=5, encoding="utf-8")
    file_handler.setFormatter(JsonFormatter())
    file_handler.addFilter(SanitizingFilter())
    root.addHandler(file_handler)
    if console:
        stream = logging.StreamHandler()
        stream.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
        stream.addFilter(SanitizingFilter())
        root.addHandler(stream)
    root.propagate = False


def recent_errors(log_dir: Path, limit: int = 20) -> list[dict[str, Any]]:
    path = log_dir / "aplicacion.log"
    if not path.exists():
        return []
    errors: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines()[-2000:]:
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict) and item.get("level") in ("ERROR", "CRITICAL"):
            errors.append(item)
    return errors[-limit:]
