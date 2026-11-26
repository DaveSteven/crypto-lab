"""Cumulative realized PnL derived from the full Fill History (Task 1.12.10-A)."""

from decimal import Decimal

import pytest

from crypto_lab.trading import ExecutionRecord, OrderSide, PortfolioEngine, realized_pnl_summary
from crypto_lab.trading.portfolio import InsufficientPositionError


def fill(
    execution_id: str,
    side: OrderSide,
    price: str,
    quantity: str,
    fee: str,
    ts: int,
    *,
    instrument: str = "okx:SPOT:BTC/USDT",
    account: str = "acc-1",
) -> ExecutionRecord:
    price_d, qty_d = Decimal(price), Decimal(quantity)
    quote = instrument.split("/")[1]
    return ExecutionRecord(
        execution_id=execution_id,
        order_id=f"order-{execution_id}",
        account_id=account,
        instrument_id=instrument,
        side=side,
        price=price_d,
        quantity=qty_d,
        quote_amount=price_d * qty_d,
        fee_asset=quote,
        fee_amount=Decimal(fee),
        executed_ts_ms=ts,
    )


BUY, SELL = OrderSide.BUY, OrderSide.SELL


def pnl(fills, account="acc-1") -> dict[str, Decimal]:
    return realized_pnl_summary(tuple(fills), account)["cumulative_realized_pnl_by_currency"]


def test_no_fills_is_a_legitimate_zero_set() -> None:
    summary = realized_pnl_summary((), "acc-1")
    assert summary["cumulative_realized_pnl_by_currency"] == {}
    assert summary["cumulative_fees_by_currency"] == {}


def test_single_buy_has_no_realized_pnl_but_counts_fees_once() -> None:
    summary = realized_pnl_summary((fill("f1", BUY, "100", "1", "0.1", 1),), "acc-1")
    assert summary["cumulative_realized_pnl_by_currency"] == {"USDT": Decimal("0")}
    assert summary["cumulative_fees_by_currency"] == {"USDT": Decimal("0.1")}


def test_partial_sell_realizes_against_moving_average_cost() -> None:
    # cost basis 100 + 0.1 fee = 100.1 for 1 BTC; sell 0.4 @ 110 fee 0.044:
    # relieved cost 40.04; proceeds 44 - 0.044; pnl = 3.916
    result = pnl([fill("b", BUY, "100", "1", "0.1", 1), fill("s", SELL, "110", "0.4", "0.044", 2)])
    assert result == {"USDT": Decimal("3.916")}


def test_pnl_survives_full_close_and_matches_closed_positions_projection() -> None:
    fills = [fill("b", BUY, "100", "1", "0.1", 1), fill("s", SELL, "110", "1", "0.11", 2)]
    assert pnl(fills) == {"USDT": Decimal("9.79")}  # 110 - 0.11 - 100.1
    # The positions projection drops the closed position; the summary keeps it.
    assert all(p.quantity == 0 for p in PortfolioEngine(tuple(fills)).positions())


def test_reopen_after_close_accumulates_across_cycles() -> None:
    fills = [
        fill("b1", BUY, "100", "1", "0", 1),
        fill("s1", SELL, "110", "1", "0", 2),  # +10
        fill("b2", BUY, "200", "1", "0", 3),
        fill("s2", SELL, "190", "1", "0", 4),  # -10 loss
        fill("b3", BUY, "50", "2", "0", 5),
        fill("s3", SELL, "60", "1", "0", 6),  # +10 on the open remainder
    ]
    assert pnl(fills) == {"USDT": Decimal("10")}


def test_loss_is_negative() -> None:
    result = pnl([fill("b", BUY, "100", "1", "0", 1), fill("s", SELL, "90", "1", "0", 2)])
    assert result == {"USDT": Decimal("-10")}


def test_multi_level_fills_of_one_order_equal_a_single_blended_fill() -> None:
    levels = [
        fill("b1", BUY, "100", "0.5", "0.05", 1),
        fill("b2", BUY, "102", "0.5", "0.051", 1),
        fill("s", SELL, "110", "1", "0.11", 2),
    ]
    blended = [
        fill("bb", BUY, "101", "1", "0.101", 1),
        fill("s", SELL, "110", "1", "0.11", 2),
    ]
    assert pnl(levels) == pnl(blended)


def test_duplicate_fill_is_rejected_not_double_counted() -> None:
    with pytest.raises(ValueError, match="duplicate execution"):
        realized_pnl_summary(
            (fill("f1", BUY, "100", "1", "0", 1), fill("f1", BUY, "100", "1", "0", 1)), "acc-1"
        )


def test_incremental_equals_full_rebuild() -> None:
    fills = [
        fill("b1", BUY, "100", "2", "0.2", 1),
        fill("s1", SELL, "105", "1", "0.105", 2),
        fill("b2", BUY, "99", "1", "0.099", 3),
        fill("s2", SELL, "120", "2", "0.24", 4),
    ]
    engine = PortfolioEngine()
    incremental = Decimal(0)
    for item in fills:
        engine.apply(item)
    incremental = sum((p.realized_pnl for p in engine.positions()), Decimal(0))
    assert pnl(fills)["USDT"] == incremental


def test_accounts_are_isolated() -> None:
    fills = [
        fill("a1", BUY, "100", "1", "0", 1, account="acc-1"),
        fill("a2", SELL, "110", "1", "0", 2, account="acc-1"),
        fill("b1", BUY, "100", "1", "0", 1, account="acc-2"),
        fill("b2", SELL, "50", "1", "0", 2, account="acc-2"),
    ]
    assert pnl(fills, "acc-1") == {"USDT": Decimal("10")}
    assert pnl(fills, "acc-2") == {"USDT": Decimal("-50")}
    assert pnl(fills, "acc-3") == {}


def test_settlement_currencies_are_never_added_together() -> None:
    fills = [
        fill("u1", BUY, "100", "1", "0", 1),
        fill("u2", SELL, "110", "1", "0", 2),
        fill("j1", BUY, "10000", "1", "0", 3, instrument="okx:SPOT:BTC/JPY"),
        fill("j2", SELL, "9000", "1", "0", 4, instrument="okx:SPOT:BTC/JPY"),
    ]
    assert pnl(fills) == {"JPY": Decimal("-1000"), "USDT": Decimal("10")}


def test_sell_beyond_position_is_unavailable_not_silently_zero() -> None:
    with pytest.raises(InsufficientPositionError):
        realized_pnl_summary((fill("s", SELL, "100", "1", "0", 1),), "acc-1")
