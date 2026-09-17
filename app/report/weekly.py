"""Weekly review (V0.5): aggregate 7 days -> L3 review -> Weekly/YYYY-Www.md.

Standalone command (Sunday 21:30 launchd), reuses the same engine/repo layer.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.core.log import get_logger
from app.db.repository import Repository
from app.knowledge.renderer import atomic_write


def week_bounds(anchor: date) -> Tuple[date, date, str]:
    """ISO week (Mon..Sun) containing ``anchor`` -> (start, end, 'YYYY-Www')."""
    start = anchor - timedelta(days=anchor.weekday())
    end = start + timedelta(days=6)
    year, week, _ = anchor.isocalendar()
    return start, end, "%04d-W%02d" % (year, week)


def build_weekly_ctx(repo: Repository, start: date, end: date) -> Dict[str, Any]:
    dailies: List[Dict] = []
    from app.db.models import AnalysisRow, EventRow

    for i in range(7):
        d = start + timedelta(days=i)
        summary_row = repo.get_analysis_for_date(d, "daily_summary")
        events = repo._s.query(EventRow).filter(
            EventRow.collected_at >= _day_start(d), EventRow.collected_at < _day_start(d + timedelta(days=1))
        ).all()
        p0 = sum(1 for e in events if e.importance == "P0")
        p1 = sum(1 for e in events if e.importance == "P1")
        dailies.append({
            "date": str(d),
            "summary": (summary_row.result_json or {}).get("summary", "") if summary_row else "（无日报）",
            "p0": p0, "p1": p1, "new_events": len(events),
        })

    thesis_stats = []
    for t in repo.list_theses():
        rows = [e for e in repo.list_thesis_evidence(t.id, limit=100) if start <= e.review_date <= end]
        # weak 反证来自 devil_advocate 分析（不落 thesis_evidence，从 analyses 统计）
        weak_contra = 0
        for a in repo.analyses_for_date(end, "devil_advocate"):
            if a.thesis_id == t.id:
                weak_contra += len((a.result_json or {}).get("counter_points") or [])
        thesis_stats.append({
            "id": t.id, "title": t.title, "status": t.status,
            "supporting": sum(1 for e in rows if e.direction == "supporting"),
            "contradicting": sum(1 for e in rows if e.direction == "contradicting"),
            "weak_contra": weak_contra,
        })
    return {"dailies": dailies, "thesis_stats": thesis_stats}


def _day_start(d: date):
    from datetime import datetime

    return datetime.combine(d, datetime.min.time())


def render_weekly_md(model: Dict) -> str:
    r = model["review"]
    lines = ["# Weekly Review — %s" % model["label"], ""]
    lines.append("> 周期：%s ~ %s" % (model["start"], model["end"]))
    lines.append("")
    if r.get("week_summary"):
        lines.append("## 本周净变化")
        lines.append("")
        lines.append(r["week_summary"])
        lines.append("")
    for title, key in (("行业变化", "industry_changes"), ("Thesis 变化", "thesis_changes")):
        rows = r.get(key) or []
        if rows:
            lines.append("## %s" % title)
            lines.append("")
            for row in rows:
                name = row.get("sector") or row.get("thesis_id") or "?"
                lines.append("- **%s**：%s" % (name, row.get("change", "")))
            lines.append("")
    for title, key in (("✅ 本周被验证", "validated"), ("❌ 本周被证伪/削弱", "falsified")):
        rows = r.get(key) or []
        if rows:
            lines.append("## %s" % title)
            lines.append("")
            lines.extend("- %s" % x for x in rows)
            lines.append("")
    watch = r.get("next_week_watch") or []
    if watch:
        lines.append("## 下周跟踪")
        lines.append("")
        lines.extend("- %s" % w for w in watch)
        lines.append("")
    thesis_stats = model.get("thesis_stats") or []
    if thesis_stats:
        lines.append("## Thesis 证据分布")
        lines.append("")
        lines.append("| Thesis | 状态 | 支持 | 反对(weak) |")
        lines.append("|---|---|---|---|")
        for t in thesis_stats:
            lines.append("| [[Theses/%s\\|%s]] | %s | %d | %d(%d) |" % (
                t["id"], t["title"], t["status"], t["supporting"], t["contradicting"], t["weak_contra"],
            ))
        lines.append("")
    return "\n".join(lines)


def generate_weekly(engine, repo: Repository, vault: Path, anchor: date, force: bool = False) -> Optional[Path]:
    """Run the weekly review; returns the written path (None on analysis failure)."""
    log = get_logger("report.weekly")
    start, end, label = week_bounds(anchor)

    if not force:
        existing = repo.get_analysis_for_date(end, "weekly_review")
        if existing is not None:
            # 幂等：本周已生成，仅确保文件存在
            path = vault / "Weekly" / ("%s.md" % label)
            if not path.exists():
                atomic_write(path, render_weekly_md({
                    "label": label, "start": str(start), "end": str(end),
                    "review": existing.result_json or {}, "thesis_stats": build_weekly_ctx(repo, start, end)["thesis_stats"],
                }))
            return path

    weekly_ctx = build_weekly_ctx(repo, start, end)
    outcome = engine.run(
        "weekly_review",
        prompt_ctx={
            "week": {"start": str(start), "end": str(end), "label": label},
            "dailies": weekly_ctx["dailies"],
            "thesis_stats": weekly_ctx["thesis_stats"],
        },
        report_date=end,  # 聚合键挂周末
        allowed_thesis_ids={t["id"] for t in weekly_ctx["thesis_stats"]},  # THESES 枚举注入（防幻觉 thesis id）
    )
    if not outcome.ok:
        log.warning("weekly review failed", extra={"ctx": {"kind": outcome.error_kind}})
        return None

    model = {
        "label": label, "start": str(start), "end": str(end),
        "review": outcome.result or {}, "thesis_stats": weekly_ctx["thesis_stats"],
    }
    path = vault / "Weekly" / ("%s.md" % label)
    atomic_write(path, render_weekly_md(model))
    repo.upsert_report("weekly", end, str(path), {"week": label})
    log.info("weekly written", extra={"ctx": {"path": str(path)}})
    return path
