"""Serial dispatch of canonical market events into simulated trading engines.

The dispatcher receives every validated Canonical event from the shared feed
and applies it to each registered simulation environment in a dedicated
database transaction. Environment trading state (orders, ledger, positions,
simulated liquidity, scheduler) stays fully isolated per environment; only
the canonical market data itself is shared.

Design constraints carried over from Tasks 1.5-1.9:

- Simulated liquidity is per environment; a consuming order never affects
  another environment's book.
- Trades drive TRADE_THROUGH passive matching; order books back market
  execution and limit-order entry through the existing serial services.
- Every processed trade is registered in ``processed_market_events`` so a
  dispatcher restart cannot double-process the same exchange trade, and the
  conservative ordering key is restored from that registry.
- Due scheduled executions run through the existing ExecutionScheduler and
  ScheduledOrderExecutor, preserving Task 1.7/1.8 semantics, including the
  MARKET_DATA_UNAVAILABLE rejection when no valid book is available.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Any

from crypto_lab.market_data import InvalidOrderBookStateError, OrderBookView
from crypto_lab.models import DataQualityStatus, ExchangeId, MarketEventEnvelope, Trade
from crypto_lab.trading import (
    ExecutionSimulator,
    FeeSchedule,
    LimitOrderExecutionService,
    ManualClock,
    MarketRules,
    OrderBookExecutionService,
    PortfolioEngine,
    SimulatedLiquidityView,
    TradeThroughEngine,
)
from crypto_lab.trading.delayed_execution import ScheduledOrderExecutor

logger = logging.getLogger(__name__)

# Distinguishes orders whose scheduled execution time passed while the service
# was down from a normal-operation MARKET_DATA_UNAVAILABLE rejection.
EXECUTION_EXPIRED_ON_RESTART = "EXECUTION_EXPIRED_ON_RESTART"


@dataclass(frozen=True)
class EnvironmentRecovery:
    """Outcome of restoring one environment at startup."""

    environment_id: str
    status: str  # RECOVERED | FAILED
    expired_order_ids: tuple[str, ...] = ()
    error: str | None = None


class LatestBookState:
    """Executable-book gate over the latest valid canonical order-book view.

    Duck-types the part of ``OrderBookMarketState`` used by the execution
    services so the shared feed view can back per-environment matching
    without rebuilding envelope objects.
    """

    def __init__(self) -> None:
        self._views: dict[tuple[str, str], OrderBookView] = {}

    def update(self, view: OrderBookView) -> None:
        self._views[(view.exchange_id.value, view.instrument_id)] = view

    def snapshot(self) -> LatestBookState:
        """Immutable-in-practice copy used to decide one scheduler run consistently."""
        copy = LatestBookState()
        copy._views = dict(self._views)
        return copy

    def latest(self, exchange_id: str, instrument_id: str) -> OrderBookView | None:
        return self._views.get((exchange_id, instrument_id))

    def executable_book(
        self,
        exchange_id: ExchangeId,
        instrument_id: str,
        *,
        decision_ts_ms: int,
        max_age_ms: int,
    ) -> OrderBookView:
        view = self._views.get((exchange_id.value, instrument_id))
        if view is None:
            raise InvalidOrderBookStateError("order book does not exist")
        if view.received_ts_ms > decision_ts_ms:
            raise InvalidOrderBookStateError(
                "order book was received after decision time"
            )
        if decision_ts_ms - view.received_ts_ms > max_age_ms:
            raise InvalidOrderBookStateError("order book is stale")
        if view.quality_status is not DataQualityStatus.VALID or not view.synchronized:
            raise InvalidOrderBookStateError("order book is not executable")
        if not view.source_connected:
            raise InvalidOrderBookStateError("order-book source is disconnected")
        if not view.bids or not view.asks:
            raise InvalidOrderBookStateError("order book requires both sides")
        return view


class EnvironmentMarketDispatcher:
    """Apply shared canonical events to isolated per-environment engines."""

    def __init__(
        self,
        *,
        transaction: Callable[[str], AbstractContextManager[Any]],
        environment_exists: Callable[[str], bool],
        fee_schedule: FeeSchedule,
        market_rules: MarketRules | Mapping[str, MarketRules],
        instruments: Iterable[str],
        now_ms: Callable[[], int],
        max_book_age_ms: int = 5_000,
        max_trade_age_ms: int = 2_000,
        due_environments: Callable[[int], set[str]] | None = None,
    ) -> None:

        self.transaction = transaction
        self.environment_exists = environment_exists
        self.fee_schedule = fee_schedule
        self.market_rules = market_rules
        self.instruments = tuple(instruments)
        self.now_ms = now_ms
        self.max_book_age_ms = max_book_age_ms
        self.max_trade_age_ms = max_trade_age_ms
        # Optional lock-free pre-check so idle ticks do not open a locking transaction per
        # environment (cost grows linearly with the number of environments otherwise).
        self.due_environments = due_environments
        if not self.instruments:
            raise ValueError("dispatcher requires at least one instrument")
        if isinstance(market_rules, Mapping):
            missing = [i for i in self.instruments if i not in market_rules]
            if missing:
                raise ValueError(f"market rules are missing for instruments: {missing}")
        self.books = LatestBookState()
        self.stats = {
            "trades_processed": 0,
            "trades_ignored": 0,
            "books_synchronized": 0,
            "executions_processed": 0,
            "dispatch_errors": 0,
            "recovery_failures": 0,
        }
        self._environments: dict[str, dict[str, Any]] = {}
        # Environments that failed startup recovery: never matched, never silent.
        self._recovery_failed: dict[str, str] = {}
        # (environment, instrument) pairs whose persisted liquidity was already refreshed
        # from a live book in THIS process.
        self._liquidity_refreshed: set[tuple[str, str]] = set()

    def environments(self) -> tuple[str, ...]:
        return tuple(self._environments)

    def recovery_status(self) -> dict[str, Any]:
        """Explicit per-environment recovery state (docs: restart recovery rules)."""
        return {
            "recovered": sorted(self._environments),
            "failed": dict(self._recovery_failed),
        }

    def restore_environments(
        self, environment_ids: Iterable[str], recovery_ts_ms: int
    ) -> list[EnvironmentRecovery]:
        """Startup recovery against one unified baseline time.

        For each environment, atomically: reject every PENDING_EXECUTION order whose
        scheduled time is at or before ``recovery_ts_ms`` (reason
        ``EXECUTION_EXPIRED_ON_RESTART``, reservation released, no fill, no liquidity
        consumed), leave not-yet-due schedules and resting GTC orders untouched, then
        register the environment for normal processing. An environment that fails is
        isolated, recorded in ``recovery_status`` and never matched; it is retried by
        calling this method again (idempotent).
        """
        results: list[EnvironmentRecovery] = []
        for environment_id in environment_ids:
            try:
                expired = self._expire_overdue_orders(environment_id, recovery_ts_ms)
                if environment_id not in self._environments and not self.register_environment(
                    environment_id
                ):
                    raise RuntimeError("environment could not be registered")
                self._recovery_failed.pop(environment_id, None)
                results.append(
                    EnvironmentRecovery(environment_id, "RECOVERED", tuple(expired))
                )
            except Exception as exc:
                self.stats["recovery_failures"] += 1
                self._environments.pop(environment_id, None)
                self._recovery_failed[environment_id] = f"{type(exc).__name__}: {exc}"
                logger.exception("startup recovery failed for environment %s", environment_id)
                results.append(
                    EnvironmentRecovery(
                        environment_id, "FAILED", error=self._recovery_failed[environment_id]
                    )
                )
        return results

    def _expire_overdue_orders(self, environment_id: str, recovery_ts_ms: int) -> list[str]:
        expired: list[str] = []
        with self.transaction(environment_id) as store:
            groups = store.due_schedule_groups(environment_id, recovery_ts_ms)
            if not groups:
                return expired
            environment = store.load_environment(environment_id)
            for account_id, _order_ids in groups:
                ids = store.restore_id_generator(environment_id, environment["id_namespace"])
                clock = ManualClock(recovery_ts_ms)
                ledger = store.restore_account_ledger(
                    account_id=account_id, id_generator=ids, clock=clock
                )
                orders = store.restore_orders(ledger, environment_id)
                scheduler = store.restore_scheduler(
                    environment_id=environment_id, orders=orders, clock=clock
                )
                account_expired: list[str] = []

                def reject_overdue(order: Any, _execution_ts_ms: int, *, _orders: Any = orders,
                                   _sink: list[str] = account_expired) -> None:
                    _orders.reject(order.order_id, reason=EXECUTION_EXPIRED_ON_RESTART)
                    _sink.append(order.order_id)

                scheduler.run_due(reject_overdue)
                if not account_expired:
                    continue
                executions = store.restore_executions(environment_id)
                projection = PortfolioEngine(executions)
                store.persist_trading_state(
                    environment_id=environment_id,
                    ledger=ledger,
                    orders=orders,
                    executions=executions,
                    portfolio=projection,
                    scheduler=scheduler,
                )
                store.persist_id_generator(environment_id, ids)
                state_version = store.bump_state_version(environment_id, recovery_ts_ms)
                store.stage_execution_events(
                    environment_id=environment_id,
                    account_id=account_id,
                    state_version=state_version,
                    transaction_id=f"recovery:{recovery_ts_ms}:{state_version}",
                    orders=[
                        order.model_dump(mode="json")
                        for order in orders.orders()
                        if order.order_id in account_expired
                    ],
                    balances=[b.model_dump(mode="json") for b in ledger.balances()],
                    created_ts_ms=recovery_ts_ms,
                    executions=[],
                    positions=[
                        position.model_dump(mode="json")
                        for position in projection.positions()
                        if position.account_id == account_id
                    ],
                )
                expired.extend(account_expired)
        return expired

    def register_environment(self, environment_id: str) -> bool:
        """Register an environment and seed it with the current book snapshot."""
        if environment_id in self._environments:
            return False
        if not self.environment_exists(environment_id):
            return False
        with self.transaction(environment_id) as store:
            for instrument_id in self.instruments:
                view = self.books.latest("okx", instrument_id)
                if view is None or not self._executable_view(view):
                    continue
                liquidity = SimulatedLiquidityView(environment_id)
                liquidity.synchronize(view)
                store.persist_liquidity(
                    environment_id=environment_id,
                    liquidity=liquidity,
                    updated_ts_ms=self.now_ms(),
                )
        self._environments[environment_id] = {"trade_state": None}
        return True

    def apply_order_book_view(self, view: OrderBookView) -> None:
        """Update the shared book gate and synchronize registered environments."""
        if view.instrument_id not in self.instruments:
            return
        self.books.update(view)
        executable = self._executable_view(view)
        for environment_id in self._environments:
            try:
                self._apply_book_to_environment(environment_id, view, executable)
            except Exception:
                self.stats["dispatch_errors"] += 1
                logger.exception(
                    "failed to apply order book to environment %s", environment_id
                )

    def apply_trade(self, event: MarketEventEnvelope[Trade]) -> None:
        """Run TRADE_THROUGH passive matching for every registered environment."""
        if not isinstance(event.payload, Trade) or event.instrument_id not in self.instruments:
            return
        if event.quality_status is not DataQualityStatus.VALID:
            self.stats["trades_ignored"] += 1
            return
        for environment_id in self._environments:
            try:
                self._apply_trade_to_environment(environment_id, event)
            except Exception:
                self.stats["dispatch_errors"] += 1
                logger.exception(
                    "failed to apply trade %s to environment %s",
                    event.event_id,
                    environment_id,
                )

    def run_due(self) -> dict[str, Any]:
        """Execute every due scheduled order across registered environments."""
        # Snapshot the books BEFORE reading the clock: every view in the snapshot was
        # received at or before ``now_ms``, so books the feed delivers while this run
        # executes (it runs in a worker thread) cannot trip the no-lookahead gate.
        books = self.books.snapshot()
        now_ms = self.now_ms()
        executed: list[str] = []
        rejected: list[str] = []
        candidates: Iterable[str] = self._environments
        if self.due_environments is not None:
            try:
                due = self.due_environments(now_ms)
                candidates = [env for env in self._environments if env in due]
            except Exception:
                # Fall back to checking every environment; never skip due work on a probe failure.
                self.stats["dispatch_errors"] += 1
                logger.exception("due-environment pre-check failed")
        for environment_id in candidates:
            try:
                outcome = self._run_due_for_environment(environment_id, now_ms, books)
                executed.extend(outcome["executed"])
                rejected.extend(outcome["rejected"])
            except Exception:
                self.stats["dispatch_errors"] += 1
                logger.exception(
                    "failed to run due executions for environment %s", environment_id
                )
        self.stats["executions_processed"] += len(executed)
        return {"executed": executed, "rejected": rejected, "executed_ts_ms": now_ms}

    def _apply_book_to_environment(
        self, environment_id: str, view: OrderBookView, executable: bool
    ) -> None:
        with self.transaction(environment_id) as store:
            liquidity = self._restore_or_create_liquidity(
                store, environment_id, view
            )
            if liquidity is None:
                return
            if executable:
                key = (environment_id, view.instrument_id)
                if key not in self._liquidity_refreshed:
                    # First live book since this process started: persisted liquidity is from
                    # an earlier process (older generation numbering, stale residuals).
                    liquidity.reset_for_resynchronized_book(view, after_process_restart=True)
                else:
                    self._synchronize_liquidity(liquidity, view)
                self.stats["books_synchronized"] += 1
                self._liquidity_refreshed.add(key)
            store.persist_liquidity(
                environment_id=environment_id,
                liquidity=liquidity,
                updated_ts_ms=self.now_ms(),
            )

    def _apply_trade_to_environment(
        self, environment_id: str, event: MarketEventEnvelope[Trade]
    ) -> None:
        new_trade_state: tuple | None = None
        trade_key = (
            f"{event.exchange_id.value}:{event.instrument_id}:trade:{event.payload.trade_id}"
        )
        ordering_key = [
            event.exchange_ts_ms,
            event.received_ts_ms,
            event.event_id,
        ]
        with self.transaction(environment_id) as store:
            # The prior ordering key must be read before this trade is
            # registered, otherwise the registry would contain the current
            # event itself.
            prior_ordering_key = store.last_processed_trade_ordering_key(environment_id)
            inserted = store.record_processed_market_event(
                environment_id=environment_id,
                source_event_key=f"trade:{trade_key}",
                event_type="TRADE",
                processed_ts_ms=self.now_ms(),
                result={"event_id": event.event_id, "ordering_key": ordering_key},
            )
            if not inserted:
                self.stats["trades_ignored"] += 1
                return
            account_id = self._primary_account_id(store, environment_id)
            if account_id is None:
                self.stats["trades_ignored"] += 1
                return
            environment = store.load_environment(environment_id)
            ids = store.restore_id_generator(environment_id, environment["id_namespace"])
            clock = ManualClock(self.now_ms())
            ledger = store.restore_account_ledger(
                account_id=account_id, id_generator=ids, clock=clock
            )
            orders = store.restore_orders(ledger, environment_id)
            executions = store.restore_executions(environment_id)
            simulator = ExecutionSimulator(orders)
            engine = TradeThroughEngine(
                simulation_environment_id=environment_id,
                exchange_id=event.exchange_id,
                instrument_id=event.instrument_id,
                simulator=simulator,
                fee_schedule=self.fee_schedule,
                max_trade_age_ms=self.max_trade_age_ms,
            )
            cached_state = self._environments[environment_id]["trade_state"]
            if cached_state is not None:
                engine.restore_state(cached_state)
            elif prior_ordering_key is not None:
                engine.restore_state(
                    (set(), set(), {}, tuple(prior_ordering_key))
                )
            result = engine.process_trade(event, observed_ts_ms=self.now_ms())
            # The cache is updated only after the transaction commits; a
            # rollback must leave the trade reprocessable.
            new_trade_state = engine.snapshot_state()
            if result.status.value == "PROCESSED":
                self.stats["trades_processed"] += 1
            else:
                self.stats["trades_ignored"] += 1
            new_executions = simulator.executions()
            if not new_executions:
                return
            store.persist_trading_state(
                environment_id=environment_id,
                ledger=ledger,
                orders=orders,
                executions=(*executions, *new_executions),
                # The projection must include this transaction's new fills.
                portfolio=PortfolioEngine((*executions, *new_executions)),
            )
            store.persist_id_generator(environment_id, ids)
            state_version = store.bump_state_version(environment_id, clock.now_utc_ms())
            allocation_ids = {allocation.order_id for allocation in result.allocations}
            position_projection = PortfolioEngine((*executions, *new_executions))
            store.stage_execution_events(
                environment_id=environment_id,
                account_id=account_id,
                state_version=state_version,
                transaction_id=f"market:{event.event_id}:{state_version}",
                orders=[
                    order.model_dump(mode="json")
                    for order in orders.orders()
                    if order.order_id in allocation_ids
                ],
                balances=[
                    balance.model_dump(mode="json") for balance in ledger.balances()
                ],
                created_ts_ms=self.now_ms(),
                executions=[item.model_dump(mode="json") for item in new_executions],
                positions=[
                    position.model_dump(mode="json")
                    for position in position_projection.positions()
                    if position.account_id == account_id
                ],
            )
        if new_trade_state is not None:
            self._environments[environment_id]["trade_state"] = new_trade_state

    def _run_due_for_environment(
        self, environment_id: str, now_ms: int, books: LatestBookState | None = None
    ) -> dict[str, Any]:
        executed: list[str] = []
        rejected: list[str] = []
        with self.transaction(environment_id) as store:
            due_groups = self._pending_schedule_groups(store, environment_id)
            if not due_groups:
                return {"executed": executed, "rejected": rejected}
            environment = store.load_environment(environment_id)
            for account_id, _order_ids in due_groups:
                ids = store.restore_id_generator(environment_id, environment["id_namespace"])
                clock = ManualClock(now_ms)
                ledger = store.restore_account_ledger(
                    account_id=account_id, id_generator=ids, clock=clock
                )
                orders = store.restore_orders(ledger, environment_id)
                scheduler = store.restore_scheduler(
                    environment_id=environment_id, orders=orders, clock=clock
                )
                executions_before = store.restore_executions(environment_id)
                simulator = ExecutionSimulator(orders)
                outcomes: dict[str, str] = {}

                def route(
                    order: Any,
                    execution_ts_ms: int,
                    *,
                    _orders: Any = orders,
                    _simulator: ExecutionSimulator = simulator,
                    _outcomes: dict[str, str] = outcomes,
                ) -> None:
                    outcome = self._execute_due_order(
                        store,
                        environment_id=environment_id,
                        orders=_orders,
                        simulator=_simulator,
                        order=order,
                        execution_ts_ms=execution_ts_ms,
                        books=books,
                    )
                    _outcomes[order.order_id] = outcome

                scheduler.run_due(route)
                for order_id, outcome in outcomes.items():
                    if outcome == "REJECTED":
                        rejected.append(order_id)
                    else:
                        executed.append(order_id)
                new_executions = simulator.executions()
                position_projection = PortfolioEngine((*executions_before, *new_executions))
                store.persist_trading_state(
                    environment_id=environment_id,
                    ledger=ledger,
                    orders=orders,
                    executions=(*executions_before, *new_executions),
                    # The projection must include this transaction's new fills.
                    portfolio=position_projection,
                    scheduler=scheduler,
                )
                store.persist_id_generator(environment_id, ids)
                state_version = store.bump_state_version(environment_id, clock.now_utc_ms())
                store.stage_execution_events(
                    environment_id=environment_id,
                    account_id=account_id,
                    state_version=state_version,
                    transaction_id=f"dispatch:{now_ms}:{state_version}",
                    orders=[
                        order.model_dump(mode="json")
                        for order in orders.orders()
                        if order.order_id in outcomes
                    ],
                    balances=[
                        balance.model_dump(mode="json") for balance in ledger.balances()
                    ],
                    created_ts_ms=self.now_ms(),
                    executions=[item.model_dump(mode="json") for item in new_executions],
                    positions=[
                        position.model_dump(mode="json")
                        for position in position_projection.positions()
                        if position.account_id == account_id
                    ],
                )
        return {"executed": executed, "rejected": rejected}

    def _execute_due_order(
        self,
        store: Any,
        *,
        environment_id: str,
        orders: Any,
        simulator: ExecutionSimulator,
        order: Any,
        execution_ts_ms: int,
        books: LatestBookState | None = None,
    ) -> str:
        books = books if books is not None else self.books
        liquidity = self._restore_or_create_liquidity_by_instrument(
            store, environment_id, order.instrument_id, books=books
        )
        if liquidity is None:
            orders.record_scheduled_execution(
                order.order_id,
                executed_ts_ms=execution_ts_ms,
                execution_quote_event_id=None,
            )
            orders.reject(order.order_id, reason="MARKET_DATA_UNAVAILABLE")
            return "REJECTED"
        executor = ScheduledOrderExecutor(
            orders=orders,
            market_state=books,
            market_execution=OrderBookExecutionService(books, simulator, liquidity),
            limit_execution=LimitOrderExecutionService(books, simulator, liquidity),
        )
        executor.register(
            order.order_id,
            exchange_id=ExchangeId.OKX,
            max_book_age_ms=self.max_book_age_ms,
            fee_schedule=self.fee_schedule,
            market_rules=self._rules_for(order.instrument_id),
            consumption_id=f"dispatch:{environment_id}:{order.order_id}:{execution_ts_ms}",
        )
        executor(order, execution_ts_ms)
        return executor.outcome(order.order_id).outcome

    def _rules_for(self, instrument_id: str) -> MarketRules:
        """Per-instrument tick/lot/min rules; a shared rule set is only for single-rule setups."""
        if isinstance(self.market_rules, Mapping):
            return self.market_rules[instrument_id]
        return self.market_rules

    def _pending_schedule_groups(
        self, store: Any, environment_id: str
    ) -> list[tuple[str, list[str]]]:
        """Due order IDs grouped by account in deterministic execution order."""
        return store.due_schedule_groups(environment_id, self.now_ms())

    def _restore_or_create_liquidity(
        self, store: Any, environment_id: str, view: OrderBookView
    ) -> SimulatedLiquidityView | None:
        return self._restore_or_create_liquidity_by_instrument(
            store, environment_id, view.instrument_id, view
        )

    def _restore_or_create_liquidity_by_instrument(
        self,
        store: Any,
        environment_id: str,
        instrument_id: str,
        view: OrderBookView | None = None,
        *,
        books: LatestBookState | None = None,
    ) -> SimulatedLiquidityView | None:
        existing = store.restore_liquidity_optimistic(
            environment_id=environment_id,
            exchange_id=ExchangeId.OKX,
            instrument_id=instrument_id,
        )
        if existing is not None:
            return existing
        if view is None:
            view = (books or self.books).latest("okx", instrument_id)
        if view is None or not self._executable_view(view):
            return None
        liquidity = SimulatedLiquidityView(environment_id)
        liquidity.synchronize(view)
        return liquidity

    def _synchronize_liquidity(
        self, liquidity: SimulatedLiquidityView, view: OrderBookView
    ) -> None:
        try:
            liquidity.synchronize(view)
        except ValueError:
            # A resynchronized exchange book invalidates residual consumption;
            # the existing liquidity view must not be treated as still valid.
            liquidity.reset_for_resynchronized_book(view)

    def _primary_account_id(self, store: Any, environment_id: str) -> str | None:
        return store.primary_account_id(environment_id)

    @staticmethod
    def _executable_view(view: OrderBookView) -> bool:
        return (
            view.quality_status is DataQualityStatus.VALID
            and view.synchronized
            and view.source_connected
            and bool(view.bids and view.asks)
        )
