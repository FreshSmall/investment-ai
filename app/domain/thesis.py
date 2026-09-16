"""Domain: thesis direction & status. NO scores, NO buy/sell recommendations (rule D10)."""

from __future__ import annotations

from enum import Enum


class Direction(str, Enum):
    SUPPORTING = "supporting"
    NEUTRAL = "neutral"
    CONTRADICTING = "contradicting"


class ThesisStatus(str, Enum):
    ACTIVE = "active"
    WEAKENED = "weakened"        # 连续多日强反证（规则流转，非 LLM 决定）
    FALSIFIED = "falsified"      # 触发证伪条件
    ARCHIVED = "archived"


class EvidenceWeight(str, Enum):
    STRONG = "strong"
    WEAK = "weak"                # Devil Advocate 产出上限（区分理论风险与实际反证）
