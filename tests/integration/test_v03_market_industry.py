"""V0.3 集成测试：MarketStep（快照幂等 + 复盘）与 IndustryUpdateStep（节级更新幂等）。"""

from __future__ import annotations

import json
from datetime import datetime

from app.db.repository import Repository
from app.domain.event import EventStatus, NormalizedEvent, make_event_id


def _p0_event(source_id: str, title: str, sector: str) -> NormalizedEvent:
    return NormalizedEvent(
        source="cls", source_id=source_id, title=title, content=title + "：订单与产能信号积极。",
        url=None, published_at=datetime(2026, 9, 17, 10, 0), collected_at=datetime(2026, 9, 17, 20, 0),
        raw={}, norm_title=title, norm_content=title,
    )


def _seed_ai_event(repo: Repository) -> None:
    """一条 ai_semiconductor P0 已分析事件（驱动 market/industry 两个步骤）。"""
    repo.upsert_events([_p0_event("mk-1", "AI 服务器订单超预期，光模块需求上修", "ai")])
    ev = repo.get_event(make_event_id("cls", "mk-1"))
    repo.mark_classified(ev.id, ["ai_semiconductor"], "order_demand", "P0")
    repo.mark_event_status(ev.id, EventStatus.ANALYZED)
    repo.save_analysis(
        strategy="event_analysis", model="mock", prompt_version="v1",
        result={"summary": "订单上修，需求信号强。", "causal_chain": ["算力需求", "光模块订单"],
                "uncertainty": ["持续性待验证"], "facts": [], "affected_industries": ["ai_semiconductor"]},
        event_id=ev.id,
    )
    return ev.id


def test_market_step_snapshot_idempotent_and_review(pipeline_ctx) -> None:
    from app.db.models import DailySnapshotRow
    from app.pipeline.steps.market import MarketStep

    ctx = pipeline_ctx
    _seed_ai_event(ctx.repo)

    res = MarketStep().run(ctx)
    assert res.ok
    assert res.stats["market_snapshot"] is True
    assert res.stats["market_review_ok"] is True
    assert ctx.repo._s.query(DailySnapshotRow).count() == 1

    # 重跑：快照 upsert 不加行；market_review 为 refresh 语义（原地更新）
    MarketStep().run(ctx)
    assert ctx.repo._s.query(DailySnapshotRow).count() == 1
    from app.db.models import AnalysisRow

    assert ctx.repo._s.query(AnalysisRow).filter(AnalysisRow.strategy == "market_review").count() == 1

    # 快照读取 API
    snap = ctx.repo.get_snapshot(ctx.report_date)
    assert snap["indices"][0]["name"] == "上证指数"
    assert ctx.repo.get_prev_snapshot(ctx.report_date) is None  # 无历史快照


def test_market_step_provider_failure_degrades(pipeline_ctx) -> None:
    from app.pipeline.steps.market import MarketStep

    ctx = pipeline_ctx

    class BrokenProvider:
        name = "broken"

        def fetch_daily(self, trade_date):
            raise RuntimeError("connection refused")

    ctx.market_provider = BrokenProvider()
    res = MarketStep().run(ctx)
    assert res.ok  # 降级不阻塞
    assert res.stats["market_snapshot"] is False
    assert "market_error" in res.stats


def test_industry_update_step_updates_only_hit_sectors(pipeline_ctx) -> None:
    from app.knowledge.updater import industry_path
    from app.pipeline.steps.industry_update import IndustryUpdateStep

    ctx = pipeline_ctx
    _seed_ai_event(ctx.repo)

    # 首建骨架（生产由 report 步骤的 ensure_skeletons 保证；这里显式建）
    from app.knowledge.renderer import ensure_skeletons

    theses = [
        {"id": t.id, "title": t.title, "core_hypothesis": t.core_hypothesis,
         "falsification_conditions": t.falsification_conditions, "key_metrics": t.key_metrics,
         "status": t.status}
        for t in ctx.repo.list_theses()
    ]
    ensure_skeletons(ctx.vault_path, ctx.sectors, theses)

    res = IndustryUpdateStep().run(ctx)
    assert res.ok
    assert res.stats["industries_updated"] == 1  # 只有 ai_semiconductor 有事件
    assert res.stats["sections_changed"] >= 1

    ai_file = industry_path(ctx.vault_path, "ai_semiconductor", ctx.sectors).read_text(encoding="utf-8")
    assert "mock 更新" in ai_file
    assert "| 2026-09-17 | 催化剂：下游订单信号增强 |" in ai_file
    # 无事件行业长文档不动
    power_file = industry_path(ctx.vault_path, "power_energy", ctx.sectors).read_text(encoding="utf-8")
    assert "（待首次更新）" in power_file

    # 幂等：重跑后 changelog 行数不翻倍（同一 refresh 行覆盖，changelog 追加依赖当日变化集）
    calls = ctx.mock_llm.call_count("industry_update")
    IndustryUpdateStep().run(ctx)
    text = industry_path(ctx.vault_path, "ai_semiconductor", ctx.sectors).read_text(encoding="utf-8")
    rows = [ln for ln in text.splitlines() if ln.startswith("| 2026-09-17")]
    assert len(rows) == 1  # 同日重跑不重复追加
    assert ctx.mock_llm.call_count("industry_update") == calls + 1  # refresh 语义 +1 次调用


def test_daily_report_contains_market_board(pipeline_ctx) -> None:
    from app.pipeline.steps.industry_update import IndustryUpdateStep
    from app.pipeline.steps.market import MarketStep
    from app.pipeline.steps.report import ReportStep

    ctx = pipeline_ctx
    _seed_ai_event(ctx.repo)
    MarketStep().run(ctx)
    IndustryUpdateStep().run(ctx)
    ReportStep().run(ctx)

    daily = (ctx.vault_path / "Daily" / "2026-09-17.md").read_text(encoding="utf-8")
    assert "## 市场复盘" in daily
    assert "上证指数" in daily
    assert "mock 市场复盘" in daily
