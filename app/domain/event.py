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


def l0_match(title: str, content: str, keywords: List[str], min_content_hits: int = 2) -> bool:
    """Cheap relevance filter: title hit outweighs content hit (title-only is enough).

    Content-only matches must contain ``min_content_hits`` distinct keywords —
    single generic-word mentions (AI/芯片/机器人 in market chatter) are noise.
    """
    norm_kw = [normalize_text(k).lower() for k in keywords if k]
    title_l = normalize_text(title).lower()
    if any(k in title_l for k in norm_kw):
        return True
    content_l = normalize_text(content).lower()
    return sum(1 for k in set(norm_kw) if k in content_l) >= min_content_hits


# ---------------- near-duplicate titles (same-story merge) ----------------


def _title_bigrams(title: str) -> set:
    folded = "".join(normalize_text(title).lower().split())
    return {folded[i:i + 2] for i in range(len(folded) - 1)}


def title_jaccard(a: str, b: str) -> float:
    """Char-bigram Jaccard on normalized titles; 0.0 on empty input."""
    A, B = _title_bigrams(a), _title_bigrams(b)
    if not A or not B:
        return 0.0
    return len(A & B) / len(A | B)


def lcs_len(a: str, b: str) -> int:
    """Longest common substring length (run of identical chars)."""
    best = 0
    prev = [0] * (len(b) + 1)
    for i in range(1, len(a) + 1):
        cur = [0] * (len(b) + 1)
        ai = a[i - 1]
        for j in range(1, len(b) + 1):
            if ai == b[j - 1]:
                cur[j] = prev[j - 1] + 1
                if cur[j] > best:
                    best = cur[j]
        prev = cur
    return best


def _fold(title: str) -> str:
    return "".join(normalize_text(title).lower().split())


def is_near_dup_title(a: str, b: str, jaccard_min: float = 0.6, lcs_min: int = 10) -> bool:
    """Same-story test for flash headlines.

    Two conditions keep periodic digests apart ("早间/晚间新闻精选" share J≈0.73
    but no long common run; "9月16/17日涨停分析" likewise), while cross-source
    reprints and "财联社X日电，" prefix variants merge.
    """
    fa, fb = _fold(a), _fold(b)
    if not fa or not fb:
        return False
    A, B = _title_bigrams(a), _title_bigrams(b)
    if len(A & B) / len(A | B) < jaccard_min:
        return False
    return lcs_len(fa, fb) >= lcs_min
