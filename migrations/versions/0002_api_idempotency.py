"""Add REST API idempotency records."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002_api_idempotency"
down_revision = "0001_initial_persistence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "api_idempotency_keys",
        sa.Column("environment_id", sa.String(length=64), nullable=False),
        sa.Column("scope", sa.String(length=100), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("response_status", sa.BigInteger(), nullable=False),
        sa.Column("response_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_ts_ms", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint(
            "environment_id", "scope", "idempotency_key", name="pk_api_idempotency_keys"
        ),
    )


def downgrade() -> None:
    op.drop_table("api_idempotency_keys")
