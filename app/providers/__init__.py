"""Provider package: importing submodules populates the registries."""

from __future__ import annotations

from app.providers.base import (  # noqa: F401
    LLMProvider,
    NewsProvider,
    ProviderError,
    build_news_providers,
    register_news,
)

# Import for registration side effects.
from app.providers.news import mock as _mock_news  # noqa: F401
from app.providers.llm import mock as _llm_mock  # noqa: F401
