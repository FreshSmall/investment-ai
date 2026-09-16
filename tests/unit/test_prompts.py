from __future__ import annotations

import pytest

from app.analysis.prompts import load_prompt, parse_prompt_version, render_prompt

SECTOR_KEYS = ["ai_semiconductor", "power_energy", "robotics"]


def test_parse_prompt_version() -> None:
    assert parse_prompt_version("event_analysis_v1.md") == ("event_analysis", "v1")
    assert parse_prompt_version("daily_summary_v12.md") == ("daily_summary", "v12")
    with pytest.raises(ValueError):
        parse_prompt_version("badname.md")


def test_classification_render_contains_ids_and_schema() -> None:
    ctx = {
        "sector_keys": SECTOR_KEYS,
        "events": [
            {"event_id": "addf091f74bca86a", "title": "GPU 新闻", "content_head": "正文摘要"},
            {"event_id": "dead00000000beef", "title": "电网新闻", "content_head": "正文摘要"},
        ],
    }
    system, user, version = render_prompt("classification_v1.md", ctx)
    assert version == "v1"
    assert '"results"' in system  # system 含 JSON 结构说明
    assert "ai_semiconductor" in system  # 行业枚举注入
    assert "[addf091f74bca86a] GPU 新闻" in user
    assert "[dead00000000beef] 电网新闻" in user


def test_event_analysis_render_event_and_history() -> None:
    ctx = {
        "sector_keys": SECTOR_KEYS,
        "event": {
            "event_id": "addf091f74bca86a",
            "title": "HBM 涨价",
            "published_at": "2026-09-17 09:32",
            "content": "正文全文……",
        },
        "history": [{"summary": "上周先进封装稼动率上行"}],
    }
    system, user, _ = render_prompt("event_analysis_v1.md", ctx)
    assert "source_event_id" in system and "禁止编造" in system
    assert "[addf091f74bca86a] HBM 涨价" in user
    assert "上周先进封装稼动率上行" in user


def test_event_analysis_render_no_history_branch() -> None:
    ctx = {
        "sector_keys": SECTOR_KEYS,
        "event": {"event_id": "a" * 16, "title": "t", "published_at": "x", "content": "c"},
        "history": [],
    }
    _, user, _ = render_prompt("event_analysis_v1.md", ctx)
    assert "暂无相关历史分析" in user


def test_daily_summary_render_and_calm_day() -> None:
    ctx = {"report_date": "2026-09-17", "analyses": []}
    _, user, _ = render_prompt("daily_summary_v1.md", ctx)
    assert "平静日" in user


def test_missing_ctx_var_raises_strictly() -> None:
    with pytest.raises(Exception):
        render_prompt("classification_v1.md", {"sector_keys": SECTOR_KEYS})  # 缺 events


def test_all_three_templates_loadable() -> None:
    for f in ("classification_v1.md", "event_analysis_v1.md", "daily_summary_v1.md"):
        system, user = load_prompt(f)
        assert system and user
