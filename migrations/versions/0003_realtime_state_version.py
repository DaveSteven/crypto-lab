"""Add authoritative environment state version for realtime resync."""

import sqlalchemy as sa
from alembic import op

revision = "0003_realtime_state_version"
down_revision = "0002_api_idempotency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "simulation_environments",
        sa.Column("state_version", sa.BigInteger(), server_default="0", nullable=False),
    )
    op.create_check_constraint(
        "ck_environment_state_version_nonnegative",
        "simulation_environments",
        "state_version >= 0",
    )
    op.alter_column("simulation_environments", "state_version", server_default=None)


def downgrade() -> None:
    op.drop_constraint(
        "ck_environment_state_version_nonnegative",
        "simulation_environments",
        type_="check",
    )
    op.drop_column("simulation_environments", "state_version")
