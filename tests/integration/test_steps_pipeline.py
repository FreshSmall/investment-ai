"""Integration tests for S1~S9 steps (TASK-018~021) on the real test DB with mocks."""

from __future__ import annotations

import json

from app.db.models import EventRow, ReportRow
from app.domain.event import EventStatus
from app.pipeline.steps.analyze import AnalyzeStep
from app.pipeline.steps.classify import ClassifyStep
from app.pipeline.steps.collect import CollectStep
from app.pipeline.steps.normalize import IngestStep
from app.pipeline.steps.report import ReportStep


def run_collect_ingest(ctx) -> dict:
    c = CollectStep().run(ctx)
    i = IngestStep().run(ctx)
    return {**c.stats, **i.stats}


def test_collect_and_ingest_full_flow(pipeline_ctx) -> None:
    ctx = pipeline_ctx
    stats = run_collect_ingest(ctx)
    assert stats["events_fetched"] == 11        # 12 fixtures - 1 坏时间戳
    assert stats["events_l0_filtered"] == 1     # 饮料新闻
    assert stats["events_deduplicated"] == 1    # 跨源同文（eastmoney/2001 vs cls/1001）
    assert stats["events_new"] == 9
    rows = ctx.repo.get_events_for_classify()
    assert len(rows) == 9


def test_ingest_rerun_zero_new(pipeline_ctx) -> None:
    ctx = pipeline_ctx
    run_collect_ingest(ctx)
    second = IngestStep().run(ctx)  # 同一批 raw_events 再次入库
    assert second.stats["events_new"] == 0
    assert second.stats["events_deduplicated"] == 10  # 9 条 (source,source_id) + 1 条跨源同文 hash


def test_classify_step_assigns_importance(pipeline_ctx) -> None:
    ctx = pipeline_ctx
    run_collect_ingest(ctx)
    stats = ClassifyStep().run(ctx).stats
    assert stats["events_classified"] == 9
    assert sum(stats["by_importance"].values()) == 9
    # P3 归档：mock 轮换表第 4 项是 P3（9 条 → 至少 2 条 P3）
    assert stats["by_importance"].get("P3", 0) >= 2
    archived = ctx.repo.get_events_for_classify()  # raw/unclassified 不应存在
    assert archived == []
    session = ctx.repo._s
    n_archived = session.query(EventRow).filter_by(status=EventStatus.ARCHIVED.value).count()
    assert n_archived == stats["by_importance"]["P3"]


def test_classify_rerun_no_work(pipeline_ctx) -> None:
    ctx = pipeline_ctx
    run_collect_ingest(ctx)
    ClassifyStep().run(ctx)
    again = ClassifyStep().run(ctx)
    assert again.stats["events_classified"] == 0


def test_analyze_step_processes_p0_p1(pipeline_ctx) -> None:
    ctx = pipeline_ctx
    run_collect_ingest(ctx)
    cstats = ClassifyStep().run(ctx).stats
    expected = cstats["by_importance"].get("P0", 0) + cstats["by_importance"].get("P1", 0)

    stats = AnalyzeStep().run(ctx).stats
    assert stats["events_analyzed"] == expected
    assert ctx.mock_llm.call_count("event_analysis") == expected
    # 重跑：全部已分析 → 零调用（幂等）
    again = AnalyzeStep().run(ctx)
    assert again.stats["events_analyzed"] == 0


def test_analyze_parse_error_terminal_state(pipeline_ctx, monkeypatch) -> None:
    ctx = pipeline_ctx
    run_collect_ingest(ctx)
    cstats = ClassifyStep().run(ctx).stats
    p0p1 = cstats["by_importance"].get("P0", 0) + cstats["by_importance"].get("P1", 0)

    # 注入：每个事件前两次响应都是坏 JSON
    ctx.mock_llm._overrides["event_analysis"] = ["坏的一", "坏的二"] * p0p1
    stats = AnalyzeStep().run(ctx).stats
    assert stats["parse_errors"] == p0p1
    session = ctx.repo._s
    assert session.query(EventRow).filter_by(status=EventStatus.PARSE_ERROR.value).count() == p0p1
    # parse_error 是终态：重跑不再取这些事件
    again = AnalyzeStep().run(ctx).stats
    assert again["events_analyzed"] == 0 and again["parse_errors"] == 0


def test_report_step_writes_vault_and_db(pipeline_ctx) -> None:
    ctx = pipeline_ctx
    run_collect_ingest(ctx)
    ClassifyStep().run(ctx)
    AnalyzeStep().run(ctx)
    stats = ReportStep().run(ctx).stats

    assert stats["daily_summary_ok"] is True
    path = ctx.vault_path / "Daily" / "2026-09-17.md"
    assert path.exists()
    content = path.read_text(encoding="utf-8")
    assert "Daily Research — 2026-09-17" in content
    assert "来源: cls" in content and "event:" in content  # 溯源脚注
    assert (ctx.vault_path / "Home.md").exists()
    # 骨架三行业
    for f in ("AI-Semiconductor.md", "Power-Energy.md", "Robotics.md"):
        assert (ctx.vault_path / "Industries" / f).exists()

    session = ctx.repo._s
    reports = session.query(ReportRow).all()
    assert len(reports) == 1 and reports[0].type == "daily"


def test_report_calm_day(pipeline_ctx) -> None:
    ctx = pipeline_ctx
    stats = ReportStep().run(ctx).stats  # 无任何事件
    content = (ctx.vault_path / "Daily" / "2026-09-17.md").read_text(encoding="utf-8")
    assert "平静日" in content
    assert stats["report_events"] == 0


def test_report_rerun_deterministic_and_cached(pipeline_ctx) -> None:
    ctx = pipeline_ctx
    run_collect_ingest(ctx)
    ClassifyStep().run(ctx)
    AnalyzeStep().run(ctx)
    ReportStep().run(ctx)
    first = (ctx.vault_path / "Daily" / "2026-09-17.md").read_text(encoding="utf-8")
    calls_before = ctx.mock_llm.call_count("daily_summary")

    ReportStep().run(ctx)
    second = (ctx.vault_path / "Daily" / "2026-09-17.md").read_text(encoding="utf-8")
    assert first == second  # 字节级一致（渲染确定性）
    assert ctx.mock_llm.call_count("daily_summary") == calls_before  # aggregate 缓存命中
    session = ctx.repo._s
    assert session.query(ReportRow).count() == 1  # upsert 不重复
