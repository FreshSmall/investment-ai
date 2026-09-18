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
    from app.db.usage import UsageStore

    app_cfg = get_app_config()
    sectors = get_sectors()
    session = get_session_factory()()
    repo = Repository(session)
    seed_theses(session)  # 首次运行引导（幂等）

    # V0.6 兜底：注入跨进程账本，daily_budget_cny 变为当日全局熔断线
    budget = BudgetGuard(app_cfg.llm.daily_budget_cny, store=UsageStore())
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

    # V0.3/V0.4: 行情快照 + 公告源（mock 模式联动）
    if providers_mode == "mock":
        from app.providers.announcement.mock import MockAnnouncementProvider
        from app.providers.market.tencent import MockMarketProvider

        market_provider = MockMarketProvider()
        announcement_provider = MockAnnouncementProvider()
    else:
        from app.providers.announcement.cninfo import CninfoAnnouncementProvider
        from app.providers.market.tencent import TencentMarketProvider

        market_provider = TencentMarketProvider()
        announcement_provider = CninfoAnnouncementProvider()

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
        market_provider=market_provider,
        announcement_provider=announcement_provider,
    )
    ctx.llm = llm  # type: ignore[attr-defined]
    return ctx


def _steps():
    from app.pipeline.steps.analyze import AnalyzeStep
    from app.pipeline.steps.announcements import AnnouncementStep
    from app.pipeline.steps.classify import ClassifyStep
    from app.pipeline.steps.collect import CollectStep
    from app.pipeline.steps.company_impact import CompanyImpactStep
    from app.pipeline.steps.devil_advocate import DevilAdvocateStep
    from app.pipeline.steps.industry_update import IndustryUpdateStep
    from app.pipeline.steps.market import MarketStep
    from app.pipeline.steps.normalize import IngestStep
    from app.pipeline.steps.report import ReportStep
    from app.pipeline.steps.thesis_review import ThesisReviewStep

    return [
        CollectStep(), AnnouncementStep(), IngestStep(), ClassifyStep(), AnalyzeStep(),
        MarketStep(), CompanyImpactStep(), ThesisReviewStep(), DevilAdvocateStep(),
        IndustryUpdateStep(), ReportStep(),
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
    # blocked → 0：兜底门拦截后以成功码退出，不给 KeepAlive=SuccessfulExit:false 喂重启循环
    return {"partial": 2, "failed": 3, "db_unreachable": 3, "blocked": 0}.get(summary.status.value, 0)


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
    import re

    from app.db.engine import get_session_factory
    from app.db.repository import Repository
    from app.db.seed import seed_theses
    from app.knowledge.renderer import atomic_write, ensure_skeletons, get_section, replace_section
    from app.knowledge.updater import industry_path

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
    sectors = get_sectors()
    app_cfg = get_app_config()
    vault = effective_vault_path(app_cfg, settings)
    created = ensure_skeletons(vault, sectors, theses)
    if not args.all:
        print("vault: %s（新建 %d 个骨架文件；已有文件永不覆盖；--all 从 DB 全量重渲染）" % (vault, len(created)))
        return 0

    # --all：以 DB 为真值重渲染既有产物（渲染格式升级 / 文件损坏后的恢复入口）。
    # write_daily_report 内部会同步重渲染全部 Thesis 长文件（滚动窗以 DB 为准）；
    # 历史重放不带当次运行的 status_changes 标注，Thesis 状态以 DB 当前值为准。
    from app.report.daily import write_daily_report

    dates = sorted(
        p.stem for p in (vault / "Daily").glob("*.md")
        if len(p.stem) == 10 and p.stem[4] == "-"
    )
    for stem in dates:
        d = _date.fromisoformat(stem)
        summary_row = repo.get_analysis_for_date(d, "daily_summary")
        write_daily_report(
            repo, d, (summary_row.result_json if summary_row else None),
            vault, theses, sectors, p1_cap=app_cfg.pipeline.daily_p1_cap,
        )

    # 存量修复：行业 changelog 旧格式表格补分隔行；系统文件 marker 与正文间距规范化
    # （紧贴 HTML 注释的表格在 Obsidian 实时预览中不渲染，必须空行分隔）
    # 链接迁移（含被 Obsidian 表格编辑器劈开的形式）→ markdown 链接：
    #   [[Daily/date#^eXXXX\|label]] / [[Daily/date#eXXXX | label]] → [label](../Daily/date.md#^eXXXX)
    #   [[Theses/id\|label]] → [label](../Theses/id.md)
    # markdown 链接不含竖线，表格编辑器重排单元格时不会再被破坏
    from app.knowledge.renderer import normalize_section_spacing

    def _daily_link(m: "re.Match") -> str:
        d, anc, disp = m.group(1), m.group(2), m.group(3).strip()
        return "[%s](../Daily/%s.md#^%s)" % (disp or d, d, anc)

    daily_link_re = re.compile(r"\[\[Daily/(\d{4}-\d{2}-\d{2})#\^?(e[0-9a-f]{4})\s*\\?\|\s*([^\]]*)\]\]")
    thesis_link_re = re.compile(r"\[\[Theses/([a-z0-9-]+)\\?\|\s*([^\]]*)\]\]")
    fixed = 0
    targets = [industry_path(vault, key, sectors) for key in sectors.keys()]
    targets += [vault / "Theses" / ("%s.md" % t["id"]) for t in theses]
    targets += list((vault / "Weekly").glob("*.md"))
    for path in targets:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        body = get_section(text, "changelog") if path.parent.name == "Industries" else None
        if body is not None and not any(ln.startswith("|---") for ln in body.splitlines()):
            body_lines = body.splitlines()
            if body_lines and body_lines[0].startswith("|"):
                body_lines.insert(1, "|---|---|---|")
                text = replace_section(text, "changelog", "\n".join(body_lines))
        new_text = normalize_section_spacing(
            thesis_link_re.sub(lambda m: "[%s](../Theses/%s.md)" % (m.group(2).strip() or m.group(1), m.group(1)),
                               daily_link_re.sub(_daily_link, text))
        )
        if new_text != text:
            atomic_write(path, new_text)
            fixed += 1
    print("vault 重渲染: %s（骨架新建 %d · 日报 %d 篇 · 存量格式修复 %d 个文件）" % (vault, len(created), len(dates), fixed))
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


def cmd_weekly(args) -> int:
    from app.report.weekly import generate_weekly
    from app.pipeline.orchestrator import run_gate_check

    settings = get_settings()
    report_date = _date.fromisoformat(args.date) if args.date else clock.today()
    ctx = _build_ctx(report_date, args.providers, settings)
    setup_logging(run_id=ctx.run_id)
    gate = run_gate_check(ctx)  # 兜底频率门同样覆盖 weekly（L3 调用更贵）
    if gate is not None:
        notify("investment-ai weekly", "run gate blocked: %s" % gate)
        print("run gate: 已拦截 %s" % gate)
        return 0
    path = generate_weekly(ctx.engine, ctx.repo, ctx.vault_path, report_date, force=args.force)
    if path is None:
        print("weekly review 失败（详见日志）")
        return 3
    print("weekly written: %s" % path)
    return 0


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

    p_render = sub.add_parser("render", help="重建 vault 骨架；--all 以 DB 为真值重渲染既有日报/Thesis")
    p_render.add_argument("--all", action="store_true", help="全量重渲染（日报 + Thesis + changelog 表头修复）")
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

    p_weekly = sub.add_parser("weekly", help="周度复盘（V0.5，默认本周）")
    p_weekly.add_argument("--date", help="锚定日期 YYYY-MM-DD（默认今天）")
    p_weekly.add_argument("--force", action="store_true", help="重新生成本周（L3 调用）")
    p_weekly.add_argument("--providers", choices=["real", "mock"], default="real")
    p_weekly.set_defaults(func=cmd_weekly)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
