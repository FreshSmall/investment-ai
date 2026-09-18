"""V0.6: llm_usage_daily 跨进程 LLM 日用量账本（兜底熔断）

Revision ID: 0004_v06
Revises: 0003_v03
Create Date: 2026-09-18
"""

from alembic import op
import sqlalchemy as sa

revision = "0004_v06"
down_revision = "0003_v03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "llm_usage_daily",
        sa.Column("usage_date", sa.Date(), primary_key=True),
        sa.Column("calls", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("input_tokens", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("cost_cny", sa.Numeric(12, 6), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )


def downgrade() -> None:
    op.drop_table("llm_usage_daily")
