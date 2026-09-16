"""Repository: the ONLY place SQL lives. Idempotency semantics live here (arch §8.3).

Every mutating method commits on success so short-lived CLI steps share one
consistent view per call.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from sqlalchemy import select
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.orm import Session

from app.core.log import get_logger
from app.db.models import (
    AnalysisRow,
    EventRow,
    ReportRow,
    RunRow,
    ThesisRow,
)
from app.domain.event import EventStatus, Importance, NormalizedEvent
from app.domain.report import RunStatus

import json


@dataclass
class InsertStats:
    inserted: int = 0
    dup_source: int = 0   # (source, source_id) already present — same-source repeat
    dup_hash: int = 0     # content_hash collision — cross-source verbatim copy


class Repository:
    def __init__(self, session: Session) -> None:
        self._s = session
        self._log = get_logger("repo")

    # ---------------- events ----------------

    def upsert_events(self, events: Sequence[NormalizedEvent]) -> InsertStats:
        stats = InsertStats()
        for ev in events:
            stmt = (
                mysql_insert(EventRow)
                .values(
                    id=ev.event_id,
                    source=ev.source,
                    source_id=ev.source_id,
                    source_url=ev.url,
                    content_hash=ev.content_hash,
                    title=ev.title,
                    content=ev.content,
                    published_at=ev.published_at,
                    collected_at=ev.collected_at,
                    status=EventStatus.RAW.value,
                    raw_payload=ev.raw or None,
                )
                .prefix_with("IGNORE")
            )
            result = self._s.execute(stmt)
            if result.rowcount == 0:
                same_source = self._s.execute(
                    select(EventRow.id).where(EventRow.source == ev.source, EventRow.source_id == ev.source_id)
                ).scalar()
                if same_source:
                    stats.dup_source += 1
                else:
                    stats.dup_hash += 1
            else:
                stats.inserted += 1
        self._s.commit()
        return stats

    def get_events_for_classify(self, limit: Optional[int] = None) -> List[EventRow]:
        stmt = select(EventRow).where(
            EventRow.status.in_([EventStatus.RAW.value, EventStatus.UNCLASSIFIED.value])
        ).order_by(EventRow.published_at)
        if limit:
            stmt = stmt.limit(limit)
        return list(self._s.scalars(stmt))

    def mark_classified(
        self, event_id: str, sectors: List[str], event_type: str, importance: str
    ) -> None:
        row = self._s.get(EventRow, event_id)
        if row is None:
            return
        row.sectors = json.dumps(sectors, ensure_ascii=False)
        row.event_type = event_type
        row.importance = importance
        row.status = (
            EventStatus.ARCHIVED.value if importance == Importance.P3.value else EventStatus.CLASSIFIED.value
        )
        self._s.commit()

    def get_events_for_analysis(
        self, importances: Sequence[str] = ("P0", "P1"), limit: Optional[int] = None
    ) -> List[EventRow]:
        stmt = select(EventRow).where(
            EventRow.status == EventStatus.CLASSIFIED.value,
            EventRow.importance.in_(list(importances)),
        ).order_by(EventRow.published_at)
        if limit:
            stmt = stmt.limit(limit)
        return list(self._s.scalars(stmt))

    def mark_event_status(self, event_id: str, status: EventStatus) -> None:
        row = self._s.get(EventRow, event_id)
        if row is not None:
            row.status = status.value
            self._s.commit()

    def get_event(self, event_id: str) -> Optional[EventRow]:
        return self._s.get(EventRow, event_id)

    def get_report_events(self, report_date: date) -> List[EventRow]:
        """P0/P1 analyzed events for the daily report.

        Window: published_at >= report_date-1 12:00 — deliberately overlaps the
        previous day so late-collected items are never silently dropped
        (re-shown beats missing; documented trade-off).
        """
        window_start = datetime.combine(report_date - timedelta(days=1), datetime.min.time()) + timedelta(hours=12)
        stmt = (
            select(EventRow)
            .where(
                EventRow.status == EventStatus.ANALYZED.value,
                EventRow.importance.in_(["P0", "P1"]),
                EventRow.published_at >= window_start,
            )
            .order_by(EventRow.published_at)
        )
        return list(self._s.scalars(stmt))

    # ---------------- analyses ----------------

    def save_analysis(
        self,
        strategy: str,
        model: str,
        prompt_version: str,
        result: Dict[str, Any],
        event_id: Optional[str] = None,
        report_date: Optional[date] = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cost_cny: float = 0.0,
        quality_flag: Optional[str] = None,
    ) -> Tuple[int, bool]:
        """Returns (analysis_id, created). UNIQUE hit returns the existing row id."""
        stmt = select(AnalysisRow).where(
            AnalysisRow.strategy == strategy,
            AnalysisRow.prompt_version == prompt_version,
            *( [AnalysisRow.event_id == event_id] if event_id else [AnalysisRow.event_id.is_(None)] ),
            *( [AnalysisRow.report_date == report_date] if report_date else [AnalysisRow.report_date.is_(None)] ),
        )
        existing = self._s.scalars(stmt).first()
        if existing is not None:
            return existing.id, False
        row = AnalysisRow(
            event_id=event_id,
            report_date=report_date,
            strategy=strategy,
            model=model,
            prompt_version=prompt_version,
            result_json=result,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_cny=cost_cny,
            quality_flag=quality_flag,
        )
        self._s.add(row)
        self._s.commit()
        return row.id, True

    def get_analysis_for_event(self, event_id: str, strategy: str) -> Optional[AnalysisRow]:
        stmt = select(AnalysisRow).where(AnalysisRow.event_id == event_id, AnalysisRow.strategy == strategy)
        return self._s.scalars(stmt).first()

    def get_analysis_for_date(self, report_date: date, strategy: str) -> Optional[AnalysisRow]:
        stmt = select(AnalysisRow).where(
            AnalysisRow.report_date == report_date, AnalysisRow.strategy == strategy
        )
        return self._s.scalars(stmt).first()

    def list_recent_analyses(self, strategy: str, limit: int = 30) -> List[AnalysisRow]:
        stmt = (
            select(AnalysisRow)
            .where(AnalysisRow.strategy == strategy)
            .order_by(AnalysisRow.created_at.desc())
            .limit(limit)
        )
        return list(self._s.scalars(stmt))

    def analyses_for_events(self, event_ids: Sequence[str], strategy: str) -> Dict[str, AnalysisRow]:
        if not event_ids:
            return {}
        stmt = select(AnalysisRow).where(
            AnalysisRow.event_id.in_(list(event_ids)), AnalysisRow.strategy == strategy
        )
        return {row.event_id: row for row in self._s.scalars(stmt)}

    # ---------------- runs ----------------

    def create_run(self, run_id: str, command: str, report_date: date, started_at: datetime) -> None:
        self._s.add(RunRow(run_id=run_id, command=command, report_date=report_date, started_at=started_at, status=RunStatus.RUNNING.value))
        self._s.commit()

    def latest_run(self, report_date: date, command: str = "daily") -> Optional[RunRow]:
        stmt = (
            select(RunRow)
            .where(RunRow.report_date == report_date, RunRow.command == command)
            .order_by(RunRow.started_at.desc())
            .limit(1)
        )
        return self._s.scalars(stmt).first()

    def finish_run(
        self, run_id: str, status: RunStatus, finished_at: datetime, stats: Dict[str, Any]
    ) -> None:
        row = self._s.get(RunRow, run_id)
        if row is not None:
            row.status = status.value
            row.finished_at = finished_at
            row.stats_json = stats
            self._s.commit()

    def list_recent_runs(self, days: int = 7) -> List[RunRow]:
        return list(
            self._s.scalars(
                select(RunRow).order_by(RunRow.started_at.desc()).limit(days * 4)
            )
        )

    # ---------------- reports ----------------

    def upsert_report(
        self, report_type: str, report_date: date, obsidian_path: Optional[str], metrics: Dict[str, Any]
    ) -> None:
        stmt = select(ReportRow).where(ReportRow.type == report_type, ReportRow.report_date == report_date)
        row = self._s.scalars(stmt).first()
        if row is None:
            row = ReportRow(type=report_type, report_date=report_date)
            self._s.add(row)
        row.obsidian_path = obsidian_path
        row.metrics_json = metrics
        self._s.commit()

    # ---------------- theses ----------------

    def list_theses(self, active_only: bool = False) -> List[ThesisRow]:
        stmt = select(ThesisRow).order_by(ThesisRow.id)
        if active_only:
            stmt = stmt.where(ThesisRow.status == "active")
        return list(self._s.scalars(stmt))

    def day_metrics(self, report_date: date) -> Dict[str, Any]:
        """Aggregate stats for the pipeline execution report (observability §11)."""
        rows = list(
            self._s.scalars(
                select(AnalysisRow).where(AnalysisRow.report_date == report_date)
            )
        )
        event_rows = list(
            self._s.scalars(
                select(EventRow).where(EventRow.collected_at >= datetime.combine(report_date, datetime.min.time()))
            )
        )
        by_importance: Dict[str, int] = {}
        for e in event_rows:
            if e.importance:
                by_importance[e.importance] = by_importance.get(e.importance, 0) + 1
        return {
            "events_new_today": len(event_rows),
            "by_importance": by_importance,
            "analyses_today": len(rows),
            "input_tokens": sum(r.input_tokens for r in rows),
            "output_tokens": sum(r.output_tokens for r in rows),
            "estimated_cost_cny": float(sum(float(r.cost_cny) for r in rows)),
        }
