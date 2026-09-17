"""V0.2 集成测试：company_impact + thesis_review 两步骤 + 渲染产物端到端。"""

from __future__ import annotations

import json
from datetime import date, datetime

from app.db.repository import Repository
from app.domain.event import EventStatus, make_event_id


def _seed(session, repo: Repository) -> None:
    from app.db.models import CompanyRow
    from app.db.seed import seed_companies, seed_theses

    seed_theses(session)
    seed_companies(session)
    # 一条命中自选股（中际旭创）的 P0 事件，直接以 classified+analyzed 前态入库
    repo.upsert_events([_norm_ev("cls", "zx-1", "中际旭创获北美客户 800G 光模块大额订单",
                                 "中际旭创公告获得北美云厂商 800G 光模块批量订单，交付周期延伸至明年。")])
    ev = repo.get_event(make_event_id("cls", "zx-1"))
    repo.mark_classified(ev.id, ["ai_semiconductor"], "order_demand", "P0")
    repo.mark_event_status(ev.id, EventStatus.ANALYZED)
    # 一条命中自选股（绿的谐波）的 P1 事件
    repo.upsert_events([_norm_ev("cls", "zx-2", "绿的谐波机器人用谐波减速器出货爬坡",
                                 "绿的谐波表示机器人客户订单进入小批量交付阶段。")])
    ev2 = repo.get_event(make_event_id("cls", "zx-2"))
    repo.mark_classified(ev2.id, ["robotics"], "order_demand", "P1")
    repo.mark_event_status(ev2.id, EventStatus.ANALYZED)
    # 预置事件级分析（company_impact 步骤的输入依赖它取摘要）
    for eid in (ev.id, ev2.id):
        repo.save_analysis(strategy="event_analysis", model="mock", prompt_version="v1",
                           result={"summary": "订单信号积极。", "facts": [], "affected_industries": []},
                           event_id=eid)


def _norm_ev(source, source_id, title, content):
    from app.domain.event import NormalizedEvent

    return NormalizedEvent(
        source=source, source_id=source_id, title=title, content=content, url=None,
        published_at=datetime(2026, 9, 17, 10, 0), collected_at=datetime(2026, 9, 17, 20, 0),
        raw={}, norm_title=title, norm_content=content,
    )


def test_company_impact_and_thesis_review_chain(pipeline_ctx) -> None:
    from app.pipeline.steps.company_impact import CompanyImpactStep
    from app.pipeline.steps.thesis_review import ThesisReviewStep
    from app.db.models import AnalysisRow, ThesisEvidenceRow

    ctx = pipeline_ctx
    _seed(ctx.repo._s, ctx.repo)

    # ---- S6.5 company impact ----
    res1 = CompanyImpactStep().run(ctx)
    assert res1.ok and res1.stats["company_impacts"] == 2  # 两条命中事件各一次
    rows = ctx.repo._s.query(AnalysisRow).filter(AnalysisRow.strategy == "company_impact").all()
    assert len(rows) == 2
    affected = {c["name"] for r in rows for c in (r.result_json.get("affected_companies") or [])}
    assert "中际旭创" in affected
    # event 级缓存：重跑零新行零新调用
    calls_before = ctx.mock_llm.call_count("company_impact")
    CompanyImpactStep().run(ctx)
    assert ctx.mock_llm.call_count("company_impact") == calls_before
    assert ctx.repo._s.query(AnalysisRow).filter(AnalysisRow.strategy == "company_impact").count() == 2

    # ---- S7 thesis review ----
    res2 = ThesisReviewStep().run(ctx)
    assert res2.ok
    # 4 个种子 thesis 全部复盘；ai 相关 thesis 引用了命中事件
    assert res2.stats["theses_reviewed"] == 4
    evidence = ctx.repo._s.query(ThesisEvidenceRow).all()
    assert len(evidence) >= 1
    directions = res2.stats["thesis_reviews"]
    assert set(directions.values()) <= {"supporting", "neutral", "contradicting"}
    # 状态不被单日信号翻转
    assert all(t.status == "active" for t in ctx.repo.list_theses())
    # 幂等：evidence 行数与 analyses(thesis_review) 行数在重跑后不变（refresh 原地更新）
    n_ev = len(evidence)
    n_an = ctx.repo._s.query(AnalysisRow).filter(AnalysisRow.strategy == "thesis_review").count()
    ThesisReviewStep().run(ctx)
    assert ctx.repo._s.query(ThesisEvidenceRow).count() == n_ev
    assert ctx.repo._s.query(AnalysisRow).filter(AnalysisRow.strategy == "thesis_review").count() == n_an


def test_report_contains_v02_boards_and_thesis_file(pipeline_ctx) -> None:
    from app.knowledge.renderer import atomic_write, thesis_skeleton
    from app.pipeline.steps.company_impact import CompanyImpactStep
    from app.pipeline.steps.report import ReportStep
    from app.pipeline.steps.thesis_review import ThesisReviewStep

    ctx = pipeline_ctx
    _seed(ctx.repo._s, ctx.repo)
    CompanyImpactStep().run(ctx)
    ThesisReviewStep().run(ctx)

    res = ReportStep().run(ctx)
    assert res.ok

    daily = (ctx.vault_path / "Daily" / "2026-09-17.md").read_text(encoding="utf-8")
    assert "## Thesis 复盘" in daily
    assert "## 自选股影响" in daily
    assert "中际旭创" in daily
    assert "[[Theses/ai-demand-growth|" in daily or "[[Theses/ai-demand-growth]]" in daily

    thesis_path = ctx.vault_path / "Theses" / "ai-demand-growth.md"
    thesis_md = thesis_path.read_text(encoding="utf-8")
    assert "🟢 active" in thesis_md           # 状态徽章（DB 为准）
    assert "## 支持证据" in thesis_md
    assert "[[Daily/2026-09-17#" in thesis_md  # 证据回链到日报事件锚点

    # 人工内容保护：在节外写一行私人笔记，重渲染后必须字节级保留
    human_note = "\n## 人工笔记（勿动）\n我的独立判断：需求周期未完。\n"
    atomic_write(thesis_path, thesis_md + human_note)
    ReportStep().run(ctx)
    assert human_note in thesis_path.read_text(encoding="utf-8")
    assert "## 支持证据" in thesis_path.read_text(encoding="utf-8")  # 系统节仍在


def test_quiet_day_thesis_review_neutral(pipeline_ctx) -> None:
    """平静日：无 P0/P1 事件 → 全部 thesis neutral、evidence 空、日报无事件。"""
    from app.db.seed import seed_theses
    from app.pipeline.steps.thesis_review import ThesisReviewStep

    ctx = pipeline_ctx
    seed_theses(ctx.repo._s)
    res = ThesisReviewStep().run(ctx)
    assert res.ok
    assert set(res.stats["thesis_reviews"].values()) == {"neutral"}
    assert ctx.repo.list_thesis_evidence("ai-demand-growth") == []
