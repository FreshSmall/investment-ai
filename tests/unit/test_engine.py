from __future__ import annotations

from typing import Optional

from app.analysis.engine import AnalysisEngine
from app.core.config import AppCfg, LlmCfg, ModelTierCfg, PipelineCfg, load_sectors
from app.providers.llm.mock import MockLLMProvider
from app.providers.llm.openai_compat import BudgetGuard

SECTORS = load_sectors()
EID = "addf091f74bca86a"


def make_cfg() -> AppCfg:
    return AppCfg(
        pipeline=PipelineCfg(),
        llm=LlmCfg(
            tiers={
                "L1": ModelTierCfg(model="mock-flash", temperature=0.1, max_tokens=1000),
                "L2": ModelTierCfg(model="mock-pro", temperature=0.3, max_tokens=2500),
            }
        ),
    )


class FakeRow:
    def __init__(self, id_: int, result: dict) -> None:
        self.id = id_
        self.result_json = result


class FakeRepo:
    def __init__(self) -> None:
        self.store = {}
        self._next = 1

    def get_analysis_for_event(self, event_id, strategy):
        return self.store.get((event_id, strategy))

    def save_analysis(self, strategy, model, prompt_version, result, event_id=None, report_date=None, **kw):
        key = (event_id, strategy)
        if key in self.store:
            return self.store[key].id, False
        row = FakeRow(self._next, result)
        self._next += 1
        self.store[key] = row
        return row.id, True


def make_engine(llm: MockLLMProvider, budget_cny: float = 10.0):
    repo = FakeRepo()
    guard = BudgetGuard(budget_cny)
    engine = AnalysisEngine(llm=llm, repo=repo, sectors=SECTORS, app_cfg=make_cfg(), budget=guard)
    return engine, repo, guard


def event_ctx() -> dict:
    return {
        "sector_keys": SECTORS.keys(),
        "event": {"event_id": EID, "title": "HBM 涨价", "published_at": "2026-09-17 09:32", "content": "正文"},
        "history": [],
    }


def test_success_path_persists_with_tokens() -> None:
    llm = MockLLMProvider()
    engine, repo, _ = make_engine(llm)
    outcome = engine.run("event_analysis", prompt_ctx=event_ctx(), allowed_event_ids={EID}, event_id=EID)
    assert outcome.ok and outcome.result is not None
    assert outcome.analysis_id == 1
    assert outcome.input_tokens > 0
    assert (EID, "event_analysis") in repo.store


def test_bad_json_retried_once_then_success() -> None:
    good = {
        "summary": "算力产业链出现需求侧重要边际变化，信号强于预期。",
        "facts": [{"text": "公司公告新增产能。", "source_event_id": EID}],
        "interpretations": ["产能扩张反映信心。"],
        "hypotheses": ["供需两季度内趋紧。"],
        "affected_industries": ["ai_semiconductor"],
        "affected_companies": [{"name": "示例公司", "code": None, "channel": "订单弹性"}],
        "causal_chain": ["算力需求", "订单"],
        "supporting_evidence": [{"text": "客户追加订单。", "source_event_id": EID}],
        "counter_evidence": [{"text": "同业扩产。", "source_event_id": EID}],
        "uncertainty": ["落地节奏未验证。"],
        "follow_up_questions": ["跟踪订单指引。"],
    }
    llm = MockLLMProvider(overrides={"event_analysis": ["垃圾输出不是JSON", good]})
    engine, _, _ = make_engine(llm)
    outcome = engine.run("event_analysis", prompt_ctx=event_ctx(), allowed_event_ids={EID}, event_id=EID)
    assert outcome.ok, outcome.error_kind
    assert llm.call_count("event_analysis") == 2  # 重试发生
    assert "上一次输出未通过校验" in llm.calls[-1].user  # 错误回喂


def test_two_bad_outputs_parse_error() -> None:
    llm = MockLLMProvider(overrides={"event_analysis": ["坏的一", "坏的二"]})
    engine, _, _ = make_engine(llm)
    outcome = engine.run("event_analysis", prompt_ctx=event_ctx(), allowed_event_ids={EID}, event_id=EID)
    assert not outcome.ok and outcome.error_kind == "parse_error"


