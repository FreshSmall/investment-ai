"""S9 report: LLM daily summary + vault write + metrics; S10 finalize lives in orchestrator."""

from __future__ import annotations

from app.core.log import get_logger
from app.domain.report import StepResult
from app.pipeline.context import StepContext
from app.pipeline.orchestrator import Step
from app.report.daily import build_daily_model, write_daily_report


class ReportStep(Step):
    name = "report"

    def run(self, ctx: StepContext) -> StepResult:
        log = get_logger("step.report")

        # 1) LLM 日度综述（预算不足或失败时报告照出，summary 置空）
        preview = build_daily_model(ctx.repo, ctx.report_date, summary=None)
        summary_outcome = ctx.engine.run(
            "daily_summary",
            prompt_ctx={
                "report_date": str(ctx.report_date),
                "analyses": [
                    {
                        "event_id": e["event_id"],
                        "importance": e["importance"],
                        "sectors": ",".join(e["sectors"]),
                        "summary": (e["analysis"] or {}).get("summary", e["title"]),
                    }
                    for e in preview["events"]
                ],
            },
            allowed_event_ids={e["event_id"] for e in preview["events"]},
            report_date=ctx.report_date,
        )
        summary = summary_outcome.result if summary_outcome.ok else {}

        # 2) Thesis 字典化（骨架保证）
        theses = [
            {
                "id": t.id, "title": t.title, "core_hypothesis": t.core_hypothesis,
                "falsification_conditions": t.falsification_conditions,
                "key_metrics": t.key_metrics, "status": t.status,
            }
            for t in ctx.repo.list_theses()
        ]

        try:
            path = write_daily_report(ctx.repo, ctx.report_date, summary, ctx.vault_path, theses, ctx.sectors)
        except OSError as e:
            log.error("vault 写入失败（DB 不回滚，render --all 可重建）", extra={"ctx": {"error": str(e)[:200]}})
            return StepResult(
                name=self.name, ok=True,  # 报告失败必须可见但不阻塞 run 收口
                stats={"report_error": str(e)[:200]},
            )

        return StepResult(
            name=self.name,
            ok=True,
            stats={
                "report_path": str(path),
                "daily_summary_ok": summary_outcome.ok,
                "report_events": len(preview["events"]),
            },
        )
