from __future__ import annotations

import json
from datetime import datetime

import httpx
import pytest

import app.providers  # noqa: F401
from app.core.http import HttpClient, TIER_CLS, TIER_EASTMONEY
from app.providers.base import NEWS_PROVIDER_REGISTRY, ProviderError
from app.providers.news.cls import ClsNewsProvider, cls_sign
from app.providers.news.eastmoney import EastmoneyNewsProvider


class NoSleep:
    def __call__(self, s: float) -> None:
        pass


def make_http(handler, tier: str) -> HttpClient:
    return HttpClient(tier=tier, transport=httpx.MockTransport(handler), sleeper=NoSleep())


# ---------------- cls ----------------

def test_cls_sign_fixed_snapshot() -> None:
    params = {"appName": "CailianpressWeb", "os": "web", "sv": "7.7.5",
              "last_time": "", "refresh_type": "1", "rn": "50"}
    # 算法: md5(sha1(sorted-qs))
    import hashlib
    qs = "&".join("%s=%s" % (k, params[k]) for k in sorted(params))
    expected = hashlib.md5(hashlib.sha1(qs.encode()).hexdigest().encode()).hexdigest()
    assert cls_sign(params) == expected
    assert len(cls_sign(params)) == 32


def _cls_payload(n: int, start_ts: int = 1760000000) -> dict:
    roll = []
    for i in range(n):
        roll.append({
            "id": 9000 + i,
            "ctime": start_ts - i * 60,
            "title": "电报标题%d" % i,
            "content": "电报正文%d：算力与电网投资动态。" % i,
        })
    return {"errno": 0, "data": {"roll_data": roll}}


def test_cls_fetch_pages_until_since() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json=_cls_payload(50))

    provider = ClsNewsProvider(http=make_http(handler, TIER_CLS), page_size=50, max_pages=3)
    # 所有条目时间相同量级 -> 翻页直到 max_pages 或遇到 < since
    since = datetime.fromtimestamp(1760000000 - 60)
    items = provider.fetch(since)
    assert len(items) > 0
    assert all(e.published_at >= since for e in items)
    assert calls["n"] >= 1


def test_cls_errno_raises_provider_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"errno": 500, "errmsg": "sign error"})

    provider = ClsNewsProvider(http=make_http(handler, TIER_CLS))
    with pytest.raises(ProviderError, match="errno"):
        provider.fetch(datetime(2026, 9, 17))


def test_cls_registered() -> None:
    assert "cls" in NEWS_PROVIDER_REGISTRY


# ---------------- eastmoney ----------------

def _em_payload() -> dict:
    return {
        "code": 0,
        "data": {
            "fastNewsList": [
                {"code": "A1", "title": "算力新闻一", "summary": "摘要一",
                 "showTime": "2026-09-17 15:00:00", "uniqueUrl": "https://x/1"},
                {"code": "A2", "title": "储能新闻二", "summary": "摘要二",
                 "showTime": "2026-09-17 09:00:00", "uniqueUrl": None},
                {"code": "A3", "title": "旧闻", "summary": "旧",
                 "showTime": "2026-09-15 08:00:00"},  # 窗口外
                {"code": "A4", "title": "", "summary": "无标题应跳过",
                 "showTime": "2026-09-17 10:00:00"},
                {"code": "A5", "title": "坏时间", "summary": "x",
                 "showTime": "not-a-date"},
            ]
        },
    }


def test_eastmoney_fetch_maps_and_filters() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_em_payload())

    provider = EastmoneyNewsProvider(http=make_http(handler, TIER_EASTMONEY))
    items = provider.fetch(datetime(2026, 9, 16, 0, 0))
    assert [e.source_id for e in items] == ["A1", "A2"]
    assert items[0].published_at == datetime(2026, 9, 17, 15, 0)
    assert items[0].url == "https://x/1"


def test_eastmoney_uses_throttled_tier_by_default() -> None:
    provider = EastmoneyNewsProvider()  # 默认客户端
    assert provider._http.tier == TIER_EASTMONEY


def test_eastmoney_registered() -> None:
    assert "eastmoney" in NEWS_PROVIDER_REGISTRY
