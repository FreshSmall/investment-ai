"""S6.5 company impact: watched-company rule match on today's P0/P1 analyzed
events -> one focused L2 analysis per hit event (arch §7.2 company_impact).

Event-level cache key (event_id, strategy) makes re-runs free.
"""

from __future__ import annotations

import json
from typing import Dict, List

from app.core.log import get_logger
from app.domain.report import StepResult
from app.pipeline.context import StepContext
from app.pipeline.orchestrator import Step


def match_companies(text: str, companies) -> List[Dict]:
    """Rule match: watched name (>=2 chars) or bare 6-digit code appears in text."""
    hits: List[Dict] = []
    for c in companies:
        if c.name and len(c.name) >= 2 and c.name in text:
            hits.append(_company_dict(c))
        elif c.code and c.code in text:
            hits.append(_company_dict(c))
    return hits


def _company_dict(c) -> Dict:
    profile = ""
    if isinstance(c.profile, dict):
        profile = c.profile.get("text", "")
    return {
        "code": c.code, "name": c.name, "sector": c.sector or "",
        "profile": profile or "（无档案，按行业暴露推断）",
    }


class CompanyImpactStep(Step):
    name = "company_impact"

    def run(self, ctx: StepContext) -> StepResult:
        log = get_logger("step.company_impact")
        companies = ctx.repo.list_companies(watched_only=True)
        if not companies:
            return StepResult(name=self.name, ok=True, stats={"company_impacts": 0, "watched": 0})

        event_rows = ctx.repo.get_report_events(ctx.report_date)
        event_analyses = ctx.repo.analyses_for_events([r.id for r in event_rows], "event_analysis")
        analyzed_events = [r for r in event_rows if r.id in event_analyses]

        impacts = 0
        budget_hit = False
        for row in analyzed_events:
            text = "%s\n%s" % (row.title, row.content)
            hits = match_companies(text, companies)
            if not hits:
                continue
            summary = (event_analyses[row.id].result_json or {}).get("summary", "")
            outcome = ctx.engine.run(
                "company_impact",
                prompt_ctx={
                    "sector_keys": ctx.sectors.keys(),
                    "event": {
                        "event_id": row.id,
                        "title": row.title,
                        "importance": row.importance or "",
                        "event_type": row.event_type or "",
                        "content": row.content,
                        "analysis_summary": summary or "（无事件级分析）",
                    },
                    "companies": hits,
                },
                allowed_event_ids={row.id},
                event_id=row.id,
            )
            if outcome.ok:
                impacts += 1
            elif outcome.error_kind == "budget_exceeded":
                budget_hit = True
                break  # 预算熔断：剩余命中事件顺延（event 级缓存下轮免费重试）
            # parse/provider 错误：留档跳过，不阻塞

        stats: Dict = {
            "company_impacts": impacts,
            "watched": len(companies),
            "analyzed_events": len(analyzed_events),  # 当日已分析事件基数（命中数为 company_impacts）
        }
        if budget_hit:
            stats["budget_hit"] = True
            log.warning("company_impact 预算熔断，剩余命中事件顺延")
        return StepResult(name=self.name, ok=True, stats=stats)
