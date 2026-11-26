"""Account lifetime realized PnL through the real REST app on PostgreSQL (Task 1.12.10-A)."""

from __future__ import annotations

import contextlib
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from test_restart_recovery_postgres import (  # sibling module: shared PostgreSQL helpers
    INSTRUMENT,
    World,
    book,
    start_app,
    trade,
)

from crypto_lab.persistence.store import PostgresStore


def run_round_trip(world: World, env: str, acc: str, *, exit_bid: str, tag: str) -> None:
    """Maker buy (resting limit @100 filled by a through-trade), then taker market sell."""
    dispatcher = world.old_dispatcher(env)
    world.clock.now += 10
    dispatcher.apply_order_book_view(book(world.clock.now, bid="99", ask="101"))
    world.order(
        env,
        acc,
        f"{tag}-buy",
        order_type="LIMIT",
        side="BUY",
        quantity="1",
        limit_price="100",
        latency_preset="IDEAL",
        custom_latency_ms=None,
    )
    world.clock.now += 10
    dispatcher.run_due()  # limit order enters the market
    world.clock.now += 10
    dispatcher.apply_trade(trade(f"{tag}-t1", "99", "5", world.clock.now))  # maker fill @100
    world.clock.now += 10
    dispatcher.apply_order_book_view(book(world.clock.now, bid=exit_bid, ask="120"))
    world.order(
        env,
        acc,
        f"{tag}-sell",
        side="SELL",
        quantity="1",
        latency_preset="IDEAL",
        custom_latency_ms=None,
    )
    world.clock.now += 10
    dispatcher.run_due()  # taker market sell at the bid


def get_pnl(client: TestClient, env: str, acc: str) -> dict:
    response = client.get(f"/api/v1/environments/{env}/accounts/{acc}/pnl")
    assert response.status_code == 200, response.text
    return response.json()


def test_closed_round_trip_keeps_cumulative_pnl_with_maker_and_taker_fees(engine, clock) -> None:
    world = World(engine, clock)
    env, acc = world.environment("pnl")
    run_round_trip(world, env, acc, exit_bid="110", tag="r1")
    app = start_app(engine, clock)
    with TestClient(app) as client:
        pnl = get_pnl(client, env, acc)
        snapshot = client.get(
            f"/api/v1/environments/{env}/snapshot", params={"account_id": acc}
        ).json()
    # maker buy @100 fee 0.1, taker sell @110 fee 0.11: 110 - 0.11 - 100.1
    assert pnl["status"] == "AVAILABLE"
    assert pnl["scope"] == "ACCOUNT_LIFETIME_FILL_HISTORY"
    assert pnl["cost_method"] == "MOVING_AVERAGE"
    assert Decimal(pnl["cumulative_realized_pnl_by_currency"]["USDT"]) == Decimal("9.79")
    assert Decimal(pnl["cumulative_fees_by_currency"]["USDT"]) == Decimal("0.21")
    # The closed position is gone from the projection, the PnL is not.
    assert snapshot["positions"] == []
    assert (
        snapshot["pnl"]["cumulative_realized_pnl_by_currency"]
        == pnl["cumulative_realized_pnl_by_currency"]
    )
    assert snapshot["pnl"]["state_version"] == snapshot["state_version"]
    assert len(snapshot["executions"]) == 2


def test_pnl_is_identical_after_service_restart(engine, clock) -> None:
    world = World(engine, clock)
    env, acc = world.environment("restart")
    run_round_trip(world, env, acc, exit_bid="105", tag="r")
    values = []
    for _ in range(2):
        clock.now += 5_000
        with TestClient(start_app(engine, clock)) as client:
            pnl = get_pnl(client, env, acc)
            values.append(
                (pnl["cumulative_realized_pnl_by_currency"], pnl["cumulative_fees_by_currency"])
            )
    assert values[0] == values[1]
    assert Decimal(values[0][0]["USDT"]) == Decimal("4.795")  # 105 - 0.105 - 100.1


