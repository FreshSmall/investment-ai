from __future__ import annotations

import uuid
from datetime import date, datetime

import pytest
from sqlalchemy.exc import OperationalError

from app.core.config import AppCfg, LlmCfg, ModelTierCfg, PipelineCfg, Settings, load_sectors
from app.domain.report import RunStatus, StepResult
from app.pipeline.context import StepContext
from app.pipeline.orchestrator import Orchestrator, Step, StepError


class FakeRunRow:
    def __init__(self, status: str) -> None:
        self.status = status


class FakeRepo:
    def __init__(self, existing_status: str = None) -> None:
        self.existing_status = existing_status
        self.created = []
        self.finished = []

    def latest_run(self, report_date, command="daily"):
        return FakeRunRow(self.existing_status) if self.existing_status else None

    def create_run(self, run_id, command, report_date, started_at):
        self.created.append(run_id)

    def finish_run(self, run_id, status, finished_at, stats):
        self.finished.append((run_id, status, stats))


class OkStep(Step):
    name = "ok"

    def __init__(self, name="ok", stats=None) -> None:
        self.name = name
        self._stats = stats or {"items": 1}
        self.executed = False

    def run(self, ctx) -> StepResult:
        self.executed = True
        return StepResult(name=self.name, ok=True, stats=dict(self._stats))


class BoomStep(Step):
    name = "boom"

    def __init__(self, name="boom") -> None:
        self.name = name
        self.executed = False

    def run(self, ctx) -> StepResult:
        self.executed = True
        raise StepError("模拟步骤级失败")


def make_ctx(repo) -> StepContext:
    return StepContext(
        run_id=str(uuid.uuid4()),
        report_date=date(2026, 9, 17),
        settings=Settings(db_host="h", db_user="u", db_password="p"),
        app_cfg=AppCfg(pipeline=PipelineCfg(), llm=LlmCfg(tiers={"L1": ModelTierCfg(model="m")})),
        sectors=load_sectors(),
        repo=repo,  # type: ignore[arg-type]
        engine=None,  # type: ignore[arg-type]
        news_providers=[],
    )


def test_all_success() -> None:
    repo = FakeRepo()
    s1, s2 = OkStep("one"), OkStep("two", {"more": 5})
    summary = Orchestrator([s1, s2]).run_daily(make_ctx(repo))
    assert summary.status == RunStatus.SUCCESS
    assert s1.executed and s2.executed
    assert summary.stats["items"] == 1 and summary.stats["more"] == 5
    assert repo.finished[0][1] == RunStatus.SUCCESS.value


def test_step_error_aborts_remaining_and_partial() -> None:
    repo = FakeRepo()
    s1, boom, s3 = OkStep("one"), BoomStep("boom"), OkStep("three")
    summary = Orchestrator([s1, boom, s3]).run_daily(make_ctx(repo))
    assert summary.status == RunStatus.PARTIAL
    assert s1.executed and boom.executed and not s3.executed
    assert summary.failed_steps == ["boom"]
    assert "boom" in summary.stats["step_errors"]


def test_idempotent_skip_when_already_succeeded() -> None:
    repo = FakeRepo(existing_status="success")
    s1 = OkStep()
    summary = Orchestrator([s1]).run_daily(make_ctx(repo))
    assert summary.status == RunStatus.SKIPPED
    assert not s1.executed and repo.created == []


def test_force_reruns_despite_success() -> None:
    repo = FakeRepo(existing_status="success")
    s1 = OkStep()
    summary = Orchestrator([s1]).run_daily(make_ctx(repo), force=True)
    assert summary.status == RunStatus.SUCCESS and s1.executed


def test_db_unreachable_fast_exit() -> None:
    class DeadRepo(FakeRepo):
        def latest_run(self, report_date, command="daily"):
            raise OperationalError("stmt", {}, Exception("connection refused"))

    repo = DeadRepo()
    s1 = OkStep()
    summary = Orchestrator([s1]).run_daily(make_ctx(repo))
    assert summary.status == RunStatus.DB_UNREACHABLE
    assert not s1.executed


def test_unknown_exception_converges_to_partial() -> None:
    """真实运行暴露的缺陷回归：LLMClientError 等未知异常必须收敛为步骤失败+终态（TASK-028）。"""

    class WeirdStep(Step):
        name = "weird"

        def __init__(self) -> None:
            self.executed = False

        def run(self, ctx) -> StepResult:
            self.executed = True
            raise RuntimeError("LLM HTTP 400: 模型名不支持")

    repo = FakeRepo()
    after = OkStep("after")
    summary = Orchestrator([WeirdStep(), after]).run_daily(make_ctx(repo))
    assert summary.status == RunStatus.PARTIAL
    assert summary.failed_steps == ["weird"]
    assert not after.executed
    assert "RuntimeError" in summary.stats["step_errors"]["weird"]
    assert repo.finished[0][1] == RunStatus.PARTIAL.value  # run 有终态，不再卡 running
