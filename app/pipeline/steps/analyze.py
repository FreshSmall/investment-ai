"""S6 analyze: L2 deep analysis for P0/P1 events. Budget hit degrades (report still runs)."""

from __future__ import annotations

import json
from typing import List

from app.core.log import get_logger
from app.domain.event import EventStatus
from app.domain.report import StepResult
from app.pipeline.context import StepContext
from app.pipeline.orchestrator import Step


def _recent_history(repo, sectors_json: str, limit: int = 3) -> List[dict]:
    """Related recent analyses sharing a sector (context slimming: summaries only)."""
    try:
        keys = set(json.loads(sectors_json or "[]"))
    except (json.JSONDecodeError, TypeError):
        keys = set()
    if not keys:
        return []
    history: List[dict] = []
    for row in repo.list_recent_analyses("event_analysis", limit=30):
        try:
            row_sectors = set(row.result_json.get("affected_industries") or [])
        except Exception:
            row_sectors = set()
        if keys & row_sectors:
            history.append({"summary": row.result_json.get("summary", "")})
        if len(history) >= limit:
            break
    return history


class AnalyzeStep(Step):
    name = "analyze"

    def run(self, ctx: StepContext) -> StepResult:
        log = get_logger("step.analyze")
        rows = ctx.repo.get_events_for_analysis()
        analyzed = 0
        parse_errors = 0
        retry_later = 0
        budget_skipped = 0
        budget_hit = False

        for row in rows:
            outcome = ctx.engine.run(
                "event_analysis",
                prompt_ctx={
                    "sector_keys": ctx.sectors.keys(),
                    "event": {
                        "event_id": row.id,
                        "title": row.title,
                        "published_at": row.published_at.strftime("%Y-%m-%d %H:%M"),
                        "content": row.content,
                    },
                    "history": _recent_history(ctx.repo, row.sectors),
                },
                allowed_event_ids={row.id},
                event_id=row.id,
            )
            if outcome.ok:
                ctx.repo.mark_event_status(row.id, EventStatus.ANALYZED)
                analyzed += 1
            elif outcome.error_kind == "parse_error":
                ctx.repo.mark_event_status(row.id, EventStatus.PARSE_ERROR)
                parse_errors += 1
            elif outcome.error_kind == "budget_exceeded":
                budget_hit = True
                budget_skipped += 1  # 留在 classified，次日预算恢复后续跑
            else:
                retry_later += 1  # provider 错误：保持 classified，下轮重试

        stats = {
            "events_analyzed": analyzed,
            "parse_errors": parse_errors,
            "analyze_retry_later": retry_later,
        }
        if budget_hit:
            stats["budget_hit"] = True
            stats["budget_skipped"] = budget_skipped
            log.warning("LLM 预算熔断，剩余事件顺延", extra={"ctx": {"skipped": budget_skipped}})
        return StepResult(name=self.name, ok=True, stats=stats)
