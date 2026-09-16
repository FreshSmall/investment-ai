from __future__ import annotations

from typing import List, Optional

import httpx
import pytest

from app.core.http import EastmoneyRateLimited, HttpClient, HttpError, TIER_EASTMONEY


class SleepSpy:
    def __init__(self) -> None:
        self.calls: List[float] = []

    def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


def make_client(handler, tier: str = "default", sleeper: Optional[SleepSpy] = None) -> HttpClient:
    transport = httpx.MockTransport(handler)
    return HttpClient(tier=tier, transport=transport, sleeper=sleeper or SleepSpy())


def test_success_no_retry() -> None:
    spy = SleepSpy()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": 1})

    resp = make_client(handler, sleeper=spy).get("https://x.test/api")
    assert resp.json() == {"ok": 1}
    assert spy.calls == []


def test_5xx_retries_then_success() -> None:
    state = {"n": 0}
    spy = SleepSpy()

    def handler(request: httpx.Request) -> httpx.Response:
        state["n"] += 1
        if state["n"] < 3:
            return httpx.Response(502)
        return httpx.Response(200, json={"ok": 1})

    resp = make_client(handler, sleeper=spy).get("https://x.test/api")
    assert state["n"] == 3
    assert spy.calls == [2.0, 4.0]  # 指数退避
    _ = resp


def test_retries_exhausted_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    with pytest.raises(HttpError, match="重试 3 次"):
        make_client(handler).get("https://x.test/api")


def test_404_fails_immediately() -> None:
    state = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["n"] += 1
        return httpx.Response(404)

    with pytest.raises(HttpError, match="404"):
        make_client(handler).get("https://x.test/api")
    assert state["n"] == 1


def test_eastmoney_403_no_retry() -> None:
    state = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["n"] += 1
        return httpx.Response(403)

    with pytest.raises(EastmoneyRateLimited):
        make_client(handler, tier=TIER_EASTMONEY).get("https://x.test/api")
    assert state["n"] == 1  # 风控信号：绝不重试


def test_throttle_interval_between_calls() -> None:
    spy = SleepSpy()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200)

    client = make_client(handler, tier=TIER_EASTMONEY, sleeper=spy)
    client.get("https://x.test/a")
    client.get("https://x.test/b")
    # 第一次不 sleep；第二次因 _last_call 刚更新，等待 >= 1s（含抖动下限）
    assert len(spy.calls) == 1
    assert spy.calls[0] >= 1.0


def test_default_tier_no_throttle() -> None:
    spy = SleepSpy()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200)

    client = make_client(handler, tier="default", sleeper=spy)
    client.get("https://x.test/a")
    client.get("https://x.test/b")
    assert spy.calls == []
