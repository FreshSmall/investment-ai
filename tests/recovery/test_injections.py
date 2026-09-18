"""Failure Recovery Test（指令十五）：架构 §12.3 场景逐一可执行化。"""

from __future__ import annotations

import uuid
from datetime import date, datetime

import pytest

from tests.conftest import _clean_tables, make_db_session, make_pipeline_ctx


class BrokenProvider:
    """模拟整源不可用（fetch 永远抛错）。"""

    name = "broken-source"

    def health_check(self) -> bool:
        return True

    def fetch(self, since):
        from app.providers.base import ProviderError

        raise ProviderError("模拟源 404")


@pytest.fixture()
def rec_env(tmp_path):
    session = make_db_session()
    ctx = make_pipeline_ctx(session, tmp_path, frozen_time=datetime(2026, 9, 17, 20, 0))
    yield ctx
    ctx.restore_clock()
    _clean_tables(session)
    session.close()


def _run(ctx, force=True):
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


def test_scene1_single_source_failure_degrades(rec_env) -> None:
    """§12.3 场景：财联社 404 → 降级东财，流程 success。"""
    ctx = rec_env
    ctx.news_providers = [BrokenProvider()] + ctx.news_providers
    summary = _run(ctx)
    assert summary.status.value == "success"
    assert "broken-source" in summary.stats["degraded_sources"]
    assert summary.stats["events_new"] == 9  # 正常源不受影响


def test_scene2_all_sources_fail_calm_report(rec_env) -> None:
    ctx = rec_env
    ctx.news_providers = [BrokenProvider()]
    summary = _run(ctx)
    assert summary.status.value == "success"  # 单源全失败也不是系统失败
    assert summary.stats["events_fetched"] == 0
    assert (ctx.vault_path / "Daily" / "2026-09-17.md").exists()  # 平静日报告照出


def test_scene3_db_unreachable_fast_exit(rec_env) -> None:
    from sqlalchemy.exc import OperationalError

    class DeadRepo:
        def __getattr__(self, item):
            def boom(*a, **kw):
                raise OperationalError("stmt", {}, Exception("connection refused"))

            return boom

    ctx = rec_env
    ctx.repo = DeadRepo()  # type: ignore[assignment]
    summary = _run(ctx)
    assert summary.status.value == "db_unreachable"
    assert "events_fetched" not in summary.stats  # 步骤零执行


def test_scene4_vault_write_failure_partial_and_db_kept(rec_env, tmp_path) -> None:
    """vault 被占/锁死 → run=partial、DB 不回滚、报告错误可见。"""
    ctx = rec_env
    ctx.vault_path = tmp_path / "occupied.md"  # 一个文件路径 → mkdir 必然失败
    ctx.vault_path.write_text("i am a file", encoding="utf-8")
    summary = _run(ctx)
    assert summary.status.value == "partial"
    assert "report" in summary.failed_steps
    assert "report_error" in summary.stats
    from app.db.models import EventRow

    assert ctx.repo._s.query(EventRow).count() == 9  # DB 数据完好（不回滚）


def test_scene5_budget_hit_degrades_but_report_runs(rec_env) -> None:
    """预算熔断：L2 分析顺延，日报照常产出。

    BudgetGuard(0) 语义：首批免费(mock cost=0)调用后 add(0)>=0 即置 exceeded——
    后续所有 LLM 调用熔断。因此分类只完成首个批次（动态取 batch_size），分析全顺延。
    """
    from app.providers.llm.openai_compat import BudgetGuard

    ctx = rec_env
    ctx.engine._budget = BudgetGuard(0.0)  # 0 预算立即熔断
    summary = _run(ctx)
    assert summary.stats.get("budget_hit") is True
    assert summary.stats["events_analyzed"] == 0
    assert summary.stats["events_classified"] == ctx.app_cfg.pipeline.classify_batch_size  # 仅首批逃过熔断门
    assert (ctx.vault_path / "Daily" / "2026-09-17.md").exists()
    assert summary.status.value == "success"


def test_scene6_llm_provider_error_retry_next_run(rec_env) -> None:
    """provider 错误 → 事件保持 classified，下一轮好 LLM 断点续跑。"""
    ctx = rec_env
    from app.pipeline.steps.collect import CollectStep
    from app.pipeline.steps.normalize import IngestStep
    from app.pipeline.steps.classify import ClassifyStep

    CollectStep().run(ctx)
    IngestStep().run(ctx)
    ClassifyStep().run(ctx)

    # 注入 provider 级失败（区别于 parse_error：可恢复）
    p0p1 = ctx.repo._s.execute(
        __import__("sqlalchemy").text(
            "SELECT COUNT(*) FROM events WHERE status='classified' AND importance IN ('P0','P1')"
        )
    ).scalar()
    # 注入 provider 级失败（engine 对 provider 错误重试 1 次 → 每事件消耗 2 个注入）
    ctx.mock_llm._overrides["event_analysis"] = [{"__error__": "transport: timeout"}] * (p0p1 * 2)

    from app.pipeline.steps.analyze import AnalyzeStep

    stats = AnalyzeStep().run(ctx).stats
    assert stats["analyze_retry_later"] == p0p1 and stats["events_analyzed"] == 0

    # 第二轮：LLM 恢复 → 断点补齐
    ctx.mock_llm._overrides.pop("event_analysis", None)
    stats2 = AnalyzeStep().run(ctx).stats
    assert stats2["events_analyzed"] == p0p1
