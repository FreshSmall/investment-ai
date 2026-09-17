"""Cninfo announcement provider (V0.4).

Watched-company announcements from cninfo (巨潮资讯, the official disclosure
site). Announcements are the highest-priority source (原始需求 §24) and carry
``l0_bypass`` — no keyword filter, straight to classification.

Endpoint recipe verified by the local a-stock-data skill V3.2.1+: the
``hisAnnouncement/query`` POST needs the per-stock ``orgId`` from the official
``szse_stock.json`` mapping (hardcoded gssx0{code} fails for many 601xxx).
PDF bodies are NOT parsed in V0.4 — the title feeds classification directly.
"""

from __future__ import annotations

import threading
from datetime import datetime
from typing import Dict, List, Optional

from app.core.http import get_client
from app.core.log import get_logger
from app.domain.event import RawEvent
from app.providers.base import NewsProvider, ProviderError

_ORG_MAP_URL = "http://www.cninfo.com.cn/new/data/szse_stock.json"
_QUERY_URL = "http://www.cninfo.com.cn/new/hisAnnouncement/query"
_org_lock = threading.Lock()
_org_map: Optional[Dict[str, str]] = None


def _load_orgid_map() -> Dict[str, str]:
    """code -> orgId (official mapping, cached process-wide)."""
    global _org_map
    with _org_lock:
        if _org_map is not None:
            return _org_map
        try:
            resp = get_client("cninfo").get(_ORG_MAP_URL)
            data = resp.json().get("stockList") or []
            _org_map = {item["code"]: item["orgId"] for item in data if item.get("code") and item.get("orgId")}
        except Exception as e:
            get_logger("cninfo").warning("orgId 映射拉取失败", extra={"ctx": {"error": str(e)[:200]}})
            _org_map = {}
        return _org_map


class CninfoAnnouncementProvider(NewsProvider):
    name = "cninfo"

    def health_check(self) -> bool:
        try:
            return bool(_load_orgid_map())
        except Exception:
            return False

    def fetch_for_codes(self, codes: List[str], since: datetime, limit_per_code: int = 15) -> List[RawEvent]:
        """Announcements of the given stock codes published at/after ``since``."""
        log = get_logger("cninfo")
        org_map = _load_orgid_map()
        if not org_map:
            raise ProviderError("cninfo orgId 映射不可用")
        client = get_client("cninfo")
        out: List[RawEvent] = []
        collected = datetime.now()
        for code in codes:
            org_id = org_map.get(code)
            if not org_id:
                log.info("无 orgId，跳过", extra={"ctx": {"code": code}})
                continue
            params = {
                "pageNum": "1", "pageSize": str(limit_per_code),
                "column": "sse" if code.startswith("6") else "szse",
                "tabName": "fulltext", "plate": "", "stock": "%s,%s" % (org_id, code),
                "searchkey": "", "secid": "", "category": "", "trade": "",
                "seDate": "%s~%s" % (since.strftime("%Y-%m-%d"), collected.strftime("%Y-%m-%d")),
                "sortName": "", "sortType": "", "isHLtitle": "true",
            }
            try:
                resp = client.post(_QUERY_URL, data=params)
                rows = (resp.json().get("announcements") or [])
            except Exception as e:
                log.warning("公告查询失败，跳过该 code", extra={"ctx": {"code": code, "error": str(e)[:160]}})
                continue
            for a in rows:
                ts = a.get("announcementTime")
                if not ts:
                    continue
                published = datetime.fromtimestamp(ts / 1000.0)
                if published < since:
                    continue
                title = "[%s] %s" % (a.get("secName", code), a.get("announcementTitle", "").strip())
                if not title.strip():
                    continue
                out.append(RawEvent(
                    source="cninfo",
                    source_id=str(a.get("announcementId") or a.get("adjunctUrl", "")),
                    title=title,
                    content=title + "（官方公告，详见 PDF 原文）",
                    url="http://static.cninfo.com.cn/" + a.get("adjunctUrl", "") if a.get("adjunctUrl") else None,
                    published_at=published,
                    collected_at=collected,
                    raw={"l0_bypass": True, "source_priority": 1},
                ))
        return out

    # NewsProvider 协议兼容（全量拉取不适用于公告：必须按自选股）
    def fetch(self, since: datetime) -> List[RawEvent]:  # pragma: no cover
        raise ProviderError("公告采集必须指定 codes（fetch_for_codes）")
