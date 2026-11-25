"""Executable-quote spread and order-book depth calculations."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from uuid import uuid4

from crypto_lab.models import DataQualityStatus, MarketEventEnvelope, Ticker
from crypto_lab.models.spread import SpreadObservation


@dataclass(frozen=True)
class CostInputs:
    model_id: str
    buy_fee_rate: Decimal
    sell_fee_rate: Decimal
    execution_cost_rate: Decimal
    rebalance_cost_rate: Decimal
    is_assumption: bool

    def __post_init__(self) -> None:
        if not self.model_id:
            raise ValueError("cost model ID is required")
        expected_prefix = "ASSUMED:" if self.is_assumption else "VERIFIED:"
        if not self.model_id.startswith(expected_prefix):
            raise ValueError(f"cost model ID must start with {expected_prefix}")
        rates = (
            self.buy_fee_rate,
            self.sell_fee_rate,
            self.execution_cost_rate,
            self.rebalance_cost_rate,
        )
        if any(rate < 0 for rate in rates):
            raise ValueError("cost rates cannot be negative")


@dataclass(frozen=True)
class PriceLevel:
    price: Decimal
    quantity: Decimal

    def __post_init__(self) -> None:
        if self.price <= 0 or self.quantity <= 0:
            raise ValueError("price levels require positive price and quantity")


@dataclass(frozen=True)
class DepthExecution:
    quantity: Decimal
    buy_notional: Decimal
    sell_notional: Decimal


def _symbol(event: MarketEventEnvelope[Ticker]) -> str:
    return event.instrument_id.split(":", maxsplit=2)[2]


def _quality(
    buy_event: MarketEventEnvelope[Ticker],
    sell_event: MarketEventEnvelope[Ticker],
    buy_age_ms: int,
    sell_age_ms: int,
    quote_time_diff_ms: int,
    max_quote_age_ms: int,
    max_quote_time_diff_ms: int,
) -> DataQualityStatus:
    if (
        buy_event.quality_status is not DataQualityStatus.VALID
        or sell_event.quality_status is not DataQualityStatus.VALID
    ):
        return DataQualityStatus.INVALID
    if (
        buy_age_ms > max_quote_age_ms
        or sell_age_ms > max_quote_age_ms
        or quote_time_diff_ms > max_quote_time_diff_ms
    ):
        return DataQualityStatus.STALE
    return DataQualityStatus.VALID


def _quantity(
    buy_size: Decimal | None,
    sell_size: Decimal | None,
    target_quantity: Decimal | None,
) -> Decimal | None:
    if buy_size is None or sell_size is None:
        return None
    available = min(buy_size, sell_size)
    return available if target_quantity is None else min(available, target_quantity)


def analyze_spread(
    buy_event: MarketEventEnvelope[Ticker],
    sell_event: MarketEventEnvelope[Ticker],
    observed_ts_ms: int,
    *,
    target_quantity: Decimal | None = None,
    costs: CostInputs | None = None,
    max_quote_age_ms: int = 2_000,
    max_quote_time_diff_ms: int = 1_000,
) -> SpreadObservation:
    if buy_event.exchange_id == sell_event.exchange_id:
        raise ValueError("spread requires two different exchanges")
    if _symbol(buy_event) != _symbol(sell_event):
        raise ValueError("spread requires identical canonical symbols")
    if target_quantity is not None and target_quantity <= 0:
        raise ValueError("target quantity must be positive")
    if buy_event.payload.ask is None or sell_event.payload.bid is None:
        raise ValueError("buy ask and sell bid are required")

    buy_age_ms = max(0, observed_ts_ms - buy_event.received_ts_ms)
    sell_age_ms = max(0, observed_ts_ms - sell_event.received_ts_ms)
    quote_time_diff_ms = abs(buy_event.received_ts_ms - sell_event.received_ts_ms)
    quality = _quality(
        buy_event,
        sell_event,
        buy_age_ms,
        sell_age_ms,
        quote_time_diff_ms,
        max_quote_age_ms,
        max_quote_time_diff_ms,
    )
    buy_ask = buy_event.payload.ask
    sell_bid = sell_event.payload.bid
    gross_spread = sell_bid - buy_ask
    executable_quantity = _quantity(
        buy_event.payload.ask_size,
        sell_event.payload.bid_size,
        target_quantity,
    )
    buy_notional = buy_ask * executable_quantity if executable_quantity is not None else None
    sell_notional = sell_bid * executable_quantity if executable_quantity is not None else None

    buy_fee = sell_fee = execution_cost = rebalance_cost = None
    net_profit = net_return = None
    if costs is not None and buy_notional is not None and sell_notional is not None:
        buy_fee = buy_notional * costs.buy_fee_rate
        sell_fee = sell_notional * costs.sell_fee_rate
        execution_cost = buy_notional * costs.execution_cost_rate
        rebalance_cost = buy_notional * costs.rebalance_cost_rate
        net_profit = (
            sell_notional
            - buy_notional
            - buy_fee
            - sell_fee
            - execution_cost
            - rebalance_cost
        )
        net_return = net_profit / buy_notional if buy_notional else None

    return SpreadObservation(
        observation_id=str(uuid4()),
        canonical_symbol=_symbol(buy_event),
        buy_exchange_id=buy_event.exchange_id,
        sell_exchange_id=sell_event.exchange_id,
        buy_event_id=buy_event.event_id,
        sell_event_id=sell_event.event_id,
        buy_ask=buy_ask,
        sell_bid=sell_bid,
        buy_available_quantity=buy_event.payload.ask_size,
        sell_available_quantity=sell_event.payload.bid_size,
        observed_ts_ms=observed_ts_ms,
        quote_time_diff_ms=quote_time_diff_ms,
        buy_quote_age_ms=buy_age_ms,
        sell_quote_age_ms=sell_age_ms,
        timestamp_basis="received_ts_ms",
        gross_spread=gross_spread,
        gross_spread_rate=gross_spread / buy_ask,
        target_quantity=target_quantity,
        estimated_executable_quantity=executable_quantity,
        estimated_buy_notional=buy_notional,
        estimated_sell_notional=sell_notional,
        estimated_buy_fee=buy_fee,
        estimated_sell_fee=sell_fee,
        estimated_execution_cost=execution_cost,
        estimated_rebalance_cost=rebalance_cost,
        estimated_net_profit=net_profit,
        estimated_net_return_rate=net_return,
        cost_model_id=costs.model_id if costs is not None else None,
        quality_status=quality,
    )


def _walk(levels: list[PriceLevel], quantity: Decimal) -> tuple[Decimal, Decimal]:
    remaining = quantity
    filled = Decimal(0)
    notional = Decimal(0)
    for level in levels:
        take = min(level.quantity, remaining)
        filled += take
        notional += take * level.price
        remaining -= take
        if remaining == 0:
            break
    return filled, notional


def estimate_depth_spread(
    asks: list[PriceLevel],
    bids: list[PriceLevel],
    target_quantity: Decimal,
) -> DepthExecution:
    if target_quantity <= 0:
        raise ValueError("target quantity must be positive")
    if any(left.price >= right.price for left, right in zip(asks, asks[1:], strict=False)):
        raise ValueError("asks must have unique prices in ascending order")
    if any(left.price <= right.price for left, right in zip(bids, bids[1:], strict=False)):
        raise ValueError("bids must have unique prices in descending order")
    buy_filled, _ = _walk(asks, target_quantity)
    sell_filled, _ = _walk(bids, target_quantity)
    executable = min(buy_filled, sell_filled)
    _, buy_notional = _walk(asks, executable)
    _, sell_notional = _walk(bids, executable)
    return DepthExecution(executable, buy_notional, sell_notional)
