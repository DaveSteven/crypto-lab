"""SQLAlchemy Core schema for durable simulation state."""

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    MetaData,
    Numeric,
    String,
    Table,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB

metadata = MetaData()
money = Numeric(50, 24)

simulation_environments = Table(
    "simulation_environments",
    metadata,
    Column("environment_id", String(64), primary_key=True),
    Column("name", String(200), nullable=False),
    Column("status", String(32), nullable=False),
    Column("id_namespace", String(200), nullable=False, unique=True),
    Column("last_event_ts_ms", BigInteger),
    Column("next_arrival_sequence", BigInteger, nullable=False),
    Column("state_version", BigInteger, nullable=False),
    Column("created_ts_ms", BigInteger, nullable=False),
    Column("updated_ts_ms", BigInteger, nullable=False),
    CheckConstraint("next_arrival_sequence > 0", name="ck_environment_next_sequence_positive"),
    CheckConstraint("state_version >= 0", name="ck_environment_state_version_nonnegative"),
)

paper_accounts = Table(
    "paper_accounts",
    metadata,
    Column("account_id", String(64), primary_key=True),
    Column("environment_id", ForeignKey("simulation_environments.environment_id"), nullable=False),
    Column("exchange_id", String(32), nullable=False),
    Column("name", String(200), nullable=False),
    Column("created_ts_ms", BigInteger, nullable=False),
    UniqueConstraint("environment_id", "account_id", name="uq_account_environment"),
)

ledger_entries = Table(
    "ledger_entries",
    metadata,
    Column("entry_id", String(64), primary_key=True),
    Column("environment_id", String(64), nullable=False),
    Column("account_id", String(64), nullable=False),
    Column("exchange_id", String(32), nullable=False),
    Column("asset", String(32), nullable=False),
    Column("available_delta", money, nullable=False),
    Column("locked_delta", money, nullable=False),
    Column("reason", String(32), nullable=False),
    Column("reference_id", String(128)),
    Column("created_ts_ms", BigInteger, nullable=False),
    Column("ledger_sequence", BigInteger, nullable=False),
    ForeignKeyConstraint(
        ("environment_id", "account_id"),
        ("paper_accounts.environment_id", "paper_accounts.account_id"),
    ),
    CheckConstraint(
        "available_delta <> 0 OR locked_delta <> 0",
        name="ck_ledger_nonzero_delta",
    ),
    UniqueConstraint("account_id", "ledger_sequence", name="uq_ledger_account_sequence"),
)
Index("ix_ledger_account_time", ledger_entries.c.account_id, ledger_entries.c.created_ts_ms)

asset_balances = Table(
    "asset_balances",
    metadata,
    Column("account_id", ForeignKey("paper_accounts.account_id"), primary_key=True),
    Column("asset", String(32), primary_key=True),
    Column("available", money, nullable=False),
    Column("locked", money, nullable=False),
    Column("last_entry_id", ForeignKey("ledger_entries.entry_id"), nullable=False),
    Column("updated_ts_ms", BigInteger, nullable=False),
    CheckConstraint("available >= 0", name="ck_balance_available_nonnegative"),
    CheckConstraint("locked >= 0", name="ck_balance_locked_nonnegative"),
)

