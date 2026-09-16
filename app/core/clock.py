"""Injectable clock: every non-deterministic time source goes through here.

Tests monkeypatch ``app.core.clock.now`` to freeze time (deterministic rendering).
"""

from __future__ import annotations

import datetime as _dt
from typing import Optional


def now(tz: Optional[_dt.tzinfo] = None) -> _dt.datetime:
    return _dt.datetime.now(tz)


def today() -> _dt.date:
    return now().date()
