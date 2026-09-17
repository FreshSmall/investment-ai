"""S7 thesis review: today's P0/P1 analyses vs each active thesis (arch §7.4).

LLM only labels direction; status transitions (weakened/falsified) are CODE
rules in Repository.apply_thesis_review — no scores, no buy/sell output.
"""

from __future__ import annotations

import json
from typing import Dict, List, Optional

from app.core.log import get_logger
from app.domain.report import StepResult
from app.pipeline.context import StepContext
from app.pipeline.orchestrator import Step


def _thesis_sectors(thesis) -> set:
    try:
        return set(thesis.related_sectors or [])
    except TypeError:
        return set()


def _event_sectors(sector_json: Optional[str]) -> set:
    try:
        return set(json.loads(sector_json or "[]"))
    except (json.JSONDecodeError, TypeError):
        return set()


class ThesisReviewStep(Step):
    name = "thesis_review"

    def run(self, ctx: StepContext) -> StepResult:
        log = get_logger("step.thesis_review")
        theses = ctx.repo.list_theses(active_only=True)
        if not theses:
            return StepResult(name=self.name, ok=True, stats={"theses_reviewed": 0})

        # 当日 P0/P1 + 已完成深度分析的事件（复用报告窗口查询）
        event_rows = ctx.repo.get_report_events(ctx.report_date)
        analyses = ctx.repo.analyses_for_events([r.id for r in event_rows], "event_analysis")
        events_by_sector: Dict[str, List[Dict]] = {}
        for row in event_rows:
            entry = {
                "event_id": row.id,
                "title": row.title,
                "importance": row.importance or "",
                "sectors": ",".join(sorted(_event_sectors(row.sectors))),
                "summary": (analyses[row.id].result_json or {}).get("summary", row.title) if row.id in analyses else row.title,
                "facts": "; ".join(
                    f.get("text", "")
                    for f in ((analyses[row.id].result_json or {}).get("facts") or [])
                )[:300] if row.id in analyses else "",
            }
            # 事件行业标签决定它进哪些 thesis 的上下文；无标签事件对所有 thesis 可见
            for key in (_event_sectors(row.sectors) or {"*"}):
                events_by_sector.setdefault(key, []).append(entry)

        reviews: Dict[str, str] = {}
        status_changes: Dict[str, str] = {}
        budget_hit = False
        for thesis in theses:
            related = events_by_sector.get("*", [])
            for key in _thesis_sectors(thesis):
                related = _merge_unique(related, events_by_sector.get(key, []))

            outcome = ctx.engine.run(
                "thesis_review",
                prompt_ctx={
                    "thesis": {
                        "id": thesis.id,
                        "title": thesis.title,
                        "core_hypothesis": thesis.core_hypothesis.strip(),
                        "falsification_conditions": thesis.falsification_conditions or [],
                        "key_metrics": thesis.key_metrics or [],
                    },
                    "events": related,
                },
                allowed_event_ids={e["event_id"] for e in related},
                allowed_thesis_ids={thesis.id},
                report_date=ctx.report_date,
                thesis_id=thesis.id,
            )
            if not outcome.ok:
                if outcome.error_kind == "budget_exceeded":
                    budget_hit = True
                    break  # 剩余 thesis 顺延（refresh 语义下轮重跑覆盖）
                log.warning(
                    "thesis review failed",
                    extra={"ctx": {"thesis": thesis.id, "kind": outcome.error_kind}},
                )
                continue

            result = outcome.result or {}
            direction = result.get("direction", "neutral")
            evidence_items = [
                {
                    "event_id": it.get("source_event_id", ""),
                    "direction": it.get("direction", direction),
                    "weight": it.get("weight", "weak"),
                    "note": it.get("text", ""),
                }
                for it in result.get("evidence", [])
                if it.get("source_event_id")
            ]
            fals = result.get("falsification_triggered") or {}
            applied = ctx.repo.apply_thesis_review(
                thesis_id=thesis.id,
                review_date=ctx.report_date,
                direction=direction,
                evidence_items=evidence_items,
                analysis_id=outcome.analysis_id,
                falsification_triggered=bool(fals.get("triggered")),
            )
            reviews[thesis.id] = direction
            if applied.get("status_changed"):
                status_changes[thesis.id] = applied["new_status"]

        stats: Dict = {
            "theses_reviewed": len(reviews),
            "thesis_reviews": reviews,
        }
        if status_changes:
            stats["thesis_status_changes"] = status_changes
            ctx.shared["thesis_status_changes"] = status_changes  # report step 读取（日报标注）
        if budget_hit:
            stats["budget_hit"] = True
            log.warning("thesis_review 预算熔断，剩余 thesis 顺延")
        return StepResult(name=self.name, ok=True, stats=stats)


def _merge_unique(base: List[Dict], extra: List[Dict]) -> List[Dict]:
    seen = {e["event_id"] for e in base}
    return base + [e for e in extra if e["event_id"] not in seen]
