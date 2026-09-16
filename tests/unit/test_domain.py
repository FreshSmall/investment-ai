from __future__ import annotations

from app.domain.event import (
    Importance,
    EventStatus,
    NormalizedEvent,
    l0_match,
    make_content_hash,
    make_event_id,
    normalize_text,
)


def _ev() -> NormalizedEvent:
    return NormalizedEvent(  # type: ignore[call-arg]
        source="cls", source_id="123456", title="T", content="C",
        url=None, published_at=__import__("datetime").datetime(2026, 9, 17, 20, 0),
        collected_at=__import__("datetime").datetime(2026, 9, 17, 20, 5),
        norm_title="t", norm_content="c",
    )


def test_event_id_stable_snapshot() -> None:
    assert make_event_id("cls", "123456") == "addf091f74bca86a"
    assert make_event_id("cls", "123456") == make_event_id("cls", "123456")
    assert make_event_id("cls", "1") != make_event_id("eastmoney", "1")


def test_content_hash_deterministic_and_input_sensitive() -> None:
    h1 = make_content_hash("标题甲", "正文乙")
    assert h1 == make_content_hash("标题甲", "正文乙")
    assert h1 != make_content_hash("标题甲", "正文丙")
    assert len(h1) == 40


def test_normalized_event_derives_keys() -> None:
    e = _ev()
    assert e.event_id == make_event_id("cls", "123456")
    assert e.content_hash == make_content_hash("t", "c")


def test_normalize_text_strips_html_entities_fullwidth_ws() -> None:
    assert normalize_text("<p>HBM&nbsp;涨价</p>") == "HBM 涨价"
    assert normalize_text("ＧＰＵ需求") == "GPU需求"
    assert normalize_text("先进\u3000封装\t\t测试") == "先进 封装 测试"
    assert normalize_text("") == ""


def test_l0_match_title_beats_content_and_case_insensitive() -> None:
    kws = ["GPU", "光模块"]
    assert l0_match("英伟达发布新GPU", "无关正文", kws)
    assert l0_match("一般标题", "正文中提到 光模块 需求", kws)
    assert not l0_match("一般标题", "无关正文", kws)
    assert l0_match("gpu 出货增长", "", kws)  # 大小写不敏感


def test_enums_cover_contract() -> None:
    assert {s.value for s in EventStatus} == {
        "raw", "classified", "analyzed", "unclassified", "parse_error", "archived"
    }
    assert {i.value for i in Importance} == {"P0", "P1", "P2", "P3"}
