"""Strategy registry: one entry per analysis viewpoint (arch §7.2)."""

from __future__ import annotations

from app.domain.analysis import Strategy, StrategyTier

STRATEGIES = {
    "classification": Strategy(
        name="classification",
        tier=StrategyTier.L1,
        schema_name="classification_v1",
        prompt_file="classification_v1.md",
        scope="batch",
    ),
    "event_analysis": Strategy(
        name="event_analysis",
        tier=StrategyTier.L2,
        schema_name="event_analysis_v1",
        prompt_file="event_analysis_v1.md",
        scope="event",
    ),
    "daily_summary": Strategy(
        name="daily_summary",
        tier=StrategyTier.L2,
        schema_name="daily_summary_v1",
        prompt_file="daily_summary_v1.md",
        scope="aggregate",
    ),
    # V0.2: thesis review (per-thesis per-day; refresh in place on the 22:00 rerun)
    "thesis_review": Strategy(
        name="thesis_review",
        tier=StrategyTier.L2,
        schema_name="thesis_review_v1",
        prompt_file="thesis_review_v1.md",
        scope="thesis",
    ),
    # V0.2: watched-company impact for events that mention a watched name/code
    # (reuses event_analysis_v1 — same shape, company-focused prompt)
    "company_impact": Strategy(
        name="company_impact",
        tier=StrategyTier.L2,
        schema_name="event_analysis_v1",
        prompt_file="company_impact_v1.md",
        scope="event",
    ),
}
