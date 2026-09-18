"""Domain: pipeline run/step bookkeeping models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class RunStatus(str, Enum):
    RUNNING = "running"
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
    DB_UNREACHABLE = "db_unreachable"
    SKIPPED = "skipped"
    BLOCKED = "blocked"  # V0.6 兜底频率门拦截（run 数超限），CLI 以 exit 0 结束


@dataclass
class StepResult:
    name: str
    ok: bool
    stats: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


@dataclass
class RunSummary:
    run_id: str
    command: str
    report_date: date
    status: RunStatus
    started_at: datetime
    finished_at: Optional[datetime] = None
    stats: Dict[str, Any] = field(default_factory=dict)
    failed_steps: List[str] = field(default_factory=list)

    def print_report(self) -> str:
        lines = [
            "=" * 52,
            "Pipeline Execution Report",
            "=" * 52,
            "run_id      : %s" % self.run_id,
            "command     : %s" % self.command,
            "date        : %s" % self.report_date,
            "status      : %s" % self.status.value,
            "duration    : %s" % (
                "%.1fs" % (self.finished_at - self.started_at).total_seconds()
                if self.finished_at else "n/a"
            ),
        ]
        if self.failed_steps:
            lines.append("failed_steps: %s" % ", ".join(self.failed_steps))
        for k in sorted(self.stats):
            lines.append("%-12s: %s" % (k, self.stats[k]))
        lines.append("=" * 52)
        return "\n".join(lines)
