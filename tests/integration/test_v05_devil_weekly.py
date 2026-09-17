"""V0.5 集成测试：DevilAdvocateStep（weak 上限）+ weekly 命令端到端。"""

from __future__ import annotations

from datetime import datetime

from app.db.repository import Repository
from app.db.seed import seed_theses
from app.domain.event import EventStatus, NormalizedEvent, make_event_id


def _p0(repo: Repository, source_id: str, title: str, sector: str) -> None:
    ev = NormalizedEvent(
        source="cls", source_id=source_id, title=title, content=title + "：需求信号积极。",
        url=None, published_at=datetime(2026, 9, 17, 10, 0), collected_at=datetime(2026, 9, 17, 20, 0),
        raw={}, norm_title=title, norm_content=title,
    )
    repo.upsert_events([ev])
    row = repo.get_event(make_event_id("cls", source_id))
    repo.mark_classified(row.id, [sector], "catalyst", "P0")
    repo.mark_event_status(row.id, EventStatus.ANALYZED)
    repo.save_analysis(
        strategy="event_analysis", model="mock", prompt_version="v1",
        result={"summary": "需求信号积极。", "causal_chain": ["需求", "订单"], "uncertainty": ["x"],
                "facts": [], "affected_industries": [sector]},
        event_id=row.id,
    )


def test_devil_advocate_weak_cap_and_daily_board(pipeline_ctx) -> None:
    from app.db.models import AnalysisRow
    from app.pipeline.steps.devil_advocate import DevilAdvocateStep
    from app.pipeline.steps.report import ReportStep
    from app.pipeline.steps.thesis_review import ThesisReviewStep

    ctx = pipeline_ctx
    seed_theses(ctx.repo._s)
    _p0(ctx.repo, "da-1", "AI 服务器资本开支上调，算力需求超预期", "ai_semiconductor")
    _p0(ctx.repo, "da-2", "电网投资加码，变压器招标放量", "power_energy")

    # thesis_review 先行（产出 supporting 证据，devil 消费）
    ThesisReviewStep().run(ctx)
    res = DevilAdvocateStep().run(ctx)
    assert res.ok and res.stats["theses_advocated"] >= 1

    # devil 产出在 analyses 表（不落 thesis_evidence——其主键无法表达同一事件双向解读）
    devil_rows = ctx.repo._s.query(AnalysisRow).filter(AnalysisRow.strategy == "devil_advocate").all()
    assert len(devil_rows) >= 1
    assert all(
        cp.get("text", "").startswith("【") for r in devil_rows for cp in (r.result_json.get("counter_points") or [])
    )
    # day_direction 不被反方推演翻转（weak 不参与，仍是 supporting）
    assert ctx.repo.day_direction("ai-demand-growth", ctx.report_date) == "supporting"

    # 日报反方板块 + Thesis 文件反证合并渲染
    ReportStep().run(ctx)
    daily = (ctx.vault_path / "Daily" / "2026-09-17.md").read_text(encoding="utf-8")
    assert "## 🔱 反方视角" in daily
    assert "mock 反方小结" in daily
    thesis_md = (ctx.vault_path / "Theses" / "ai-demand-growth.md").read_text(encoding="utf-8")
    assert "（弱）" in thesis_md  # 反证以 weak 渲染进"反方证据"节


def test_weekly_command_end_to_end(pipeline_ctx) -> None:
    from app.report.weekly import generate_weekly, week_bounds
    from app.db.models import ReportRow

    ctx = pipeline_ctx
    seed_theses(ctx.repo._s)
    _p0(ctx.repo, "wk-1", "AI 服务器资本开支上调", "ai_semiconductor")

    start, end, label = week_bounds(ctx.report_date)
    assert label == "2026-W38"

    path = generate_weekly(ctx.engine, ctx.repo, ctx.vault_path, ctx.report_date)
    assert path is not None and path.name == "2026-W38.md"
    text = path.read_text(encoding="utf-8")
    assert "# Weekly Review — 2026-W38" in text
    assert "mock 周度综述" in text
    assert "Thesis 证据分布" in text
    assert ctx.repo._s.query(ReportRow).filter(ReportRow.type == "weekly").count() == 1

    # 幂等：再次生成不调 LLM（缓存命中），文件仍存在
    calls = ctx.mock_llm.call_count("weekly_review")
    path2 = generate_weekly(ctx.engine, ctx.repo, ctx.vault_path, ctx.report_date)
    assert path2 is not None
    assert ctx.mock_llm.call_count("weekly_review") == calls

    # --force 重新生成（refresh 语义）
    path3 = generate_weekly(ctx.engine, ctx.repo, ctx.vault_path, ctx.report_date, force=True)
    assert path3 is not None and path3.read_text(encoding="utf-8") == path.read_text(encoding="utf-8")
