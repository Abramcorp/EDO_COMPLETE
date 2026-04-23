"""initial: jobs table

Revision ID: 0001_initial
Revises:
Create Date: 2026-04-23 00:00:00

"""
from __future__ import annotations
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID


revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("stage", sa.String(40), nullable=False, server_default="initializing"),
        sa.Column("progress_pct", sa.Integer, nullable=False, server_default="0"),
        sa.Column("input_meta", JSONB, nullable=True),
        sa.Column("result_blob", sa.LargeBinary, nullable=True),
        sa.Column("result_filename", sa.String(255), nullable=True),
        sa.Column("error", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_jobs_status", "jobs", ["status"])
    op.create_index("ix_jobs_created_at", "jobs", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_jobs_created_at", table_name="jobs")
    op.drop_index("ix_jobs_status", table_name="jobs")
    op.drop_table("jobs")
