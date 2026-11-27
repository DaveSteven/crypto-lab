"""Add Trading Journal and immutable Trade Planner revisions."""

from alembic import op

from crypto_lab.persistence.schema import (
    journal_audit_events,
    trade_plan_revisions,
    trading_journals,
)

revision = "0004_trading_journal"
down_revision = "0003_realtime_state_version"
branch_labels = None
depends_on = None


def upgrade() -> None:
    trading_journals.create(op.get_bind(), checkfirst=False)
    trade_plan_revisions.create(op.get_bind(), checkfirst=False)
    journal_audit_events.create(op.get_bind(), checkfirst=False)


def downgrade() -> None:
    journal_audit_events.drop(op.get_bind(), checkfirst=False)
    trade_plan_revisions.drop(op.get_bind(), checkfirst=False)
    trading_journals.drop(op.get_bind(), checkfirst=False)
