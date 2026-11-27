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
    JournalPatch,
    JournalTransition,
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
