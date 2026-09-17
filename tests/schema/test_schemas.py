"""LLM Schema Test（指令十五）：合法/缺字段/异常 JSON/输出污染/枚举幻觉。"""

from __future__ import annotations

import json

import pytest

from app.analysis.schemas import ParseError, load_schema, parse_llm_json, validate

SECTORS = ["ai_semiconductor", "power_energy", "robotics"]
EID = "addf091f74bca86a"

# ---------------- parse_llm_json ----------------


def test_parse_plain_json() -> None:
    assert parse_llm_json('{"a": 1}') == {"a": 1}


def test_parse_dict_passthrough() -> None:
    assert parse_llm_json({"a": 1}) == {"a": 1}


def test_parse_fenced_json() -> None:
    text = '好的，以下是结果：\n```json\n{"a": 1}\n```\n以上。'
    assert parse_llm_json(text) == {"a": 1}


def test_parse_trailing_comma_recovery() -> None:
    assert parse_llm_json('{"a": [1, 2, 3,]}') == {"a": [1, 2, 3]}


def test_parse_bom_stripped() -> None:
    assert parse_llm_json('\ufeff{"a": 1}') == {"a": 1}


def test_parse_garbage_raises() -> None:
    with pytest.raises(ParseError):
        parse_llm_json("这不是JSON {{{")
    with pytest.raises(ParseError):
        parse_llm_json("")
    with pytest.raises(ParseError):
        parse_llm_json("[1,2,3]")  # 顶层非对象


# ---------------- classification_v1 ----------------


def valid_classification() -> dict:
    return {
        "results": [
            {
                "event_id": EID,
                "sectors": ["ai_semiconductor"],
                "event_type": "catalyst",
                "importance": "P0",
                "reason": "重大产业催化",
            }
        ]
    }


def test_classification_valid() -> None:
    ok, errors = validate("classification_v1", valid_classification(), SECTORS)
    assert ok, errors


def test_classification_missing_field() -> None:
    data = valid_classification()
    del data["results"][0]["importance"]
    ok, errors = validate("classification_v1", data, SECTORS)
    assert not ok and any("importance" in e for e in errors)


def test_classification_hallucinated_sector_rejected() -> None:
    data = valid_classification()
    data["results"][0]["sectors"] = ["quantum_bio"]  # 不存在的行业
    ok, errors = validate("classification_v1", data, SECTORS)
    assert not ok


def test_classification_bad_importance_enum() -> None:
    data = valid_classification()
    data["results"][0]["importance"] = "P9"
    ok, _ = validate("classification_v1", data, SECTORS)
    assert not ok


def test_classification_bad_event_id_pattern() -> None:
    data = valid_classification()
    data["results"][0]["event_id"] = "not-hex!"
    ok, _ = validate("classification_v1", data, SECTORS)
    assert not ok


def test_classification_additional_property_rejected() -> None:
    data = valid_classification()
    data["results"][0]["score"] = 95  # 评分器字段 —— 契约层面禁止
    ok, _ = validate("classification_v1", data, SECTORS)
    assert not ok


# ---------------- event_analysis_v1 ----------------


def valid_analysis() -> dict:
    return {
        "summary": "算力产业链出现需求侧重要边际变化，信号强于预期。",
        "facts": [{"text": "公司公告新增产能。", "source_event_id": EID}],
        "interpretations": ["产能扩张反映管理层对需求的信心。"],
        "hypotheses": ["若需求兑现，供需两季度内趋紧。"],
        "affected_industries": ["ai_semiconductor"],
        "affected_companies": [{"name": "示例公司", "code": None, "channel": "订单弹性"}],
        "causal_chain": ["算力需求", "服务器出货", "零部件订单"],
        "supporting_evidence": [{"text": "客户追加订单。", "source_event_id": EID}],
        "counter_evidence": [{"text": "同业扩产。", "source_event_id": EID}],
        "uncertainty": ["扩产落地节奏未验证。"],
        "follow_up_questions": ["跟踪季度订单指引。"],
    }


def test_analysis_valid() -> None:
    ok, errors = validate("event_analysis_v1", valid_analysis(), SECTORS)
    assert ok, errors


def test_analysis_missing_uncertainty_rejected() -> None:
    data = valid_analysis()
    data["uncertainty"] = []  # 不确定声明必填 —— 认知边界纪律
    ok, _ = validate("event_analysis_v1", data, SECTORS)
    assert not ok


def test_analysis_missing_top_field() -> None:
    data = valid_analysis()
    del data["causal_chain"]
    ok, errors = validate("event_analysis_v1", data, SECTORS)
    assert not ok and any("causal_chain" in e for e in errors)


def test_analysis_type_error() -> None:
    data = valid_analysis()
    data["summary"] = 12345  # 类型错
    ok, _ = validate("event_analysis_v1", data, SECTORS)
    assert not ok


