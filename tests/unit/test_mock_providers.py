from __future__ import annotations

from datetime import datetime

import pytest

import app.providers  # noqa: F401
from app.domain.analysis import LLMRequest
from app.providers.base import NEWS_PROVIDER_REGISTRY, build_news_providers
from app.providers.llm.mock import MockLLMProvider
from app.providers.news.mock import MockNewsProvider

SINCE = datetime(2026, 9, 16, 0, 0, 0)


def test_mock_registered_and_buildable() -> None:
    assert "mock" in NEWS_PROVIDER_REGISTRY
    providers, degraded = build_news_providers(["mock"])
    assert len(providers) == 1 and degraded == []


def test_fetch_deterministic_and_filters() -> None:
    p = MockNewsProvider()
    first = p.fetch(SINCE)
    second = p.fetch(SINCE)
    assert first == second  # 确定性：两次输出完全一致
    assert len(first) == 11  # 12 条中 1 条坏时间戳被跳过
    assert p.bad_records == 1
    assert {e.source for e in first} == {"cls", "eastmoney"}


def test_fetch_since_filters_old_items() -> None:
    p = MockNewsProvider()
    out = p.fetch(datetime(2026, 9, 17, 12, 0, 0))
    assert all(e.published_at >= datetime(2026, 9, 17, 12, 0, 0) for e in out)
    assert len(out) == 6  # 1005/2002/2003/1007/1008/2004


def test_cross_source_duplicate_exists_in_fixture() -> None:
    p = MockNewsProvider()
    events = p.fetch(SINCE)
    titles = [e.title for e in events]
    assert titles.count("英伟达发布新一代GPU架构 HBM用量翻倍") == 2  # cls + eastmoney 同文


def _cls_req(user: str, strategy: str = "classification") -> LLMRequest:
    return LLMRequest(system="sys", user=user, model="mock", strategy=strategy)


def test_mock_llm_classification_parses_event_ids() -> None:
    llm = MockLLMProvider()
    user = "待分类事件：\n[addf091f74bca86a] 标题A | 正文\n[dead00000000beef] 标题B | 正文"
    result = llm.complete_json(_cls_req(user))
    assert result.ok and result.data is not None
    items = result.data["results"]
    assert [i["event_id"] for i in items] == ["addf091f74bca86a", "dead00000000beef"]
    # 轮换标签表：P0/P1/P2 各归其位
    assert items[0]["importance"] == "P0" and items[0]["sectors"] == ["ai_semiconductor"]
    assert items[1]["importance"] == "P1" and items[1]["sectors"] == ["power_energy"]
    assert llm.call_count("classification") == 1


def test_mock_llm_event_analysis_cites_input_event() -> None:
    llm = MockLLMProvider()
    result = llm.complete_json(_cls_req("[abc123000000def0] 事件", strategy="event_analysis"))
    assert result.data["facts"][0]["source_event_id"] == "abc123000000def0"
    assert result.data["uncertainty"]  # uncertainty 必填纪律


def test_mock_llm_override_injects_malformed_text() -> None:
    llm = MockLLMProvider(overrides={"classification": ["这不是JSON {{{"]})
    result = llm.complete_json(_cls_req("[addf091f74bca86a] x"))
    assert result.data is None and "这不是JSON" in result.raw_text


def test_mock_llm_unknown_strategy_generic() -> None:
    llm = MockLLMProvider()
    result = llm.complete_json(_cls_req("whatever", strategy="daily_summary"))
    assert result.data["summary"]
