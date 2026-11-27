from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from crypto_lab.api import create_app
from crypto_lab.api.errors import ApplicationError
from crypto_lab.api.market_feed import OKX_SPOT_RULES
from crypto_lab.api.schemas import (
    AccountCreate,
    EnvironmentCreate,
    JournalCreate,
    JournalOrderLink,
    JournalOrderUnlink,
    JournalPatch,
    JournalTransition,
    OrderCreate,
    PlanRevisionCreate,
    TradePlannerPreview,
)
from crypto_lab.api.service import ApplicationService
from crypto_lab.persistence import schema
from crypto_lab.trading import FeeSchedule


@pytest.fixture
def journal_service(engine, clock):
    return ApplicationService(
        engine,
        fee_schedule=FeeSchedule(
            schedule_id="journal-test-v1",
            maker_rate=Decimal("0.0008"),
            taker_rate=Decimal("0.001"),
        ),
        market_rules=OKX_SPOT_RULES,
        max_market_age_ms=5_000,
        now_ms=clock,
    )


def seed_scope(service: ApplicationService, engine) -> tuple[str, str]:
    environment_id = service.create_environment(
        EnvironmentCreate(name="journal-test"), "journal-env"
    )[1]["environment_id"]
    account_id = service.create_account(
        environment_id,
        AccountCreate(
            exchange_id="okx",
            name="journal-account",
            initial_asset="USDT",
            initial_amount="751",
        ),
        "journal-account",
    )[1]["account_id"]
    with engine.begin() as connection:
        connection.execute(
            schema.simulated_liquidity.insert().values(
                environment_id=environment_id,
                exchange_id="okx",
                instrument_id="okx:SPOT:BTC/USDT",
                synchronization_generation=1,
                source_book_event_id="book-1",
                residual_bids_json=[["999.9", "10"]],
                residual_asks_json=[["1000.0", "10"]],
                market_book_json={},
                consumption_ids_json=[],
                updated_ts_ms=1_000,
            )
        )
    return environment_id, account_id


def preview_request() -> TradePlannerPreview:
    return TradePlannerPreview(
        instrument_id="okx:SPOT:BTC/USDT",
        entry_price="1000.0",
        planned_position_notional="100",
        stop_loss_price="950.0",
        take_profit_price="1120.0",
        max_position_notional="100",
        max_account_risk_rate="0.01",
        min_reward_risk_ratio="2",
    )


def revision_request(version: int) -> PlanRevisionCreate:
    values = preview_request().model_dump()
    values.pop("instrument_id")
    return PlanRevisionCreate(
        **values,
        journal_version=version,
        revision_reason="initial risk plan",
    )


def ready_journal(service: ApplicationService, environment_id: str, account_id: str) -> dict:
    journal = service.create_journal(
        environment_id,
        account_id,
        JournalCreate(title="Association", instrument_id="okx:SPOT:BTC/USDT"),
        "association-journal",
    )[1]
    service.create_plan_revision(
        environment_id,
        account_id,
        journal["journal_id"],
        revision_request(1),
        "association-revision",
    )
    return service.transition_journal(
        environment_id,
        account_id,
        journal["journal_id"],
        "READY",
        JournalTransition(version=2, reason="confirmed"),
        "association-ready",
    )[1]


def limit_order(account_id: str, *, quantity: str = "0.01") -> OrderCreate:
    return OrderCreate(
        account_id=account_id,
        instrument_id="okx:SPOT:BTC/USDT",
        side="BUY",
        order_type="LIMIT",
        quantity=quantity,
        limit_price="1000",
        latency_preset="NORMAL",
    )


