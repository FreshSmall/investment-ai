"""Deterministic mock LLM provider (zero external deps).

Default behaviours per strategy:
- ``classification``   : parse ``[event_id]`` tokens from the user message and emit
                         one classification per event, rotating a fixed label table.
- ``event_analysis``   : emit a schema-valid analysis citing the first event_id found.
- ``daily_summary``    : emit a schema-valid summary.

Inject ``overrides={strategy: [raw_text, ...]}`` (FIFO) to simulate malformed model
output — values that are valid dict passthrough, anything else becomes raw_text
for the engine's tolerant parser to deal with.
"""

from __future__ import annotations

import re
import time
from typing import Dict, List, Optional

from app.domain.analysis import LLMRequest, LLMResult
from app.providers.base import LLMProvider

_EVENT_ID_RE = re.compile(r"\[([0-9a-f]{16})\]")

_LABEL_ROUND = [
    (["ai_semiconductor"], "catalyst", "P0"),
    (["power_energy"], "policy", "P1"),
    (["robotics"], "order_demand", "P2"),
    ([], "other", "P3"),
]

_EVENT_ANALYSIS_TEMPLATE = {
    "summary": "mock 摘要：算力产业链出现重要边际变化，需求侧信号强于预期。",
    "facts": [{"text": "公司公告新增产能投放。", "source_event_id": "__EID__"}],
    "interpretations": ["产能扩张通常反映管理层对需求的信心。"],
    "hypotheses": ["若需求兑现，行业供需将在两个季度内趋紧。"],
    "affected_industries": ["ai_semiconductor"],
    "affected_companies": [{"name": "示例公司", "code": None, "channel": "订单弹性"}],
    "causal_chain": ["算力需求", "服务器出货", "核心零部件订单", "盈利预期上修"],
    "supporting_evidence": [{"text": "下游客户追加订单。", "source_event_id": "__EID__"}],
    "counter_evidence": [{"text": "同业也在扩产。", "source_event_id": "__EID__"}],
    "uncertainty": ["扩产落地节奏尚未验证。"],
    "follow_up_questions": ["跟踪下季度订单指引是否上修。"],
}

_DAILY_SUMMARY = {
    "summary": "mock 日度综述：三大行业无系统性变化，AI 算力链催化较多。",
    "highlights": [],
    "tomorrow_watch": ["关注龙头公司业绩指引", "跟踪板块资金流向"],
}


class MockLLMProvider(LLMProvider):
    name = "mock-llm"

    def __init__(self, overrides: Optional[Dict[str, List[str]]] = None) -> None:
        self._overrides: Dict[str, List[str]] = {k: list(v) for k, v in (overrides or {}).items()}
        self.calls: List[LLMRequest] = []
        self.total_cost_cny = 0.0

    def complete_json(self, req: LLMRequest) -> LLMResult:
        self.calls.append(req)
        t0 = time.monotonic()
        strategy = req.strategy or "generic"
        queue = self._overrides.get(strategy)
        if queue:
            raw = queue.pop(0)
        else:
            raw = self._default_response(strategy, req.user)

        if isinstance(raw, dict) and "__error__" in raw:  # 模拟 provider 级失败（超时/5xx）
            return LLMResult(ok=False, model=req.model, error=str(raw["__error__"]))

        if isinstance(raw, dict):
            data, text = raw, None
        else:
            data, text = None, str(raw)

        return LLMResult(
            ok=True,
            model=req.model,
            data=data,
            raw_text=text or "",
            input_tokens=max(1, len(req.system + req.user) // 4),
            output_tokens=64,
            cost_cny=0.0,
            latency_ms=int((time.monotonic() - t0) * 1000),
        )

    def call_count(self, strategy: Optional[str] = None) -> int:
        if strategy is None:
            return len(self.calls)
        return sum(1 for c in self.calls if (c.strategy or "generic") == strategy)

    def _default_response(self, strategy: str, user_text: str):
        if strategy == "classification":
            ids = _EVENT_ID_RE.findall(user_text)
            results = []
            for i, eid in enumerate(ids):
                sectors, event_type, importance = _LABEL_ROUND[i % len(_LABEL_ROUND)]
                results.append(
                    {
                        "event_id": eid,
                        "sectors": sectors,
                        "event_type": event_type,
                        "importance": importance,
                        "reason": "mock 分类理由",
                    }
                )
            return {"results": results}
        if strategy == "event_analysis":
            m = _EVENT_ID_RE.search(user_text)
            eid = m.group(1) if m else "0000000000000000"
            payload = dict(_EVENT_ANALYSIS_TEMPLATE)
            payload["facts"] = [dict(f, source_event_id=eid) for f in _EVENT_ANALYSIS_TEMPLATE["facts"]]
            payload["supporting_evidence"] = [
                dict(f, source_event_id=eid) for f in _EVENT_ANALYSIS_TEMPLATE["supporting_evidence"]
            ]
            payload["counter_evidence"] = [
                dict(f, source_event_id=eid) for f in _EVENT_ANALYSIS_TEMPLATE["counter_evidence"]
            ]
            return payload
        if strategy == "daily_summary":
            return dict(_DAILY_SUMMARY)
        return {"ok": True, "strategy": strategy}
