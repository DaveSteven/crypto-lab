"""Create initial trading persistence schema."""

from alembic import op

from crypto_lab.persistence.schema import metadata

revision = "0001_initial_persistence"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    metadata.create_all(
        bind=op.get_bind(),
        tables=[
            table
            for name, table in metadata.tables.items()
            if name != "api_idempotency_keys"
        ],
        checkfirst=False,
    )
    # Keep this historical revision fixed even as runtime metadata gains columns.
    op.drop_constraint(
        "ck_environment_state_version_nonnegative",
        "simulation_environments",
        type_="check",
    )
    op.drop_column("simulation_environments", "state_version")


def downgrade() -> None:
    metadata.drop_all(
        bind=op.get_bind(),
        tables=[
            table
            for name, table in metadata.tables.items()
            if name != "api_idempotency_keys"
        ],
        checkfirst=False,
    )
