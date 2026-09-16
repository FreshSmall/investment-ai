"""V0.1 initial tables: events/analyses/theses/thesis_versions/thesis_evidence/reports/runs

Revision ID: 0001_v01
Revises:
Create Date: 2026-09-17
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import BIGINT, JSON, MEDIUMTEXT

revision = "0001_v01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "events",
        sa.Column("id", sa.String(16), primary_key=True),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("source_id", sa.String(64), nullable=False),
        sa.Column("source_url", sa.String(512)),
        sa.Column("content_hash", sa.CHAR(40), nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("content", MEDIUMTEXT(), nullable=False),
        sa.Column("published_at", sa.DateTime(), nullable=False),
        sa.Column("collected_at", sa.DateTime(), nullable=False),
        sa.Column("sectors", sa.String(256)),
        sa.Column("event_type", sa.String(32)),
        sa.Column("importance", sa.String(4)),
        sa.Column("status", sa.String(16), nullable=False, server_default=sa.text("'raw'")),
        sa.Column("raw_payload", JSON()),
    )
    op.create_index("uk_source", "events", ["source", "source_id"], unique=True)
    op.create_index("uk_hash", "events", ["content_hash"], unique=True)
    op.create_index("idx_pub", "events", ["published_at"])
    op.create_index("idx_work", "events", ["status", "importance"])

    op.create_table(
        "analyses",
        sa.Column("id", BIGINT(), primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.String(16), nullable=True),
        sa.Column("report_date", sa.Date(), nullable=True),
        sa.Column("strategy", sa.String(32), nullable=False),
        sa.Column("model", sa.String(64), nullable=False),
        sa.Column("prompt_version", sa.String(16), nullable=False),
        sa.Column("result_json", JSON(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("cost_cny", sa.DECIMAL(10, 4), nullable=False, server_default=sa.text("0")),
        sa.Column("quality_flag", sa.String(16)),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("uk_anal", "analyses", ["event_id", "strategy", "prompt_version"], unique=True)
    op.create_index("uk_agg", "analyses", ["report_date", "strategy", "prompt_version"], unique=True)
    op.create_index("idx_strategy", "analyses", ["strategy", "created_at"])

    op.create_table(
        "theses",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("title", sa.String(256), nullable=False),
        sa.Column("core_hypothesis", sa.Text(), nullable=False),
        sa.Column("falsification_conditions", JSON(), nullable=False),
        sa.Column("key_metrics", JSON()),
        sa.Column("related_companies", JSON()),
        sa.Column("related_sectors", JSON()),
        sa.Column("status", sa.String(16), nullable=False, server_default=sa.text("'active'")),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )

    op.create_table(
        "thesis_versions",
        sa.Column("thesis_id", sa.String(64), primary_key=True),
        sa.Column("version", sa.Integer(), primary_key=True),
        sa.Column("snapshot", JSON(), nullable=False),
        sa.Column("changed_by", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )

    op.create_table(
        "thesis_evidence",
        sa.Column("thesis_id", sa.String(64), primary_key=True),
        sa.Column("event_id", sa.String(16), primary_key=True),
        sa.Column("review_date", sa.Date(), primary_key=True),
        sa.Column("analysis_id", BIGINT()),
        sa.Column("direction", sa.String(16), nullable=False),
        sa.Column("weight", sa.String(8), nullable=False, server_default=sa.text("'weak'")),
        sa.Column("note", sa.String(1024)),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )

    op.create_table(
        "reports",
        sa.Column("id", BIGINT(), primary_key=True, autoincrement=True),
        sa.Column("type", sa.String(16), nullable=False),
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column("obsidian_path", sa.String(512)),
        sa.Column("metrics_json", JSON()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("uk_report", "reports", ["type", "report_date"], unique=True)

    op.create_table(
        "runs",
        sa.Column("run_id", sa.CHAR(36), primary_key=True),
        sa.Column("command", sa.String(32), nullable=False),
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime()),
        sa.Column("status", sa.String(16), nullable=False, server_default=sa.text("'running'")),
        sa.Column("stats_json", JSON()),
    )
    op.create_index("idx_date", "runs", ["report_date", "status"])


def downgrade() -> None:
    for table in (
        "runs", "reports", "thesis_evidence", "thesis_versions",
        "theses", "analyses", "events",
    ):
        op.drop_table(table)
