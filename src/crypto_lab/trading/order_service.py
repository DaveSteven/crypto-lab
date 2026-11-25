"""Balance-aware placement and cancellation of paper spot orders."""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from uuid import uuid4

from crypto_lab.trading.clock import Clock, SystemClock
from crypto_lab.trading.fees import FeeSchedule
from crypto_lab.trading.ledger import AccountLedger
from crypto_lab.trading.orders import OrderSide, OrderStatus, OrderType, PaperOrder


class InvalidOrderTransitionError(ValueError):
    pass


def split_instrument(instrument_id: str) -> tuple[str, str, str]:
    try:
        exchange_and_market, symbol = instrument_id.rsplit(":", maxsplit=1)
        exchange_id, market_type = exchange_and_market.split(":", maxsplit=1)
        base_asset, quote_asset = symbol.split("/", maxsplit=1)
    except ValueError as exc:
        raise ValueError("invalid instrument_id") from exc
    if market_type != "SPOT" or not all((exchange_id, base_asset, quote_asset)):
        raise ValueError("only canonical SPOT instruments are supported")
    return exchange_id, base_asset, quote_asset


class OrderService:
    def __init__(
        self,
        ledger: AccountLedger,
        *,
        clock: Clock | Callable[[], int] | None = None,
    ) -> None:
        self.ledger = ledger
        self._clock = SystemClock() if clock is None else clock
        self._orders: dict[str, PaperOrder] = {}
        self._next_order_sequence = 1

    def get(self, order_id: str) -> PaperOrder:
        try:
            return self._orders[order_id]
        except KeyError as exc:
            raise KeyError(f"unknown order: {order_id}") from exc

    def orders(self) -> tuple[PaperOrder, ...]:
        return tuple(self._orders.values())

    def place(
        self,
        *,
        instrument_id: str,
        side: OrderSide,
        order_type: OrderType,
        quantity: Decimal,
        limit_price: Decimal | None = None,
        market_reference_price: Decimal | None = None,
        estimated_buy_fee_rate: Decimal = Decimal(0),
        fee_schedule: FeeSchedule | None = None,
    ) -> PaperOrder:
        self._require_decimal_positive(quantity, "quantity")
        self._require_decimal_nonnegative(estimated_buy_fee_rate, "estimated_buy_fee_rate")
        if fee_schedule is not None and estimated_buy_fee_rate != 0:
            raise ValueError("use either fee_schedule or estimated_buy_fee_rate")
        exchange_id, base_asset, quote_asset = split_instrument(instrument_id)
        if exchange_id != self.ledger.account.exchange_id.value:
            raise ValueError("instrument exchange does not match account exchange")

        if order_type is OrderType.LIMIT:
            if limit_price is None:
                raise ValueError("limit_price is required for limit orders")
            self._require_decimal_positive(limit_price, "limit_price")
            if market_reference_price is not None:
                raise ValueError("limit orders do not accept market_reference_price")
            reference_price = limit_price
        else:
            if limit_price is not None:
                raise ValueError("market orders do not accept limit_price")
            if market_reference_price is None:
                raise ValueError("market orders require an executable reference price")
            self._require_decimal_positive(market_reference_price, "market_reference_price")
            reference_price = market_reference_price

        if side is OrderSide.BUY:
            reserved_asset = quote_asset
            reserved_fee_rate = (
                fee_schedule.maximum_rate if fee_schedule is not None else estimated_buy_fee_rate
            )
            reserved_amount = quantity * reference_price * (Decimal(1) + reserved_fee_rate)
        else:
            reserved_asset = base_asset
            reserved_fee_rate = Decimal(0)
            reserved_amount = quantity

        order_id = str(uuid4())
        now_ms = self._now_utc_ms()
        order_sequence = self._next_order_sequence
        order = PaperOrder(
            order_id=order_id,
            account_id=self.ledger.account.account_id,
            instrument_id=instrument_id,
            side=side,
            order_type=order_type,
            quantity=quantity,
            limit_price=limit_price,
            reference_price=reference_price,
            reserved_asset=reserved_asset,
            reserved_amount=reserved_amount,
            fee_schedule_id=(fee_schedule.schedule_id if fee_schedule is not None else None),
            reserved_fee_rate=reserved_fee_rate,
            status=OrderStatus.OPEN,
            submitted_ts_ms=now_ms,
            order_sequence=order_sequence,
            created_ts_ms=now_ms,
            updated_ts_ms=now_ms,
        )
        self.ledger.reserve(reserved_asset, reserved_amount, order_id)
        self._orders[order_id] = order
        self._next_order_sequence += 1
        return order

    def enter_market(self, order_id: str, *, market_entry_ts_ms: int | None = None) -> PaperOrder:
        order = self.get(order_id)
        if order.status not in {
            OrderStatus.PENDING_EXECUTION,
            OrderStatus.OPEN,
            OrderStatus.PARTIALLY_FILLED,
        }:
            raise InvalidOrderTransitionError(f"cannot enter market in {order.status} state")
        if order.market_entry_ts_ms is not None:
            raise InvalidOrderTransitionError("order has already entered the market")
        entry_ts_ms = self._now_utc_ms() if market_entry_ts_ms is None else market_entry_ts_ms
        if entry_ts_ms < order.submitted_ts_ms:
            raise ValueError("market entry time cannot precede submission time")
        entered = order.model_copy(
            update={
                "status": OrderStatus.OPEN,
                "market_entry_ts_ms": entry_ts_ms,
                "updated_ts_ms": entry_ts_ms,
            }
        )
        self._orders[order_id] = entered
        return entered

    def cancel(self, order_id: str, *, reason: str | None = None) -> PaperOrder:
        order = self.get(order_id)
        if order.status not in {
            OrderStatus.PENDING_EXECUTION,
            OrderStatus.OPEN,
            OrderStatus.PARTIALLY_FILLED,
        }:
            raise InvalidOrderTransitionError(f"cannot cancel order in {order.status} state")
        remaining_reservation = self.remaining_reservation(order)
        if remaining_reservation > 0:
            self.ledger.release(order.reserved_asset, remaining_reservation, order.order_id)
        canceled = order.model_copy(
            update={
                "status": OrderStatus.CANCELED,
                "termination_reason": reason,
                "updated_ts_ms": self._now_utc_ms(),
            }
        )
        self._orders[order_id] = canceled
        return canceled

    def schedule_execution(
        self,
        order_id: str,
        *,
        configured_latency_ms: int,
        submission_quote_event_id: str | None,
    ) -> PaperOrder:
        order = self.get(order_id)
        if order.status is not OrderStatus.OPEN or order.market_entry_ts_ms is not None:
            raise InvalidOrderTransitionError("only a new order can be scheduled")
        if configured_latency_ms < 0:
            raise ValueError("configured latency cannot be negative")
        scheduled_ts_ms = order.submitted_ts_ms + configured_latency_ms
        pending = order.model_copy(
            update={
                "status": OrderStatus.PENDING_EXECUTION,
                "scheduled_execution_ts_ms": scheduled_ts_ms,
                "configured_latency_ms": configured_latency_ms,
                "submission_quote_event_id": submission_quote_event_id,
            }
        )
        self._orders[order_id] = pending
        return pending

    def record_scheduled_execution(
        self,
        order_id: str,
        *,
        executed_ts_ms: int,
        execution_quote_event_id: str | None,
    ) -> PaperOrder:
        order = self.get(order_id)
        if order.status is not OrderStatus.PENDING_EXECUTION:
            raise InvalidOrderTransitionError("order is not pending execution")
        if order.scheduled_execution_ts_ms is None:
            raise InvalidOrderTransitionError("pending order has no execution schedule")
        if executed_ts_ms < order.scheduled_execution_ts_ms:
            raise InvalidOrderTransitionError("order is not due")
        updated = order.model_copy(
            update={
                "executed_ts_ms": executed_ts_ms,
                "actual_simulated_delay_ms": executed_ts_ms - order.submitted_ts_ms,
                "scheduler_lag_ms": executed_ts_ms - order.scheduled_execution_ts_ms,
                "execution_quote_event_id": execution_quote_event_id,
                "updated_ts_ms": executed_ts_ms,
            }
        )
        self._orders[order_id] = updated
        return updated

    def reject(self, order_id: str, *, reason: str) -> PaperOrder:
        if not reason:
            raise ValueError("rejection reason is required")
        order = self.get(order_id)
        if order.status not in {OrderStatus.PENDING_EXECUTION, OrderStatus.OPEN}:
            raise InvalidOrderTransitionError(f"cannot reject order in {order.status} state")
        remaining_reservation = self.remaining_reservation(order)
        if remaining_reservation > 0:
            self.ledger.release(order.reserved_asset, remaining_reservation, order.order_id)
        rejected = order.model_copy(
            update={
                "status": OrderStatus.REJECTED,
                "termination_reason": reason,
                "updated_ts_ms": self._now_utc_ms(),
            }
        )
        self._orders[order_id] = rejected
        return rejected

    def replace_after_execution(self, order: PaperOrder) -> None:
        current = self.get(order.order_id)
        if current.status not in {OrderStatus.OPEN, OrderStatus.PARTIALLY_FILLED}:
            raise InvalidOrderTransitionError("order is not executable")
        if order.filled_quantity <= current.filled_quantity:
            raise InvalidOrderTransitionError("execution must increase filled quantity")
        self._orders[order.order_id] = order

    @staticmethod
    def remaining_reservation(order: PaperOrder) -> Decimal:
        if order.side is OrderSide.BUY:
            consumed = order.cumulative_quote_amount + order.cumulative_fee
            remaining = order.reserved_amount - consumed
        else:
            remaining = order.quantity - order.filled_quantity
        if remaining < 0:
            raise ValueError("order consumed more than its reservation")
        return remaining

    @staticmethod
    def _require_decimal_positive(value: Decimal, name: str) -> None:
        if not isinstance(value, Decimal):
            raise TypeError(f"{name} must be Decimal")
        if value <= 0:
            raise ValueError(f"{name} must be positive")

    @staticmethod
    def _require_decimal_nonnegative(value: Decimal, name: str) -> None:
        if not isinstance(value, Decimal):
            raise TypeError(f"{name} must be Decimal")
        if value < 0:
            raise ValueError(f"{name} cannot be negative")

    def _now_utc_ms(self) -> int:
        if isinstance(self._clock, Clock):
            return self._clock.now_utc_ms()
        return self._clock()
