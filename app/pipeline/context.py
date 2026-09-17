"""StepContext: the only object passed between pipeline steps (arch §4)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.analysis.engine import AnalysisEngine
from app.core.config import AppCfg, SectorsCfg, Settings
from app.db.repository import Repository
from app.domain.analysis import Strategy
from app.providers.base import MarketProvider, NewsProvider


@dataclass
class StepContext:
    run_id: str
    report_date: date
    settings: Settings
    app_cfg: AppCfg
    sectors: SectorsCfg
    repo: Repository
    engine: AnalysisEngine
    news_providers: List[NewsProvider]
    degraded_sources: List[str] = field(default_factory=list)
    vault_path: Path = Path("~/Investment-KB").expanduser()
    shared: Dict[str, Any] = field(default_factory=dict)  # step-to-step payload bus
    market_provider: Optional[MarketProvider] = None     # V0.3: None = market step degrades to skip
    announcement_provider: Optional[Any] = None          # V0.4: NewsProvider-like (fetch_for_codes)
