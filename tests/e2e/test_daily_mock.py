"""E2E（TASK-027）：subprocess 级 mock 全链路 —— CLI → DB → vault → 执行报告。"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


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


@pytest.fixture(autouse=True)
def clean_db():
    from tests.conftest import make_db_session

    session = make_db_session()
    yield
    session.close()


def test_e2e_daily_mock_full_chain(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()

    result = run_cli("daily", "--providers", "mock", "--date", "2026-09-17", vault=vault)
    assert result.returncode == 0, result.stderr

    # 1) Pipeline Execution Report 全字段（指令十九）
    out = result.stdout
    for field in (
        "run_id", "command", "date", "status", "duration",
        "events_fetched", "events_l0_filtered", "events_deduplicated", "events_new",
        "events_classified", "by_importance", "events_analyzed",
        "llm_calls", "input_tokens", "output_tokens", "estimated_cost_cny",
        "degraded_sources", "report_path",
    ):
        assert field in out, "执行报告缺字段: %s" % field
    assert "status      : success" in out

    # 2) vault 产物：日报 + 骨架 + 溯源脚注 + 因果链
    daily = vault / "Daily" / "2026-09-17.md"
    content = daily.read_text(encoding="utf-8")
    assert "P0 重大事件" in content
    assert "因果链" in content and "→" in content
    assert "来源: cls" in content and "event:" in content
    assert "不确定性" in content  # 认知边界纪律落在产物上
    for f in ("Industries/AI-Semiconductor.md", "Industries/Power-Energy.md",
              "Industries/Robotics.md", "Home.md", "Theses/ai-demand-growth.md"):
        assert (vault / f).exists(), "缺 vault 文件: %s" % f

    # 3) DB 计数符合 fixtures 预期
    from app.db.models import AnalysisRow, EventRow, ReportRow, RunRow
    from app.db.engine import get_session_factory

    session = get_session_factory()()
    try:
        assert session.query(EventRow).count() == 9
        assert session.query(AnalysisRow).filter_by(strategy="event_analysis").count() >= 1
        assert session.query(AnalysisRow).filter_by(strategy="daily_summary").count() == 1
        assert session.query(ReportRow).count() == 1
        runs = session.query(RunRow).all()
        assert len(runs) == 1 and runs[0].status == "success"
        stats = runs[0].stats_json
        assert stats["llm_calls"] > 0 and stats["events_new"] == 9
    finally:
        session.close()

    # 4) 固定日期重跑稳定（幂等 skip）
    again = run_cli("daily", "--providers", "mock", "--date", "2026-09-17", vault=vault)
    assert again.returncode == 0 and "skipped" in again.stdout