paper_orders = Table(
    "paper_orders",
    metadata,
    Column("order_id", String(64), primary_key=True),
    Column("environment_id", ForeignKey("simulation_environments.environment_id"), nullable=False),
    Column("account_id", ForeignKey("paper_accounts.account_id"), nullable=False),
    Column("instrument_id", String(100), nullable=False),
    Column("side", String(8), nullable=False),
    Column("order_type", String(16), nullable=False),
    Column("quantity", money, nullable=False),
    Column("limit_price", money),
    Column("reference_price", money, nullable=False),
    Column("max_quote_budget", money),
    Column("reserved_asset", String(32), nullable=False),
    Column("reserved_amount", money, nullable=False),
    Column("filled_quantity", money, nullable=False),
    Column("cumulative_quote_amount", money, nullable=False),
    Column("cumulative_fee", money, nullable=False),
    Column("average_fill_price", money),
    Column("time_in_force", String(16), nullable=False),
    Column("fee_schedule_id", String(100)),
    Column("reserved_fee_rate", money, nullable=False),
    Column("status", String(32), nullable=False),
    Column("submitted_ts_ms", BigInteger, nullable=False),
    Column("scheduled_execution_ts_ms", BigInteger),
    Column("market_entry_ts_ms", BigInteger),
    Column("executed_ts_ms", BigInteger),
    Column("configured_latency_ms", BigInteger),
    Column("actual_simulated_delay_ms", BigInteger),
    Column("scheduler_lag_ms", BigInteger),
    Column("submission_quote_event_id", String(200)),
    Column("execution_quote_event_id", String(200)),
    Column("termination_reason", String(100)),
    Column("order_sequence", BigInteger, nullable=False),
    Column("created_ts_ms", BigInteger, nullable=False),
    Column("updated_ts_ms", BigInteger, nullable=False),
    UniqueConstraint("environment_id", "order_sequence", name="uq_order_environment_sequence"),
    CheckConstraint("quantity > 0", name="ck_order_quantity_positive"),
    CheckConstraint("filled_quantity >= 0", name="ck_order_filled_nonnegative"),
    CheckConstraint("filled_quantity <= quantity", name="ck_order_not_overfilled"),
)

executions = Table(
    "executions",
    metadata,
    Column("execution_id", String(64), primary_key=True),
    Column("environment_id", ForeignKey("simulation_environments.environment_id"), nullable=False),
    Column("order_id", ForeignKey("paper_orders.order_id"), nullable=False),
    Column("account_id", ForeignKey("paper_accounts.account_id"), nullable=False),
    Column("instrument_id", String(100), nullable=False),
    Column("side", String(8), nullable=False),
    Column("price", money, nullable=False),
    Column("quantity", money, nullable=False),
    Column("quote_amount", money, nullable=False),
    Column("fee_asset", String(32), nullable=False),
    Column("fee_amount", money, nullable=False),
    Column("executed_ts_ms", BigInteger, nullable=False),
    Column("liquidity_role", String(16), nullable=False),
    Column("market_event_id", String(200)),
    Column("fill_sequence", BigInteger, nullable=False),
    Column("execution_sequence", BigInteger, nullable=False),
    UniqueConstraint("order_id", "fill_sequence", name="uq_execution_order_sequence"),
    UniqueConstraint(
        "environment_id", "execution_sequence", name="uq_execution_environment_sequence"
    ),
    CheckConstraint("price > 0 AND quantity > 0", name="ck_execution_values_positive"),
)

positions = Table(
    "positions",
    metadata,
    Column("account_id", ForeignKey("paper_accounts.account_id"), primary_key=True),
    Column("instrument_id", String(100), primary_key=True),
    Column("base_asset", String(32), nullable=False),
    Column("quote_asset", String(32), nullable=False),
    Column("quantity", money, nullable=False),
    Column("cost_basis", money, nullable=False),
    Column("average_cost", money),
    Column("realized_pnl", money, nullable=False),
    Column("cumulative_fees", money, nullable=False),
    Column("last_execution_id", ForeignKey("executions.execution_id")),
    Column("updated_ts_ms", BigInteger, nullable=False),
    CheckConstraint("quantity >= 0 AND cost_basis >= 0", name="ck_position_nonnegative"),
)

simulation_events = Table(
    "simulation_events",
    metadata,
    Column("event_id", String(200), primary_key=True),
    Column("environment_id", ForeignKey("simulation_environments.environment_id"), nullable=False),
    Column("event_kind", String(32), nullable=False),
    Column("event_ts_ms", BigInteger, nullable=False),
    Column("arrival_sequence", BigInteger, nullable=False),
    Column("payload_json", JSONB, nullable=False),
    Column("status", String(16), nullable=False),
    Column("result_json", JSONB),
    Column("error_code", String(100)),
    UniqueConstraint("environment_id", "arrival_sequence", name="uq_event_environment_sequence"),
)

