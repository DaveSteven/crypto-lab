"""Deterministic in-memory scheduler for delayed paper-order execution."""

from __future__ import annotations

from collections.abc import Callable

from pydantic import Field

from crypto_lab.trading.clock import Clock, ExecutionLatency
from crypto_lab.trading.models import FrozenModel
from crypto_lab.trading.order_service import OrderService
from crypto_lab.trading.orders import OrderStatus, PaperOrder


class ScheduledExecution(FrozenModel):
    order_id: str = Field(min_length=1)
    scheduled_execution_ts_ms: int = Field(ge=0)
    order_sequence: int = Field(gt=0)


class SchedulerRunResult(FrozenModel):
    executed_order_ids: tuple[str, ...]
    skipped_order_ids: tuple[str, ...]


ExecutionHandler = Callable[[PaperOrder, int], None]


class ExecutionScheduler:
    def __init__(self, orders: OrderService, clock: Clock) -> None:
        self.orders = orders
        self.clock = clock
        self._scheduled: dict[str, ScheduledExecution] = {}
        self._completed: set[str] = set()

    def schedule(
        self,
        order_id: str,
        *,
        latency: ExecutionLatency,
        submission_quote_event_id: str | None = None,
    ) -> PaperOrder:
        if order_id in self._scheduled or order_id in self._completed:
            raise ValueError("order has already been scheduled")
        order = self.orders.schedule_execution(
            order_id,
            configured_latency_ms=latency.milliseconds,
            submission_quote_event_id=submission_quote_event_id,
        )
        assert order.scheduled_execution_ts_ms is not None
        self._scheduled[order_id] = ScheduledExecution(
            order_id=order_id,
            scheduled_execution_ts_ms=order.scheduled_execution_ts_ms,
            order_sequence=order.order_sequence,
        )
        return order

    def due(self) -> tuple[ScheduledExecution, ...]:
        now_ms = self.clock.now_utc_ms()
        return tuple(
            sorted(
                (
                    item
                    for item in self._scheduled.values()
                    if item.scheduled_execution_ts_ms <= now_ms
                ),
                key=lambda item: (item.scheduled_execution_ts_ms, item.order_sequence),
            )
        )

    def cancel(self, order_id: str) -> PaperOrder:
        if order_id not in self._scheduled:
            raise ValueError("order is not scheduled")
        canceled = self.orders.cancel(order_id)
        self._scheduled.pop(order_id)
        self._completed.add(order_id)
        return canceled

    def run_due(self, handler: ExecutionHandler) -> SchedulerRunResult:
        executed: list[str] = []
        skipped: list[str] = []
        for item in self.due():
            order = self.orders.get(item.order_id)
            if order.status is not OrderStatus.PENDING_EXECUTION:
                self._scheduled.pop(item.order_id, None)
                self._completed.add(item.order_id)
                skipped.append(item.order_id)
                continue
            handler(order, self.clock.now_utc_ms())
            self._scheduled.pop(item.order_id, None)
            self._completed.add(item.order_id)
            executed.append(item.order_id)
        return SchedulerRunResult(
            executed_order_ids=tuple(executed),
            skipped_order_ids=tuple(skipped),
        )
