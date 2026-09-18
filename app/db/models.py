"""SQLAlchemy ORM models (V0.1: 7 tables, DDL per architecture §8)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    CHAR,
    DATE,
    DATETIME,
    DECIMAL,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.mysql import BIGINT, JSON, MEDIUMTEXT
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class EventRow(Base):
    __tablename__ = "events"

    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    source_id: Mapped[str] = mapped_column(String(64), nullable=False)
    source_url: Mapped[Optional[str]] = mapped_column(String(512))
    content_hash: Mapped[str] = mapped_column(CHAR(40), nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    content: Mapped[str] = mapped_column(MEDIUMTEXT, nullable=False)
    published_at: Mapped[datetime] = mapped_column(DATETIME, nullable=False)
    collected_at: Mapped[datetime] = mapped_column(DATETIME, nullable=False)
    sectors: Mapped[Optional[str]] = mapped_column(String(256))       # JSON array as string
    event_type: Mapped[Optional[str]] = mapped_column(String(32))
    importance: Mapped[Optional[str]] = mapped_column(String(4))
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'raw'"))
    raw_payload: Mapped[Optional[dict]] = mapped_column(JSON)

    __table_args__ = (
        Index("uk_source", "source", "source_id", unique=True),
        Index("uk_hash", "content_hash", unique=True),
        Index("idx_pub", "published_at"),
        Index("idx_work", "status", "importance"),
    )


class AnalysisRow(Base):
    __tablename__ = "analyses"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    event_id: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    report_date: Mapped[Optional[date]] = mapped_column(DATE, nullable=True)
    thesis_id: Mapped[str] = mapped_column(String(64), nullable=False, server_default=text("''"))  # V0.2: thesis_review 逐 thesis 缓存键；'' 哨兵=非 thesis 聚合（NULL 不参与唯一判重，故用空串）
    strategy: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(16), nullable=False)
    result_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    cost_cny: Mapped[float] = mapped_column(DECIMAL(10, 4), nullable=False, server_default=text("0"))
    quality_flag: Mapped[Optional[str]] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DATETIME, nullable=False, server_default=text("CURRENT_TIMESTAMP"))

    __table_args__ = (
        Index("uk_anal", "event_id", "strategy", "prompt_version", unique=True),
        Index("uk_agg", "report_date", "thesis_id", "strategy", "prompt_version", unique=True),
        Index("idx_strategy", "strategy", "created_at"),
    )


class ThesisRow(Base):
    __tablename__ = "theses"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    core_hypothesis: Mapped[str] = mapped_column(Text, nullable=False)
    falsification_conditions: Mapped[dict] = mapped_column(JSON, nullable=False)
    key_metrics: Mapped[Optional[dict]] = mapped_column(JSON)
    related_companies: Mapped[Optional[dict]] = mapped_column(JSON)
    related_sectors: Mapped[Optional[dict]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'active'"))
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_at: Mapped[datetime] = mapped_column(DATETIME, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    updated_at: Mapped[datetime] = mapped_column(DATETIME, nullable=False, server_default=text("CURRENT_TIMESTAMP"))


class ThesisVersionRow(Base):
    __tablename__ = "thesis_versions"

    thesis_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    changed_by: Mapped[str] = mapped_column(String(16), nullable=False)  # system | human
    created_at: Mapped[datetime] = mapped_column(DATETIME, nullable=False, server_default=text("CURRENT_TIMESTAMP"))


class ThesisEvidenceRow(Base):
    __tablename__ = "thesis_evidence"

    thesis_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    event_id: Mapped[str] = mapped_column(String(16), primary_key=True)
    review_date: Mapped[date] = mapped_column(DATE, primary_key=True)
    analysis_id: Mapped[Optional[int]] = mapped_column(BIGINT)
    direction: Mapped[str] = mapped_column(String(16), nullable=False)  # supporting/neutral/contradicting
    weight: Mapped[str] = mapped_column(String(8), nullable=False, server_default=text("'weak'"))
    note: Mapped[Optional[str]] = mapped_column(String(1024))
    created_at: Mapped[datetime] = mapped_column(DATETIME, nullable=False, server_default=text("CURRENT_TIMESTAMP"))


class ReportRow(Base):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    type: Mapped[str] = mapped_column(String(16), nullable=False)   # daily | weekly
    report_date: Mapped[date] = mapped_column(DATE, nullable=False)
    obsidian_path: Mapped[Optional[str]] = mapped_column(String(512))
    metrics_json: Mapped[Optional[dict]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DATETIME, nullable=False, server_default=text("CURRENT_TIMESTAMP"))

    __table_args__ = (
        Index("uk_report", "type", "report_date", unique=True),
    )


class RunRow(Base):
    __tablename__ = "runs"

    run_id: Mapped[str] = mapped_column(CHAR(36), primary_key=True)
    command: Mapped[str] = mapped_column(String(32), nullable=False)
    report_date: Mapped[date] = mapped_column(DATE, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DATETIME, nullable=False)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DATETIME)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'running'"))
    stats_json: Mapped[Optional[dict]] = mapped_column(JSON)

    __table_args__ = (
        Index("idx_date", "report_date", "status"),
    )


class CompanyRow(Base):
    """V0.2: watched companies (seed from config/companies.yaml)."""

    __tablename__ = "companies"

    code: Mapped[str] = mapped_column(String(12), primary_key=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    sector: Mapped[Optional[str]] = mapped_column(String(64))
    watched: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))  # tinyint
    profile: Mapped[Optional[dict]] = mapped_column(JSON)   # {"text": "..."} 前端展示与 prompt 共用


class DailySnapshotRow(Base):
    """V0.3: market snapshot per trade date (indices + sector boards)."""

    __tablename__ = "daily_snapshots"

    trade_date: Mapped[date] = mapped_column(DATE, primary_key=True)
    snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)


class LlmUsageRow(Base):
    """V0.6: 跨进程 LLM 日用量账本（兜底熔断数据面，一天一行）。

    2026-09-18 KeepAlive 事故：daily_budget_cny 原为进程内熔断，连环重启下每次清零。
    每次调用后由 UsageStore 原子累加（col=col+n），BudgetGuard.check() 读当日累计。
    """

    __tablename__ = "llm_usage_daily"

    usage_date: Mapped[date] = mapped_column(DATE, primary_key=True)
    calls: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    input_tokens: Mapped[int] = mapped_column(BIGINT, nullable=False, server_default=text("0"))
    output_tokens: Mapped[int] = mapped_column(BIGINT, nullable=False, server_default=text("0"))
    cost_cny: Mapped[float] = mapped_column(DECIMAL(12, 6), nullable=False, server_default=text("0"))
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
