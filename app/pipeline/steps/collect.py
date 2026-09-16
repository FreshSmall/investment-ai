"""S1 collect: fan out news providers, degrade on per-source failure, cache raw payload."""

from __future__ import annotations

import json
from datetime import timedelta

from app.core import clock
from app.core.config import PROJECT_ROOT
from app.core.log import get_logger
from app.domain.report import StepResult
from app.pipeline.context import StepContext
from app.pipeline.orchestrator import Step


class CollectStep(Step):
    name = "collect"

    def run(self, ctx: StepContext) -> StepResult:
        log = get_logger("step.collect")
        since = clock.now() - timedelta(hours=ctx.app_cfg.pipeline.lookback_hours)
        raw_events = []
        degraded: list = []
        for provider in ctx.news_providers:
            try:
                items = provider.fetch(since)
                raw_events.extend(items)
                log.info("collected", extra={"ctx": {"provider": provider.name, "count": len(items)}})
            except Exception as e:  # source-level failure degrades, never blocks
                degraded.append(provider.name)
                log.warning("provider 失败，降级", extra={"ctx": {"provider": provider.name, "error": str(e)[:200]}})

        if degraded:
            ctx.degraded_sources.extend(degraded)

        # raw cache: 先落盘再入库，DB 故障时重跑不重复拉取（arch §11）
        try:
            cache_dir = PROJECT_ROOT / "data" / "raw_cache"
            cache_dir.mkdir(parents=True, exist_ok=True)
            cache_file = cache_dir / ("%s_%s.json" % (ctx.report_date, ctx.run_id[:8]))
            cache_file.write_text(
                json.dumps([e.__dict__ | {"published_at": e.published_at.isoformat(), "collected_at": e.collected_at.isoformat()} for e in raw_events], ensure_ascii=False, default=str),
                encoding="utf-8",
            )
        except OSError as e:
            log.warning("raw cache 写入失败（不影响流程）", extra={"ctx": {"error": str(e)[:100]}})

        ctx.shared["raw_events"] = raw_events
        return StepResult(
            name=self.name,
            ok=True,
            stats={"events_fetched": len(raw_events), "degraded_sources": degraded},
        )
