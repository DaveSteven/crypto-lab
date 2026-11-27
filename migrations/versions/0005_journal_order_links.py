"""Add unique Journal ownership for paper orders."""

from alembic import op

from crypto_lab.persistence.schema import journal_order_links

revision = "0005_journal_order_links"
down_revision = "0004_trading_journal"
branch_labels = None
depends_on = None


def upgrade() -> None:
    journal_order_links.create(op.get_bind(), checkfirst=False)


def downgrade() -> None:
    journal_order_links.drop(op.get_bind(), checkfirst=False)
