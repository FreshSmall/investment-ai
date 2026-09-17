"""S7.5 devil's advocate (V0.5): counter-analysis for theses that gained
supporting evidence today. Output is capped at weight=weak by CODE (arch
§7.4) — it enriches the counter-evidence record but never flips status alone.
"""

from __future__ import annotations

import json
from typing import Dict, List

from app.core.log import get_logger
from app.domain.report import StepResult
from app.pipeline.context import StepContext
from app.pipeline.orchestrator import Step


def _event_sectors(sector_json) -> set:
    try:
        return set(json.loads(sector_json or "[]"))
    except (json.JSONDecodeError, TypeError):
        return set()


class DevilAdvocateStep(Step):
    name = "devil_advocate"

    def run(self, ctx: StepContext) -> StepResult:
        log = get_logger("step.devil_advocate")
        theses = ctx.repo.list_theses(active_only=True)

        # 当日证据与事件（thesis_review 先行，本步骤消费其证据）
        event_rows = ctx.repo.get_report_events(ctx.report_date)
        analyses = ctx.repo.analyses_for_events([r.id for r in event_rows], "event_analysis")
        events_by_id = {
            r.id: {
                "event_id": r.id, "title": r.title,
                "summary": (analyses[r.id].result_json or {}).get("summary", r.title) if r.id in analyses else r.title,
                "sectors": _event_sectors(r.sectors),
            }
            for r in event_rows
        }

        stats: Dict = {"theses_advocated": 0, "counter_points": 0}
        budget_hit = False
        for thesis in theses:
            related = [
                e for e in events_by_id.values()
                if not e["sectors"] or e["sectors"] & set(thesis.related_sectors or [])
            ]
            supporting = [
                {"event_id": e.event_id, "text": e.note or ""}
                for e in ctx.repo.list_thesis_evidence(thesis.id, limit=20)
                if e.review_date == ctx.report_date and e.direction == "supporting"
            ]
            if not related and not supporting:
                continue  # 当日无支持证据也无事件：反方分析无对象

            outcome = ctx.engine.run(
                "devil_advocate",
                prompt_ctx={
                    "thesis": {
                        "id": thesis.id, "title": thesis.title,
                        "core_hypothesis": thesis.core_hypothesis.strip(),
                        "falsification_conditions": thesis.falsification_conditions or [],
                    },
                    "supporting": supporting,
                    "events": related,
                },
                allowed_event_ids={e["event_id"] for e in related},
                allowed_thesis_ids={thesis.id},
                report_date=ctx.report_date,
                thesis_id=thesis.id,  # per-thesis aggregate 缓存键（refresh 语义）
            )
            if not outcome.ok:
                if outcome.error_kind == "budget_exceeded":
                    budget_hit = True
                    break
                log.warning("devil advocate failed", extra={"ctx": {"thesis": thesis.id, "kind": outcome.error_kind}})
                continue

            result = outcome.result or {}
            # 反证不落 thesis_evidence（其主键 thesis+event+date 无法表达同一事件
            # 的双向解读，且 thesis_evidence 语义 = thesis_review 采信的证据）——
            # devil 产出保留在 analyses 表，由渲染层（日报反方板块/Thesis 文件）合并展示
            stats["theses_advocated"] += 1
            stats["counter_points"] += len(result.get("counter_points") or [])

        if budget_hit:
            stats["budget_hit"] = True
            log.warning("devil_advocate 预算熔断，剩余 thesis 顺延")
        return StepResult(name=self.name, ok=True, stats=stats)
