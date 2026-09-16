from __future__ import annotations

from sqlalchemy import text

from app.db import models
from app.db.seed import seed_theses


def test_upgrade_created_all_tables(db_session) -> None:
    names = {row[0] for row in db_session.execute(text("SHOW TABLES")).fetchall()}
    expected = {
        "events", "analyses", "theses", "thesis_versions",
        "thesis_evidence", "reports", "runs",
    }
    assert expected <= names, "缺失表: %s" % (expected - names)


def test_events_idempotency_indexes(db_session) -> None:
    ddl = db_session.execute(text("SHOW CREATE TABLE events")).fetchone()[1]
    assert "uk_source" in ddl and "uk_hash" in ddl
    assert "UNIQUE" in ddl.upper()


def test_analyses_unique_keys(db_session) -> None:
    ddl = db_session.execute(text("SHOW CREATE TABLE analyses")).fetchone()[1]
    assert "uk_anal" in ddl and "uk_agg" in ddl


def test_seed_theses_idempotent(db_session) -> None:
    first = seed_theses(db_session)
    assert first == 4
    second = seed_theses(db_session)
    assert second == 0
    count = db_session.query(models.ThesisRow).count()
    assert count == 4
    versions = db_session.query(models.ThesisVersionRow).count()
    assert versions == 4
