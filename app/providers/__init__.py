"""Provider package. Submodule imports are added as providers land (mock -> cls -> eastmoney)."""

from __future__ import annotations

from app.providers.base import (  # noqa: F401
    LLMProvider,
    NewsProvider,
    ProviderError,
    build_news_providers,
    register_news,
)
