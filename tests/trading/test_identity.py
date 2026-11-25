from decimal import Decimal

from crypto_lab.models import ExchangeId
from crypto_lab.trading import (
    DeterministicIdGenerator,
    ExecutionSimulator,
    ManualClock,
    OrderService,
    OrderSide,
    OrderType,
    create_paper_account,
)


def run_identity_sequence(namespace: str) -> tuple[object, ...]:
    generator = DeterministicIdGenerator(namespace)
    clock = ManualClock(1_000)
    ledger = create_paper_account(
        ExchangeId.OKX,
        id_generator=generator,
        clock=clock,
    )
    orders = OrderService(ledger, clock=clock)
    order = orders.place(
        instrument_id="okx:SPOT:BTC/USDT",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("1"),
        limit_price=Decimal("100"),
    )
    return (
        ledger.account.account_id,
        order.order_id,
        tuple(entry.entry_id for entry in ledger.entries),
    )


def test_same_namespace_and_inputs_generate_same_business_ids() -> None:
    assert run_identity_sequence("experiment-1") == run_identity_sequence("experiment-1")


def test_independent_environment_namespaces_are_isolated() -> None:
    assert run_identity_sequence("experiment-1") != run_identity_sequence("experiment-2")


def test_deterministic_generator_state_can_be_rolled_back() -> None:
    generator = DeterministicIdGenerator("experiment-1")
    snapshot = generator.snapshot_state()
    first = generator.next_id("execution")
    generator.restore_state(snapshot)

    assert generator.next_id("execution") == first


def replay_execution() -> tuple[object, ...]:
    generator = DeterministicIdGenerator("full-replay")
    clock = ManualClock(1_000)
    ledger = create_paper_account(
        ExchangeId.OKX,
        id_generator=generator,
        clock=clock,
    )
    orders = OrderService(ledger, clock=clock)
    order = orders.place(
        instrument_id="okx:SPOT:BTC/USDT",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("1"),
        limit_price=Decimal("100"),
    )
    execution = ExecutionSimulator(orders).execute(
        order.order_id,
        price=Decimal("100"),
        quantity=Decimal("1"),
        fee_rate=Decimal("0"),
    )
    return (
        orders.get(order.order_id).model_dump(),
        execution.model_dump(),
        tuple(entry.model_dump() for entry in ledger.entries),
        ledger.balances(),
    )


def test_full_execution_business_state_replays_with_identical_ids() -> None:
    assert replay_execution() == replay_execution()
