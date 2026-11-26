"""Conservative TRADE_THROUGH allocation for resting GTC limit orders."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from uuid import NAMESPACE_URL, uuid5

from pydantic import Field

from crypto_lab.models import (
    DataQualityStatus,
    ExchangeId,
    MarketEventEnvelope,
    Trade,
    TradeSide,
)
from crypto_lab.trading.execution import ExecutionRecord, ExecutionSimulator
from crypto_lab.trading.fees import FeeSchedule
from crypto_lab.trading.models import FrozenModel
from crypto_lab.trading.orders import OrderSide, OrderStatus, OrderType, PaperOrder
from crypto_lab.trading.unit_of_work import InMemoryUnitOfWork


class TradeProcessingStatus(StrEnum):
    PROCESSED = "PROCESSED"
    DUPLICATE = "DUPLICATE"
    IGNORED = "IGNORED"
    OUT_OF_ORDER = "OUT_OF_ORDER"


class TradeAllocation(FrozenModel):
    order_id: str = Field(min_length=1)
    quantity: Decimal = Field(gt=0)
    execution: ExecutionRecord


class TradeProcessingResult(FrozenModel):
    event_id: str = Field(min_length=1)
    status: TradeProcessingStatus
    allocations: tuple[TradeAllocation, ...]
    remaining_trade_quantity: Decimal = Field(ge=0)
    reason: str | None = None


@dataclass
class _TradeProgress:
    remaining_quantity: Decimal
    allocated_order_ids: set[str] = field(default_factory=set)


class TradeThroughEngine:
    def __init__(
        self,
        *,
        simulation_environment_id: str,
        exchange_id: ExchangeId,
        instrument_id: str,
        simulator: ExecutionSimulator,
        fee_schedule: FeeSchedule,
        max_trade_age_ms: int,
        unit_of_work: InMemoryUnitOfWork | None = None,
    ) -> None:
        if not simulation_environment_id:
            raise ValueError("simulation environment ID is required")
        if not instrument_id.startswith(f"{exchange_id.value}:SPOT:"):
            raise ValueError("instrument does not belong to exchange SPOT market")
        if max_trade_age_ms < 0:
            raise ValueError("max_trade_age_ms cannot be negative")
        self.simulation_environment_id = simulation_environment_id
        self.exchange_id = exchange_id
        self.instrument_id = instrument_id
        self.simulator = simulator
        self.fee_schedule = fee_schedule
        self.max_trade_age_ms = max_trade_age_ms
        self.unit_of_work = unit_of_work
        self._processed_event_ids: set[str] = set()
        self._processed_trade_keys: set[str] = set()
        self._progress: dict[str, _TradeProgress] = {}
        self._last_ordering_key: tuple[int, int, str] | None = None

    def process_trade(
        self,
        event: MarketEventEnvelope[Trade],
        *,
        observed_ts_ms: int,
    ) -> TradeProcessingResult:
        if self.unit_of_work is None:
            return self._process_trade(event, observed_ts_ms=observed_ts_ms)
        return self.unit_of_work.run(
            lambda: self._process_trade(event, observed_ts_ms=observed_ts_ms)
        )

    def _process_trade(
        self,
        event: MarketEventEnvelope[Trade],
        *,
        observed_ts_ms: int,
    ) -> TradeProcessingResult:
        trade_key = self._trade_key(event)
        if event.event_id in self._processed_event_ids or trade_key in self._processed_trade_keys:
            return self._result(
                event,
                TradeProcessingStatus.DUPLICATE,
                remaining=Decimal(0),
                reason="trade event was already processed",
            )

        invalid_reason = self._invalid_reason(event, observed_ts_ms)
        if invalid_reason is not None:
            self._mark_processed(event, trade_key)
            return self._result(
                event,
                TradeProcessingStatus.IGNORED,
                remaining=event.payload.quantity,
                reason=invalid_reason,
            )

        assert event.exchange_ts_ms is not None
        ordering_key = (event.exchange_ts_ms, event.received_ts_ms, event.event_id)
        if self._last_ordering_key is not None and ordering_key <= self._last_ordering_key:
            self._mark_processed(event, trade_key)
            return self._result(
                event,
                TradeProcessingStatus.OUT_OF_ORDER,
                remaining=event.payload.quantity,
                reason="trade event is not newer than the last processed event",
            )
        if self._progress and trade_key not in self._progress:
            raise RuntimeError("a previous trade event has incomplete settlement")

        progress = self._progress.setdefault(
            trade_key,
            _TradeProgress(remaining_quantity=event.payload.quantity),
        )
        allocations: list[TradeAllocation] = []
        for order in self._eligible_orders(event):
            if progress.remaining_quantity == 0:
                break
            if order.order_id in progress.allocated_order_ids:
                continue
            if order.fee_schedule_id != self.fee_schedule.schedule_id:
                raise ValueError("fee schedule does not match resting order reservation")
            quantity = min(
                order.quantity - order.filled_quantity,
                progress.remaining_quantity,
            )
            execution_id = str(
                uuid5(
                    NAMESPACE_URL,
                    f"{self.simulation_environment_id}:{trade_key}:{order.order_id}",
                )
            )
            execution = self.simulator.execute_passive_fill(
                order.order_id,
                quantity=quantity,
                fee_rate=self.fee_schedule.maker_rate,
                market_event_id=event.event_id,
                execution_id=execution_id,
                executed_ts_ms=observed_ts_ms,
            )
            progress.remaining_quantity -= quantity
            progress.allocated_order_ids.add(order.order_id)
            allocations.append(
                TradeAllocation(
                    order_id=order.order_id,
                    quantity=quantity,
                    execution=execution,
                )
            )

        remaining = progress.remaining_quantity
        self._progress.pop(trade_key)
        self._mark_processed(event, trade_key)
        self._last_ordering_key = ordering_key
        return self._result(
            event,
            TradeProcessingStatus.PROCESSED,
            allocations=tuple(allocations),
            remaining=remaining,
        )

    def snapshot_state(
        self,
    ) -> tuple[
        set[str],
        set[str],
        dict[str, _TradeProgress],
        tuple[int, int, str] | None,
    ]:
        return (
            self._processed_event_ids.copy(),
            self._processed_trade_keys.copy(),
            {
                key: _TradeProgress(
                    remaining_quantity=value.remaining_quantity,
                    allocated_order_ids=value.allocated_order_ids.copy(),
                )
                for key, value in self._progress.items()
            },
            self._last_ordering_key,
        )

    def restore_state(
        self,
        state: tuple[
            set[str],
            set[str],
            dict[str, _TradeProgress],
            tuple[int, int, str] | None,
        ],
    ) -> None:
        processed_event_ids, processed_trade_keys, progress, last_ordering_key = state
        self._processed_event_ids = processed_event_ids.copy()
        self._processed_trade_keys = processed_trade_keys.copy()
        self._progress = {
            key: _TradeProgress(
                remaining_quantity=value.remaining_quantity,
                allocated_order_ids=value.allocated_order_ids.copy(),
            )
            for key, value in progress.items()
        }
        self._last_ordering_key = last_ordering_key

    def _eligible_orders(self, event: MarketEventEnvelope[Trade]) -> list[PaperOrder]:
        orders = [order for order in self.simulator.orders.orders() if self._eligible(order, event)]
        if event.payload.side is TradeSide.SELL:
            return sorted(
                orders,
                key=lambda order: (
                    -order.limit_price,  # type: ignore[operator]
                    order.market_entry_ts_ms,
                    order.order_sequence,
                ),
            )
        return sorted(
            orders,
            key=lambda order: (
                order.limit_price,
                order.market_entry_ts_ms,
                order.order_sequence,
            ),
        )

    @staticmethod
    def _eligible(order: PaperOrder, event: MarketEventEnvelope[Trade]) -> bool:
        if order.instrument_id != event.instrument_id:
            return False
        if order.order_type is not OrderType.LIMIT:
            return False
        if order.status not in {OrderStatus.OPEN, OrderStatus.PARTIALLY_FILLED}:
            return False
        if order.market_entry_ts_ms is None or event.exchange_ts_ms is None:
            return False
        if event.received_ts_ms <= order.market_entry_ts_ms:
            return False
        if event.exchange_ts_ms <= order.market_entry_ts_ms:
            return False
        assert order.limit_price is not None
        if event.payload.side is TradeSide.SELL:
            return order.side is OrderSide.BUY and event.payload.price < order.limit_price
        if event.payload.side is TradeSide.BUY:
            return order.side is OrderSide.SELL and event.payload.price > order.limit_price
        return False

    def _invalid_reason(
        self,
        event: MarketEventEnvelope[Trade],
        observed_ts_ms: int,
    ) -> str | None:
        if event.event_type != "TRADE":
            return "event type is not TRADE"
        if event.exchange_id is not self.exchange_id or event.instrument_id != self.instrument_id:
            return "trade belongs to a different market"
        if event.quality_status is not DataQualityStatus.VALID:
            return "trade quality is not valid"
        if event.exchange_ts_ms is None:
            return "trade exchange time is required for conservative ordering"
        if event.received_ts_ms > observed_ts_ms:
            return "trade was received after processing time"
        if observed_ts_ms - event.received_ts_ms > self.max_trade_age_ms:
            return "trade is stale"
        return None

    def _trade_key(self, event: MarketEventEnvelope[Trade]) -> str:
        if event.payload.trade_id is not None:
            return f"{event.exchange_id.value}:{event.instrument_id}:trade:{event.payload.trade_id}"
        return f"{event.exchange_id.value}:{event.instrument_id}:event:{event.event_id}"

    def _mark_processed(self, event: MarketEventEnvelope[Trade], trade_key: str) -> None:
        self._processed_event_ids.add(event.event_id)
        self._processed_trade_keys.add(trade_key)

    @staticmethod
    def _result(
        event: MarketEventEnvelope[Trade],
        status: TradeProcessingStatus,
        *,
        allocations: tuple[TradeAllocation, ...] = (),
        remaining: Decimal,
        reason: str | None = None,
    ) -> TradeProcessingResult:
        return TradeProcessingResult(
            event_id=event.event_id,
            status=status,
            allocations=allocations,
            remaining_trade_quantity=remaining,
            reason=reason,
        )
