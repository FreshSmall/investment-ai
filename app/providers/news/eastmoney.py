"""东财全球资讯 provider (np-weblist 7x24, 财联社的独立备份源).

All requests MUST go through the eastmoney-tier client (>=1s + jitter, 403 = no retry).
Single page of 100 items covers the 26h lookback window in practice; if the oldest
item is still newer than ``since`` we log a truncation warning (MVP trade-off).
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime
from typing import List, Optional

from app.core import clock
from app.core.http import TIER_EASTMONEY, HttpClient, get_client
from app.core.log import get_logger
from app.domain.event import RawEvent
from app.providers.base import NewsProvider, ProviderError, register_news

_API_URL = "https://np-weblist.eastmoney.com/comm/web/getFastNewsList"
_HEADERS = {"Referer": "https://kuaixun.eastmoney.com/"}


@register_news("eastmoney")
class EastmoneyNewsProvider(NewsProvider):
    def __init__(self, http: Optional[HttpClient] = None, page_size: int = 100) -> None:
        self._http = http or get_client(TIER_EASTMONEY)
        self._page_size = page_size
        self._log = get_logger("eastmoney.news")

    def health_check(self) -> bool:
        try:
            return self._fetch() is not None
        except Exception:
            return False

    def fetch(self, since: datetime) -> List[RawEvent]:
        items = self._fetch() or []
        now = clock.now()
        out: List[RawEvent] = []
        for idx, item in enumerate(items):
            show_time = item.get("showTime") or ""
            try:
                published = datetime.strptime(show_time, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                continue
            if published < since:
                continue
            title = (item.get("title") or "").strip()
            if not title:
                continue
            source_id = str(item.get("code") or hashlib.sha1(
                ("%s|%s" % (title, show_time)).encode("utf-8")
            ).hexdigest()[:16])
            out.append(
                RawEvent(
                    source="eastmoney",
                    source_id=source_id,
                    title=title,
                    content=(item.get("summary") or title).strip(),
                    url=item.get("uniqueUrl") or None,
                    published_at=published,
                    collected_at=now,
                    raw={"showTime": show_time, "title": title[:80]},
                )
            )
        if out and items and (items[-1].get("showTime")):
            try:
                oldest = datetime.strptime(items[-1]["showTime"], "%Y-%m-%d %H:%M:%S")
                if oldest >= since:
                    self._log.warning("东财单页可能截断", extra={"ctx": {"oldest": str(oldest)}})
            except ValueError:
                pass
        self._log.info("eastmoney fetch done", extra={"ctx": {"count": len(out)}})
        return out

    def _fetch(self) -> Optional[List[dict]]:
        params = {
            "client": "web",
            "biz": "web_724",
            "fastColumn": "102",
            "sortEnd": "",
            "pageSize": str(self._page_size),
            "req_trace": str(uuid.uuid4()),
        }
        resp = self._http.get(_API_URL, params=params, headers=_HEADERS)
        data = resp.json()
        if data.get("code") not in (0, None) and data.get("status") not in (0, None, 200):
            raise ProviderError("东财快讯返回异常: %s" % str(data)[:150])
        return (data.get("data") or {}).get("fastNewsList") or []


if __name__ == "__main__":  # 真实冒烟
    provider = EastmoneyNewsProvider()
    items = provider.fetch(datetime.now().replace(hour=0, minute=0, second=0))
    print("fetched %d items" % len(items))
    for it in items[:5]:
        print(" %s | %s" % (it.published_at.strftime("%H:%M"), it.title[:50]))
