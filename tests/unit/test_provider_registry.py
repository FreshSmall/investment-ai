from __future__ import annotations

from datetime import datetime

import pytest

import app.providers  # noqa: F401  (registration side effects)
from app.providers.base import (
    NEWS_PROVIDER_REGISTRY,
    NewsProvider,
    ProviderError,
    build_news_providers,
    register_news,
)


def test_registry_starts_empty_then_registers() -> None:
    # Real providers register via app.providers.__init__ as they land (TASK-009/011/012);
    # here we verify the registration mechanism itself with a local probe class.
    assert isinstance(NEWS_PROVIDER_REGISTRY, dict)

    @register_news("probe-fake")
    class Probe(NewsProvider):
        def fetch(self, since: datetime):
            return []

    assert NEWS_PROVIDER_REGISTRY["probe-fake"] is Probe


def test_unknown_provider_fails_fast() -> None:
    with pytest.raises(KeyError, match="未注册"):
        build_news_providers(["nonexistent"])


@register_news("healthy-fake")
class HealthyFake(NewsProvider):
    def fetch(self, since: datetime):
        return []


@register_news("sick-fake")
class SickFake(NewsProvider):
    def health_check(self) -> bool:
        return False

    def fetch(self, since: datetime):
        return []


@register_news("boom-fake")
class BoomFake(NewsProvider):
    def __init__(self) -> None:
        raise ProviderError("ctor explosion")

    def fetch(self, since: datetime):
        return []


def test_unhealthy_provider_degrades_not_blocks() -> None:
    providers, degraded = build_news_providers(["healthy-fake", "sick-fake", "boom-fake"])
    assert [p.name for p in providers] == ["healthy-fake"]
    assert degraded == ["sick-fake", "boom-fake"]


def test_empty_list_builds_nothing() -> None:
    providers, degraded = build_news_providers([])
    assert providers == [] and degraded == []
