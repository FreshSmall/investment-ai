"""Mock announcement provider: deterministic watched-company announcements."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import List

from app.domain.event import RawEvent

_SAMPLES = [
    ("300308", "中际旭创", "关于收到国外客户标志性订单的公告"),
    ("688017", "绿的谐波", "2026 年半年度业绩预增公告"),
    ("600089", "特变电工", "关于签署海外输变电项目合同的公告"),
]


class MockAnnouncementProvider:
    name = "mock-announcement"

    def health_check(self) -> bool:
        return True

    def fetch_for_codes(self, codes: List[str], since: datetime, limit_per_code: int = 15) -> List[RawEvent]:
        now = datetime(2026, 9, 17, 19, 0)
        out = []
        for code, name, title in _SAMPLES:
            if code not in codes:
                continue
            out.append(RawEvent(
                source="cninfo",
                source_id="mock-ann-%s" % code,
                title="[%s] %s" % (name, title),
                content="[%s] %s（官方公告，详见 PDF 原文）" % (name, title),
                url="http://static.cninfo.com.cn/mock/%s.pdf" % code,
                published_at=now - timedelta(hours=2),
                collected_at=now,
                raw={"l0_bypass": True, "source_priority": 1},
            ))
        return out
