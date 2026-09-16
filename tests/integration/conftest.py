"""Integration test fixtures: real MySQL test database (investment_ai_test)."""

from __future__ import annotations

import uuid
from datetime import date, datetime

import pytest
from alembic import command
from alembic.config import Config


@pytest.fixture(scope="session")
def migrated_db():
    cfg = Config("alembic.ini")
    command.upgrade(cfg, "head")
    yield


@pytest.fixture()
def db_session(migrated_db):
    from app.db import models
    from app.db.engine import get_session_factory

    session = get_session_factory()()
    yield session
    session.rollback()
    for table in reversed(models.Base.metadata.sorted_tables):
        session.execute(table.delete())
    session.commit()
    session.close()


@pytest.fixture()
def pipeline_ctx(db_session, tmp_path, monkeypatch):
    """Full StepContext on the test DB: mock news + mock LLM + tmp vault + frozen clock."""
    from datetime import datetime

    from tests.conftest import make_pipeline_ctx

    frozen = datetime(2026, 9, 17, 20, 0)
    ctx = make_pipeline_ctx(db_session, tmp_path, frozen_time=frozen)
    yield ctx
    ctx.restore_clock()
