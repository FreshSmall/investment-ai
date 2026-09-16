"""Domain: events, dedup hashing and text normalization (pure, zero deps)."""

from __future__ import annotations

import hashlib
import html
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class EventStatus(str, Enum):
    RAW = "raw"
    CLASSIFIED = "classified"
    ANALYZED = "analyzed"
    UNCLASSIFIED = "unclassified"  # 分类失败，下轮重试
    PARSE_ERROR = "parse_error"    # 分析失败终态，留档
    ARCHIVED = "archived"          # P3 归档


class Importance(str, Enum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"


@dataclass
class RawEvent:
    source: str                 # "cls" | "eastmoney" | ...
    source_id: str              # 源内唯一 ID
    title: str
    content: str
    url: Optional[str]
    published_at: datetime
    collected_at: datetime
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class NormalizedEvent(RawEvent):
    """NormalizedEvent carries the cleaned text plus both idempotency keys."""

    norm_title: str = ""
    norm_content: str = ""

    @property
    def event_id(self) -> str:
        return make_event_id(self.source, self.source_id)

    @property
    def content_hash(self) -> str:
        return make_content_hash(self.norm_title, self.norm_content)


def make_event_id(source: str, source_id: str) -> str:
    return hashlib.sha1(("%s:%s" % (source, source_id)).encode("utf-8")).hexdigest()[:16]


def make_content_hash(norm_title: str, norm_content: str) -> str:
    joined = norm_title.strip() + "\n" + norm_content.strip()
    return hashlib.sha1(joined.encode("utf-8")).hexdigest()


_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
# CJK-adjacent fullwidth forms that affect matching
_FULLWIDTH_MAP = {chr(c): chr(c - 0xFEE0) for c in range(0xFF01, 0xFF5F)}
_QUOTE_MAP = {"‘": "'", "’": "'", "“": '"', "”": '"', "（": "(", "）": ")", "，": ",", "。": "."}


def normalize_text(text: str) -> str:
    """HTML strip + entity unescape + fullwidth->halfwidth + whitespace fold."""
    if not text:
        return ""
    text = html.unescape(text)
    text = _TAG_RE.sub(" ", text)
    text = text.translate(str.maketrans({**_FULLWIDTH_MAP, **_QUOTE_MAP}))
    text = _WS_RE.sub(" ", text)
    return text.strip()


def l0_match(title: str, content: str, keywords: List[str]) -> bool:
    """Cheap relevance filter: title hit outweighs content hit (title-only is enough)."""
    norm_kw = [normalize_text(k).lower() for k in keywords if k]
    title_l = normalize_text(title).lower()
    if any(k in title_l for k in norm_kw):
        return True
    content_l = normalize_text(content).lower()
    return any(k in content_l for k in norm_kw)
