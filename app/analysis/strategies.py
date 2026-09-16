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
}
