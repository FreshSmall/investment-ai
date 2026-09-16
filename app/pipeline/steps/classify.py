"""S5 classify: L1 Flash batch classification + importance grading."""

from __future__ import annotations

from typing import List, Sequence

from app.core.log import get_logger
from app.domain.event import EventStatus
from app.domain.report import StepResult
from app.pipeline.context import StepContext
from app.pipeline.orchestrator import Step


def _chunks(seq: Sequence, size: int) -> List[List]:
    return [seq[i:i + size] for i in range(0, len(seq), size)]


class ClassifyStep(Step):
    name = "classify"

    def run(self, ctx: StepContext) -> StepResult:
        log = get_logger("step.classify")
        rows = ctx.repo.get_events_for_classify()
        if not rows:
            return StepResult(name=self.name, ok=True, stats={"events_classified": 0})

        batch_size = ctx.app_cfg.pipeline.classify_batch_size
        classified = 0
        failed = 0
        by_importance: dict = {}

        for batch in _chunks(rows, batch_size):
            events_payload = [
                {
                    "event_id": r.id,
                    "title": r.title,
                    "content_head": (r.content or "")[:200],
                }
                for r in batch
            ]
            outcome = ctx.engine.run(
                "classification",
                prompt_ctx={"sector_keys": ctx.sectors.keys(), "events": events_payload},
                allowed_event_ids={r.id for r in batch},
            )
            if not outcome.ok:
                failed += len(batch)
                for r in batch:
                    ctx.repo.mark_event_status(r.id, EventStatus.UNCLASSIFIED)
                log.warning("分类批次失败", extra={"ctx": {"size": len(batch), "kind": outcome.error_kind}})
                continue

            got_ids = set()
            for item in outcome.result["results"]:
                try:
                    ctx.repo.mark_classified(
                        item["event_id"], item["sectors"], item["event_type"], item["importance"]
                    )
                    got_ids.add(item["event_id"])
                    classified += 1
                    by_importance[item["importance"]] = by_importance.get(item["importance"], 0) + 1
                except Exception as e:
                    failed += 1
                    log.warning("mark_classified 失败", extra={"ctx": {"id": item.get("event_id"), "error": str(e)[:120]}})
            for r in batch:  # 批中被幻觉剔除/遗漏的事件：下轮重试
                if r.id not in got_ids:
                    ctx.repo.mark_event_status(r.id, EventStatus.UNCLASSIFIED)

        return StepResult(
            name=self.name,
            ok=True,
            stats={
                "events_classified": classified,
                "classify_failed": failed,
                "by_importance": by_importance,
            },
        )
