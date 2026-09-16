"""CLI 集成测试（subprocess 级，mock providers + 测试库 + tmp vault）。"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _clean_test_db() -> None:
    """CLI subprocess 不经过 db_session fixture —— 显式清表保证跨运行隔离。"""
    from app.core.config import get_settings
    from app.db.engine import build_database_url
    from sqlalchemy import create_engine, text

    engine = create_engine(build_database_url(get_settings()))
    with engine.connect() as conn:
        for table in ("runs", "reports", "analyses", "thesis_evidence",
                      "thesis_versions", "theses", "events"):
            conn.execute(text("DELETE FROM %s" % table))
        conn.commit()
    engine.dispose()


import pytest


@pytest.fixture(autouse=True)
def clean_db():
    _clean_test_db()
    yield
    _clean_test_db()


def run_cli(*args: str, vault: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.update({
        "DB_NAME": "investment_ai_test",
        "IAI_VAULT_PATH": str(vault),
        "IAI_NO_NOTIFY": "1",
    })
    return subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "main.py"), *args],
        capture_output=True, text=True, env=env, cwd=str(PROJECT_ROOT), timeout=120,
    )


def test_daily_mock_e2e_and_skip(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()

    first = run_cli("daily", "--providers", "mock", "--date", "2026-09-17", vault=vault)
    assert first.returncode == 0, first.stderr
    assert "Pipeline Execution Report" in first.stdout
    assert "status      : success" in first.stdout

    daily = vault / "Daily" / "2026-09-17.md"
    assert daily.exists() and "来源: cls" in daily.read_text(encoding="utf-8")

    # 幂等 skip
    second = run_cli("daily", "--providers", "mock", "--date", "2026-09-17", vault=vault)
    assert second.returncode == 0
    assert "skipped" in second.stdout


def test_daily_force_rerun_idempotent(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    run_cli("daily", "--providers", "mock", "--date", "2026-09-18", vault=vault)
    before = (vault / "Daily" / "2026-09-18.md").read_text(encoding="utf-8")

    forced = run_cli("daily", "--providers", "mock", "--date", "2026-09-18", "--force", vault=vault)
    assert forced.returncode == 0
    after = (vault / "Daily" / "2026-09-18.md").read_text(encoding="utf-8")
    assert before == after  # UNIQUE 缓存 + 确定性渲染 → 零重复


def test_status_and_event_and_thesis(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    run_cli("daily", "--providers", "mock", "--date", "2026-09-19", vault=vault)

    status = run_cli("status", vault=vault)
    assert status.returncode == 0 and "success" in status.stdout

    thesis = run_cli("thesis", "list", vault=vault)
    assert "ai-demand-growth" in thesis.stdout

    event = run_cli("event", "nonexistent0000", vault=vault)  # 不存在 → 退出码 1 但不崩溃
    assert event.returncode == 1


def test_render_creates_missing_only(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    first = run_cli("render", vault=vault)
    assert "新建 8" in first.stdout  # 3 行业 + 4 thesis + Home（seed 后）
    second = run_cli("render", vault=vault)
    assert "新建 0" in second.stdout
