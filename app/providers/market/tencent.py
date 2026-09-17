"""TencentMarketProvider: index quotes (qt.gtimg.cn, no-IP-ban) + sector board
ranking (eastmoney clist, rate-limited tier). Endpoint recipes verified by the
local a-stock-data skill V3.4 (2026-07).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List

from app.core.http import get_client
from app.core.log import get_logger
from app.providers.base import MarketProvider

# (tencent symbol, display name)
_INDICES = [
    ("sh000001", "上证指数"),
    ("sh000300", "沪深300"),
    ("sz399006", "创业板指"),
    ("sh000688", "科创50"),
]

_EM_SECTOR_URL = "https://push2.eastmoney.com/api/qt/clist/get"


def _f(v: str) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


class TencentMarketProvider(MarketProvider):
    name = "tencent"

    def health_check(self) -> bool:
        try:
            quotes = self._fetch_indices()
            return len(quotes) >= 2
        except Exception:
            return False

    def fetch_daily(self, trade_date: date) -> Dict[str, Any]:
        """Snapshot: indices + top/bottom sectors. Raises on total failure."""
        indices = self._fetch_indices()
        sectors = self._fetch_sectors()
        return {
            "trade_date": str(trade_date),
            "collected_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "indices": indices,
            "sectors_top": sectors["top"],
            "sectors_bottom": sectors["bottom"],
        }

    # ---------------- indices (tencent, GBK, no ban) ----------------

    def _fetch_indices(self) -> List[Dict[str, Any]]:
        url = "https://qt.gtimg.cn/q=" + ",".join(sym for sym, _ in _INDICES)
        resp = get_client("default").get(url)
        data = resp.content.decode("gbk", errors="ignore")
        out: List[Dict[str, Any]] = []
        for line in data.strip().split(";"):
            if "=" not in line or '"' not in line:
                continue
            vals = line.split('"')[1].split("~")
            if len(vals) < 39:
                continue
            out.append({
                "code": line.split("=")[0].split("_")[-1],
                "name": vals[1],
                "close": _f(vals[3]),
                "change_pct": _f(vals[32]),
                "amount_yi": round(_f(vals[37]) / 10000.0, 1),  # 万 -> 亿
            })
        return out

    # ---------------- sector boards (eastmoney clist, throttled) ----------------

    def _fetch_sectors(self, top_n: int = 5) -> Dict[str, List[Dict[str, Any]]]:
        params = {
            "pn": "1", "pz": "100", "po": "1", "np": "1",
            "fltt": "2", "invt": "2", "fid": "f3",
            "fs": "m:90+t:2",
            "fields": "f3,f12,f14,f104,f105,f140",
        }
        resp = get_client("eastmoney").get(_EM_SECTOR_URL, params=params)
        items = ((resp.json() or {}).get("data") or {}).get("diff") or []
        rows: List[Dict[str, Any]] = []
        for it in items:
            rows.append({
                "name": it.get("f14", ""),
                "change_pct": it.get("f3", 0),
                "up": it.get("f104", 0),
                "down": it.get("f105", 0),
                "leader": it.get("f140", ""),
            })
        rows = [r for r in rows if isinstance(r["change_pct"], (int, float))]
        rows.sort(key=lambda r: r["change_pct"], reverse=True)
        return {"top": rows[:top_n], "bottom": list(reversed(rows[-top_n:]))}


class MockMarketProvider(MarketProvider):
    name = "mock-market"

    def __init__(self) -> None:
        self._log = get_logger("mock.market")

    def health_check(self) -> bool:
        return True

    def fetch_daily(self, trade_date: date) -> Dict[str, Any]:
        return {
            "trade_date": str(trade_date),
            "collected_at": "2026-09-17 22:00",
            "indices": [
                {"code": "sh000001", "name": "上证指数", "close": 3250.0, "change_pct": 0.85, "amount_yi": 6200.0},
                {"code": "sh000300", "name": "沪深300", "close": 3900.0, "change_pct": 1.02, "amount_yi": 3100.0},
                {"code": "sz399006", "name": "创业板指", "close": 2100.0, "change_pct": 1.40, "amount_yi": 1800.0},
                {"code": "sh000688", "name": "科创50", "close": 980.0, "change_pct": 2.10, "amount_yi": 520.0},
            ],
            "sectors_top": [
                {"name": "半导体", "change_pct": 4.2, "up": 80, "down": 5, "leader": "中际旭创"},
                {"name": "通信设备", "change_pct": 3.1, "up": 60, "down": 8, "leader": "新易盛"},
            ],
            "sectors_bottom": [
                {"name": "房地产", "change_pct": -1.2, "up": 10, "down": 70, "leader": "万科A"},
                {"name": "银行", "change_pct": -0.4, "up": 12, "down": 30, "leader": "工商银行"},
            ],
        }
