"""S8 industry update (V0.3): per-sector aggregate -> SectionDiff -> vault.

Only sectors with today's P0/P1 analyzed events trigger an LLM call; the
aggregate cache key reuses the analyses.thesis_id column (sector key).
"""

from __future__ import annotations

import json
from typing import Dict, List

from app.core.log import get_logger
from app.domain.report import StepResult
from app.knowledge.updater import apply_industry_update, build_section_ctx
from app.pipeline.context import StepContext
from app.pipeline.orchestrator import Step

_CONTENT_SECTIONS = ("overview", "supply_demand", "catalysts", "risks", "metrics")


def _sector_events(ctx: StepContext, sector_key: str) -> List[Dict]:
    rows = ctx.repo.get_report_events(ctx.report_date)
    analyses = ctx.repo.analyses_for_events([r.id for r in rows], "event_analysis")
    out: List[Dict] = []
    for r in rows:
        try:
            sectors = set(json.loads(r.sectors or "[]"))
        except (json.JSONDecodeError, TypeError):
            sectors = set()
        if sector_key not in sectors:
            continue
        result = (analyses[r.id].result_json or {}) if r.id in analyses else {}
        out.append({
            "event_id": r.id,
            "title": r.title,
            "importance": r.importance or "",
            "summary": result.get("summary", r.title),
            "causal_chain": " → ".join(result.get("causal_chain") or []),
            "uncertainty": "；".join(result.get("uncertainty") or []),
        })
    return out


class IndustryUpdateStep(Step):
    name = "industry_update"

    def run(self, ctx: StepContext) -> StepResult:
        log = get_logger("step.industry_update")
        stats: Dict = {"industries_updated": 0, "sections_changed": 0}
        budget_hit = False

        for key in ctx.sectors.keys():
            events = _sector_events(ctx, key)
            if not events:
                continue  # 当日无该行业事件：长文档不动（节级保守更新）

            sec = ctx.sectors.sectors[key]
            outcome = ctx.engine.run(
                "industry_update",
                prompt_ctx={
                    "sector": {"key": key, "name": sec.name},
                    "events": events,
                    "sections": build_section_ctx(ctx.vault_path, key, ctx.sectors),
                },
                allowed_event_ids={e["event_id"] for e in events},
                report_date=ctx.report_date,
                thesis_id=key,  # 聚合维度键：行业（复用 uk_agg 缓存列）
            )
            if not outcome.ok:
                if outcome.error_kind == "budget_exceeded":
                    budget_hit = True
                    break
                log.warning(
                    "industry update failed",
                    extra={"ctx": {"sector": key, "kind": outcome.error_kind}},
                )
                continue

            applied = apply_industry_update(
                ctx.vault_path, key, ctx.sectors, outcome.result or {}, str(ctx.report_date),
            )
            if applied["sections_changed"] or applied["changelog_added"]:
                stats["industries_updated"] += 1
                stats["sections_changed"] += applied["sections_changed"]

        if budget_hit:
            stats["budget_hit"] = True
            log.warning("industry_update 预算熔断，剩余行业顺延")
        return StepResult(name=self.name, ok=True, stats=stats)
