"""Domain: LLM request/result and analysis strategy descriptors."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


class StrategyTier(str, Enum):
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"


@dataclass
class LLMRequest:
    system: str
    user: str
    model: str
    temperature: float = 0.3
    max_tokens: int = 2000
    timeout_seconds: int = 60
    response_json: bool = True
    strategy: str = ""             # analysis strategy name (for routing/metering)


@dataclass
class LLMResult:
    ok: bool
    model: str
    data: Optional[Dict[str, Any]] = None          # parsed JSON payload (if ok)
    error: Optional[str] = None                    # error kind: transport/auth/parse/...
    raw_text: str = ""                             # original model output (audit)
    input_tokens: int = 0
    output_tokens: int = 0
    cost_cny: float = 0.0
    latency_ms: int = 0


@dataclass
class Strategy:
    name: str
    tier: StrategyTier
    schema_name: str            # e.g. "event_analysis_v1"
    prompt_file: str            # e.g. "event_analysis_v1.md"
    scope: str = "event"        # event | batch | aggregate
    max_input_events: int = 1


class ErrorKind(str, Enum):
    PARSE_ERROR = "parse_error"
    RETRY_EXHAUSTED = "retry_exhausted"
    BUDGET_EXCEEDED = "budget_exceeded"
    PROVIDER_ERROR = "provider_error"


@dataclass
class AnalysisOutcome:
    strategy: str
    ok: bool
    result: Optional[Dict[str, Any]] = None
    error_kind: Optional[str] = None
    analysis_id: Optional[int] = None
    input_tokens: int = 0
    output_tokens: int = 0
    cost_cny: float = 0.0
    warnings: list = field(default_factory=list)   # e.g. 剔除的幻觉引用
    cached: bool = False                           # UNIQUE 命中，未调用 LLM
