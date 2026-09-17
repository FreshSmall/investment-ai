"""pytest 全局夹具与测试环境约定。

测试库切换在最顶部完成（先于任何 app.core.config 导入）：
DB_NAME 环境变量优先级高于 .env，因此 integration/e2e 全部落在 investment_ai_test。
"""

from __future__ import annotations

import os

os.environ["DB_NAME"] = "investment_ai_test"


def pytest_configure(config):
    """将需要测试库的目录标记收集顺序约束（unit 不依赖 DB）。"""
    config.addinivalue_line("markers", "db: 需要测试库的用例")


def _clean_tables(session):
    from app.db import models

    session.rollback()
    for table in reversed(models.Base.metadata.sorted_tables):
        session.execute(table.delete())
    session.commit()


def make_db_session():
    from app.db.engine import get_session_factory

    session = get_session_factory()()
    _clean_tables(session)
    return session


def make_pipeline_ctx(session, vault_path, frozen_time=None):
    """构造完整 StepContext（mock news + mock LLM + 指定 vault）。"""
    import uuid
    from datetime import date, datetime

    from app.analysis.engine import AnalysisEngine
    from app.core.config import load_app_config, load_sectors
    from app.db.repository import Repository
    from app.pipeline.context import StepContext
    from app.providers.llm.mock import MockLLMProvider
    from app.providers.llm.openai_compat import BudgetGuard
    from app.providers.news.mock import MockNewsProvider

    restore_clock = None
    if frozen_time is not None:
        import app.core.clock as clock_mod

        _orig_now = clock_mod.now
        clock_mod.now = lambda: frozen_time  # 全局冻结（collect 步骤依赖）
        restore_clock = lambda: setattr(clock_mod, "now", _orig_now)

    llm = MockLLMProvider()
    sectors = load_sectors()
    app_cfg = load_app_config()
    repo = Repository(session)
    from app.providers.market.tencent import MockMarketProvider

    ctx = StepContext(
        run_id=uuid.uuid4().hex,
        report_date=date(2026, 9, 17),
        settings=type("S", (), {"db_host": "h", "db_user": "u", "db_password": "p", "vault_path": None})(),
        app_cfg=app_cfg,
        sectors=sectors,
        repo=repo,
        engine=AnalysisEngine(llm=llm, repo=repo, sectors=sectors, app_cfg=app_cfg, budget=BudgetGuard(1000.0)),
        news_providers=[MockNewsProvider()],
        vault_path=vault_path,
        market_provider=MockMarketProvider(),
    )
    ctx.mock_llm = llm  # type: ignore[attr-defined]
    ctx.restore_clock = restore_clock or (lambda: None)  # type: ignore[attr-defined]
    return ctx
