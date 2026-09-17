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

_THESIS_ID_RE = re.compile(r"## Thesis：.*?（([a-z0-9-]+)）")


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
        if strategy == "thesis_review":
            # 无相关事件 → neutral；有事件 → supporting（引用首个事件，weak）
            tm = _THESIS_ID_RE.search(user_text)
            thesis_id = tm.group(1) if tm else "unknown"
            em = _EVENT_ID_RE.search(user_text)
            if em is None:
                return {
                    "thesis_id": thesis_id, "direction": "neutral", "evidence": [],
                    "falsification_triggered": {"triggered": False, "condition_id": None, "reason": "今日无相关事件"},
                    "note": "mock 复盘：无相关事件，方向中性。",
                    "next_questions": ["mock：下期跟踪指标是否有更新数据"],
                }
            eid = em.group(1)
            return {
                "thesis_id": thesis_id, "direction": "supporting",
                "evidence": [
                    {"text": "mock 支持证据：产业链需求信号积极。", "source_event_id": eid,
                     "direction": "supporting", "weight": "strong"},
                ],
                "falsification_triggered": {"triggered": False, "condition_id": None, "reason": "无证伪信号"},
                "note": "mock 复盘：今日事件与假设方向一致。",
                "next_questions": ["mock：验证下季度数据是否延续"],
            }
        if strategy == "company_impact":
            m = _EVENT_ID_RE.search(user_text)
            eid = m.group(1) if m else "0000000000000000"
            payload = dict(_EVENT_ANALYSIS_TEMPLATE)
            payload["summary"] = "mock 公司影响：事件对命中公司构成订单端正面传导。"
            payload["affected_companies"] = [{"name": "中际旭创", "code": "300308", "channel": "AI CAPEX 订单弹性"}]
            payload["facts"] = [dict(f, source_event_id=eid) for f in _EVENT_ANALYSIS_TEMPLATE["facts"]]
            payload["supporting_evidence"] = [
                dict(f, source_event_id=eid) for f in _EVENT_ANALYSIS_TEMPLATE["supporting_evidence"]
            ]
            payload["counter_evidence"] = [
                dict(f, source_event_id=eid) for f in _EVENT_ANALYSIS_TEMPLATE["counter_evidence"]
            ]
            return payload
        if strategy == "market_review":
            return {
                "market_summary": "mock 市场复盘：指数放量上行，成长风格占优，科技板块与基本面催化互相印证。",
                "sector_moves": [
                    {"sector": "半导体", "direction": "up", "note": "订单催化驱动"},
                    {"sector": "房地产", "direction": "down", "note": "政策预期回落"},
                ],
                "style_note": "量能温和放大，风险偏好回升但未过热。",
                "risk_flags": ["缩量回落风险"],
                "tomorrow_watch": ["关注算力板块持续性"],
            }
        if strategy == "industry_update":
            # 前两个节标记更新，其余 changed=false 原样返回
            sections = []
            for name in ("overview", "supply_demand", "catalysts", "risks", "metrics"):
                changed = name in ("overview", "catalysts")
                sections.append({
                    "name": name,
                    "content": ("行业景气度上行：AI 需求驱动订单与产能双扩张（mock 更新）。"
                                if changed else "（待首次更新）"),
                    "changed": changed,
                    **({"based_on_event_ids": [eid] for eid in _EVENT_ID_RE.findall(user_text)[:1]} if changed else {}),
                })
            evs = _EVENT_ID_RE.findall(user_text)
            return {
                "sections": sections,
                "changelog_rows": (
                    [{"change": "催化剂：下游订单信号增强", "evidence_event_id": evs[0]}] if evs else []
                ),
            }
        return {"ok": True, "strategy": strategy}
