"""Pipeline orchestrator: run lifecycle + step sequencing + failure isolation (arch §5/§12).

Failure taxonomy (steps handle item/source-level failures themselves and stay ok):
- ``StepError``         -> step-level failure: abort remaining steps, run = partial
- ``SystemUnavailable`` -> DB unreachable: fast exit, run = db_unreachable
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Callable, List

from sqlalchemy.exc import OperationalError, SQLAlchemyError

from app.core import clock
from app.core.log import get_logger
from app.domain.report import RunStatus, RunSummary, StepResult
from app.pipeline.context import StepContext


class StepError(Exception):
    """Step-level failure — remaining steps are skipped, run finishes partial."""


class SystemUnavailable(Exception):
    """External DB unreachable — fast exit."""


class Step:
    name: str = "base"

    def run(self, ctx: StepContext) -> StepResult:  # pragma: no cover - interface
        raise NotImplementedError


class Orchestrator:
    def __init__(self, steps: List[Step]) -> None:
        self._steps = steps
        self._log = get_logger("orchestrator")

    def run_daily(self, ctx: StepContext, force: bool = False) -> RunSummary:
        started = clock.now()
        run_id = ctx.run_id
        command = "daily"

        # S0: idempotency gate + run bookkeeping
        try:
            latest = ctx.repo.latest_run(ctx.report_date, command)
            if latest is not None and latest.status == RunStatus.SUCCESS.value and not force:
                self._log.info("skip: already succeeded today", extra={"ctx": {"date": str(ctx.report_date)}})
                return RunSummary(
                    run_id=run_id, command=command, report_date=ctx.report_date,
                    status=RunStatus.SKIPPED, started_at=started, finished_at=clock.now(),
                    stats={"skipped_reason": "already_succeeded"},
                )
            ctx.repo.create_run(run_id, command, ctx.report_date, started)
        except (OperationalError, SQLAlchemyError) as e:
            self._log.error("DB 不可达", extra={"ctx": {"error": str(e)[:200]}})
            return RunSummary(
                run_id=run_id, command=command, report_date=ctx.report_date,
                status=RunStatus.DB_UNREACHABLE, started_at=started, finished_at=clock.now(),
                stats={"error": str(e)[:200]},
            )

        stats: dict = {}
        failed_steps: List[str] = []
        if ctx.degraded_sources:
            stats["degraded_sources"] = ctx.degraded_sources

        for step in self._steps:
            try:
                result = step.run(ctx)
                stats.update(result.stats)
                if not result.ok:  # 软失败：本步完成但核心产出受损（如 vault 写失败）→ partial
                    failed_steps.append(step.name)
                self._log.info("step done", extra={"ctx": {"step": step.name, "ok": result.ok}})
            except StepError as e:
                failed_steps.append(step.name)
                stats.setdefault("step_errors", {})[step.name] = str(e)[:300]
                self._log.warning("step failed, aborting remaining", extra={"ctx": {"step": step.name, "error": str(e)[:200]}})
                break

        status = RunStatus.SUCCESS if not failed_steps else RunStatus.PARTIAL
        finished = clock.now()
        stats["success_count"] = stats.get("events_new", 0)
        stats["failure_count"] = len(failed_steps)
        stats["duration_sec"] = round((finished - started).total_seconds(), 1)
        engine = getattr(ctx, "engine", None)
        if engine is not None:  # LLM 用量与成本（指令十九）
            stats["llm_calls"] = engine.total_calls
            stats["input_tokens"] = engine.total_input_tokens
            stats["output_tokens"] = engine.total_output_tokens
            stats["estimated_cost_cny"] = round(engine.total_cost_cny, 4)
        try:
            ctx.repo.finish_run(run_id, status, finished, stats)
        except SQLAlchemyError as e:  # DB died mid-run: report but don't crash
            self._log.error("finalize 失败（DB）", extra={"ctx": {"error": str(e)[:200]}})
            status = RunStatus.DB_UNREACHABLE

        return RunSummary(
            run_id=run_id, command=command, report_date=ctx.report_date, status=status,
            started_at=started, finished_at=finished, stats=stats, failed_steps=failed_steps,
        )
