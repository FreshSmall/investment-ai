from __future__ import annotations

from app.domain.event import (
    Importance,
    EventStatus,
    NormalizedEvent,
    is_near_dup_title,
    l0_match,
    make_content_hash,
    make_event_id,
    normalize_text,
    title_jaccard,
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
    assert l0_match("一般标题", "正文提到 光模块 与 GPU 需求", kws)  # 正文命中需 ≥2 个不同关键词
    assert not l0_match("一般标题", "正文提到 光模块 需求", kws)     # 单个泛词命中不再放行
    assert not l0_match("一般标题", "无关正文", kws)
    assert l0_match("gpu 出货增长", "", kws)  # 大小写不敏感
    assert l0_match("一般标题", "正文提到 光模块 需求", kws, min_content_hits=1)  # 显式放宽


def test_near_dup_merges_same_story_variants() -> None:
    # 跨源同题（标点差异）与"财联社X日电，"前缀变体 → 合并
    assert is_near_dup_title(
        "阳光电源：已向客户交付几台SST，预计四季度投运",
        "阳光电源：已向客户交付几台SST 预计四季度投运",
    )
    assert is_near_dup_title(
        "财联社9月17日电，美国最大区域电网运营商PJM因持续高温天气发布一级电网紧急警报",
        "美国最大区域电网运营商PJM因持续高温天气发布一级电网紧急警报",
    )
    assert is_near_dup_title(
        "英伟达CEO黄仁勋：英伟达明年芯片销量将是今年的两倍",
        "黄仁勋：英伟达明年芯片销量将是今年的两倍",
    )


def test_near_dup_keeps_periodic_digests_apart() -> None:
    # 早/晚间新闻精选、不同日期的涨停分析：Jaccard 高但无长公共子串 → 不合并
    assert not is_near_dup_title("财联社9月17日早间新闻精选", "财联社9月17日晚间新闻精选")
    assert not is_near_dup_title("9月17日午间新闻精选", "财联社9月17日晚间新闻精选")
    assert not is_near_dup_title("9月17日涨停分析", "9月16日涨停分析")
    assert not is_near_dup_title("", "任意标题")  # 空标题不判重


def test_title_jaccard_bounds() -> None:
    assert title_jaccard("华为发布昇腾960", "华为发布昇腾960") == 1.0
    assert title_jaccard("华为发布昇腾960", "储能电池需求增长") == 0.0
    assert title_jaccard("", "华为发布昇腾960") == 0.0


def test_enums_cover_contract() -> None:
    assert {s.value for s in EventStatus} == {
        "raw", "classified", "analyzed", "unclassified", "parse_error", "archived"
    }
    assert {i.value for i in Importance} == {"P0", "P1", "P2", "P3"}
