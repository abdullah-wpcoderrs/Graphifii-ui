"""add immutable extraction runs and callback replay ledger

Revision ID: f83a49b127d1
Revises: a2c6dcfb8864
Create Date: 2026-08-01
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID


revision: str = "f83a49b127d1"
down_revision: Union[str, Sequence[str], None] = "a2c6dcfb8864"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


RUN_STATUS = sa.Enum(
    "QUEUED",
    "STARTING",
    "CLONING",
    "INDEXING",
    "READY",
    "FAILED",
    "CANCELED",
    name="extractionrunstatus",
    native_enum=False,
)


def upgrade() -> None:
    op.create_table(
        "extraction_runs",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", UUID(as_uuid=True), nullable=False),
        sa.Column("status", RUN_STATUS, nullable=False),
        sa.Column("active_slot", sa.Integer(), nullable=True),
        sa.Column("repo_url", sa.String(length=1024), nullable=False),
        sa.Column("repo_full_name", sa.String(length=512), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("default_branch", sa.String(length=255), nullable=False),
        sa.Column("llm_provider", sa.String(length=64), nullable=False),
        sa.Column("llm_model", sa.String(length=255), nullable=True),
        sa.Column("deployment_id", sa.String(length=255), nullable=True),
        sa.Column("callback_secret_hash", sa.String(length=64), nullable=True),
        sa.Column("progress_percent", sa.Integer(), server_default="0", nullable=False),
        sa.Column("status_message", sa.String(length=512), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("graph_json_url", sa.String(length=1024), nullable=True),
        sa.Column("lease_owner", sa.String(length=255), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "progress_percent >= 0 AND progress_percent <= 100",
            name="ck_extraction_runs_progress_percent",
        ),
        sa.CheckConstraint(
            "active_slot IS NULL OR active_slot = 1",
            name="ck_extraction_runs_active_slot",
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("active_slot", name="uq_extraction_runs_active_slot"),
        sa.UniqueConstraint("deployment_id", name="uq_extraction_runs_deployment_id"),
    )
    op.create_index("ix_extraction_runs_project_id", "extraction_runs", ["project_id"])
    op.create_index("ix_extraction_runs_status", "extraction_runs", ["status"])

    op.add_column("projects", sa.Column("current_run_id", UUID(as_uuid=True), nullable=True))
    op.create_index("ix_projects_current_run_id", "projects", ["current_run_id"])
    op.create_foreign_key(
        "fk_projects_current_run_id_extraction_runs",
        "projects",
        "extraction_runs",
        ["current_run_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "extraction_callback_events",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", UUID(as_uuid=True), nullable=False),
        sa.Column("event_id", UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["run_id"], ["extraction_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "event_id", name="uq_extraction_callback_run_event"),
    )
    op.create_index(
        "ix_extraction_callback_events_run_id", "extraction_callback_events", ["run_id"]
    )

    op.add_column("usage_events", sa.Column("run_id", UUID(as_uuid=True), nullable=True))
    op.create_index("ix_usage_events_run_id", "usage_events", ["run_id"])
    op.create_foreign_key(
        "fk_usage_events_run_id_extraction_runs",
        "usage_events",
        "extraction_runs",
        ["run_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # Existing terminal project rows become immutable historical runs. Any
    # legacy in-flight row is failed closed because it has no trustworthy run
    # identity or per-run callback credential.
    op.execute(
        sa.text(
            """
            INSERT INTO extraction_runs (
                id, project_id, status, repo_url, repo_full_name, provider,
                default_branch, llm_provider, progress_percent, status_message,
                error_message, graph_json_url, started_at, finished_at
            )
            SELECT
                gen_random_uuid(), p.id,
                CASE WHEN p.status IN ('READY', 'FAILED') THEN p.status ELSE 'FAILED' END,
                p.repo_url, p.repo_name, p.provider, p.default_branch, 'legacy',
                CASE WHEN p.status = 'READY' THEN 100 ELSE p.progress_percent END,
                p.status_message,
                CASE
                    WHEN p.status IN ('CLONING', 'INDEXING')
                    THEN 'Legacy in-flight run invalidated during run isolation migration'
                    ELSE p.error_message
                END,
                p.graph_json_url, p.started_at,
                CASE WHEN p.status IN ('CLONING', 'INDEXING') THEN now() ELSE p.finished_at END
            FROM projects p
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE projects p
            SET current_run_id = r.id,
                status = CASE WHEN p.status IN ('CLONING', 'INDEXING') THEN 'FAILED' ELSE p.status END,
                error_message = CASE
                    WHEN p.status IN ('CLONING', 'INDEXING')
                    THEN 'Legacy in-flight run invalidated during run isolation migration'
                    ELSE p.error_message
                END,
                finished_at = CASE
                    WHEN p.status IN ('CLONING', 'INDEXING') THEN now() ELSE p.finished_at
                END
            FROM extraction_runs r
            WHERE r.project_id = p.id
            """
        )
    )


def downgrade() -> None:
    op.drop_constraint("fk_usage_events_run_id_extraction_runs", "usage_events", type_="foreignkey")
    op.drop_index("ix_usage_events_run_id", table_name="usage_events")
    op.drop_column("usage_events", "run_id")

    op.drop_index("ix_extraction_callback_events_run_id", table_name="extraction_callback_events")
    op.drop_table("extraction_callback_events")

    op.drop_constraint("fk_projects_current_run_id_extraction_runs", "projects", type_="foreignkey")
    op.drop_index("ix_projects_current_run_id", table_name="projects")
    op.drop_column("projects", "current_run_id")

    op.drop_index("ix_extraction_runs_status", table_name="extraction_runs")
    op.drop_index("ix_extraction_runs_project_id", table_name="extraction_runs")
    op.drop_table("extraction_runs")
