import os
from decimal import Decimal

import pytest
from sqlalchemy import create_engine

from crypto_lab.api.errors import ApplicationError
from crypto_lab.api.schemas import AccountCreate, EnvironmentCreate, OrderCreate
from crypto_lab.api.service import ApplicationService
from crypto_lab.persistence import schema
from crypto_lab.trading import FeeSchedule


@pytest.fixture(scope="module")
def database_url() -> str:
    value = os.getenv("CRYPTO_LAB_TEST_DATABASE_URL")
    if not value:
        pytest.skip("CRYPTO_LAB_TEST_DATABASE_URL is not configured")
    return value


@pytest.fixture
def service(database_url: str):
    engine = create_engine(database_url)
    with engine.begin() as connection:
        for table in reversed(schema.metadata.sorted_tables):
            connection.execute(table.delete())
    result = ApplicationService(
        engine,
        fee_schedule=FeeSchedule(
            schedule_id="test-v1",
            maker_rate=Decimal("0.001"),
            taker_rate=Decimal("0.002"),
        ),
        now_ms=lambda: 1_000,
    )
    yield result
    engine.dispose()


def create_environment_and_account(service: ApplicationService):
    _, environment = service.create_environment(EnvironmentCreate(name="test"), "env-key")
    environment_id = environment["environment_id"]
    _, account = service.create_account(
        environment_id,
        AccountCreate(
            exchange_id="okx",
            name="paper",
            initial_asset="USDT",
            initial_amount="10000",
        ),
        "account-key",
    )
    return environment_id, account["account_id"]


def test_environment_creation_is_idempotent_and_detects_key_reuse(service) -> None:
    request = EnvironmentCreate(name="one")
    first = service.create_environment(request, "same-key")
    second = service.create_environment(request, "same-key")
    assert first == second

    with pytest.raises(ApplicationError, match="different request") as error:
        service.create_environment(EnvironmentCreate(name="two"), "same-key")
    assert error.value.code == "IDEMPOTENCY_KEY_REUSED"


def test_limit_order_freezes_funds_persists_pending_and_cancel_releases(service) -> None:
    environment_id, account_id = create_environment_and_account(service)
    request = OrderCreate(
        account_id=account_id,
        instrument_id="okx:SPOT:BTC/USDT",
        side="BUY",
        order_type="LIMIT",
        quantity="2",
        limit_price="100",
        latency_preset="NORMAL",
    )
    first = service.create_order(environment_id, request, "order-key")
    replay = service.create_order(environment_id, request, "order-key")
    assert first == replay
    order = first[1]
    assert order["status"] == "PENDING_EXECUTION"
    assert order["configured_latency_ms"] == 100

    balances = service.balances(environment_id, account_id)
    assert balances[0]["available"] == "9799.600000000000000000000000"
    assert balances[0]["locked"] == "200.400000000000000000000000"

    canceled = service.cancel_order(environment_id, order["order_id"], "cancel-key")
    assert canceled[1]["status"] == "CANCELED"
    balances = service.balances(environment_id, account_id)
    assert balances[0]["available"] == "10000.000000000000000000000000"
    assert balances[0]["locked"] == "0E-24"


def test_resources_are_scoped_to_environment(service) -> None:
    environment_id, account_id = create_environment_and_account(service)
    other_id = service.create_environment(EnvironmentCreate(name="other"), "other-key")[1][
        "environment_id"
    ]
    with pytest.raises(ApplicationError) as error:
        service.get_account(other_id, account_id)
    assert error.value.code == "ACCOUNT_NOT_FOUND"
    assert service.get_account(environment_id, account_id)["account_id"] == account_id


def test_two_accounts_keep_independent_pending_schedules(service) -> None:
    environment_id, first_account = create_environment_and_account(service)
    second_account = service.create_account(
        environment_id,
        AccountCreate(
            exchange_id="okx",
            name="second",
            initial_asset="USDT",
            initial_amount="1000",
        ),
        "second-account-key",
    )[1]["account_id"]
    for number, account_id in enumerate((first_account, second_account), start=1):
        service.create_order(
            environment_id,
            OrderCreate(
                account_id=account_id,
                instrument_id="okx:SPOT:BTC/USDT",
                side="BUY",
                order_type="LIMIT",
                quantity="1",
                limit_price="10",
            ),
            f"order-key-{number}",
        )
    orders = service.list_orders(environment_id, 10, None, "PENDING_EXECUTION")
    assert {order["account_id"] for order in orders} == {first_account, second_account}
