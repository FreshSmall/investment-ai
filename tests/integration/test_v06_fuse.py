"""V0.6 兜底拦截：跨进程预算熔断（llm_usage_daily）+ run 频率门。

背景：2026-09-18 KeepAlive 配置反了（SuccessfulExit=true）导致 daily 无限连环
重跑 8 小时 ¥118。进程内预算每次重启清零，故两层兜底都以 DB 为共享状态。
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.core import clock as clock_mod
from app.db.usage import UsageStore
from app.domain.report import RunStatus, StepResult
from app.pipeline.orchestrator import Orchestrator, run_gate_check
from app.providers.llm.openai_compat import BudgetExceeded, BudgetGuard


# ---------------- UsageStore 账本 ----------------

def test_ledger_bump_accumulates(db_session) -> None:
    import datetime as dt

    day = dt.date(2026, 9, 18)
    store = UsageStore()
    store.bump(day, 2, 100, 50, 0.5)
    store.bump(day, 3, 10, 5, 0.25)
    assert store.cost_for(day) == pytest.approx(0.75)
    usage = store.usage_for(day)
    assert usage["calls"] == 5
    assert usage["input_tokens"] == 110
    assert store.usage_for(dt.date(2026, 9, 19)) is None


def test_budget_guard_cross_process_shared_ledger(db_session) -> None:
    """两个"进程"（独立 guard）共享同一账本：A 超限后 B 也必须被拦。"""
    import datetime as dt

    day = dt.date(2026, 9, 18)
    store = UsageStore()
    guard_a = BudgetGuard(1.0, store=store, today_fn=lambda: day)
    guard_b = BudgetGuard(1.0, store=store, today_fn=lambda: day)

    guard_a.check()  # 未超限
    guard_a.record(0, 0, 0.6)
    guard_a.record(0, 0, 0.6)  # 当日累计 1.2 ≥ 1.0
    with pytest.raises(BudgetExceeded):
        guard_b.check()  # 跨进程可见


def test_budget_guard_in_memory_fallback() -> None:
    """store=None 退回原进程内语义（兼容既有单测/ mock 模式）。"""
    guard = BudgetGuard(0.5)
    guard.record(0, 0, 0.3)
    guard.check()
    guard.record(0, 0, 0.3)
    with pytest.raises(BudgetExceeded):
        guard.check()


# ---------------- run 频率门 ----------------

class _SpyStep:
    name = "spy"

    def __init__(self) -> None:
        self.ran = False

    def run(self, ctx):  # pragma: no cover - 不应被执行
        self.ran = True
        return StepResult(name="spy", ok=True)


def _seed_runs(ctx, n: int, age_seconds: int = 300) -> None:
    now_dt = clock_mod.now()
    for i in range(n):
        ctx.repo.create_run(
            "gate-seed-%d" % i, "daily", ctx.report_date,
            now_dt - timedelta(seconds=age_seconds * (i + 1)),
        )


def test_run_gate_blocks_after_hour_cap(pipeline_ctx) -> None:
    cfg = pipeline_ctx.app_cfg.pipeline
    _seed_runs(pipeline_ctx, cfg.run_gate_max_per_hour)

    spy = _SpyStep()
    summary = Orchestrator([spy]).run_daily(pipeline_ctx, force=True)

    assert summary.status == RunStatus.BLOCKED
    assert spy.ran is False  # 步骤未执行：未产生任何 LLM 调用
    assert summary.stats["blocked_reason"] == "run_gate"
    assert summary.stats["runs_last_hour"] == cfg.run_gate_max_per_hour
    # 拦截本身也落 runs 表（可审计，且计入后续门判定）
    latest = pipeline_ctx.repo.latest_run(pipeline_ctx.report_date)
    assert latest is not None and latest.status == RunStatus.BLOCKED.value


def test_run_gate_blocks_after_day_cap(pipeline_ctx) -> None:
    cfg = pipeline_ctx.app_cfg.pipeline
    # 小时数达标但当日总数超限（runs 摊到数小时前）
    now_dt = clock_mod.now()
    for i in range(cfg.run_gate_max_per_day):
        pipeline_ctx.repo.create_run(
            "gate-day-%d" % i, "daily", pipeline_ctx.report_date,
            now_dt - timedelta(hours=2, minutes=i),
        )
    assert run_gate_check(pipeline_ctx) is not None


def test_run_gate_passes_normal_day(pipeline_ctx) -> None:
    _seed_runs(pipeline_ctx, 3, age_seconds=3600)  # 正常：早晚各一次 + 手动补跑
    assert run_gate_check(pipeline_ctx) is None
