"""S1.5 announcements (V0.4): watched-company official disclosures.

Official announcements are the highest-priority source (原始需求 §24): they
bypass the L0 keyword filter (l0_bypass in raw payload) and go straight to
classification. Step sits between collect and ingest, appending raw events.
"""

from __future__ import annotations

from typing import List, Optional

from app.core.log import get_logger
from app.domain.report import StepResult
from app.pipeline.context import StepContext
from app.pipeline.orchestrator import Step


class AnnouncementStep(Step):
    name = "announcements"

    def run(self, ctx: StepContext) -> StepResult:
        log = get_logger("step.announcements")
        provider = getattr(ctx, "announcement_provider", None)
        if provider is None:
            return StepResult(name=self.name, ok=True, stats={"announcements": 0, "skipped": "no provider"})

        companies = ctx.repo.list_companies(watched_only=True)
        codes = [c.code for c in companies]
        if not codes:
            return StepResult(name=self.name, ok=True, stats={"announcements": 0, "skipped": "no watched companies"})

        lookback = ctx.app_cfg.pipeline.lookback_hours
        since = _since(lookback)
        try:
            raws = provider.fetch_for_codes(codes, since)
        except Exception as e:
            log.warning("公告采集失败，降级", extra={"ctx": {"error": str(e)[:200]}})
            return StepResult(name=self.name, ok=True, stats={"announcements": 0, "announcement_error": str(e)[:200]})

        ctx.shared.setdefault("raw_events", []).extend(raws)
        return StepResult(name=self.name, ok=True, stats={"announcements": len(raws), "codes": len(codes)})


def _since(lookback_hours: int):
    """与新闻采集同口径的回看窗口（重叠 + 幂等去重兜底）。"""
    from datetime import timedelta

    import app.core.clock as clock_mod

    return clock_mod.now() - timedelta(hours=lookback_hours)
