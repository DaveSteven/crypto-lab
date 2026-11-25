from decimal import Decimal

import pytest

from crypto_lab.models import (
    DataQualityStatus,
    DataSourceType,
    ExchangeId,
    MarketEventEnvelope,
    Ticker,
    TransportType,
)
from crypto_lab.trading import (
    ExecutionRecord,
    InsufficientPositionError,
    OrderSide,
    PortfolioEngine,
)


def execution(
    execution_id: str,
    side: OrderSide,
    price: str,
    quantity: str,
    fee: str,
    executed_ts_ms: int,
) -> ExecutionRecord:
    decimal_price = Decimal(price)
    decimal_quantity = Decimal(quantity)
    return ExecutionRecord(
        execution_id=execution_id,
        order_id=f"order-{execution_id}",
        account_id="account-1",
        instrument_id="binance:SPOT:BTC/USDT",
        side=side,
        price=decimal_price,
        quantity=decimal_quantity,
        quote_amount=decimal_price * decimal_quantity,
        fee_asset="USDT",
        fee_amount=Decimal(fee),
        executed_ts_ms=executed_ts_ms,
    )


def ticker(bid: str, *, quality: DataQualityStatus = DataQualityStatus.VALID):
    return MarketEventEnvelope[Ticker](
        event_id="price-event",
        event_type="TICKER",
        exchange_id=ExchangeId.BINANCE,
        instrument_id="binance:SPOT:BTC/USDT",
        source_type=DataSourceType.MOCK,
        transport=TransportType.FILE,
        received_ts_ms=10,
        quality_status=quality,
        payload=Ticker(bid=bid, ask="999999", last="1"),
    )


def populated_portfolio() -> PortfolioEngine:
    portfolio = PortfolioEngine()
    portfolio.apply(execution("buy-1", OrderSide.BUY, "50000", "0.1", "5", 1))
    portfolio.apply(execution("buy-2", OrderSide.BUY, "60000", "0.1", "6", 2))
    return portfolio


def test_buys_use_weighted_average_cost_including_fees() -> None:
    position = populated_portfolio().position("account-1", "binance:SPOT:BTC/USDT")

    assert position.quantity == Decimal("0.2")
    assert position.cost_basis == Decimal("11011.0")
    assert position.average_cost == Decimal("55055")
    assert position.cumulative_fees == Decimal("11")


def test_sell_realizes_pnl_and_reduces_cost_basis() -> None:
    portfolio = populated_portfolio()
    position = portfolio.apply(
        execution("sell-1", OrderSide.SELL, "70000", "0.05", "3.5", 3)
    )

    assert position.quantity == Decimal("0.15")
    assert position.cost_basis == Decimal("8258.25")
    assert position.average_cost == Decimal("55055")
    assert position.realized_pnl == Decimal("743.75")
    assert position.cumulative_fees == Decimal("14.5")


def test_valuation_uses_bid_and_keeps_realized_separate() -> None:
    portfolio = populated_portfolio()
    portfolio.apply(execution("sell-1", OrderSide.SELL, "70000", "0.05", "3.5", 3))

    valuation = portfolio.value(
        "account-1",
        "binance:SPOT:BTC/USDT",
        ticker("60000"),
    )

    assert valuation.price_basis == "BID"
    assert valuation.mark_price == Decimal("60000")
    assert valuation.mark_price != Decimal("1")
    assert valuation.market_value == Decimal("9000.00")
    assert valuation.unrealized_pnl == Decimal("741.75")
    assert valuation.realized_pnl == Decimal("743.75")
    assert valuation.total_pnl == Decimal("1485.50")


def test_oversell_is_atomic() -> None:
    portfolio = populated_portfolio()
    before = portfolio.positions()

    with pytest.raises(InsufficientPositionError):
        portfolio.apply(execution("sell-too-much", OrderSide.SELL, "70000", "0.3", "1", 3))

    assert portfolio.positions() == before


def test_duplicate_execution_is_rejected() -> None:
    portfolio = PortfolioEngine()
    sample = execution("same", OrderSide.BUY, "50000", "0.1", "5", 1)
    portfolio.apply(sample)

    with pytest.raises(ValueError, match="duplicate"):
        portfolio.apply(sample)


def test_portfolio_rebuilds_from_execution_history() -> None:
    history = (
        execution("buy-1", OrderSide.BUY, "50000", "0.1", "5", 1),
        execution("buy-2", OrderSide.BUY, "60000", "0.1", "6", 2),
        execution("sell-1", OrderSide.SELL, "70000", "0.05", "3.5", 3),
    )

    rebuilt = PortfolioEngine(history)
    incremental = PortfolioEngine()
    for item in history:
        incremental.apply(item)

    assert rebuilt.positions() == incremental.positions()


def test_invalid_ticker_cannot_value_position() -> None:
    portfolio = populated_portfolio()

    with pytest.raises(ValueError, match="not valid"):
        portfolio.value(
            "account-1",
            "binance:SPOT:BTC/USDT",
            ticker("60000", quality=DataQualityStatus.STALE),
        )


def test_out_of_order_execution_is_rejected() -> None:
    portfolio = PortfolioEngine()
    portfolio.apply(execution("newer", OrderSide.BUY, "50000", "0.1", "5", 2))

    with pytest.raises(ValueError, match="older"):
        portfolio.apply(execution("older", OrderSide.BUY, "50000", "0.1", "5", 1))
