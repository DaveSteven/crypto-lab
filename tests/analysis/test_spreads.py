from decimal import Decimal

import pytest

from crypto_lab.analysis.spreads import (
    CostInputs,
    PriceLevel,
    analyze_spread,
    estimate_depth_spread,
)
from crypto_lab.models import (
    DataQualityStatus,
    DataSourceType,
    ExchangeId,
    MarketEventEnvelope,
    Ticker,
    TransportType,
)


def ticker_event(
    event_id: str,
    exchange: ExchangeId,
    received_ts_ms: int,
    *,
    bid: str,
    bid_size: str | None,
    ask: str,
    ask_size: str | None,
) -> MarketEventEnvelope[Ticker]:
    return MarketEventEnvelope[Ticker](
        event_id=event_id,
        event_type="TICKER",
        exchange_id=exchange,
        instrument_id=f"{exchange.value}:SPOT:BTC/USDT",
        source_type=DataSourceType.MOCK,
        transport=TransportType.FILE,
        received_ts_ms=received_ts_ms,
        quality_status=DataQualityStatus.VALID,
        payload=Ticker(bid=bid, bid_size=bid_size, ask=ask, ask_size=ask_size),
    )


def events() -> tuple[MarketEventEnvelope[Ticker], MarketEventEnvelope[Ticker]]:
    buy = ticker_event(
        "buy",
        ExchangeId.BINANCE,
        1_000,
        bid="99",
        bid_size="3",
        ask="100",
        ask_size="2",
    )
    sell = ticker_event(
        "sell",
        ExchangeId.OKX,
        1_100,
        bid="102",
        bid_size="1.5",
        ask="103",
        ask_size="4",
    )
    return buy, sell


def test_spread_uses_buy_ask_and_sell_bid() -> None:
    buy, sell = events()
    result = analyze_spread(buy, sell, 1_200)

    assert result.gross_spread == Decimal("2")
    assert result.gross_spread_rate == Decimal("0.02")
    assert result.estimated_executable_quantity == Decimal("1.5")
    assert result.estimated_net_profit is None


def test_complete_assumed_cost_model_calculates_net_profit() -> None:
    buy, sell = events()
    costs = CostInputs(
        model_id="ASSUMED:TEST",
        buy_fee_rate=Decimal("0.001"),
        sell_fee_rate=Decimal("0.001"),
        execution_cost_rate=Decimal("0.0005"),
        rebalance_cost_rate=Decimal("0.0005"),
        is_assumption=True,
    )
    result = analyze_spread(buy, sell, 1_200, target_quantity=Decimal("1"), costs=costs)

    assert result.estimated_buy_notional == Decimal("100")
    assert result.estimated_sell_notional == Decimal("102")
    assert result.estimated_buy_fee == Decimal("0.100")
    assert result.estimated_sell_fee == Decimal("0.102")
    assert result.estimated_net_profit == Decimal("1.6980")


def test_stale_or_time_misaligned_quotes_are_not_valid() -> None:
    buy, sell = events()
    result = analyze_spread(buy, sell, 5_000)

    assert result.quality_status is DataQualityStatus.STALE


def test_negative_spread_is_retained() -> None:
    buy, sell = events()
    sell.payload.bid = Decimal("98")
    result = analyze_spread(buy, sell, 1_200)

    assert result.gross_spread == Decimal("-2")


def test_mismatched_quote_currency_is_rejected() -> None:
    buy, sell = events()
    sell.instrument_id = "okx:SPOT:BTC/JPY"

    with pytest.raises(ValueError, match="identical canonical symbols"):
        analyze_spread(buy, sell, 1_200)


def test_depth_walk_uses_same_executable_quantity_on_both_sides() -> None:
    result = estimate_depth_spread(
        asks=[PriceLevel(Decimal("100"), Decimal("1")), PriceLevel(Decimal("101"), Decimal("2"))],
        bids=[PriceLevel(Decimal("104"), Decimal("0.5")), PriceLevel(Decimal("103"), Decimal("1"))],
        target_quantity=Decimal("2"),
    )

    assert result.quantity == Decimal("1.5")
    assert result.buy_notional == Decimal("150.5")
    assert result.sell_notional == Decimal("155.0")


def test_depth_walk_rejects_unsorted_books() -> None:
    with pytest.raises(ValueError, match="asks must"):
        estimate_depth_spread(
            asks=[
                PriceLevel(Decimal("101"), Decimal("1")),
                PriceLevel(Decimal("100"), Decimal("1")),
            ],
            bids=[PriceLevel(Decimal("99"), Decimal("1"))],
            target_quantity=Decimal("1"),
        )


def test_cost_model_identifies_assumptions() -> None:
    with pytest.raises(ValueError, match="ASSUMED"):
        CostInputs(
            model_id="ambiguous",
            buy_fee_rate=Decimal("0"),
            sell_fee_rate=Decimal("0"),
            execution_cost_rate=Decimal("0"),
            rebalance_cost_rate=Decimal("0"),
            is_assumption=True,
        )
