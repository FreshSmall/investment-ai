"""财联社电报 provider (cls.cn v1/roll/get_roll_list + 本地签名, 2026-07 实测可用).

Sign is computed locally (zero key): md5(sha1(query-sorted-string)).
Pagination: ``last_time`` carries the previous page's last ``ctime``.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import List, Optional

from app.core import clock
from app.core.http import TIER_CLS, HttpClient, get_client
from app.core.log import get_logger
from app.domain.event import RawEvent
from app.providers.base import NewsProvider, ProviderError, register_news

_API_URL = "https://www.cls.cn/v1/roll/get_roll_list"
_HEADERS = {"Referer": "https://www.cls.cn/"}


def cls_sign(params: dict) -> str:
    qs = "&".join("%s=%s" % (k, params[k]) for k in sorted(params))
    return hashlib.md5(hashlib.sha1(qs.encode("utf-8")).hexdigest().encode("utf-8")).hexdigest()


@register_news("cls")
class ClsNewsProvider(NewsProvider):
    def __init__(self, http: Optional[HttpClient] = None, page_size: int = 50, max_pages: int = 30) -> None:
        self._http = http or get_client(TIER_CLS)
        self._page_size = page_size
        self._max_pages = max_pages
        self._log = get_logger("cls")

    def health_check(self) -> bool:
        try:
            rows = self._fetch_page(last_time="")
            return rows is not None
        except Exception:
            return False

    def fetch(self, since: datetime) -> List[RawEvent]:
        out: List[RawEvent] = []
        last_time = ""
        now = clock.now()
        for _page in range(self._max_pages):
            rows = self._fetch_page(last_time=last_time)
            if not rows:
                break
            stop = False
            for idx, item in enumerate(rows):
                ctime = item.get("ctime")
                if not ctime:
                    continue
                published = datetime.fromtimestamp(int(ctime))
                if published < since:
                    stop = True
                    break
                source_id = str(item.get("id") or "%s-%d" % (ctime, idx))
                title = (item.get("title") or item.get("brief") or "").strip()
                content = (item.get("content") or item.get("brief") or "").strip()
                if not title:
                    continue
                out.append(
                    RawEvent(
                        source="cls",
                        source_id=source_id,
                        title=title,
                        content=content or title,
                        url="https://www.cls.cn/telegraph/%s" % source_id,
                        published_at=published,
                        collected_at=now,
                        raw={"ctime": ctime, "title": title[:80]},
                    )
                )
                last_time = str(ctime)
            if stop:
                break
        self._log.info("cls fetch done", extra={"ctx": {"count": len(out)}})
        return out

    def _fetch_page(self, last_time: str = "") -> Optional[List[dict]]:
        params = {
            "appName": "CailianpressWeb",
            "os": "web",
            "sv": "7.7.5",
            "last_time": last_time,
            "refresh_type": "1",
            "rn": str(self._page_size),
        }
        qs = "&".join("%s=%s" % (k, params[k]) for k in sorted(params))
        url = "%s?%s&sign=%s" % (_API_URL, qs, cls_sign(params))
        resp = self._http.get(url, headers=_HEADERS)
        data = resp.json()
        if data.get("errno", 0) != 0:
            raise ProviderError("财联社 errno=%s: %s" % (data.get("errno"), str(data.get("errmsg"))[:100]))
        return (data.get("data") or {}).get("roll_data") or []


if __name__ == "__main__":  # 真实冒烟（联调用，非 CI）
    provider = ClsNewsProvider()
    items = provider.fetch(datetime.now().replace(hour=0, minute=0, second=0))
    print("fetched %d items" % len(items))
    for it in items[:5]:
        print(" %s | %s" % (it.published_at.strftime("%H:%M"), it.title[:50]))
