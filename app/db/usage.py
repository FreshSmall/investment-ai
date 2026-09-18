"""跨进程 LLM 用量账本（兜底拦截的数据面）。

2026-09-18 KeepAlive 事故教训：进程内预算在连环重启下每次清零，形同虚设。
本模块提供进程间共享的当日累计：每次调用后短会话原子累加（col=col+n），
BudgetGuard.check() 读取当日值实现跨进程成本熔断。

并发安全：UPDATE 原子自增；首次插入撞主键（IntegrityError）时回退重试 UPDATE。
"""

from __future__ import annotations

from datetime import date as _date
from typing import Optional

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.db import models
from app.db.engine import get_session_factory


class UsageStore:
    def __init__(self, session_factory=None) -> None:
        self._sf = session_factory or get_session_factory()

    def cost_for(self, usage_date: _date) -> float:
        with self._sf() as session:
            row = session.get(models.LlmUsageRow, usage_date)
            return float(row.cost_cny) if row is not None else 0.0

    def usage_for(self, usage_date: _date) -> Optional[dict]:
        with self._sf() as session:
            row = session.get(models.LlmUsageRow, usage_date)
            if row is None:
                return None
            return {
                "calls": row.calls,
                "input_tokens": row.input_tokens,
                "output_tokens": row.output_tokens,
                "cost_cny": float(row.cost_cny),
            }

    def bump(
        self,
        usage_date: _date,
        calls: int,
        input_tokens: int,
        output_tokens: int,
        cost_cny: float,
    ) -> None:
        with self._sf() as session:
            for _ in range(3):
                res = session.execute(
                    update(models.LlmUsageRow)
                    .where(models.LlmUsageRow.usage_date == usage_date)
                    .values(
                        calls=models.LlmUsageRow.calls + calls,
                        input_tokens=models.LlmUsageRow.input_tokens + input_tokens,
                        output_tokens=models.LlmUsageRow.output_tokens + output_tokens,
                        cost_cny=models.LlmUsageRow.cost_cny + cost_cny,
                    )
                )
                if res.rowcount:
                    session.commit()
                    return
                session.rollback()
                try:
                    session.add(models.LlmUsageRow(
                        usage_date=usage_date, calls=calls,
                        input_tokens=input_tokens, output_tokens=output_tokens,
                        cost_cny=cost_cny,
                    ))
                    session.commit()
                    return
                except IntegrityError:  # 并发首插撞主键 → 回到 UPDATE 重试
                    session.rollback()
            raise SQLAlchemyError("llm_usage_daily 累加失败（并发竞争重试耗尽）")
