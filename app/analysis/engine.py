"""AnalysisEngine: the single LLM entrypoint.

Pipeline per call (arch §7.1): budget gate -> cache check -> prompt render ->
LLM -> tolerant parse -> reference scrub (anti-hallucination) -> schema validate
-> (on failure, one error-fed retry) -> persist with usage/cost.
"""

from __future__ import annotations

from datetime import date as _date
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from app.analysis.prompts import render_prompt
from app.analysis.schemas import ParseError, parse_llm_json, validate
from app.analysis.strategies import STRATEGIES
from app.core.config import AppCfg, SectorsCfg
from app.core.log import get_logger
from app.db.repository import Repository
from app.domain.analysis import AnalysisOutcome, ErrorKind, LLMRequest
from app.providers.base import LLMProvider
from app.providers.llm.openai_compat import BudgetExceeded

_REF_KEYS = {"source_event_id", "event_id"}


class AnalysisEngine:
    def __init__(
        self,
        llm: LLMProvider,
        repo: Repository,
        sectors: SectorsCfg,
        app_cfg: AppCfg,
        budget,
    ) -> None:
        self._llm = llm
        self._repo = repo
        self._sectors = sectors
        self._cfg = app_cfg
        self._budget = budget
        self._log = get_logger("engine")

    def run(
        self,
        strategy_name: str,
        *,
        prompt_ctx: Dict[str, Any],
        allowed_event_ids: Optional[Set[str]] = None,
        event_id: Optional[str] = None,
        report_date: Optional[_date] = None,
    ) -> AnalysisOutcome:
        strategy = STRATEGIES[strategy_name]
        allowed = allowed_event_ids or set()
        sector_keys = self._sectors.keys()

        # 1) budget circuit breaker
        try:
            self._budget.check()
        except BudgetExceeded as e:
            return self._fail(strategy.name, ErrorKind.BUDGET_EXCEEDED, str(e))

        # 2) result cache (idempotency): same event+strategy already analyzed
        if event_id:
            existing = self._repo.get_analysis_for_event(event_id, strategy.name)
            if existing is not None:
                return AnalysisOutcome(
                    strategy=strategy.name, ok=True,
                    result=existing.result_json, analysis_id=existing.id, cached=True,
                )

        tier_cfg = self._cfg.llm.tiers[strategy.tier.value]
        system, user, prompt_version = render_prompt(strategy.prompt_file, prompt_ctx)
        timeout = self._cfg.pipeline.llm_timeout_seconds

        last_error = ""
        for attempt in (1, 2):  # one error-fed retry
            req = LLMRequest(
                system=system,
                user=user if attempt == 1 else user + "\n\n你上一次输出未通过校验：%s\n请严格按 schema 重新输出，只输出 JSON 对象。" % last_error,
                model=tier_cfg.model,
                temperature=tier_cfg.temperature,
                max_tokens=tier_cfg.max_tokens,
                timeout_seconds=timeout,
                strategy=strategy.name,
            )
            result = self._llm.complete_json(req)
            if not result.ok:
                last_error = result.error or "provider error"
                if attempt == 2:
                    return self._fail(strategy.name, ErrorKind.PROVIDER_ERROR, last_error)
                continue

            try:
                data = parse_llm_json(result.raw_text if result.raw_text else result.data)
            except ParseError as e:
                last_error = str(e)
                if attempt == 2:
                    return self._fail(strategy.name, ErrorKind.PARSE_ERROR, last_error, result)
                continue

            data, warnings = self._scrub_hallucinated_refs(data, allowed)
            ok, errors = validate(strategy.schema_name, data, sector_keys)
            if not ok:
                last_error = "; ".join(errors)
                if attempt == 2:
                    return self._fail(strategy.name, ErrorKind.PARSE_ERROR, last_error, result, warnings)
                continue

            analysis_id, _ = self._repo.save_analysis(
                strategy=strategy.name,
                model=result.model,
                prompt_version=prompt_version,
                result=data,
                event_id=event_id,
                report_date=report_date,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                cost_cny=result.cost_cny,
            )
            self._budget.add(result.cost_cny)
            return AnalysisOutcome(
                strategy=strategy.name,
                ok=True,
                result=data,
                analysis_id=analysis_id,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                cost_cny=result.cost_cny,
                warnings=warnings,
            )
        return self._fail(strategy.name, ErrorKind.RETRY_EXHAUSTED, "unreachable")

    def _fail(
        self,
        strategy: str,
        kind: ErrorKind,
        error: str,
        result=None,
        warnings: Optional[List[str]] = None,
    ) -> AnalysisOutcome:
        self._log.warning(
            "analysis failed",
            extra={"ctx": {"strategy": strategy, "kind": kind.value, "error": error[:200]}},
        )
        return AnalysisOutcome(
            strategy=strategy,
            ok=False,
            error_kind=kind.value,
            warnings=warnings or [],
            input_tokens=result.input_tokens if result is not None else 0,
            output_tokens=result.output_tokens if result is not None else 0,
        )

    @staticmethod
    def _scrub_hallucinated_refs(data: Any, allowed: Set[str]) -> Tuple[Any, List[str]]:
        """Drop items whose reference ids are not in the input event set."""
        warnings: List[str] = []

        def scrub_list(items: List[Any]) -> List[Any]:
            kept = []
            for item in items:
                if isinstance(item, dict):
                    for key in _REF_KEYS:
                        ref = item.get(key)
                        if isinstance(ref, str) and ref and allowed and ref not in allowed:
                            warnings.append("剔除幻觉引用 %s=%s" % (key, ref))
                            item = None
                            break
                if item is not None:
                    kept.append(item)
            return kept

        def walk(node: Any) -> Any:
            if isinstance(node, list):
                return scrub_list([walk(x) for x in node])
            if isinstance(node, dict):
                return {k: walk(v) for k, v in node.items()}
            return node

        return walk(data), warnings
