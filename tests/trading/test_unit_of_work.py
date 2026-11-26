from decimal import Decimal

import pytest

from crypto_lab.models import ExchangeId
from crypto_lab.trading import (
    DeterministicIdGenerator,
    ExecutionSimulator,
    InMemoryUnitOfWork,
    ManualClock,
    OrderService,
    OrderSide,
    OrderType,
    PortfolioEngine,
    create_paper_account,
)


def setup_transaction():
    ids = DeterministicIdGenerator("uow-test")
    clock = ManualClock(1_000)
    ledger = create_paper_account(ExchangeId.OKX, id_generator=ids, clock=clock)
    orders = OrderService(ledger, clock=clock)
    portfolio = PortfolioEngine()
    simulator = ExecutionSimulator(orders, portfolio=portfolio)
    uow = InMemoryUnitOfWork((ledger, orders, simulator, portfolio, ids))
    return ids, ledger, orders, portfolio, simulator, uow


def test_commit_publishes_ledger_order_fill_and_portfolio_together() -> None:
    _, ledger, orders, portfolio, simulator, uow = setup_transaction()
    order = orders.place(
        instrument_id="okx:SPOT:BTC/USDT",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("1"),
        limit_price=Decimal("100"),
        estimated_buy_fee_rate=Decimal("0.01"),
    )

    execution = uow.run(
        lambda: simulator.execute(
            order.order_id,
            price=Decimal("100"),
            quantity=Decimal("1"),
            fee_rate=Decimal("0.01"),
        )
    )

    assert simulator.executions() == (execution,)
    assert portfolio.position(order.account_id, order.instrument_id).quantity == Decimal("1")
    assert ledger.balance("BTC").available == Decimal("1")


def test_commit_hook_failure_rolls_back_all_participants_and_id_state() -> None:
    ids, ledger, orders, portfolio, simulator, uow = setup_transaction()
    order = orders.place(
        instrument_id="okx:SPOT:BTC/USDT",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("1"),
        limit_price=Decimal("100"),
        estimated_buy_fee_rate=Decimal("0.01"),
    )
    before = (
        ledger.entries,
        ledger.balances(),
        orders.get(order.order_id),
        simulator.executions(),
        portfolio.positions(),
        ids.snapshot_state(),
    )

    def fail_commit() -> None:
        raise RuntimeError("injected commit failure")

    with pytest.raises(RuntimeError, match="injected"):
        uow.run(
            lambda: simulator.execute(
                order.order_id,
                price=Decimal("100"),
                quantity=Decimal("1"),
                fee_rate=Decimal("0.01"),
            ),
            before_commit=fail_commit,
        )

    after = (
        ledger.entries,
        ledger.balances(),
        orders.get(order.order_id),
        simulator.executions(),
        portfolio.positions(),
        ids.snapshot_state(),
    )
    assert after == before


def test_failed_transaction_retries_with_same_execution_and_entry_ids() -> None:
    _, ledger, orders, _, simulator, uow = setup_transaction()
    order = orders.place(
        instrument_id="okx:SPOT:BTC/USDT",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("1"),
        limit_price=Decimal("100"),
    )
    captured: list[tuple[str, tuple[str, ...]]] = []

    def operation():
        execution = simulator.execute(
            order.order_id,
            price=Decimal("100"),
            quantity=Decimal("1"),
            fee_rate=Decimal("0"),
        )
        captured.append(
            (execution.execution_id, tuple(entry.entry_id for entry in ledger.entries[-3:]))
        )
        return execution

    with pytest.raises(RuntimeError):
        uow.run(operation, before_commit=lambda: (_ for _ in ()).throw(RuntimeError("fail")))
    retried = uow.run(operation)

    assert captured[0] == captured[1]
    assert retried.execution_id == captured[0][0]


@pytest.mark.parametrize("failure_stage", ["LEDGER", "ORDER", "PORTFOLIO", "FILL_HISTORY"])
def test_failure_injection_at_each_commit_stage_restores_state(failure_stage: str) -> None:
    ids = DeterministicIdGenerator(f"failure-{failure_stage}")
    clock = ManualClock(1_000)
    ledger = create_paper_account(ExchangeId.OKX, id_generator=ids, clock=clock)
    orders = OrderService(ledger, clock=clock)
    portfolio = PortfolioEngine()

    def inject(stage: str) -> None:
        if stage == failure_stage:
            raise RuntimeError(f"injected {stage}")

    simulator = ExecutionSimulator(orders, portfolio=portfolio, failure_injector=inject)
    uow = InMemoryUnitOfWork((ledger, orders, simulator, portfolio, ids))
    order = orders.place(
        instrument_id="okx:SPOT:BTC/USDT",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("1"),
        limit_price=Decimal("100"),
    )
    before = (ledger.entries, ledger.balances(), orders.orders(), portfolio.positions())

    with pytest.raises(RuntimeError, match=failure_stage):
        uow.run(
            lambda: simulator.execute(
                order.order_id,
                price=Decimal("100"),
                quantity=Decimal("1"),
                fee_rate=Decimal("0"),
            )
        )

    assert (ledger.entries, ledger.balances(), orders.orders(), portfolio.positions()) == before
    assert simulator.executions() == ()


def test_incremental_portfolio_equals_rebuild_from_complete_fill_history() -> None:
    _, _, orders, portfolio, simulator, uow = setup_transaction()
    first_buy = orders.place(
        instrument_id="okx:SPOT:BTC/USDT",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("1"),
        limit_price=Decimal("100"),
        estimated_buy_fee_rate=Decimal("0.01"),
    )
    uow.run(
        lambda: simulator.execute(
            first_buy.order_id,
            price=Decimal("100"),
            quantity=Decimal("1"),
            fee_rate=Decimal("0.01"),
        )
    )
    second_buy = orders.place(
        instrument_id="okx:SPOT:BTC/USDT",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("1"),
        limit_price=Decimal("120"),
        estimated_buy_fee_rate=Decimal("0.01"),
    )
    uow.run(
        lambda: simulator.execute(
            second_buy.order_id,
            price=Decimal("120"),
            quantity=Decimal("1"),
            fee_rate=Decimal("0.01"),
        )
    )
    sell = orders.place(
        instrument_id="okx:SPOT:BTC/USDT",
        side=OrderSide.SELL,
        order_type=OrderType.LIMIT,
        quantity=Decimal("0.5"),
        limit_price=Decimal("130"),
    )
    uow.run(
        lambda: simulator.execute(
            sell.order_id,
            price=Decimal("130"),
            quantity=Decimal("0.5"),
            fee_rate=Decimal("0.01"),
        )
    )

    rebuilt = PortfolioEngine(simulator.executions())

    assert portfolio.positions() == rebuilt.positions()
    position = portfolio.position(first_buy.account_id, first_buy.instrument_id)
    assert position.quantity == Decimal("1.5")
    assert position.realized_pnl == Decimal("8.80")
