"""Provider protocols + runtime registry (architecture §6).

All outbound integrations live behind these protocols; swapping a data source
means adding one class + one registry entry, nothing else changes.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Callable, Dict, List, Tuple

from app.core.log import get_logger
from app.domain.analysis import LLMRequest, LLMResult
from app.domain.event import RawEvent


class ProviderError(Exception):
    """Provider-level failure (network, upstream error, unexpected payload)."""


class NewsProvider(ABC):
    name: str = "base"

    @abstractmethod
    def fetch(self, since: datetime) -> List[RawEvent]:
        """Fetch news items published at/after ``since``."""

    def health_check(self) -> bool:
        return True


class LLMProvider(ABC):
    name: str = "base"

    @abstractmethod
    def complete_json(self, req: LLMRequest) -> LLMResult:
        """Call the model in JSON mode and return usage-metered result."""


class MarketProvider(ABC):
    """V0.3: daily market snapshot (indices + sector boards)."""

    name: str = "base"

    @abstractmethod
    def fetch_daily(self, trade_date) -> Dict:
        """Snapshot dict: {trade_date, collected_at, indices[], sectors_top[], sectors_bottom[]}."""


NEWS_PROVIDER_REGISTRY: Dict[str, Callable[[], NewsProvider]] = {}


def register_news(name: str) -> Callable:
    def deco(cls):
        cls.name = name
        NEWS_PROVIDER_REGISTRY[name] = cls
        return cls

    return deco


def build_news_providers(names: List[str]) -> Tuple[List[NewsProvider], List[str]]:
    """Instantiate providers by name; unknown name fails fast, unhealthy one degrades.

    Returns (providers, degraded_names) — a degraded source never blocks the pipeline.
    """
    log = get_logger("providers")
    providers: List[NewsProvider] = []
    degraded: List[str] = []
    for name in names:
        factory = NEWS_PROVIDER_REGISTRY.get(name)
        if factory is None:
            raise KeyError("未注册的 news provider: %s（可选: %s）" % (name, sorted(NEWS_PROVIDER_REGISTRY)))
        try:
            p = factory()
            if not p.health_check():
                degraded.append(name)
                log.warning("provider 健康检查失败，降级", extra={"ctx": {"provider": name}})
                continue
            providers.append(p)
        except Exception as e:  # instantiation failure also degrades
            degraded.append(name)
            log.warning("provider 初始化失败，降级", extra={"ctx": {"provider": name, "error": str(e)}})
    return providers, degraded
