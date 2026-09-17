#!/usr/bin/env python
"""investment-ai CLI.

Commands: daily / status / event / render / thesis / backfill
Exit codes: 0 success|skip, 2 partial, 3 failed, 99 watchdog timeout.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import uuid
from datetime import date as _date
from datetime import datetime, timedelta
from typing import List

from app.core import clock
from app.core.config import (
    Settings,
    effective_vault_path,
    get_app_config,
    get_sectors,
    get_settings,
)
from app.core.log import get_logger, setup_logging
from app.core.notify import notify


def _watchdog(minutes: int) -> None:
    def handler(signum, frame):  # pragma: no cover
        print("WATCHDOG: pipeline 超时 %d 分钟，强制退出" % minutes, file=sys.stderr)
        os._exit(99)

    signal.signal(signal.SIGALRM, handler)
    signal.alarm(minutes * 60)


def _build_ctx(report_date: _date, providers_mode: str, settings: Settings):
    from app.analysis.engine import AnalysisEngine
    from app.db.repository import Repository
    from app.db.seed import seed_theses
    from app.pipeline.context import StepContext
    from app.providers.base import build_news_providers
    from app.providers.llm.mock import MockLLMProvider
    from app.providers.llm.openai_compat import BudgetGuard, OpenAICompatLLMProvider
    from app.db.engine import get_session_factory

    app_cfg = get_app_config()
    sectors = get_sectors()
    session = get_session_factory()()
    repo = Repository(session)
    seed_theses(session)  # 首次运行引导（幂等）

    budget = BudgetGuard(app_cfg.llm.daily_budget_cny)
    if providers_mode == "mock":
        llm = MockLLMProvider()
        news_names = ["mock"]
    else:
        settings.validate_required()
        if not settings.llm_api_key:
            raise SystemExit("缺少 LLM_API_KEY（.env）—— 或使用 --providers mock")
        llm = OpenAICompatLLMProvider(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            price_lookup=lambda m: (
                app_cfg.llm.price_of(m).input_per_m,
                app_cfg.llm.price_of(m).output_per_m,
            ),
            min_call_interval=app_cfg.llm.min_call_interval_seconds,
        )
        news_names = app_cfg.news_providers
    news_providers, degraded = build_news_providers(news_names)

    ctx = StepContext(
        run_id=str(uuid.uuid4()),
        report_date=report_date,
        settings=settings,
        app_cfg=app_cfg,
        sectors=sectors,
        repo=repo,
        engine=AnalysisEngine(llm=llm, repo=repo, sectors=sectors, app_cfg=app_cfg, budget=budget),
        news_providers=news_providers,
        degraded_sources=degraded,
        vault_path=effective_vault_path(app_cfg, settings),
    )
    ctx.llm = llm  # type: ignore[attr-defined]
    return ctx


def _steps():
    from app.pipeline.steps.analyze import AnalyzeStep
    from app.pipeline.steps.classify import ClassifyStep
    from app.pipeline.steps.collect import CollectStep
    from app.pipeline.steps.company_impact import CompanyImpactStep
    from app.pipeline.steps.normalize import IngestStep
    from app.pipeline.steps.report import ReportStep
    from app.pipeline.steps.thesis_review import ThesisReviewStep

    return [
        CollectStep(), IngestStep(), ClassifyStep(), AnalyzeStep(),
        CompanyImpactStep(), ThesisReviewStep(), ReportStep(),
    ]


def cmd_daily(args) -> int:
    settings = get_settings()
    report_date = _date.fromisoformat(args.date) if args.date else clock.today()
    ctx = _build_ctx(report_date, args.providers, settings)
    setup_logging(run_id=ctx.run_id)
    _watchdog(get_app_config().pipeline.watchdog_minutes)

    from app.pipeline.orchestrator import Orchestrator

    summary = Orchestrator(_steps()).run_daily(ctx, force=args.force)
    print(summary.print_report())
    if summary.status.value not in ("success", "skipped"):
        notify("investment-ai daily", "run %s: %s" % (summary.run_id[:8], summary.status.value))
    return {"partial": 2, "failed": 3, "db_unreachable": 3}.get(summary.status.value, 0)


def cmd_status(args) -> int:
    from app.db.engine import get_session_factory
    from app.db.repository import Repository

    repo = Repository(get_session_factory()())
    runs = repo.list_recent_runs(args.days)
    if not runs:
        print("（无运行记录）")
        return 0
    print("%-34s %-11s %-10s %-8s %s" % ("run_id", "date", "status", "cost", "events_new"))
    for r in runs:
        stats = r.stats_json or {}
        print(
            "%-34s %-11s %-10s %-8s %s" % (
                r.run_id, str(r.report_date), r.status,
                stats.get("estimated_cost_cny", "-"), stats.get("events_new", "-"),
            )
        )
    return 0


def cmd_event(args) -> int:
    from app.db.engine import get_session_factory
    from app.db.repository import Repository

    repo = Repository(get_session_factory()())
    row = repo.get_event(args.event_id)
    if row is None:
        print("事件不存在: %s" % args.event_id)
        return 1
    print("id          : %s" % row.id)
    print("source      : %s / %s" % (row.source, row.source_id))
    print("published   : %s" % row.published_at)
    print("importance  : %s (%s) %s" % (row.importance, row.event_type, row.sectors or ""))
    print("status      : %s" % row.status)
    print("url         : %s" % (row.source_url or "-"))
    print("title       : %s" % row.title)
    print("content     : %s" % row.content[:500])
    analysis = repo.get_analysis_for_event(row.id, "event_analysis")
    if analysis:
        print("--- analysis (%s / %s) ---" % (analysis.model, analysis.prompt_version))
        print(json.dumps(analysis.result_json, ensure_ascii=False, indent=2)[:2000])
    return 0


def cmd_render(args) -> int:
    from app.db.engine import get_session_factory
    from app.db.repository import Repository
    from app.db.seed import seed_theses
    from app.knowledge.renderer import ensure_skeletons

    settings = get_settings()
    session = get_session_factory()()
    seed_theses(session)  # 幂等：空库时保证 thesis 骨架可渲染
    repo = Repository(session)
    theses = [
        {"id": t.id, "title": t.title, "core_hypothesis": t.core_hypothesis,
         "falsification_conditions": t.falsification_conditions,
         "key_metrics": t.key_metrics, "status": t.status}
        for t in repo.list_theses()
    ]
    vault = effective_vault_path(get_app_config(), settings)
    created = ensure_skeletons(vault, get_sectors(), theses)
    print("vault: %s（新建 %d 个骨架文件；已有文件永不覆盖）" % (vault, len(created)))
    return 0


def cmd_thesis(args) -> int:
    from app.db.engine import get_session_factory
    from app.db.repository import Repository
    from app.db.seed import seed_companies, seed_theses

    repo = Repository(get_session_factory()())
    if args.action == "seed":
        print("seeded %d theses" % seed_theses(repo._s))
        print("seeded %d companies" % seed_companies(repo._s))
        return 0
    theses = repo.list_theses()
    if args.action == "list":
        for t in theses:
            print("%-28s %-10s %s" % (t.id, t.status, t.title))
        return 0
    if args.action == "show":
        for t in theses:
            if t.id == args.thesis_id:
                print(json.dumps({
                    "id": t.id, "title": t.title, "status": t.status,
                    "core_hypothesis": t.core_hypothesis,
                    "falsification_conditions": t.falsification_conditions,
                }, ensure_ascii=False, indent=2))
                return 0
        print("不存在: %s" % args.thesis_id)
        return 1
    if args.action == "restore":
        t = repo._s.get(__import__("app.db.models", fromlist=["ThesisRow"]).ThesisRow, args.thesis_id)
        if t is None:
            print("不存在: %s" % args.thesis_id)
            return 1
        t.status = "active"
        repo._s.commit()
        print("%s -> active（人工操作）" % args.thesis_id)
        return 0
    return 1


def cmd_backfill(args) -> int:
    since = _date.fromisoformat(args.since)
    until = _date.fromisoformat(args.until)
    rc = 0
    current = since
    while current <= until:
        print("== backfill %s ==" % current)
        ns = argparse.Namespace(date=str(current), force=False, providers=args.providers)
        rc = cmd_daily(ns) or rc
        current += timedelta(days=1)
    return rc


def main(argv: List[str] = None) -> int:
    parser = argparse.ArgumentParser(prog="investment-ai")
    sub = parser.add_subparsers(dest="command", required=True)

    p_daily = sub.add_parser("daily", help="完整日度流水线")
    p_daily.add_argument("--date", help="YYYY-MM-DD（默认今天）")
    p_daily.add_argument("--force", action="store_true", help="忽略当日已成功检查")
    p_daily.add_argument("--providers", choices=["real", "mock"], default="real")
    p_daily.set_defaults(func=cmd_daily)

    p_status = sub.add_parser("status", help="最近运行概览")
    p_status.add_argument("--days", type=int, default=7)
    p_status.set_defaults(func=cmd_status)

    p_event = sub.add_parser("event", help="查看事件与分析")
    p_event.add_argument("event_id")
    p_event.set_defaults(func=cmd_event)

    p_render = sub.add_parser("render", help="重建 vault 骨架（缺失文件）")
    p_render.add_argument("--all", action="store_true")
    p_render.set_defaults(func=cmd_render)

    p_thesis = sub.add_parser("thesis", help="Thesis 管理")
    p_thesis.add_argument("action", choices=["list", "show", "restore", "seed"])
    p_thesis.add_argument("thesis_id", nargs="?")
    p_thesis.set_defaults(func=cmd_thesis)

    p_backfill = sub.add_parser("backfill", help="历史日期重放")
    p_backfill.add_argument("--since", required=True)
    p_backfill.add_argument("--until", required=True)
    p_backfill.add_argument("--providers", choices=["real", "mock"], default="real")
    p_backfill.set_defaults(func=cmd_backfill)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
