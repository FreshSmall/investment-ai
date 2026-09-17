"""S6.6 market: snapshot upsert (idempotent) + L2 market review (V0.3).

Snapshot source comes from ctx.market_provider (mock in tests, tencent in
production). A failed fetch degrades the step — the daily report still runs.
"""

from __future__ import annotations

import json
from typing import Dict, List, Optional

from app.core.log import get_logger
from app.domain.report import StepResult
from app.pipeline.context import StepContext
from app.pipeline.orchestrator import Step


def _events_digest(ctx: StepContext) -> List[dict]:
    rows = ctx.repo.get_report_events(ctx.report_date)
    analyses = ctx.repo.analyses_for_events([r.id for r in rows], "event_analysis")
    out = []
    for r in rows:
        try:
            sectors = ",".join(json.loads(r.sectors or "[]"))
        except (json.JSONDecodeError, TypeError):
            sectors = ""
        out.append({
            "event_id": r.id,
            "title": r.title,
            "sectors": sectors,
            "summary": (analyses[r.id].result_json or {}).get("summary", r.title) if r.id in analyses else r.title,
        })
    return out


class MarketStep(Step):
    name = "market"

    def run(self, ctx: StepContext) -> StepResult:
        log = get_logger("step.market")
        stats: Dict = {"market_snapshot": False, "market_review_ok": False}

        provider = getattr(ctx, "market_provider", None)

        if provider is None:
            stats["market_skipped"] = "no provider"
            return StepResult(name=self.name, ok=True, stats=stats)

        # 1) 快照（幂等 upsert；失败降级不阻塞）
        try:
            snapshot = provider.fetch_daily(ctx.report_date)
            ctx.repo.upsert_snapshot(ctx.report_date, snapshot)
            stats["market_snapshot"] = True
            stats["indices"] = len(snapshot.get("indices") or [])
        except Exception as e:
            log.warning("行情快照失败，降级", extra={"ctx": {"error": str(e)[:200]}})
            stats["market_error"] = str(e)[:200]

        snapshot = ctx.repo.get_snapshot(ctx.report_date)
        if snapshot is None:
            # 无快照数据（provider 失败且当日首次）：复盘无输入，跳过 LLM 调用
            stats["market_review_ok"] = False
            stats["market_review_skipped"] = "no snapshot"
            return StepResult(name=self.name, ok=True, stats=stats)

        prev = ctx.repo.get_prev_snapshot(ctx.report_date)
        outcome = ctx.engine.run(
            "market_review",
            prompt_ctx={
                "snapshot": snapshot,
                "prev_snapshot": prev or {},
                "events": _events_digest(ctx),
            },
            report_date=ctx.report_date,
        )
        stats["market_review_ok"] = outcome.ok
        if outcome.error_kind == "budget_exceeded":
            stats["budget_hit"] = True
        return StepResult(name=self.name, ok=True, stats=stats)
