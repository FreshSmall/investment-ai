"""Idempotency Test（指令十五）：`daily` 连跑两次 + force 重跑，多级零重复断言。

使用 main._steps() 生产步骤序列（V0.2 起含 company_impact/thesis_review），
并预置 theses+companies 种子，覆盖 Thesis 链路的幂等语义。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path

import pytest

from tests.conftest import _clean_tables, make_db_session, make_pipeline_ctx


@pytest.fixture()
def idem_env(tmp_path):
    session = make_db_session()
    ctx = make_pipeline_ctx(session, tmp_path, frozen_time=datetime(2026, 9, 17, 20, 0))
    from app.db.seed import seed_companies, seed_theses

    seed_theses(session)
    seed_companies(session)
    yield ctx
    ctx.restore_clock()
    _clean_tables(session)
    session.close()


def _run_pipeline(ctx, force: bool = False):
    from main import _steps
    from app.pipeline.orchestrator import Orchestrator

    ctx.run_id = uuid.uuid4().hex
    return Orchestrator(_steps()).run_daily(ctx, force=force)


def _db_counts(ctx):
    from app.db.models import AnalysisRow, EventRow, ReportRow, RunRow, ThesisEvidenceRow

    s = ctx.repo._s
    return {
        "events": s.query(EventRow).count(),
        "analyses": s.query(AnalysisRow).count(),
        "reports": s.query(ReportRow).count(),
        "runs": s.query(RunRow).count(),
        "evidence": s.query(ThesisEvidenceRow).count(),
    }


def test_daily_twice_full_idempotency(idem_env) -> None:
    ctx = idem_env
    first = _run_pipeline(ctx)
    assert first.status.value == "success"
    counts1 = _db_counts(ctx)
    llm_calls1 = ctx.mock_llm.call_count()
    report1 = (ctx.vault_path / "Daily" / "2026-09-17.md").read_text(encoding="utf-8")
    assert counts1["evidence"] >= 1  # thesis 链路确实跑过
    # 首跑各策略调用量快照（相对断言基准，不依赖 fixtures 行业分布）
    event_scoped = ("classification", "event_analysis", "company_impact")
    refresh_scoped = ("daily_summary", "market_review", "thesis_review", "industry_update")
    snap1 = {s: ctx.mock_llm.call_count(s) for s in event_scoped + refresh_scoped}
    assert snap1["market_review"] == 1 and snap1["thesis_review"] == 4

    second = _run_pipeline(ctx)
    assert second.status.value == "skipped"
    assert _db_counts(ctx) == counts1
    assert ctx.mock_llm.call_count() == llm_calls1  # LLM 零调用
    assert (ctx.vault_path / "Daily" / "2026-09-17.md").read_text(encoding="utf-8") == report1

    third = _run_pipeline(ctx, force=True)
    assert third.status.value == "success"
    assert third.stats["events_new"] == 0
    counts3 = _db_counts(ctx)
    assert counts3["events"] == counts1["events"]
    assert counts3["analyses"] == counts1["analyses"]  # refresh 策略原地更新不加行
    assert counts3["reports"] == counts1["reports"]  # upsert 不重复
    assert counts3["evidence"] == counts1["evidence"]  # 联合主键 upsert，证据零重复
    # 事件级策略（UNIQUE 缓存）调用数不变；refresh 策略恰好翻倍
    for s in event_scoped:
        assert ctx.mock_llm.call_count(s) == snap1[s], s
    for s in refresh_scoped:
        assert ctx.mock_llm.call_count(s) == snap1[s] * 2, s
    assert (ctx.vault_path / "Daily" / "2026-09-17.md").read_text(encoding="utf-8") == report1
