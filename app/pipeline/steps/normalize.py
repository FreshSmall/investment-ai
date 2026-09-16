"""S2+S3+S4 ingest: normalize -> L0 keyword filter -> idempotent dedup insert."""

from __future__ import annotations

from typing import List

from app.core.log import get_logger
from app.domain.event import NormalizedEvent, l0_match, normalize_text
from app.domain.report import StepResult
from app.pipeline.context import StepContext
from app.pipeline.orchestrator import Step


class IngestStep(Step):
    name = "ingest"

    def run(self, ctx: StepContext) -> StepResult:
        log = get_logger("step.ingest")
        keywords = ctx.sectors.all_keywords()
        candidates: List[NormalizedEvent] = []
        l0_filtered = 0
        bad_records = 0

        for raw in ctx.shared.get("raw_events", []):
            norm_title = normalize_text(raw.title)
            norm_content = normalize_text(raw.content)
            if not norm_title or not raw.published_at:
                bad_records += 1
                continue
            if not l0_match(norm_title, norm_content, keywords):
                l0_filtered += 1
                continue
            candidates.append(
                NormalizedEvent(
                    source=raw.source,
                    source_id=raw.source_id,
                    title=raw.title,
                    content=raw.content,
                    url=raw.url,
                    published_at=raw.published_at,
                    collected_at=raw.collected_at,
                    raw=raw.raw,
                    norm_title=norm_title,
                    norm_content=norm_content,
                )
            )

        stats = ctx.repo.upsert_events(candidates)
        log.info(
            "ingest done",
            extra={"ctx": {"fetched": len(ctx.shared.get("raw_events", [])), "new": stats.inserted,
                           "dup_source": stats.dup_source, "dup_hash": stats.dup_hash}},
        )
        return StepResult(
            name=self.name,
            ok=True,
            stats={
                "events_l0_filtered": l0_filtered,
                "events_bad_records": bad_records,
                "events_deduplicated": stats.dup_source + stats.dup_hash,
                "events_new": stats.inserted,
            },
        )
