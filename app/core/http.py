"""Unified outbound HTTP client: per-host-tier throttling + retry + UA.

Tiers (architecture §12.1, mirrors the a-stock-data anti-ban rules):
- ``default``   : no throttle, retry on transient errors
- ``cls``       : >=1s serial interval (财联社电报)
- ``eastmoney`` : >=1s + jitter; HTTP 403 is a rate-control signal -> NO retry

Retry policy: 3 attempts, exponential backoff 2/4/8s on transport errors, 429 and 5xx.
Other 4xx fail immediately.
"""

from __future__ import annotations

import random
import time
from typing import Dict, List, Optional, Tuple

import httpx

from app.core.log import get_logger

DEFAULT_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko)"

TIER_DEFAULT = "default"
TIER_CLS = "cls"
TIER_EASTMONEY = "eastmoney"

# tier -> (min_interval_seconds, max_jitter_seconds)
_TIER_SPEC: Dict[str, Tuple[float, float]] = {
    TIER_DEFAULT: (0.0, 0.0),
    TIER_CLS: (1.0, 0.3),
    TIER_EASTMONEY: (1.0, 0.4),
}

_MAX_RETRIES = 3


class HttpError(Exception):
    """Non-retryable or retries-exhausted HTTP failure."""


class EastmoneyRateLimited(HttpError):
    """403 from eastmoney: back off, do NOT hammer (风控信号)."""


class HttpClient:
    def __init__(
        self,
        tier: str = TIER_DEFAULT,
        timeout: float = 15.0,
        transport: Optional[httpx.BaseTransport] = None,
        sleeper: Optional[callable] = None,
    ) -> None:
        self.tier = tier
        self.interval, self.jitter = _TIER_SPEC.get(tier, _TIER_SPEC[TIER_DEFAULT])
        self._sleep = sleeper if sleeper is not None else time.sleep
        self._client = httpx.Client(
            transport=transport,
            timeout=timeout,
            headers={"User-Agent": DEFAULT_UA},
        )
        self._last_call = 0.0
        self._log = get_logger("http")

    def get(
        self,
        url: str,
        params: Optional[Dict[str, object]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> httpx.Response:
        last_error: Optional[str] = None
        for attempt in range(1, _MAX_RETRIES + 1):
            self._throttle()
            try:
                resp = self._client.get(url, params=params, headers=headers)
            except httpx.TransportError as e:
                last_error = "transport: %s" % e
                if attempt == _MAX_RETRIES:
                    break
                self._backoff(attempt)
                continue

            if resp.status_code == 403 and self.tier == TIER_EASTMONEY:
                raise EastmoneyRateLimited("东财 403 风控（不重试）: %s" % url)

            if resp.status_code == 429 or 500 <= resp.status_code < 600:
                last_error = "HTTP %d" % resp.status_code
                if attempt == _MAX_RETRIES:
                    break
                self._backoff(attempt)
                continue

            if resp.status_code >= 400:
                raise HttpError("HTTP %d: %s %s" % (resp.status_code, url, resp.text[:200]))
            return resp

        raise HttpError("重试 %d 次后仍失败 (%s): %s [%s]" % (_MAX_RETRIES, last_error, url, self.tier))

    def close(self) -> None:
        self._client.close()

    def _throttle(self) -> None:
        if self.interval <= 0:
            return
        elapsed = time.monotonic() - self._last_call
        wait = self.interval - elapsed
        if wait > 0:
            self._sleep(wait + (random.uniform(0, self.jitter) if self.jitter else 0.0))
        self._last_call = time.monotonic()

    def _backoff(self, attempt: int) -> None:
        delay = float(2 ** attempt)  # 2, 4, 8
        self._log.info("HTTP 重试", extra={"ctx": {"tier": self.tier, "attempt": attempt, "backoff_s": delay}})
        self._sleep(delay)


_clients: Dict[str, HttpClient] = {}


def get_client(tier: str = TIER_DEFAULT) -> HttpClient:
    """Process-wide shared client per tier (keep-alive reuse, serial throttling)."""
    if tier not in _clients:
        _clients[tier] = HttpClient(tier=tier)
    return _clients[tier]


def reset_clients() -> None:
    """Test hook."""
    for c in _clients.values():
        c.close()
    _clients.clear()