scheduled_executions = Table(
    "scheduled_executions",
    metadata,
    Column("order_id", ForeignKey("paper_orders.order_id"), primary_key=True),
    Column("environment_id", ForeignKey("simulation_environments.environment_id"), nullable=False),
    Column("scheduled_execution_ts_ms", BigInteger, nullable=False),
    Column("order_sequence", BigInteger, nullable=False),
    Column("status", String(16), nullable=False),
)

processed_market_events = Table(
    "processed_market_events",
    metadata,
    Column(
        "environment_id", ForeignKey("simulation_environments.environment_id"), primary_key=True
    ),
    Column("source_event_key", String(250), primary_key=True),
    Column("event_type", String(50), nullable=False),
    Column("processed_ts_ms", BigInteger, nullable=False),
    Column("result_json", JSONB, nullable=False),
)

simulated_liquidity = Table(
    "simulated_liquidity",
    metadata,
    Column(
        "environment_id", ForeignKey("simulation_environments.environment_id"), primary_key=True
    ),
    Column("exchange_id", String(32), primary_key=True),
    Column("instrument_id", String(100), primary_key=True),
    Column("synchronization_generation", BigInteger, nullable=False),
    Column("source_book_event_id", String(200), nullable=False),
    Column("residual_bids_json", JSONB, nullable=False),
    Column("residual_asks_json", JSONB, nullable=False),
    Column("market_book_json", JSONB, nullable=False),
    Column("consumption_ids_json", JSONB, nullable=False),
    Column("updated_ts_ms", BigInteger, nullable=False),
)

liquidity_consumptions = Table(
    "liquidity_consumptions",
    metadata,
    Column("consumption_id", String(128), primary_key=True),
    Column("environment_id", ForeignKey("simulation_environments.environment_id"), nullable=False),
    Column("order_id", ForeignKey("paper_orders.order_id"), nullable=False),
    Column("book_event_id", String(200), nullable=False),
    Column("execution_ids_json", JSONB, nullable=False),
    Column("consumption_json", JSONB, nullable=False),
    Column("created_ts_ms", BigInteger, nullable=False),
)

id_generator_state = Table(
    "id_generator_state",
    metadata,
    Column(
        "environment_id", ForeignKey("simulation_environments.environment_id"), primary_key=True
    ),
    Column("id_kind", String(50), primary_key=True),
    Column("next_sequence", BigInteger, nullable=False),
    CheckConstraint("next_sequence > 0", name="ck_id_sequence_positive"),
)

api_idempotency_keys = Table(
    "api_idempotency_keys",
    metadata,
    Column("environment_id", String(64), primary_key=True),
    Column("scope", String(100), primary_key=True),
    Column("idempotency_key", String(200), primary_key=True),
    Column("request_hash", String(64), nullable=False),
    Column("response_status", BigInteger, nullable=False),
    Column("response_json", JSONB, nullable=False),
    Column("created_ts_ms", BigInteger, nullable=False),
)

trading_journals = Table(
    "trading_journals",
    metadata,
    Column("journal_id", String(64), primary_key=True),
    Column("environment_id", String(64), nullable=False),
    Column("account_id", String(64), nullable=False),
    Column("instrument_id", String(100), nullable=False),
    Column("title", String(200), nullable=False),
    Column("status", String(20), nullable=False),
    Column("version", BigInteger, nullable=False),
    Column("current_plan_revision_id", String(64)),
    Column("timeframe", String(20)),
    Column("market_trend", String(32)),
    Column("trade_reason", String),
    Column("entry_conditions", String),
    Column("execution_notes", String),
    Column("review_summary", String),
    Column("archive_reason", String),
    Column("created_ts_ms", BigInteger, nullable=False),
    Column("updated_ts_ms", BigInteger, nullable=False),
    Column("ready_ts_ms", BigInteger),
    Column("activated_ts_ms", BigInteger),
    Column("closed_ts_ms", BigInteger),
    Column("reviewed_ts_ms", BigInteger),
    Column("cancelled_ts_ms", BigInteger),
    ForeignKeyConstraint(
        ("environment_id", "account_id"),
        ("paper_accounts.environment_id", "paper_accounts.account_id"),
    ),
    CheckConstraint("version > 0", name="ck_journal_version_positive"),
    CheckConstraint(
        "status IN ('DRAFT','READY','ACTIVE','CLOSED','REVIEWED','CANCELLED')",
        name="ck_journal_status",
    ),
)
Index(
    "ix_journal_account_updated",
    trading_journals.c.environment_id,
    trading_journals.c.account_id,
    trading_journals.c.updated_ts_ms.desc(),
)
Index("ix_journal_status", trading_journals.c.status)
Index("ix_journal_instrument", trading_journals.c.instrument_id)