def test_context_preview_and_journal_revision_do_not_change_trading_state(
    journal_service, engine
) -> None:
    environment_id, account_id = seed_scope(journal_service, engine)
    state_before = journal_service.get_environment(environment_id)["state_version"]

    context = journal_service.planner_context(
        environment_id, account_id, "okx:SPOT:BTC/USDT"
    )
    assert context["valuation_status"] == "COMPLETE"
    assert context["effective_account_equity"] == "751.000000000000000000000000"
    assert context["fee_schedule"]["conservative_fee_rate"] == "0.001"
    assert context["market_status"] == "VALID"

    preview = journal_service.preview_trade_plan(
        environment_id, account_id, preview_request()
    )
    assert preview["validation_status"] == "PASS"
    assert Decimal(preview["calculation"]["quantity"]) == Decimal("0.1")

    status, journal = journal_service.create_journal(
        environment_id,
        account_id,
        JournalCreate(
            title="Support bounce",
            instrument_id="okx:SPOT:BTC/USDT",
            timeframe="1h",
        ),
        "create-journal-1",
    )
    assert status == 201
    replay = journal_service.create_journal(
        environment_id,
        account_id,
        JournalCreate(
            title="Support bounce",
            instrument_id="okx:SPOT:BTC/USDT",
            timeframe="1h",
        ),
        "create-journal-1",
    )
    assert replay == (status, journal)

    revision = journal_service.create_plan_revision(
        environment_id,
        account_id,
        journal["journal_id"],
        revision_request(1),
        "revision-1",
    )[1]
    assert revision["validation_status"] == "PASS"
    assert revision["journal_version"] == 2

    ready = journal_service.transition_journal(
        environment_id,
        account_id,
        journal["journal_id"],
        "READY",
        JournalTransition(version=2, reason="numeric plan confirmed"),
        "ready-1",
    )[1]
    assert ready["status"] == "READY"
    assert ready["version"] == 3
    assert journal_service.get_environment(environment_id)["state_version"] == state_before


def test_optimistic_lock_scope_and_immutable_revision(journal_service, engine) -> None:
    environment_id, account_id = seed_scope(journal_service, engine)
    journal = journal_service.create_journal(
        environment_id,
        account_id,
        JournalCreate(title="Plan", instrument_id="okx:SPOT:BTC/USDT"),
        "create-plan",
    )[1]
    updated = journal_service.patch_journal(
        environment_id,
        account_id,
        journal["journal_id"],
        JournalPatch(version=1, title="Updated", change_reason="clarify title"),
    )
    assert updated["version"] == 2
    with pytest.raises(ApplicationError) as conflict:
        journal_service.patch_journal(
            environment_id,
            account_id,
            journal["journal_id"],
            JournalPatch(version=1, title="Stale", change_reason="stale edit"),
        )
    assert conflict.value.code == "JOURNAL_VERSION_CONFLICT"

    other_account = journal_service.create_account(
        environment_id,
        AccountCreate(
            exchange_id="okx",
            name="other",
            initial_asset="USDT",
            initial_amount="100",
        ),
        "other-account",
    )[1]["account_id"]
    with pytest.raises(ApplicationError) as missing:
        journal_service.get_journal(environment_id, other_account, journal["journal_id"])
    assert missing.value.code == "JOURNAL_NOT_FOUND"

    first = journal_service.create_plan_revision(
        environment_id,
        account_id,
        journal["journal_id"],
        revision_request(2),
        "revision-immutable",
    )[1]
    second_request = revision_request(3).model_copy(
        update={"planned_position_notional": Decimal("90"), "revision_reason": "reduce size"}
    )
    journal_service.create_plan_revision(
        environment_id,
        account_id,
        journal["journal_id"],
        second_request,
        "revision-immutable-2",
    )
    with engine.connect() as connection:
        original = connection.execute(
            select(schema.trade_plan_revisions).where(
                schema.trade_plan_revisions.c.plan_revision_id == first["plan_revision_id"]
            )
        ).mappings().one()
    assert original["planned_position_notional"] == Decimal("100")
    assert original["revision_number"] == 1


