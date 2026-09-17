"""Daily report assembly: DB view -> render model (deterministic) -> vault file + reports row."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.log import get_logger
from app.db.repository import Repository
from app.knowledge.renderer import atomic_write, ensure_skeletons, render_daily_md


def build_daily_model(repo: Repository, report_date: date, summary: Optional[Dict], p1_cap: int = 0) -> Dict[str, Any]:
    event_rows = repo.get_report_events(report_date)
    analyses = repo.analyses_for_events([r.id for r in event_rows], "event_analysis")
    impact_analyses = repo.analyses_for_events([r.id for r in event_rows], "company_impact")
    events: List[Dict] = []
    for r in event_rows:
        try:
            sectors = json.loads(r.sectors or "[]")
        except json.JSONDecodeError:
            sectors = []
        analysis_row = analyses.get(r.id)
        events.append(
            {
                "event_id": r.id,
                "title": r.title,
                "importance": r.importance,
                "sectors": sectors,
                "event_type": r.event_type,
                "published_at": r.published_at.strftime("%Y-%m-%d %H:%M"),
                "source_name": r.source,
                "source_url": r.source_url,
                "analysis": (analysis_row.result_json if analysis_row else None),
            }
        )
    # P1 cap: drop the OLDEST overflow — the report window overlaps the previous
    # day's evening report, so the oldest P1 items were already shown there.
    p1_hidden = 0
    if p1_cap:
        p1_idx = [i for i, e in enumerate(events) if e["importance"] == "P1"]
        p1_hidden = max(0, len(p1_idx) - p1_cap)
        for i in reversed(p1_idx[:p1_hidden]):
            events.pop(i)

    # V0.2: thesis review board (thesis_reviews carry direction/note per thesis)
    thesis_titles = {t.id: t.title for t in repo.list_theses()}
    thesis_updates: List[Dict] = []
    for row in repo.analyses_for_date(report_date, "thesis_review"):
        result = row.result_json or {}
        thesis_updates.append({
            "thesis_id": row.thesis_id,
            "title": thesis_titles.get(row.thesis_id, row.thesis_id),
            "direction": result.get("direction", "neutral"),
            "note": result.get("note", ""),
        })

    # V0.2: watched-company impact board
    company_impacts: List[Dict] = []
    for r in event_rows:
        row = impact_analyses.get(r.id)
        if row is None:
            continue
        result = row.result_json or {}
        company_impacts.append({
            "companies": result.get("affected_companies") or [],
            "importance": r.importance,
            "summary": result.get("summary", ""),
        })

    return {
        "report_date": str(report_date),
        "summary": summary or {},
        "events": events,
        "metrics": repo.day_metrics(report_date),
        "p1_hidden": p1_hidden,
        "thesis_updates": thesis_updates,
        "company_impacts": company_impacts,
    }


def write_daily_report(
    repo: Repository,
    report_date: date,
    summary: Optional[Dict],
    vault: Path,
    theses: List[Dict],
    sectors_cfg,
    p1_cap: int = 0,
    status_changes: Optional[Dict[str, str]] = None,
) -> Path:
    model = build_daily_model(repo, report_date, summary, p1_cap)
    # V0.2: 标注状态变更（thesis_review step 经 ctx.shared 传入）
    changes = status_changes or {}
    for t in model["thesis_updates"]:
        if t["thesis_id"] in changes:
            t["status_changed"] = True
            t["new_status"] = changes[t["thesis_id"]]
    ensure_skeletons(vault, sectors_cfg, theses)

    # V0.2: Thesis 长文件以 DB 为准重渲染（evidence/changes 滚动窗口）
    from app.knowledge.renderer import write_thesis_file

    for t in theses:
        evidence = [
            {
                "review_date": str(e.review_date), "direction": e.direction,
                "weight": e.weight, "note": e.note, "event_id": e.event_id,
            }
            for e in repo.list_thesis_evidence(t["id"], limit=20)
        ]
        write_thesis_file(vault, t, evidence)

    md = render_daily_md(model)
    path = vault / "Daily" / ("%s.md" % report_date)
    atomic_write(path, md)
    repo.upsert_report("daily", report_date, str(path), model["metrics"])
    get_logger("report.daily").info(
        "daily report written",
        extra={"ctx": {"path": str(path), "events": len(model["events"]), "p1_hidden": model["p1_hidden"]}},
    )
    return path