trade_plan_revisions = Table(
    "trade_plan_revisions",
    metadata,
    Column("plan_revision_id", String(64), primary_key=True),
    Column(
        "journal_id",
        ForeignKey("trading_journals.journal_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("revision_number", BigInteger, nullable=False),
    Column("entry_price", money, nullable=False),
    Column("planned_position_notional", money, nullable=False),
    Column("stop_loss_price", money, nullable=False),
    Column("take_profit_price", money, nullable=False),
    Column("max_position_notional", money, nullable=False),
    Column("max_account_risk_rate", money, nullable=False),
    Column("min_reward_risk_ratio", money, nullable=False),
    Column("context_json", JSONB, nullable=False),
    Column("calculation_json", JSONB, nullable=False),
    Column("validation_results_json", JSONB, nullable=False),
    Column("validation_status", String(20), nullable=False),
    Column("calculator_version", String(32), nullable=False),
    Column("revision_reason", String, nullable=False),
    Column("is_initial_confirmed", Boolean, nullable=False),
    Column("created_ts_ms", BigInteger, nullable=False),
    Column("confirmed_ts_ms", BigInteger),
    UniqueConstraint("journal_id", "revision_number", name="uq_plan_revision_number"),
    CheckConstraint("revision_number > 0", name="ck_plan_revision_number_positive"),
)
Index(
    "uq_plan_initial_confirmed",
    trade_plan_revisions.c.journal_id,
    unique=True,
    postgresql_where=trade_plan_revisions.c.is_initial_confirmed.is_(True),
)

journal_audit_events = Table(
    "journal_audit_events",
    metadata,
    Column("audit_event_id", String(64), primary_key=True),
    Column(
        "journal_id",
        ForeignKey("trading_journals.journal_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("event_type", String(50), nullable=False),
    Column("from_status", String(20)),
    Column("to_status", String(20)),
    Column("reason", String),
    Column("journal_version", BigInteger, nullable=False),
    Column("details_json", JSONB, nullable=False),
    Column("created_ts_ms", BigInteger, nullable=False),
)
Index(
    "ix_journal_audit_sequence",
    journal_audit_events.c.journal_id,
    journal_audit_events.c.created_ts_ms,
    journal_audit_events.c.audit_event_id,
)

journal_order_links = Table(
    "journal_order_links",
    metadata,
    Column(
        "journal_id",
        ForeignKey("trading_journals.journal_id", ondelete="RESTRICT"),
        primary_key=True,
    ),
    Column(
        "order_id",
        ForeignKey("paper_orders.order_id", ondelete="RESTRICT"),
        primary_key=True,
        unique=True,
    ),
    Column("environment_id", String(64), nullable=False),
    Column("account_id", String(64), nullable=False),
    Column("linked_ts_ms", BigInteger, nullable=False),
    Column("note", String),
    Column("link_sequence", BigInteger, nullable=False),
    UniqueConstraint("journal_id", "link_sequence", name="uq_journal_link_sequence"),
    ForeignKeyConstraint(
        ("environment_id", "account_id"),
        ("paper_accounts.environment_id", "paper_accounts.account_id"),
    ),
    CheckConstraint("link_sequence > 0", name="ck_journal_link_sequence_positive"),
)
Index(
    "ix_journal_order_account",
    journal_order_links.c.environment_id,
    journal_order_links.c.account_id,
)
