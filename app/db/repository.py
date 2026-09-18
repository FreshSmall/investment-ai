"""Repository: the ONLY place SQL lives. Idempotency semantics live here (arch §8.3).

Every mutating method commits on success so short-lived CLI steps share one
consistent view per call.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from sqlalchemy import func, select
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.orm import Session

from app.core import clock
from app.core.log import get_logger
from app.db.models import (
    AnalysisRow,
    CompanyRow,
    DailySnapshotRow,
    EventRow,
    ReportRow,
    RunRow,
    ThesisEvidenceRow,
    ThesisRow,
    ThesisVersionRow,
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

    def recent_event_titles(self, hours: int) -> List[str]:
        """Titles of events published in the last N hours — near-dup comparison input."""
        cutoff = clock.now() - timedelta(hours=hours)
        stmt = select(EventRow.title).where(
            EventRow.published_at >= cutoff, EventRow.title.is_not(None)
        )
        return [t for t in self._s.scalars(stmt) if t]

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
        thesis_id: str = "",
        input_tokens: int = 0,
        output_tokens: int = 0,
        cost_cny: float = 0.0,
        quality_flag: Optional[str] = None,
        refresh: bool = False,
    ) -> Tuple[int, bool]:
        """Returns (analysis_id, created).

        Default: UNIQUE hit returns the existing row (result cache). With
        ``refresh=True`` (aggregate strategies on a twice-a-day schedule) the
        existing row is updated in place — the day's summary must reflect the
        full day, and rows never duplicate. ``thesis_id`` narrows the aggregate
        key for per-thesis strategies (thesis_review); '' for everything else.
        """
        stmt = select(AnalysisRow).where(
            AnalysisRow.strategy == strategy,
            AnalysisRow.prompt_version == prompt_version,
            AnalysisRow.thesis_id == thesis_id,
            *( [AnalysisRow.event_id == event_id] if event_id else [AnalysisRow.event_id.is_(None)] ),
            *( [AnalysisRow.report_date == report_date] if report_date else [AnalysisRow.report_date.is_(None)] ),
        )
        existing = self._s.scalars(stmt).first()
        if existing is not None:
            if refresh:
                existing.result_json = result
                existing.model = model
                existing.input_tokens = input_tokens
                existing.output_tokens = output_tokens
                existing.cost_cny = cost_cny
                self._s.commit()
            return existing.id, False
        row = AnalysisRow(
            event_id=event_id,
            report_date=report_date,
            thesis_id=thesis_id,
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

    def get_analysis_for_date(
        self, report_date: date, strategy: str, thesis_id: str = ""
    ) -> Optional[AnalysisRow]:
        stmt = select(AnalysisRow).where(
            AnalysisRow.report_date == report_date,
            AnalysisRow.strategy == strategy,
            AnalysisRow.thesis_id == thesis_id,
            AnalysisRow.event_id.is_(None),
        )
        return self._s.scalars(stmt).first()

    def analyses_for_date(self, report_date: date, strategy: str) -> List[AnalysisRow]:
        """All rows of one aggregate/thesis strategy on a date (V0.2)."""
        stmt = (
            select(AnalysisRow)
            .where(AnalysisRow.report_date == report_date, AnalysisRow.strategy == strategy)
            .order_by(AnalysisRow.thesis_id, AnalysisRow.event_id)
        )
        return list(self._s.scalars(stmt))

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

    def count_runs_since(self, since: datetime) -> int:
        """兜底频率门数据源：started_at 以来的 run 数（含崩溃未落终态的）。"""
        stmt = select(func.count()).select_from(RunRow).where(RunRow.started_at >= since)
        return int(self._s.scalar(stmt) or 0)

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

    # ---------------- companies (V0.2) ----------------

    def list_companies(self, watched_only: bool = True) -> List[CompanyRow]:
        stmt = select(CompanyRow).order_by(CompanyRow.code)
        if watched_only:
            stmt = stmt.where(CompanyRow.watched == 1)
        return list(self._s.scalars(stmt))

    def seed_companies(self, companies: Sequence[Dict[str, Any]]) -> int:
        """Idempotent seed from config/companies.yaml. Returns rows inserted."""
        inserted = 0
        for c in companies:
            stmt = mysql_insert(CompanyRow).values(
                code=c["code"], name=c["name"], sector=c.get("sector"),
                watched=1 if c.get("watched", True) else 0,
                profile={"text": c.get("profile", "")},
            )
            stmt = stmt.on_duplicate_key_update(
                name=stmt.inserted.name, sector=stmt.inserted.sector,
                profile=stmt.inserted.profile,
            )
            self._s.execute(stmt)
            inserted += 1
        self._s.commit()
        return inserted

    # ---------------- thesis review (V0.2) ----------------

    def save_thesis_evidence(
        self,
        thesis_id: str,
        review_date: date,
        items: List[Dict[str, Any]],
        analysis_id: Optional[int] = None,
    ) -> int:
        """Idempotent evidence write (PK thesis_id+event_id+review_date upsert).

        ``items``: [{"event_id", "direction", "weight", "note"}]. Returns rows
        processed; idempotency is asserted by unchanged table row counts.
        """
        inserted = 0
        for it in items:
            # 幂等：联合主键命中则更新 weight/note，不重复插行
            stmt = mysql_insert(ThesisEvidenceRow).values(
                thesis_id=thesis_id,
                event_id=it["event_id"],
                review_date=review_date,
                analysis_id=analysis_id,
                direction=it["direction"],
                weight=it.get("weight", "weak"),
                note=(it.get("note") or "")[:1000] or None,
            )
            stmt = stmt.on_duplicate_key_update(weight=stmt.inserted.weight, note=stmt.inserted.note)
            self._s.execute(stmt)
            inserted += 1
        self._s.commit()
        return inserted

    def day_direction(self, thesis_id: str, review_date: date) -> Optional[str]:
        """Dominant direction of one review day: 'supporting'/'contradicting'/None.

        A day counts as contradicting only when strong opposite evidence
        outnumbers strong supporting evidence (arch §7.4 — Devil Advocate
        output is capped at 'weak', so it can never flip a day alone).
        """
        stmt = select(ThesisEvidenceRow).where(
            ThesisEvidenceRow.thesis_id == thesis_id,
            ThesisEvidenceRow.review_date == review_date,
        )
        rows = list(self._s.scalars(stmt))
        if not rows:
            return None
        strong_con = sum(1 for r in rows if r.direction == "contradicting" and r.weight == "strong")
        strong_sup = sum(1 for r in rows if r.direction == "supporting" and r.weight == "strong")
        if strong_con > strong_sup:
            return "contradicting"
        if strong_sup > 0:
            return "supporting"
        return "neutral"

    def consecutive_contradicting_days(self, thesis_id: str, before_date: date, window: int = 3) -> int:
        """Length of the contradicting-day streak ending at ``before_date`` (inclusive)."""
        streak = 0
        d = before_date
        for _ in range(window):
            if self.day_direction(thesis_id, d) != "contradicting":
                break
            streak += 1
            d -= timedelta(days=1)
        return streak

    def apply_thesis_review(
        self,
        thesis_id: str,
        review_date: date,
        direction: str,
        evidence_items: List[Dict[str, Any]],
        analysis_id: Optional[int] = None,
        falsification_triggered: bool = False,
        weakened_streak: int = 3,
    ) -> Dict[str, Any]:
        """Persist one thesis_review outcome. Status transitions are CODE rules
        (arch §7.4) — the LLM only labels direction, never flips status.

        Transitions:
        - falsification_triggered            -> falsified (terminal, human restore)
        - N consecutive contradicting days   -> weakened
        - otherwise                          -> status unchanged
        Returns {"status_changed": bool, "new_status": str, "evidence_rows": int}.
        """
        self.save_thesis_evidence(thesis_id, review_date, evidence_items, analysis_id)
        thesis = self._s.get(ThesisRow, thesis_id)
        result = {"status_changed": False, "new_status": thesis.status if thesis else "", "evidence_rows": len(evidence_items)}
        if thesis is None:
            return result

        new_status: Optional[str] = None
        reason = ""
        if falsification_triggered and thesis.status in ("active", "weakened"):
            new_status, reason = "falsified", "证伪条件触发"
        elif (
            thesis.status == "active"
            and direction == "contradicting"
            and self.consecutive_contradicting_days(thesis_id, review_date, weakened_streak) >= weakened_streak
        ):
            new_status, reason = "weakened", "连续 %d 日强反证" % weakened_streak

        if new_status is not None:
            self._transition_thesis(thesis, new_status, changed_by="system", reason=reason)
            result.update(status_changed=True, new_status=new_status)
        return result

    def _transition_thesis(self, thesis: ThesisRow, new_status: str, changed_by: str, reason: str) -> None:
        """Bump version + snapshot the previous state (thesis_versions)."""
        snapshot = {
            "id": thesis.id, "title": thesis.title, "status": new_status,
            "core_hypothesis": thesis.core_hypothesis,
            "falsification_conditions": thesis.falsification_conditions,
            "key_metrics": thesis.key_metrics, "reason": reason,
        }
        thesis.status = new_status
        thesis.version += 1
        thesis.updated_at = clock.now()
        self._s.add(ThesisVersionRow(
            thesis_id=thesis.id, version=thesis.version, snapshot=snapshot, changed_by=changed_by,
        ))
        self._s.commit()

    def list_thesis_evidence(self, thesis_id: str, limit: int = 50) -> List[ThesisEvidenceRow]:
        stmt = (
            select(ThesisEvidenceRow)
            .where(ThesisEvidenceRow.thesis_id == thesis_id)
            .order_by(ThesisEvidenceRow.review_date.desc(), ThesisEvidenceRow.created_at.desc())
            .limit(limit)
        )
        return list(self._s.scalars(stmt))

    def get_thesis(self, thesis_id: str) -> Optional[ThesisRow]:
        return self._s.get(ThesisRow, thesis_id)

    # ---------------- market snapshots (V0.3) ----------------

    def upsert_snapshot(self, trade_date: date, snapshot: Dict[str, Any]) -> bool:
        """Idempotent daily market snapshot. Returns True when inserted first time."""
        stmt = select(DailySnapshotRow).where(DailySnapshotRow.trade_date == trade_date)
        row = self._s.scalars(stmt).first()
        if row is not None:
            row.snapshot = snapshot  # 22:00 收盘后覆盖 09:00 占位（若当日已有）
            self._s.commit()
            return False
        self._s.add(DailySnapshotRow(trade_date=trade_date, snapshot=snapshot))
        self._s.commit()
        return True

    def get_snapshot(self, trade_date: date) -> Optional[Dict[str, Any]]:
        row = self._s.get(DailySnapshotRow, trade_date)
        return row.snapshot if row is not None else None

    def get_prev_snapshot(self, before: date) -> Optional[Dict[str, Any]]:
        stmt = (
            select(DailySnapshotRow)
            .where(DailySnapshotRow.trade_date < before)
            .order_by(DailySnapshotRow.trade_date.desc())
            .limit(1)
        )
        row = self._s.scalars(stmt).first()
        return row.snapshot if row is not None else None

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
