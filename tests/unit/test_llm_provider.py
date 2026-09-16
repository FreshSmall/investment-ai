from __future__ import annotations

import json
from typing import List

import httpx
import pytest

from app.domain.analysis import LLMRequest
from app.providers.llm.openai_compat import (
    BudgetExceeded,
    BudgetGuard,
    LLMClientError,
    OpenAICompatLLMProvider,
)


class NoSleep:
    def __init__(self) -> None:
        self.calls: List[float] = []

    def __call__(self, s: float) -> None:
        self.calls.append(s)


def make_provider(handler, prices=(4.0, 16.0)):
    return OpenAICompatLLMProvider(
        base_url="https://api.test/v1",
        api_key="sk-test",
        price_lookup=lambda m: prices,
        transport=httpx.MockTransport(handler),
        sleeper=NoSleep(),
    )


def _req(strategy="event_analysis") -> LLMRequest:
    return LLMRequest(system="sys", user="user", model="deepseek-chat", strategy=strategy)


def _ok_body(content='{"summary": "ok"}', in_tok=100, out_tok=50) -> dict:
    return {
        "choices": [{"message": {"content": content}}],
        "usage": {"prompt_tokens": in_tok, "completion_tokens": out_tok},
    }


def test_request_body_json_mode_and_metering() -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content.decode())
        captured["auth"] = request.headers.get("Authorization")
        return httpx.Response(200, json=_ok_body())

    provider = make_provider(handler)
    result = provider.complete_json(_req())

    assert captured["body"]["response_format"] == {"type": "json_object"}
    assert captured["body"]["model"] == "deepseek-chat"
    assert captured["auth"] == "Bearer sk-test"
    assert result.ok and result.input_tokens == 100 and result.output_tokens == 50
    # 100/1M*4 + 50/1M*16 = 0.0004 + 0.0008
    assert abs(result.cost_cny - 0.0012) < 1e-6
    assert result.raw_text == '{"summary": "ok"}'


def test_401_fails_immediately_no_retry() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(401, text="unauthorized")

    with pytest.raises(LLMClientError, match="鉴权失败"):
        make_provider(handler).complete_json(_req())
    assert calls["n"] == 1


def test_429_retries_then_succeeds() -> None:
    state = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["n"] += 1
        if state["n"] == 1:
            return httpx.Response(429, text="rate limited")
        return httpx.Response(200, json=_ok_body())

    provider = make_provider(handler)
    result = provider.complete_json(_req())
    assert result.ok and state["n"] == 2


def test_transport_error_retries_exhausted() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timeout")

    result = make_provider(handler).complete_json(_req())
    assert not result.ok and "transport" in (result.error or "")


def test_budget_guard_flow() -> None:
    guard = BudgetGuard(budget_cny=0.001)
    guard.add(0.0005)
    guard.check()  # 未超
    guard.add(0.001)
    with pytest.raises(BudgetExceeded):
        guard.check()
