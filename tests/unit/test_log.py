from __future__ import annotations

import json
import logging
from pathlib import Path

from app.core import log
from app.core.log import get_logger, sanitize, setup_logging


def test_sanitize_masks_common_secrets() -> None:
    assert sanitize("key=sk-abcd1234efgh") == "key=sk-***"
    assert sanitize("Authorization: Bearer abc.def.ghi") == "Authorization: Bearer ***"
    assert sanitize("password=SuperSecret1") == "password=***"
    assert sanitize("API_KEY: whatever123") == "API_KEY=***"
    assert sanitize("plain text 123") == "plain text 123"


def test_jsonl_output_parseable_with_run_id(tmp_path: Path) -> None:
    logger = setup_logging(log_dir=tmp_path, run_id="run-xyz")
    logger.info("采集开始", extra={"ctx": {"provider": "cls", "count": 10}})
    logger.error("boom", extra={"ctx": {"password=hunter2"}})

    for h in logging.getLogger(log.ROOT_LOGGER_NAME).handlers:
        h.flush()
    files = list(tmp_path.glob("*.jsonl"))
    assert len(files) == 1
    lines = files[0].read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    rec1 = json.loads(lines[0])
    rec2 = json.loads(lines[1])
    assert rec1["run_id"] == "run-xyz" and rec1["ctx"]["provider"] == "cls"
    assert rec2["level"] == "ERROR"
    assert "hunter2" not in lines[1]  # extra 里的密钥也被脱敏
    assert "password=***" in rec2["msg"] or "hunter2" not in json.dumps(rec2)


def test_get_logger_child_inherits_formatting(tmp_path: Path) -> None:
    setup_logging(log_dir=tmp_path, run_id="r1")
    child = get_logger("pipeline")
    assert child.name == "investment_ai.pipeline"
    child.info("child message")
    for h in logging.getLogger(log.ROOT_LOGGER_NAME).handlers:
        h.flush()
    content = list(tmp_path.glob("*.jsonl"))[0].read_text(encoding="utf-8")
    assert '"investment_ai.pipeline"' in content