def test_journal_rest_contract_is_strict_and_returns_authoritative_config(
    journal_service, engine
) -> None:
    environment_id, account_id = seed_scope(journal_service, engine)
    client = TestClient(create_app(service=journal_service))
    base = f"/api/v1/environments/{environment_id}/accounts/{account_id}/journals"

    fees = client.get("/api/v1/config/fee-schedule")
    assert fees.status_code == 200
    assert fees.json()["conservative_fee_rate"] == "0.001"
    rules = client.get("/api/v1/market/rules/okx:SPOT:BTC/USDT")
    assert rules.status_code == 200
    assert rules.json()["quantity_increment"] == "1E-8"

    created = client.post(
        base,
        headers={"Idempotency-Key": "rest-journal"},
        json={
            "title": "REST plan",
            "instrument_id": "okx:SPOT:BTC/USDT",
            "unknown": "rejected",
        },
    )
    assert created.status_code == 422
    created = client.post(
        base,
        headers={"Idempotency-Key": "rest-journal"},
        json={"title": "REST plan", "instrument_id": "okx:SPOT:BTC/USDT"},
    )
    assert created.status_code == 201

    preview = client.post(
        f"{base}/trade-planner/preview",
        json={
            "instrument_id": "okx:SPOT:BTC/USDT",
            "entry_price": "1000.0",
            "planned_position_notional": "100",
            "stop_loss_price": "950.0",
            "take_profit_price": "1120.0",
            "max_position_notional": "100",
            "max_account_risk_rate": "0.01",
            "min_reward_risk_ratio": "2",
        },
    )
    assert preview.status_code == 200
    assert preview.json()["validation_status"] == "PASS"

    numeric = client.post(
        f"{base}/trade-planner/preview",
        json={
            "instrument_id": "okx:SPOT:BTC/USDT",
            "entry_price": 1000,
            "planned_position_notional": "100",
            "stop_loss_price": "950.0",
            "take_profit_price": "1120.0",
            "max_position_notional": "100",
            "max_account_risk_rate": "0.01",
            "min_reward_risk_ratio": "2",
        },
    )
    assert numeric.status_code == 422


def test_order_link_is_scoped_idempotent_audited_and_does_not_change_trading_state(
    journal_service, engine
) -> None:
    environment_id, account_id = seed_scope(journal_service, engine)
    journal = ready_journal(journal_service, environment_id, account_id)
    order = journal_service.create_order(
        environment_id, limit_order(account_id), "association-order"
    )[1]
    state_before = journal_service.get_environment(environment_id)["state_version"]
    request = JournalOrderLink(journal_version=3, note="plan order")

    linked = journal_service.link_journal_order(
        environment_id,
        account_id,
        journal["journal_id"],
        order["order_id"],
        request,
        "association-link",
    )
    assert linked[0] == 200
    assert linked[1]["journal_status"] == "ACTIVE"
    assert linked[1]["journal_version"] == 4
    assert journal_service.get_environment(environment_id)["state_version"] == state_before
    assert journal_service.link_journal_order(
        environment_id,
        account_id,
        journal["journal_id"],
        order["order_id"],
        request,
        "association-link",
    ) == linked
    recovered = journal_service.link_journal_order(
        environment_id,
        account_id,
        journal["journal_id"],
        order["order_id"],
        request,
        "association-link-recovery",
    )
    assert recovered[1]["journal_version"] == 4
    assert recovered[1]["journal_status"] == "ACTIVE"

    detail = journal_service.get_journal(
        environment_id, account_id, journal["journal_id"]
    )
    assert [item["order_id"] for item in detail["linked_orders"]] == [order["order_id"]]
    assert detail["linked_executions"] == []
    assert detail["metrics"]["trade_complete"] is False
    assert set(detail["metrics"]["incomplete_reasons"]) == {
        "NO_LINKED_EXECUTIONS",
        "ACTIVE_LINKED_ORDERS",
    }

    unlinked = journal_service.unlink_journal_order(
        environment_id,
        account_id,
        journal["journal_id"],
        order["order_id"],
        JournalOrderUnlink(journal_version=4, reason="ownership corrected"),
        "association-unlink",
    )
    assert unlinked[1]["journal_version"] == 5
    assert journal_service.get_environment(environment_id)["state_version"] == state_before
    with engine.connect() as connection:
        assert connection.execute(
            select(schema.paper_orders.c.order_id).where(
                schema.paper_orders.c.order_id == order["order_id"]
            )
        ).scalar_one() == order["order_id"]
        events = connection.execute(
            select(schema.journal_audit_events.c.event_type).where(
                schema.journal_audit_events.c.journal_id == journal["journal_id"]
            )
        ).scalars().all()
    assert "ORDER_LINKED" in events
    assert "ORDER_UNLINKED" in events


