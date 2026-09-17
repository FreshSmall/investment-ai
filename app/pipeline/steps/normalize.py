"""S2+S3+S4 ingest: normalize -> L0 keyword filter -> near-dup merge -> idempotent insert."""

from __future__ import annotations

from typing import List

from app.core.log import get_logger
from app.domain.event import NormalizedEvent, is_near_dup_title, l0_match, normalize_text
from app.domain.report import StepResult
from app.pipeline.context import StepContext
from app.pipeline.orchestrator import Step


class IngestStep(Step):
    name = "ingest"

    def run(self, ctx: StepContext) -> StepResult:
        log = get_logger("step.ingest")
        pipe = ctx.app_cfg.pipeline
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
            # 官方公告（来源优先级最高，原始需求 §24）跳过关键词过滤，直接进分类
            l0_bypass = bool((raw.raw or {}).get("l0_bypass"))
            if not l0_bypass and not l0_match(norm_title, norm_content, keywords, pipe.l0_min_content_hits):
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

        # Same-story merge: earliest published wins; batch-internal + recent DB titles.
        seen_titles = ctx.repo.recent_event_titles(pipe.near_dup_hours)
        kept: List[NormalizedEvent] = []
        near_dup = 0
        for ev in sorted(candidates, key=lambda e: e.published_at):
            if any(
                is_near_dup_title(ev.title, t, pipe.near_dup_jaccard, pipe.near_dup_lcs_chars)
                for t in seen_titles
            ):
                near_dup += 1
                continue
            kept.append(ev)
            seen_titles.append(ev.title)

        stats = ctx.repo.upsert_events(kept)
        log.info(
            "ingest done",
            extra={"ctx": {"fetched": len(ctx.shared.get("raw_events", [])), "new": stats.inserted,
                           "dup_source": stats.dup_source, "dup_hash": stats.dup_hash,
                           "dup_near": near_dup}},
        )
        return StepResult(
            name=self.name,
            ok=True,
            stats={
                "events_l0_filtered": l0_filtered,
                "events_bad_records": bad_records,
                "events_deduplicated": stats.dup_source + stats.dup_hash,
                "events_near_dup": near_dup,
                "events_new": stats.inserted,
            },
        )
