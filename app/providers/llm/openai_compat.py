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
    """当日预算熔断。

    V0.6 起支持跨进程全局账本：注入 store（UsageStore）后，check() 读
    llm_usage_daily 当日累计、record() 每次调用后立即落账，连环重启的多个
    进程共享同一条熔断线。store 不可达时保守熔断（fail-closed）——DB 挂了
    分析结果也存不进去，继续付费没有意义。
    """

    def __init__(self, budget_cny: float, store=None, today_fn=None) -> None:
        self.budget = budget_cny
        self.total_cny = 0.0
        self.exceeded = False
        self._store = store
        self._today = today_fn if today_fn is not None else _default_today

    def check(self) -> None:
        if self._store is not None:
            try:
                spent = self._store.cost_for(self._today())
            except Exception as e:  # SQLAlchemyError 等：账本不可达 → 保守停
                raise BudgetExceeded("LLM 用量账本不可达（DB），保守熔断: %s" % str(e)[:80])
            if self.exceeded or spent >= self.budget:
                raise BudgetExceeded(
                    "当日 LLM 预算已用尽（%.2f/%.2f CNY），停止深度分析" % (spent, self.budget)
                )
        elif self.exceeded:  # 无 store：保持原进程内语义（记账后才可能超限）
            raise BudgetExceeded(
                "当日 LLM 预算已用尽（%.2f/%.2f CNY），停止深度分析" % (self.total_cny, self.budget)
            )

    def record(self, input_tokens: int, output_tokens: int, cost_cny: float) -> None:
        self.total_cny += cost_cny
        if self.total_cny >= self.budget:
            self.exceeded = True
        if self._store is not None:
            try:
                self._store.bump(self._today(), 1, input_tokens, output_tokens, cost_cny)
            except Exception:
                self.exceeded = True  # 账本写不进 → 下一次 check 必拦

    def add(self, cost_cny: float) -> None:
        """兼容旧调用（仅成本，无 token 明细）。"""
        self.record(0, 0, cost_cny)


def _default_today():
    from app.core import clock

    return clock.today()


class OpenAICompatLLMProvider(LLMProvider):
    name = "openai-compat"

    def __init__(
        self,
        base_url: str,
        api_key: str,
        price_lookup=None,
        transport: Optional[httpx.BaseTransport] = None,
        sleeper=None,
        min_call_interval: float = 0.0,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._api_key = api_key
        self._price_lookup = price_lookup or (lambda model: (0.0, 0.0))
        self._client = httpx.Client(transport=transport, timeout=60.0)
        self._sleep = sleeper if sleeper is not None else time.sleep
        self._min_interval = min_call_interval
        self._last_call = 0.0
        self._log = get_logger("llm")

    def _throttle(self) -> None:
        """GLM 免费档限流严格（短间隔连续调用 429），串行调用间保持最小间隔。"""
        if self._min_interval <= 0:
            return
        import time as _t

        wait = self._min_interval - (_t.monotonic() - self._last_call)
        if wait > 0:
            self._sleep(wait)
        self._last_call = _t.monotonic()

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
            self._throttle()
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
            choice = (data.get("choices") or [{}])[0]
            msg = choice.get("message") or {}
            content = msg.get("content") or ""
            finish_reason = choice.get("finish_reason")
            if not content.strip():
                # GLM 思考模型：reasoning 可能耗尽 max_tokens 导致正文为空
                hint = "（finish_reason=%s：若为 length，请上调该档位 max_tokens）" % finish_reason
                return self._error_result(req, "模型正文为空 %s" % hint, t0)
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
