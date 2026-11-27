from crypto_lab.persistence import metadata

EXPECTED_TABLES = {
    "simulation_environments",
    "paper_accounts",
    "ledger_entries",
    "asset_balances",
    "paper_orders",
    "executions",
    "positions",
    "simulation_events",
    "scheduled_executions",
    "processed_market_events",
    "simulated_liquidity",
    "liquidity_consumptions",
    "id_generator_state",
    "api_idempotency_keys",
    "trading_journals",
    "trade_plan_revisions",
    "journal_audit_events",
}


def test_persistence_schema_contains_all_transaction_participants() -> None:
    assert set(metadata.tables) == EXPECTED_TABLES


def test_financial_columns_use_fixed_precision_numeric() -> None:
    for table_name, column_name in [
        ("ledger_entries", "available_delta"),
        ("asset_balances", "available"),
        ("paper_orders", "quantity"),
        ("executions", "price"),
        ("positions", "cost_basis"),
        ("trade_plan_revisions", "entry_price"),
    ]:
        column_type = metadata.tables[table_name].c[column_name].type
        assert column_type.precision == 50
        assert column_type.scale == 24