def test_fenced_bad_then_good_recovered_without_retry() -> None:
    fenced = "```json\n{\"summary\": \"算力产业链出现需求侧重要边际变化，信号强于预期。\", \"facts\": [{\"text\": \"公告新增产能。\", \"source_event_id\": \"%s\"}], \"interpretations\": [\"产能扩张反映信心。\"], \"hypotheses\": [\"供需趋紧。\"], \"affected_industries\": [\"ai_semiconductor\"], \"affected_companies\": [], \"causal_chain\": [\"需求\", \"订单\"], \"supporting_evidence\": [{\"text\": \"客户追加订单。\", \"source_event_id\": \"%s\"}], \"counter_evidence\": [], \"uncertainty\": [\"节奏未验证。\"], \"follow_up_questions\": [\"跟踪指引。\"]}\n```" % (EID, EID)
    llm = MockLLMProvider(overrides={"event_analysis": [fenced]})
    engine, _, _ = make_engine(llm)
    outcome = engine.run("event_analysis", prompt_ctx=event_ctx(), allowed_event_ids={EID}, event_id=EID)
    assert outcome.ok  # 栅栏在 parse 层恢复，不计失败不重试
    assert llm.call_count("event_analysis") == 1


def test_hallucinated_reference_scrubbed() -> None:
    llm = MockLLMProvider()  # 默认响应引用输入 EID —— 先构造幻觉版本
    hallucinated = dict(llm_complete_default(EID, "deadbeefdeadbeef"))
    llm2 = MockLLMProvider(overrides={"event_analysis": [hallucinated]})
    engine, _, _ = make_engine(llm2)
    outcome = engine.run("event_analysis", prompt_ctx=event_ctx(), allowed_event_ids={EID}, event_id=EID)
    assert outcome.ok
    assert any("deadbeefdeadbeef" in w for w in outcome.warnings)
    # 幻觉引用的条目被整体剔除
    assert all(f["source_event_id"] == EID for f in outcome.result["facts"])


def llm_complete_default(valid_id: str, fake_id: str) -> dict:
    from app.providers.llm.mock import _EVENT_ANALYSIS_TEMPLATE

    payload = dict(_EVENT_ANALYSIS_TEMPLATE)
    payload["facts"] = [
        {"text": "有效引用的事实。", "source_event_id": valid_id},
        {"text": "幻觉引用的事实。", "source_event_id": fake_id},
    ]
    return payload


def test_budget_exceeded_short_circuits() -> None:
    llm = MockLLMProvider()
    engine, repo, guard = make_engine(llm, budget_cny=0.0001)
    guard.add(1.0)  # 预先超限
    outcome = engine.run("event_analysis", prompt_ctx=event_ctx(), allowed_event_ids={EID}, event_id=EID)
    assert not outcome.ok and outcome.error_kind == "budget_exceeded"
    assert llm.call_count() == 0


def test_cached_outcome_no_llm_call() -> None:
    llm = MockLLMProvider()
    engine, repo, _ = make_engine(llm)
    engine.run("event_analysis", prompt_ctx=event_ctx(), allowed_event_ids={EID}, event_id=EID)
    llm2 = MockLLMProvider()
    # 复用同一 repo：第二次同 event+strategy 命中缓存
    from app.providers.llm.openai_compat import BudgetGuard

    engine2 = AnalysisEngine(llm=llm2, repo=repo, sectors=SECTORS, app_cfg=make_cfg(), budget=BudgetGuard(10))
    outcome = engine2.run("event_analysis", prompt_ctx=event_ctx(), allowed_event_ids={EID}, event_id=EID)
    assert outcome.cached and llm2.call_count() == 0


def test_classification_flow() -> None:
    llm = MockLLMProvider()
    engine, _, _ = make_engine(llm)
    ctx = {
        "sector_keys": SECTORS.keys(),
        "events": [{"event_id": EID, "title": "GPU", "content_head": "x"},
                   {"event_id": "dead00000000beef", "title": "电网", "content_head": "y"}],
    }
    outcome = engine.run(
        "classification",
        prompt_ctx=ctx,
        allowed_event_ids={EID, "dead00000000beef"},
    )
    assert outcome.ok
    ids = [r["event_id"] for r in outcome.result["results"]]
    assert set(ids) == {EID, "dead00000000beef"}
