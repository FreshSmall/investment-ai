"""Idempotency Test（指令十五）：`daily` 连跑两次 + force 重跑，四级零重复断言。"""

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
    yield ctx
    ctx.restore_clock()
    _clean_tables(session)
    session.close()


def _run_pipeline(ctx, force: bool = False):
    from app.pipeline.orchestrator import Orchestrator
    from app.pipeline.steps.analyze import AnalyzeStep
    from app.pipeline.steps.classify import ClassifyStep
    from app.pipeline.steps.collect import CollectStep
    from app.pipeline.steps.normalize import IngestStep
    from app.pipeline.steps.report import ReportStep

    ctx.run_id = uuid.uuid4().hex
    return Orchestrator([CollectStep(), IngestStep(), ClassifyStep(), AnalyzeStep(), ReportStep()]).run_daily(
        ctx, force=force
    )


def _db_counts(ctx):
    from app.db.models import AnalysisRow, EventRow, ReportRow, RunRow

    s = ctx.repo._s
    return {
        "events": s.query(EventRow).count(),
        "analyses": s.query(AnalysisRow).count(),
        "reports": s.query(ReportRow).count(),
        "runs": s.query(RunRow).count(),
    }


def test_daily_twice_full_idempotency(idem_env) -> None:
    ctx = idem_env
    first = _run_pipeline(ctx)
    assert first.status.value == "success"
    counts1 = _db_counts(ctx)
    llm_calls1 = ctx.mock_llm.call_count()
    report1 = (ctx.vault_path / "Daily" / "2026-09-17.md").read_text(encoding="utf-8")

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
    assert counts3["analyses"] == counts1["analyses"]  # 含 daily_summary：refresh 为原地更新不加行
    assert counts3["reports"] == counts1["reports"]  # upsert 不重复
    # 事件级分析零新调用（UNIQUE 缓存）；唯 daily_summary 按每日两次运行的 refresh 语义 +1
    assert ctx.mock_llm.call_count("daily_summary") == 2  # 首跑 1 + force 1
    total_now = ctx.mock_llm.call_count()
    assert total_now == llm_calls1 + 1  # 恰好多一次综述，事件分析零新增
    assert (ctx.vault_path / "Daily" / "2026-09-17.md").read_text(encoding="utf-8") == report1
