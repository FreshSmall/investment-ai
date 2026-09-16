"""Deterministic mock news provider reading tests/fixtures/news_sample.json.

Covers the scenarios the ingest pipeline must handle (implementation plan TASK-009):
sector hits x3, L0 miss, same-source duplicate, cross-source same-content, bad timestamp.
``collected_at`` mirrors ``published_at`` so two fetches are byte-identical (determinism).
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from app.core.config import PROJECT_ROOT
from app.core.log import get_logger
from app.domain.event import RawEvent
from app.providers.base import NewsProvider, ProviderError, register_news

DEFAULT_FIXTURE = PROJECT_ROOT / "tests" / "fixtures" / "news_sample.json"


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


@register_news("mock")
class MockNewsProvider(NewsProvider):
    def __init__(self, fixture_path: Optional[Path] = None) -> None:
        self._path = fixture_path or DEFAULT_FIXTURE
        if not self._path.exists():
            raise ProviderError("mock fixture 不存在: %s" % self._path)
        data = json.loads(self._path.read_text(encoding="utf-8"))
        self._events = data.get("events", [])
        self.bad_records = 0  # rows skipped due to unparsable timestamps

    def health_check(self) -> bool:
        return self._path.exists()

    def fetch(self, since: datetime) -> List[RawEvent]:
        self.bad_records = 0
        out: List[RawEvent] = []
        now = datetime(2026, 9, 17, 20, 0, 0)  # frozen collection time (determinism)
        for item in self._events:
            published = _parse_dt(item.get("published_at"))
            if published is None:
                self.bad_records += 1
                continue
            if published < since:
                continue
            out.append(
                RawEvent(
                    source=item["source"],
                    source_id=str(item["source_id"]),
                    title=item["title"],
                    content=item.get("content", ""),
                    url=item.get("url"),
                    published_at=published,
                    collected_at=now,
                    raw={k: v for k, v in item.items() if k in ("source", "source_id", "title")},
                )
            )
        get_logger("mock.news").info(
            "mock fetch", extra={"ctx": {"returned": len(out), "bad": self.bad_records}}
        )
        return out