def test_analysis_hallucinated_industry() -> None:
    data = valid_analysis()
    data["affected_industries"] = ["quantum_bio"]
    ok, _ = validate("event_analysis_v1", data, SECTORS)
    assert not ok


def test_analysis_follow_up_bounds() -> None:
    data = valid_analysis()
    data["follow_up_questions"] = ["a"] * 5  # 上限 3
    ok, _ = validate("event_analysis_v1", data, SECTORS)
    assert not ok


# ---------------- daily_summary_v1 ----------------


def test_daily_summary_valid_and_invalid() -> None:
    ok, _ = validate("daily_summary_v1", {
        "summary": "三大行业无系统性变化。",
        "highlights": [{"event_id": EID, "point": "算力催化"}],
        "tomorrow_watch": ["关注业绩指引"],
    }, SECTORS)
    assert ok
    ok2, _ = validate("daily_summary_v1", {"summary": "x", "highlights": [], "tomorrow_watch": []}, SECTORS)
    assert not ok2


# ---------------- schema injection ----------------


def test_sector_injection_replaces_placeholder() -> None:
    schema = load_schema("classification_v1", ["foo_sector"])
    text = json.dumps(schema)
    assert "__SECTORS__" not in text and "foo_sector" in text


# ---------------- thesis_review_v1 (V0.2) ----------------

THESES = ["ai-demand-growth", "power-infrastructure"]


def valid_thesis_review() -> dict:
    return {
        "thesis_id": "ai-demand-growth",
        "direction": "supporting",
        "evidence": [
            {"text": "云厂商上调资本开支指引。", "source_event_id": EID,
             "direction": "supporting", "weight": "strong"},
        ],
        "falsification_triggered": {"triggered": False, "condition_id": None, "reason": "无证伪信号"},
        "note": "今日信息与假设方向一致，需求侧信号积极。",
        "next_questions": ["跟踪下季度 CAPEX 指引"],
    }


def test_thesis_review_valid() -> None:
    ok, errors = validate("thesis_review_v1", valid_thesis_review(), SECTORS, THESES)
    assert ok, errors


def test_thesis_review_hallucinated_thesis_id_rejected() -> None:
    payload = valid_thesis_review()
    payload["thesis_id"] = "made-up-thesis"
    ok, _ = validate("thesis_review_v1", payload, SECTORS, THESES)
    assert not ok  # 枚举外 thesis id = 幻觉，打回


def test_thesis_review_bad_direction_rejected() -> None:
    payload = valid_thesis_review()
    payload["direction"] = "buy"  # 评分/买卖类输出在 schema 层即拒绝
    ok, _ = validate("thesis_review_v1", payload, SECTORS, THESES)
    assert not ok


def test_thesis_review_empty_evidence_ok_on_quiet_day() -> None:
    payload = valid_thesis_review()
    payload["direction"] = "neutral"
    payload["evidence"] = []
    ok, _ = validate("thesis_review_v1", payload, SECTORS, THESES)
    assert ok


def test_thesis_review_missing_falsification_block_rejected() -> None:
    payload = valid_thesis_review()
    del payload["falsification_triggered"]
    ok, _ = validate("thesis_review_v1", payload, SECTORS, THESES)
    assert not ok


def test_thesis_injection_replaces_placeholder() -> None:
    schema = load_schema("thesis_review_v1", None, ["my-thesis"])
    text = json.dumps(schema)
    assert "__THESES__" not in text and "my-thesis" in text


# ---------------- market_review_v1 / industry_update_v1 (V0.3) ----------------


def test_market_review_valid() -> None:
    ok, errors = validate("market_review_v1", {
        "market_summary": "指数放量上行，成长风格占优，板块与事件互相印证。",
        "sector_moves": [{"sector": "半导体", "direction": "up", "note": "订单催化"}],
        "style_note": "量能温和放大。",
        "risk_flags": ["缩量回落风险"],
        "tomorrow_watch": ["关注算力板块持续性"],
    }, SECTORS)
    assert ok, errors


def test_market_review_bad_direction_rejected() -> None:
    ok, _ = validate("market_review_v1", {
        "market_summary": "x" * 10, "sector_moves": [{"sector": "半导体", "direction": "side", "note": "n"}],
        "style_note": "style", "risk_flags": [], "tomorrow_watch": ["w"],
    }, SECTORS)
    assert not ok


def test_industry_update_valid_and_bad_section() -> None:
    payload = {
        "sections": [
            {"name": "overview", "content": "行业景气上行。", "changed": True, "based_on_event_ids": [EID]},
            {"name": "metrics", "content": "（待首次更新）", "changed": False},
        ],
        "changelog_rows": [{"change": "催化剂增强", "evidence_event_id": EID}],
    }
    ok, errors = validate("industry_update_v1", payload, SECTORS)
    assert ok, errors
    payload["sections"][0]["name"] = "changelog"  # LLM 不允许动 changelog 节
    ok2, _ = validate("industry_update_v1", payload, SECTORS)
    assert not ok2
