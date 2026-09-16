"""OpenAI-compatible LLM provider (covers GLM / DeepSeek / Qwen / Claude-compatible gateways).

- JSON mode via response_format; usage metered per call; cost computed from settings prices.
- 4xx (auth/quota) fails immediately; transport errors / 429 / 5xx retried twice with backoff.
- BudgetGuard stops deep analysis once the daily budget is exceeded (cost circuit-breaker).

NOTE: JSON *parsing* is NOT done here — the Analysis Engine owns tolerant parsing
(mock providers may return dict passthrough, real ones return raw_text).
"""

from __future__ import annotations

import time
from typing import Optional

import httpx

from app.core.log import get_logger
from app.domain.analysis import LLMRequest, LLMResult
from app.providers.base import LLMProvider

_MAX_ATTEMPTS = 3


class LLMClientError(Exception):
    """Non-retryable client failure (bad key, quota, bad request)."""


class BudgetExceeded(Exception):
    """Daily LLM budget exhausted — upper layers should degrade, not crash."""


class BudgetGuard:
    def __init__(self, budget_cny: float) -> None:
        self.budget = budget_cny
        self.total_cny = 0.0
        self.exceeded = False

    def add(self, cost_cny: float) -> None:
        self.total_cny += cost_cny
        if self.total_cny >= self.budget:
            self.exceeded = True

    def check(self) -> None:
        if self.exceeded:
            raise BudgetExceeded(
                "当日 LLM 预算已用尽（%.2f/%.2f CNY），停止深度分析" % (self.total_cny, self.budget)
            )


class OpenAICompatLLMProvider(LLMProvider):
    name = "openai-compat"

    def __init__(
        self,
        base_url: str,
        api_key: str,
        price_lookup=None,
        transport: Optional[httpx.BaseTransport] = None,
        sleeper=None,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._api_key = api_key
        self._price_lookup = price_lookup or (lambda model: (0.0, 0.0))
        self._client = httpx.Client(transport=transport, timeout=60.0)
        self._sleep = sleeper if sleeper is not None else time.sleep
        self._log = get_logger("llm")

    def complete_json(self, req: LLMRequest) -> LLMResult:
        body: dict = {
            "model": req.model,
            "messages": [
                {"role": "system", "content": req.system},
                {"role": "user", "content": req.user},
            ],
            "temperature": req.temperature,
            "max_tokens": req.max_tokens,
        }
        if req.response_json:
            body["response_format"] = {"type": "json_object"}

        headers = {
            "Authorization": "Bearer %s" % self._api_key,
            "Content-Type": "application/json",
        }

        t0 = time.monotonic()
        last_error: Optional[str] = None
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                resp = self._client.post(
                    self._base + "/chat/completions",
                    json=body,
                    headers=headers,
                    timeout=req.timeout_seconds,
                )
            except httpx.TransportError as e:
                last_error = "transport: %s" % e
                if attempt == _MAX_ATTEMPTS:
                    return self._error_result(req, last_error, t0)
                self._sleep(2 ** attempt)
                continue

            if resp.status_code in (401, 403):
                raise LLMClientError("LLM 鉴权失败 HTTP %d（检查 API Key/配额）" % resp.status_code)
            if resp.status_code == 429 or resp.status_code >= 500:
                last_error = "HTTP %d" % resp.status_code
                if attempt == _MAX_ATTEMPTS:
                    return self._error_result(req, last_error, t0)
                self._sleep(2 ** attempt)
                continue
            if 400 <= resp.status_code < 500:
                raise LLMClientError(
                    "LLM HTTP %d: %s" % (resp.status_code, resp.text[:200])
                )

            data = resp.json()
            content = (((data.get("choices") or [{}])[0].get("message")) or {}).get("content", "")
            usage = data.get("usage") or {}
            input_tokens = int(usage.get("prompt_tokens", 0))
            output_tokens = int(usage.get("completion_tokens", 0))
            pin, pout = self._price_lookup(req.model)
            cost = input_tokens / 1e6 * pin + output_tokens / 1e6 * pout
            return LLMResult(
                ok=True,
                model=req.model,
                raw_text=content,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_cny=round(cost, 6),
                latency_ms=int((time.monotonic() - t0) * 1000),
            )
        return self._error_result(req, last_error or "unknown", t0)

    def _error_result(self, req: LLMRequest, error: str, t0: float) -> LLMResult:
        return LLMResult(
            ok=False, model=req.model, error=error,
            latency_ms=int((time.monotonic() - t0) * 1000),
        )