def test_new_account_and_isolated_environments(engine, clock) -> None:
    world = World(engine, clock)
    env_a, acc_a = world.environment("a")
    env_b, acc_b = world.environment("b")
    env_c, acc_c = world.environment("c")
    run_round_trip(world, env_a, acc_a, exit_bid="110", tag="a")  # profit
    run_round_trip(world, env_b, acc_b, exit_bid="90", tag="b")  # loss
    with TestClient(start_app(engine, clock)) as client:
        a, b, c = (
            get_pnl(client, e, x) for e, x in [(env_a, acc_a), (env_b, acc_b), (env_c, acc_c)]
        )
    assert Decimal(a["cumulative_realized_pnl_by_currency"]["USDT"]) == Decimal("9.79")
    assert Decimal(b["cumulative_realized_pnl_by_currency"]["USDT"]) == Decimal(
        "-10.19"
    )  # 90-0.09-100.1
    # A legitimate zero: no fills means no realized PnL, explicitly AVAILABLE.
    assert c["status"] == "AVAILABLE"
    assert c["cumulative_realized_pnl_by_currency"] == {}
    assert c["cumulative_fees_by_currency"] == {}


def test_unknown_account_is_a_404_not_zero(engine, clock) -> None:
    world = World(engine, clock)
    env, _ = world.environment("x")
    with TestClient(start_app(engine, clock)) as client:
        response = client.get(f"/api/v1/environments/{env}/accounts/nope/pnl")
    assert response.status_code == 404


def test_rebuild_failure_is_reported_unavailable_never_zero(engine, clock, monkeypatch) -> None:
    world = World(engine, clock)
    env, acc = world.environment("broken")
    run_round_trip(world, env, acc, exit_bid="110", tag="x")

    def boom(self, environment_id):
        raise RuntimeError("fill history unreadable")

    monkeypatch.setattr(PostgresStore, "restore_executions", boom)
    with TestClient(start_app(engine, clock)) as client:
        pnl = get_pnl(client, env, acc)
        snapshot = client.get(f"/api/v1/environments/{env}/snapshot", params={"account_id": acc})
    assert pnl["status"] == "UNAVAILABLE"
    assert "fill history unreadable" in pnl["reason"]
    assert "cumulative_realized_pnl_by_currency" not in pnl
    assert snapshot.status_code == 200
    assert snapshot.json()["pnl"]["status"] == "UNAVAILABLE"


def test_rolled_back_fill_does_not_change_pnl(engine, clock) -> None:
    world = World(engine, clock)
    env, acc = world.environment("rollback")
    dispatcher = world.old_dispatcher(env)
    world.clock.now += 10
    dispatcher.apply_order_book_view(book(world.clock.now))
    world.order(
        env,
        acc,
        "lim",
        order_type="LIMIT",
        side="BUY",
        quantity="1",
        limit_price="100",
        latency_preset="IDEAL",
        custom_latency_ms=None,
    )
    world.clock.now += 10
    dispatcher.run_due()
    real = dispatcher.transaction

    @contextlib.contextmanager
    def failing(environment_id: str):
        with real(environment_id) as store:
            yield store
            raise RuntimeError("injected failure before commit")

    world.clock.now += 10
    dispatcher.transaction = failing
    dispatcher.apply_trade(trade("rb", "99", "5", world.clock.now))  # isolated + rolled back
    dispatcher.transaction = real
    with TestClient(start_app(engine, clock)) as client:
        pnl = get_pnl(client, env, acc)
    assert pnl["cumulative_realized_pnl_by_currency"] == {}
    assert pnl["cumulative_fees_by_currency"] == {}


@pytest.mark.parametrize("instrument", [INSTRUMENT])
def test_pnl_endpoint_matches_full_rebuild_from_rows(engine, clock, instrument) -> None:
    """The API number equals an independent replay of the persisted fills."""
    from sqlalchemy import select

    from crypto_lab.persistence import schema
    from crypto_lab.trading import PortfolioEngine

    world = World(engine, clock)
    env, acc = world.environment("rebuild")
    run_round_trip(world, env, acc, exit_bid="108", tag="rb")
    with engine.connect() as connection:
        rows = (
            connection.execute(
                select(schema.executions)
                .where(schema.executions.c.account_id == acc)
                .order_by(schema.executions.c.execution_sequence)
            )
            .mappings()
            .all()
        )
    replay = Decimal(0)
    from crypto_lab.trading import ExecutionRecord

    fills = tuple(
        ExecutionRecord.model_validate(
            {
                k: v
                for k, v in row.items()
                if k not in {"environment_id", "fill_sequence", "execution_sequence"}
            }
        )
        for row in rows
    )
    replay = sum((p.realized_pnl for p in PortfolioEngine(fills).positions()), Decimal(0))
    with TestClient(start_app(engine, clock)) as client:
        pnl = get_pnl(client, env, acc)
    assert Decimal(pnl["cumulative_realized_pnl_by_currency"]["USDT"]) == replay
