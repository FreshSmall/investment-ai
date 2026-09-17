"""V0.3: daily_snapshots (market indices + sector boards, one row per day)

Revision ID: 0003_v03
Revises: 0002_v02
Create Date: 2026-09-18
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import JSON

revision = "0003_v03"
down_revision = "0002_v02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "daily_snapshots",
        sa.Column("trade_date", sa.Date(), primary_key=True),
        sa.Column("snapshot", JSON(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("daily_snapshots")
