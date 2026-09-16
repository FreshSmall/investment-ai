"""Structured JSONL logging with secret sanitization.

- One JSON object per line in ``logs/YYYY-MM-DD.jsonl`` plus mirrored console output.
- ``run_id`` is attached to every record of the run (observability requirement).
- Sanitizer masks API keys / bearer tokens / password assignments before formatting.
- LLM prompt bodies are never logged at full length (callers log hash + length only).
"""

from __future__ import annotations

import json
import logging
import re
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from app.core.config import PROJECT_ROOT

ROOT_LOGGER_NAME = "investment_ai"

_REDACTIONS: List[Tuple[re.Pattern, str]] = [
    (re.compile(r"sk-[A-Za-z0-9_\-]{4,}"), "sk-***"),
    (re.compile(r"Bearer\s+\S+"), "Bearer ***"),
    (re.compile(r"(?i)(password|passwd|api_key)\s*[=:]\s*\S+"), r"\1=***"),
]


def sanitize(text: str) -> str:
    for pattern, repl in _REDACTIONS:
        text = pattern.sub(repl, text)
    return text


class JsonFormatter(logging.Formatter):
    def __init__(self, run_id: Optional[str] = None) -> None:
        super().__init__()
        self.run_id = run_id

    def format(self, record: logging.LogRecord) -> str:
        payload: Dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "module": record.name,
            "msg": sanitize(record.getMessage()),
        }
        if self.run_id:
            payload["run_id"] = self.run_id
        extra = getattr(record, "ctx", None)
        if isinstance(extra, dict):
            payload["ctx"] = extra
        if record.exc_info and record.exc_info[0] is not None:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


_lock = threading.Lock()
_configured_for: Dict[str, Path] = {}


def setup_logging(log_dir: Optional[Path] = None, run_id: Optional[str] = None) -> logging.Logger:
    """Idempotent per (dir, run_id); re-configures when run_id changes."""
    log_dir = log_dir or PROJECT_ROOT / "logs"
    key = "%s|%s" % (log_dir, run_id or "")
    with _lock:
        if _configured_for.get("key") == key and _configured_for.get("dir") == log_dir:
            return logging.getLogger(ROOT_LOGGER_NAME)
        logger = logging.getLogger(ROOT_LOGGER_NAME)
        logger.setLevel(logging.INFO)
        logger.propagate = False
        for h in list(logger.handlers):
            logger.removeHandler(h)

        formatter = JsonFormatter(run_id=run_id)
        console = logging.StreamHandler(sys.stderr)
        console.setFormatter(formatter)
        logger.addHandler(console)

        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            logfile = log_dir / ("%s.jsonl" % datetime.now().strftime("%Y-%m-%d"))
            fh = logging.FileHandler(logfile, encoding="utf-8")
            fh.setFormatter(formatter)
            logger.addHandler(fh)
        except OSError:
            logger.warning("无法创建日志目录 %s，仅输出到控制台", log_dir)

        _configured_for.clear()
        _configured_for["key"] = key
        _configured_for["dir"] = log_dir
        return logger


def get_logger(name: str = ROOT_LOGGER_NAME) -> logging.Logger:
    """Child logger under the configured root (keeps run_id/JSON formatting)."""
    if name == ROOT_LOGGER_NAME:
        return setup_logging()
    return logging.getLogger("%s.%s" % (ROOT_LOGGER_NAME, name))
