"""Execution handler connecting due orders to current canonical market state."""

from __future__ import annotations

from dataclasses import dataclass

from crypto_lab.market_data import InvalidOrderBookStateError, OrderBookMarketState
from crypto_lab.models import ExchangeId
from crypto_lab.trading.constraints import MarketRules
from crypto_lab.trading.fees import FeeSchedule
from crypto_lab.trading.limit_execution import LimitOrderExecutionService
from crypto_lab.trading.market_execution import OrderBookExecutionService
from crypto_lab.trading.matching import MatchPlan
from crypto_lab.trading.models import FrozenModel
from crypto_lab.trading.order_service import OrderService
from crypto_lab.trading.orders import OrderType, PaperOrder


class DelayedExecutionOutcome(FrozenModel):
    order_id: str
    outcome: str
    reason: str | None = None
    execution_quote_event_id: str | None = None
    plan: MatchPlan | None = None


@dataclass(frozen=True)
class _ExecutionInstruction:
    exchange_id: ExchangeId
    max_book_age_ms: int
    fee_schedule: FeeSchedule
    market_rules: MarketRules
    consumption_id: str


class ScheduledOrderExecutor:
    def __init__(
        self,
        *,
        orders: OrderService,
        market_state: OrderBookMarketState,
        market_execution: OrderBookExecutionService,
        limit_execution: LimitOrderExecutionService,
    ) -> None:
        self.orders = orders
        self.market_state = market_state
        self.market_execution = market_execution
        self.limit_execution = limit_execution
        self._instructions: dict[str, _ExecutionInstruction] = {}
        self._outcomes: dict[str, DelayedExecutionOutcome] = {}

    def register(
        self,
        order_id: str,
        *,
        exchange_id: ExchangeId,
        max_book_age_ms: int,
        fee_schedule: FeeSchedule,
        market_rules: MarketRules,
        consumption_id: str,
    ) -> None:
        if order_id in self._instructions or order_id in self._outcomes:
            raise ValueError("execution instruction already exists")
        if max_book_age_ms < 0:
            raise ValueError("max book age cannot be negative")
        if not consumption_id:
            raise ValueError("consumption ID is required")
        order = self.orders.get(order_id)
        if order.fee_schedule_id not in {None, fee_schedule.schedule_id}:
            raise ValueError("fee schedule does not match order reservation")
        self._instructions[order_id] = _ExecutionInstruction(
            exchange_id=exchange_id,
            max_book_age_ms=max_book_age_ms,
            fee_schedule=fee_schedule,
            market_rules=market_rules,
            consumption_id=consumption_id,
        )

    def outcome(self, order_id: str) -> DelayedExecutionOutcome:
        return self._outcomes[order_id]

    def __call__(self, order: PaperOrder, execution_ts_ms: int) -> None:
        try:
            instruction = self._instructions[order.order_id]
        except KeyError as exc:
            raise KeyError("no execution instruction for scheduled order") from exc

        try:
            book = self.market_state.executable_book(
                instruction.exchange_id,
                order.instrument_id,
                decision_ts_ms=execution_ts_ms,
                max_age_ms=instruction.max_book_age_ms,
            )
        except InvalidOrderBookStateError as exc:
            self.orders.record_scheduled_execution(
                order.order_id,
                executed_ts_ms=execution_ts_ms,
                execution_quote_event_id=None,
            )
            self.orders.reject(order.order_id, reason="MARKET_DATA_UNAVAILABLE")
            self._finish(
                order.order_id,
                outcome="REJECTED",
                reason=f"MARKET_DATA_UNAVAILABLE: {exc}",
            )
            return

        self.orders.record_scheduled_execution(
            order.order_id,
            executed_ts_ms=execution_ts_ms,
            execution_quote_event_id=book.source_event_id,
        )
        try:
            if order.order_type is OrderType.MARKET:
                self.orders.enter_market(order.order_id, market_entry_ts_ms=execution_ts_ms)
                result = self.market_execution.execute_market_order(
                    order.order_id,
                    exchange_id=instruction.exchange_id,
                    instrument_id=order.instrument_id,
                    decision_ts_ms=execution_ts_ms,
                    max_book_age_ms=instruction.max_book_age_ms,
                    fee_rate=instruction.fee_schedule.taker_rate,
                    market_rules=instruction.market_rules,
                    consumption_id=instruction.consumption_id,
                    executed_ts_ms=execution_ts_ms,
                )
                if result.plan.filled_quantity == 0:
                    outcome = "CANCELED"
                elif result.plan.remaining_quantity:
                    outcome = "PARTIAL_CANCELED"
                else:
                    outcome = "FILLED"
            else:
                result = self.limit_execution.enter_limit_order(
                    order.order_id,
                    exchange_id=instruction.exchange_id,
                    instrument_id=order.instrument_id,
                    market_entry_ts_ms=execution_ts_ms,
                    max_book_age_ms=instruction.max_book_age_ms,
                    fee_schedule=instruction.fee_schedule,
                    market_rules=instruction.market_rules,
                    consumption_id=instruction.consumption_id,
                    executed_ts_ms=execution_ts_ms,
                )
                outcome = "RESTING" if result.resting else "FILLED"
        except Exception as exc:
            current = self.orders.get(order.order_id)
            if current.filled_quantity == 0:
                self.orders.reject(order.order_id, reason="EXECUTION_FAILED")
            self._finish(
                order.order_id,
                outcome="FAILED",
                reason=f"{type(exc).__name__}: {exc}",
                execution_quote_event_id=book.source_event_id,
            )
            return

        self._finish(
            order.order_id,
            outcome=outcome,
            execution_quote_event_id=book.source_event_id,
            plan=result.plan,
        )

    def _finish(
        self,
        order_id: str,
        *,
        outcome: str,
        reason: str | None = None,
        execution_quote_event_id: str | None = None,
        plan: MatchPlan | None = None,
    ) -> None:
        self._instructions.pop(order_id, None)
        self._outcomes[order_id] = DelayedExecutionOutcome(
            order_id=order_id,
            outcome=outcome,
            reason=reason,
            execution_quote_event_id=execution_quote_event_id,
            plan=plan,
        )
