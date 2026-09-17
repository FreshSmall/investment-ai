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
    # V0.3: market behaviour review (indices + sector boards vs fundamentals)
    "market_review": Strategy(
        name="market_review",
        tier=StrategyTier.L2,
        schema_name="market_review_v1",
        prompt_file="market_review_v1.md",
        scope="aggregate",
    ),
    # V0.3: industry long-doc section update (per-sector per-day aggregate;
    # thesis_id column carries the sector key as the aggregate dimension)
    "industry_update": Strategy(
        name="industry_update",
        tier=StrategyTier.L2,
        schema_name="industry_update_v1",
        prompt_file="industry_update_v1.md",
        scope="thesis",  # refresh-in-place semantics, dimension key = sector
    ),
    # V0.5: devil's advocate — counter-evidence candidates for today's
    # supporting theses (output weight capped at weak by code, arch §7.4)
    "devil_advocate": Strategy(
        name="devil_advocate",
        tier=StrategyTier.L2,
        schema_name="devil_advocate_v1",
        prompt_file="devil_advocate_v1.md",
        scope="thesis",
    ),
    # V0.5: weekly review (L3 flagship, Sunday)
    "weekly_review": Strategy(
        name="weekly_review",
        tier=StrategyTier.L3,
        schema_name="weekly_review_v1",
        prompt_file="weekly_review_v1.md",
        scope="aggregate",
    ),
}