def test_order_cannot_be_linked_to_more_than_one_journal(
    journal_service, engine
) -> None:
    environment_id, account_id = seed_scope(journal_service, engine)
    first = ready_journal(journal_service, environment_id, account_id)
    order = journal_service.create_order(
        environment_id, limit_order(account_id), "exclusive-order"
    )[1]
    journal_service.link_journal_order(
        environment_id,
        account_id,
        first["journal_id"],
        order["order_id"],
        JournalOrderLink(journal_version=3),
        "exclusive-link",
    )
    second = journal_service.create_journal(
        environment_id,
        account_id,
        JournalCreate(title="Second", instrument_id="okx:SPOT:BTC/USDT"),
        "second-journal",
    )[1]
    journal_service.create_plan_revision(
        environment_id,
        account_id,
        second["journal_id"],
        revision_request(1),
        "second-revision",
    )
    second = journal_service.transition_journal(
        environment_id,
        account_id,
        second["journal_id"],
        "READY",
        JournalTransition(version=2, reason="confirmed"),
        "second-ready",
    )[1]
    with pytest.raises(ApplicationError) as duplicate:
        journal_service.link_journal_order(
            environment_id,
            account_id,
            second["journal_id"],
            order["order_id"],
            JournalOrderLink(journal_version=second["version"]),
            "duplicate-owner",
        )
    assert duplicate.value.code == "ORDER_ALREADY_LINKED"

    other_account = journal_service.create_account(
        environment_id,
        AccountCreate(
            exchange_id="okx", name="other-scope", initial_asset="USDT", initial_amount="100"
        ),
        "other-scope-account",
    )[1]["account_id"]
    other_order = journal_service.create_order(
        environment_id, limit_order(other_account), "other-scope-order"
    )[1]
    with pytest.raises(ApplicationError) as scope:
        journal_service.link_journal_order(
            environment_id,
            account_id,
            second["journal_id"],
            other_order["order_id"],
            JournalOrderLink(journal_version=second["version"]),
            "scope-mismatch",
        )
    assert scope.value.code == "ORDER_SCOPE_MISMATCH"

    eth_order = journal_service.create_order(
        environment_id,
        limit_order(account_id).model_copy(
            update={"instrument_id": "okx:SPOT:ETH/USDT", "limit_price": Decimal("100")}
        ),
        "other-instrument-order",
    )[1]
    with pytest.raises(ApplicationError) as instrument:
        journal_service.link_journal_order(
            environment_id,
            account_id,
            second["journal_id"],
            eth_order["order_id"],
            JournalOrderLink(journal_version=second["version"]),
            "instrument-mismatch",
        )
    assert instrument.value.code == "INSTRUMENT_MISMATCH"


