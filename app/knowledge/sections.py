"""Section skeleton definitions for long-lived Obsidian documents (arch §9.2)."""

from __future__ import annotations

from typing import Dict, List

INDUSTRY_SECTION_TITLES: Dict[str, str] = {
    "overview": "行业概览",
    "supply_demand": "供需与价格",
    "catalysts": "催化剂",
    "risks": "核心风险",
    "metrics": "跟踪指标",
    "changelog": "变化记录",
}

THESIS_SECTIONS: List[str] = [
    "hypothesis", "evidence_for", "evidence_against", "falsification", "metrics", "latest_changes",
]

THESIS_SECTION_TITLES: Dict[str, str] = {
    "hypothesis": "核心假设",
    "evidence_for": "支持证据",
    "evidence_against": "反方证据",
    "falsification": "证伪条件",
    "metrics": "关键指标",
    "latest_changes": "最新变化",
}

DIRECTION_BADGES = {
    "supporting": "🟢 支持",
    "neutral": "⚪ 中性",
    "contradicting": "🔴 削弱",
}

THESIS_STATUS_BADGES = {
    "active": "🟢 active",
    "weakened": "🟡 weakened",
    "falsified": "🔴 falsified",
    "archived": "⚫ archived",
}
