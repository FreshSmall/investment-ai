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
    from app.analysis.engine import AnalysisEngine
    from app.core.config import load_app_config, load_sectors
    from app.db.repository import Repository
    from app.pipeline.context import StepContext
    from app.providers.llm.mock import MockLLMProvider
    from app.providers.llm.openai_compat import BudgetGuard
    from app.providers.news.mock import MockNewsProvider

    frozen = datetime(2026, 9, 17, 20, 0)
    monkeypatch.setattr("app.pipeline.steps.collect.clock.now", lambda: frozen)

    llm = MockLLMProvider()
    ctx = StepContext(
        run_id=uuid.uuid4().hex,
        report_date=date(2026, 9, 17),
        settings=type("S", (), {"db_host": "h", "db_user": "u", "db_password": "p", "vault_path": None})(),
        app_cfg=load_app_config(),
        sectors=load_sectors(),
        repo=Repository(db_session),
        engine=AnalysisEngine(
            llm=llm, repo=Repository(db_session), sectors=load_sectors(),
            app_cfg=load_app_config(), budget=BudgetGuard(1000.0),
        ),
        news_providers=[MockNewsProvider()],
        vault_path=tmp_path,
    )
    ctx.mock_llm = llm  # type: ignore[attr-defined]
    return ctx
