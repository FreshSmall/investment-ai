"""V0.2: companies table + analyses.thesis_id (thesis_review per-thesis cache key)

Revision ID: 0002_v02
Revises: 0001_v01
Create Date: 2026-09-18
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import JSON

revision = "0002_v02"
down_revision = "0001_v01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) analyses.thesis_id：'' 哨兵 = 非 thesis 聚合（NULL 不参与唯一判重，故用空串）
    op.add_column(
        "analyses",
        sa.Column("thesis_id", sa.String(64), nullable=False, server_default=sa.text("''")),
    )
    # 2) uk_agg 收窄为含 thesis_id 的四列唯一键：旧 uk_agg(date,strategy,version) 会拦截
    #    同日多个 thesis 的 thesis_review 行；daily_summary 以 '' 哨兵保持原幂等语义
    op.drop_index("uk_agg", table_name="analyses")
    op.create_index(
        "uk_agg", "analyses",
        ["report_date", "thesis_id", "strategy", "prompt_version"], unique=True,
    )
    # 3) companies 表（config/companies.yaml 种子，幂等导入见 app/db/seed.py）
    op.create_table(
        "companies",
        sa.Column("code", sa.String(12), primary_key=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("sector", sa.String(64)),
        sa.Column("watched", sa.Integer, nullable=False, server_default=sa.text("1")),
        sa.Column("profile", JSON()),
    )


def downgrade() -> None:
    op.drop_table("companies")
    op.drop_index("uk_agg", table_name="analyses")
    op.create_index("uk_agg", "analyses", ["report_date", "strategy", "prompt_version"], unique=True)
    op.drop_column("analyses", "thesis_id")