def test_metrics_replay_account_history_and_attribute_linked_sell_realized_pnl(
    journal_service, engine
) -> None:
    environment_id, account_id = seed_scope(journal_service, engine)
    journal = ready_journal(journal_service, environment_id, account_id)
    buy = journal_service.create_order(
        environment_id,
        limit_order(account_id, quantity="0.1"),
        "metrics-buy",
    )[1]
    sell_id = "order_metrics_sell"
    with engine.begin() as connection:
        connection.execute(
            schema.paper_orders.update()
            .where(schema.paper_orders.c.order_id == buy["order_id"])
            .values(status="FILLED", filled_quantity=Decimal("0.1"))
        )
        connection.execute(
            schema.paper_orders.insert().values(
                order_id=sell_id,
                environment_id=environment_id,
                account_id=account_id,
                instrument_id="okx:SPOT:BTC/USDT",
                side="SELL",
                order_type="MARKET",
                quantity=Decimal("0.1"),
                limit_price=None,
                reference_price=Decimal("1100"),
                max_quote_budget=None,
                reserved_asset="BTC",
                reserved_amount=Decimal("0.1"),
                filled_quantity=Decimal("0.1"),
                cumulative_quote_amount=Decimal("110"),
                cumulative_fee=Decimal("0.11"),
                average_fill_price=Decimal("1100"),
                time_in_force="IOC",
                fee_schedule_id="journal-test-v1",
                reserved_fee_rate=Decimal("0.001"),
                status="FILLED",
                submitted_ts_ms=2_000,
                scheduled_execution_ts_ms=2_000,
                market_entry_ts_ms=2_000,
                executed_ts_ms=2_000,
                configured_latency_ms=0,
                actual_simulated_delay_ms=0,
                scheduler_lag_ms=0,
                submission_quote_event_id="book-2",
                execution_quote_event_id="book-2",
                termination_reason=None,
                order_sequence=99,
                created_ts_ms=2_000,
                updated_ts_ms=2_000,
            )
        )
        connection.execute(
            schema.executions.insert(),
            [
                {
                    "execution_id": "exec_metrics_buy",
                    "environment_id": environment_id,
                    "order_id": buy["order_id"],
                    "account_id": account_id,
                    "instrument_id": "okx:SPOT:BTC/USDT",
                    "side": "BUY",
                    "price": Decimal("1000"),
                    "quantity": Decimal("0.1"),
                    "quote_amount": Decimal("100"),
                    "fee_asset": "USDT",
                    "fee_amount": Decimal("0.1"),
                    "executed_ts_ms": 1_000,
                    "liquidity_role": "TAKER",
                    "market_event_id": "book-1",
                    "fill_sequence": 1,
                    "execution_sequence": 1,
                },
                {
                    "execution_id": "exec_metrics_sell",
                    "environment_id": environment_id,
                    "order_id": sell_id,
                    "account_id": account_id,
                    "instrument_id": "okx:SPOT:BTC/USDT",
                    "side": "SELL",
                    "price": Decimal("1100"),
                    "quantity": Decimal("0.1"),
                    "quote_amount": Decimal("110"),
                    "fee_asset": "USDT",
                    "fee_amount": Decimal("0.11"),
                    "executed_ts_ms": 2_000,
                    "liquidity_role": "TAKER",
                    "market_event_id": "book-2",
                    "fill_sequence": 1,
                    "execution_sequence": 2,
                },
            ],
        )

    first = journal_service.link_journal_order(
        environment_id,
        account_id,
        journal["journal_id"],
        buy["order_id"],
        JournalOrderLink(journal_version=3),
        "metrics-link-buy",
    )[1]
    journal_service.link_journal_order(
        environment_id,
        account_id,
        journal["journal_id"],
        sell_id,
        JournalOrderLink(journal_version=first["journal_version"]),
        "metrics-link-sell",
    )
    metrics = journal_service.journal_metrics(
        environment_id, account_id, journal["journal_id"]
    )
    assert metrics["trade_complete"] is True
    assert Decimal(metrics["net_base_quantity"]) == 0
    assert Decimal(metrics["fees_by_asset"]["USDT"]) == Decimal("0.21")
    assert Decimal(metrics["attributed_realized_pnl_by_currency"]["USDT"]) == Decimal(
        "9.79"
    )


def test_order_association_rest_contract(journal_service, engine) -> None:
    environment_id, account_id = seed_scope(journal_service, engine)
    journal = ready_journal(journal_service, environment_id, account_id)
    order = journal_service.create_order(
        environment_id, limit_order(account_id), "rest-association-order"
    )[1]
    client = TestClient(create_app(service=journal_service))
    path = (
        f"/api/v1/environments/{environment_id}/accounts/{account_id}/journals/"
        f"{journal['journal_id']}/orders/{order['order_id']}"
    )
    linked = client.put(
        path,
        headers={"Idempotency-Key": "rest-association-link"},
        json={"journal_version": 3, "note": "REST link"},
    )
    assert linked.status_code == 200
    assert linked.json()["journal_status"] == "ACTIVE"
    metrics = client.get(path.rsplit("/orders/", 1)[0] + "/metrics")
    assert metrics.status_code == 200
    assert metrics.json()["linked_order_count"] == 1
    unlinked = client.request(
        "DELETE",
        path,
        headers={"Idempotency-Key": "rest-association-unlink"},
        json={"journal_version": 4, "reason": "REST correction"},
    )
    assert unlinked.status_code == 200
    assert unlinked.json()["journal_version"] == 5
