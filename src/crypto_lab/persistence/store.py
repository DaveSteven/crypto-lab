"""PostgreSQL repositories and transaction boundary for simulation state."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from crypto_lab.market_data import OrderBookView
from crypto_lab.models import DataQualityStatus, ExchangeId, PriceLevel
from crypto_lab.persistence import schema
from crypto_lab.trading import (
    AccountLedger,
    AssetBalance,
    ExecutionRecord,
    ExecutionScheduler,
    LedgerEntry,
    ManualClock,
    OrderService,
    PaperAccount,
    PaperOrder,
    PortfolioEngine,
    Position,
    ScheduledExecution,
    SimulatedLiquidityView,
)
from crypto_lab.trading.identity import DeterministicIdGenerator, IdGenerator


class PersistenceError(RuntimeError):
    pass


class PostgresStore:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_environment(
        self,
        *,
        environment_id: str,
        name: str,
        id_namespace: str,
        created_ts_ms: int,
    ) -> None:
        self.session.execute(
            insert(schema.simulation_environments)
            .values(
                environment_id=environment_id,
                name=name,
                status="ACTIVE",
                id_namespace=id_namespace,
                last_event_ts_ms=None,
                next_arrival_sequence=1,
                created_ts_ms=created_ts_ms,
                updated_ts_ms=created_ts_ms,
            )
            .on_conflict_do_nothing(index_elements=["environment_id"])
        )

    def lock_environment(self, environment_id: str) -> None:
        row = self.session.execute(
            select(schema.simulation_environments.c.environment_id)
            .where(schema.simulation_environments.c.environment_id == environment_id)
            .with_for_update()
        ).scalar_one_or_none()
        if row is None:
            raise PersistenceError(f"unknown simulation environment: {environment_id}")

    def persist_trading_state(
        self,
        *,
        environment_id: str,
        ledger: AccountLedger,
        orders: OrderService,
        executions: tuple[ExecutionRecord, ...],
        portfolio: PortfolioEngine,
        scheduler: ExecutionScheduler | None = None,
    ) -> None:
        _validate_financial_precision(ledger, orders, executions, portfolio)
        self._upsert_account(environment_id, ledger.account)
        self._insert_ledger_entries(environment_id, ledger.entries)
        self._upsert_balances(ledger)
        self._upsert_orders(environment_id, orders.orders())
        self._insert_executions(environment_id, executions)
        self._upsert_positions(portfolio.positions(), executions)
        if scheduler is not None:
            self._replace_schedule(environment_id, scheduler)

    def restore_account_ledger(
        self,
        *,
        account_id: str,
        id_generator: IdGenerator,
        clock: ManualClock,
    ) -> AccountLedger:
        account_row = (
            self.session.execute(
                select(schema.paper_accounts).where(
                    schema.paper_accounts.c.account_id == account_id
                )
            )
            .mappings()
            .one()
        )
        account = PaperAccount(
            account_id=account_row["account_id"],
            name=account_row["name"],
            exchange_id=ExchangeId(account_row["exchange_id"]),
            created_ts_ms=account_row["created_ts_ms"],
        )
        rows = self.session.execute(
            select(schema.ledger_entries)
            .where(schema.ledger_entries.c.account_id == account_id)
            .order_by(schema.ledger_entries.c.ledger_sequence)
        ).mappings()
        entries = tuple(
            LedgerEntry(
                entry_id=row["entry_id"],
                account_id=row["account_id"],
                exchange_id=ExchangeId(row["exchange_id"]),
                asset=row["asset"],
                available_delta=row["available_delta"],
                locked_delta=row["locked_delta"],
                reason=row["reason"],
                reference_id=row["reference_id"],
                created_ts_ms=row["created_ts_ms"],
            )
            for row in rows
        )
        ledger = AccountLedger(account, entries, id_generator=id_generator, clock=clock)
        self._verify_balance_projection(ledger)
        return ledger

    def restore_orders(self, ledger: AccountLedger, environment_id: str) -> OrderService:
        rows = self.session.execute(
            select(schema.paper_orders)
            .where(schema.paper_orders.c.environment_id == environment_id)
            .order_by(schema.paper_orders.c.order_sequence)
        ).mappings()
        restored = tuple(
            PaperOrder.model_validate(
                {key: value for key, value in row.items() if key != "environment_id"}
            )
            for row in rows
        )
        service = OrderService(ledger, clock=ledger.clock)
        service.restore_state(
            (
                {order.order_id: order for order in restored},
                max((o.order_sequence for o in restored), default=0) + 1,
            )
        )
        return service

    def restore_executions(self, environment_id: str) -> tuple[ExecutionRecord, ...]:
        rows = self.session.execute(
            select(schema.executions)
            .where(schema.executions.c.environment_id == environment_id)
            .order_by(
                schema.executions.c.execution_sequence,
            )
        ).mappings()
        ignored = {"environment_id", "fill_sequence", "execution_sequence"}
        return tuple(
            ExecutionRecord.model_validate(
                {key: value for key, value in row.items() if key not in ignored}
            )
            for row in rows
        )

    def restore_portfolio(self, environment_id: str) -> PortfolioEngine:
        executions = self.restore_executions(environment_id)
        portfolio = PortfolioEngine(executions)
        persisted = self.session.execute(select(schema.positions)).mappings()
        expected = {position_key(position): position for position in portfolio.positions()}
        actual = {
            (row["account_id"], row["instrument_id"]): Position.model_validate(
                {key: value for key, value in row.items() if key != "last_execution_id"}
            )
            for row in persisted
        }
        if actual != expected:
            raise PersistenceError("position projection differs from Fill History rebuild")
        return portfolio

    def persist_id_generator(
        self, environment_id: str, generator: DeterministicIdGenerator
    ) -> None:
        for kind, current_sequence in generator.snapshot_state().items():
            statement = insert(schema.id_generator_state).values(
                environment_id=environment_id,
                id_kind=kind,
                next_sequence=current_sequence + 1,
            )
            self.session.execute(
                statement.on_conflict_do_update(
                    index_elements=["environment_id", "id_kind"],
                    set_={"next_sequence": statement.excluded.next_sequence},
                )
            )

    def restore_id_generator(self, environment_id: str, namespace: str) -> DeterministicIdGenerator:
        rows = self.session.execute(
            select(schema.id_generator_state).where(
                schema.id_generator_state.c.environment_id == environment_id
            )
        ).mappings()
        generator = DeterministicIdGenerator(namespace)
        generator.restore_state({row["id_kind"]: row["next_sequence"] - 1 for row in rows})
        return generator

    def restore_scheduler(
        self,
        *,
        environment_id: str,
        orders: OrderService,
        clock: ManualClock,
    ) -> ExecutionScheduler:
        rows = self.session.execute(
            select(schema.scheduled_executions)
            .where(schema.scheduled_executions.c.environment_id == environment_id)
            .order_by(
                schema.scheduled_executions.c.scheduled_execution_ts_ms,
                schema.scheduled_executions.c.order_sequence,
            )
        ).mappings()
        pending = {
            row["order_id"]: ScheduledExecution(
                order_id=row["order_id"],
                scheduled_execution_ts_ms=row["scheduled_execution_ts_ms"],
                order_sequence=row["order_sequence"],
            )
            for row in rows
        }
        scheduler = ExecutionScheduler(orders, clock)
        scheduler.restore_state((pending, set()))
        return scheduler

    def persist_liquidity(
        self,
        *,
        environment_id: str,
        liquidity: SimulatedLiquidityView,
        updated_ts_ms: int,
    ) -> None:
        market_book, residual_bids, residual_asks, consumption_ids = liquidity.snapshot_state()
        if market_book is None:
            return
        statement = insert(schema.simulated_liquidity).values(
            environment_id=environment_id,
            exchange_id=market_book.exchange_id.value,
            instrument_id=market_book.instrument_id,
            synchronization_generation=market_book.synchronization_generation,
            source_book_event_id=market_book.source_event_id,
            residual_bids_json=_decimal_levels(residual_bids),
            residual_asks_json=_decimal_levels(residual_asks),
            market_book_json=_serialize_book(market_book),
            consumption_ids_json=sorted(consumption_ids),
            updated_ts_ms=updated_ts_ms,
        )
        updates = {
            column.name: getattr(statement.excluded, column.name)
            for column in schema.simulated_liquidity.c
            if column.name not in {"environment_id", "exchange_id", "instrument_id"}
        }
        self.session.execute(
            statement.on_conflict_do_update(
                index_elements=["environment_id", "exchange_id", "instrument_id"],
                set_=updates,
            )
        )

    def restore_liquidity(
        self,
        *,
        environment_id: str,
        exchange_id: ExchangeId,
        instrument_id: str,
    ) -> SimulatedLiquidityView:
        row = (
            self.session.execute(
                select(schema.simulated_liquidity).where(
                    schema.simulated_liquidity.c.environment_id == environment_id,
                    schema.simulated_liquidity.c.exchange_id == exchange_id.value,
                    schema.simulated_liquidity.c.instrument_id == instrument_id,
                )
            )
            .mappings()
            .one()
        )
        liquidity = SimulatedLiquidityView(environment_id)
        liquidity.restore_state(
            (
                _deserialize_book(row["market_book_json"]),
                _restore_decimal_levels(row["residual_bids_json"]),
                _restore_decimal_levels(row["residual_asks_json"]),
                set(row["consumption_ids_json"]),
            )
        )
        return liquidity

    def _upsert_account(self, environment_id: str, account: PaperAccount) -> None:
        values = account.model_dump(mode="python") | {"environment_id": environment_id}
        statement = insert(schema.paper_accounts).values(**values)
        self.session.execute(
            statement.on_conflict_do_update(
                index_elements=["account_id"],
                set_={"name": statement.excluded.name},
            )
        )

    def _insert_ledger_entries(self, environment_id: str, entries: tuple[LedgerEntry, ...]) -> None:
        if not entries:
            return
        values = [
            entry.model_dump(mode="python")
            | {"environment_id": environment_id, "ledger_sequence": sequence}
            for sequence, entry in enumerate(entries, start=1)
        ]
        self.session.execute(
            insert(schema.ledger_entries)
            .values(values)
            .on_conflict_do_nothing(index_elements=["entry_id"])
        )

    def _upsert_balances(self, ledger: AccountLedger) -> None:
        last_by_asset: dict[str, LedgerEntry] = {}
        for entry in ledger.entries:
            last_by_asset[entry.asset] = entry
        for balance in ledger.balances():
            statement = insert(schema.asset_balances).values(
                account_id=ledger.account.account_id,
                asset=balance.asset,
                available=balance.available,
                locked=balance.locked,
                last_entry_id=last_by_asset[balance.asset].entry_id,
                updated_ts_ms=last_by_asset[balance.asset].created_ts_ms,
            )
            self.session.execute(
                statement.on_conflict_do_update(
                    index_elements=["account_id", "asset"],
                    set_={
                        "available": statement.excluded.available,
                        "locked": statement.excluded.locked,
                        "last_entry_id": statement.excluded.last_entry_id,
                        "updated_ts_ms": statement.excluded.updated_ts_ms,
                    },
                )
            )

    def _upsert_orders(self, environment_id: str, orders: tuple[PaperOrder, ...]) -> None:
        for order in orders:
            values = order.model_dump(mode="python") | {"environment_id": environment_id}
            statement = insert(schema.paper_orders).values(**values)
            updates = {
                column.name: getattr(statement.excluded, column.name)
                for column in schema.paper_orders.c
                if column.name not in {"order_id", "environment_id", "account_id"}
            }
            self.session.execute(
                statement.on_conflict_do_update(index_elements=["order_id"], set_=updates)
            )

    def _insert_executions(
        self, environment_id: str, executions: tuple[ExecutionRecord, ...]
    ) -> None:
        sequence_by_order: defaultdict[str, int] = defaultdict(int)
        for execution_sequence, execution in enumerate(executions, start=1):
            sequence_by_order[execution.order_id] += 1
            values = execution.model_dump(mode="python") | {
                "environment_id": environment_id,
                "fill_sequence": sequence_by_order[execution.order_id],
                "execution_sequence": execution_sequence,
            }
            self.session.execute(
                insert(schema.executions)
                .values(**values)
                .on_conflict_do_nothing(index_elements=["execution_id"])
            )

    def _upsert_positions(
        self,
        positions: tuple[Position, ...],
        executions: tuple[ExecutionRecord, ...],
    ) -> None:
        last_execution: dict[tuple[str, str], str] = {}
        for execution in executions:
            last_execution[(execution.account_id, execution.instrument_id)] = execution.execution_id
        for position in positions:
            values = position.model_dump(mode="python") | {
                "last_execution_id": last_execution.get(position_key(position))
            }
            statement = insert(schema.positions).values(**values)
            updates = {
                column.name: getattr(statement.excluded, column.name)
                for column in schema.positions.c
                if column.name not in {"account_id", "instrument_id"}
            }
            self.session.execute(
                statement.on_conflict_do_update(
                    index_elements=["account_id", "instrument_id"], set_=updates
                )
            )

    def _replace_schedule(self, environment_id: str, scheduler: ExecutionScheduler) -> None:
        self.session.execute(
            delete(schema.scheduled_executions).where(
                schema.scheduled_executions.c.environment_id == environment_id
            )
        )
        pending = scheduler.snapshot_state()[0].values()
        if pending:
            self.session.execute(
                insert(schema.scheduled_executions),
                [
                    item.model_dump(mode="python")
                    | {"environment_id": environment_id, "status": "PENDING"}
                    for item in pending
                ],
            )

    def _verify_balance_projection(self, ledger: AccountLedger) -> None:
        rows = self.session.execute(
            select(schema.asset_balances).where(
                schema.asset_balances.c.account_id == ledger.account.account_id
            )
        ).mappings()
        persisted = {
            row["asset"]: AssetBalance(
                asset=row["asset"], available=row["available"], locked=row["locked"]
            )
            for row in rows
        }
        rebuilt = {balance.asset: balance for balance in ledger.balances()}
        if persisted != rebuilt:
            raise PersistenceError("balance projection differs from Ledger rebuild")


class PostgresUnitOfWork:
    def __init__(self, engine: Engine) -> None:
        self.session_factory = sessionmaker(engine, expire_on_commit=False)

    @contextmanager
    def transaction(self, environment_id: str) -> Iterator[PostgresStore]:
        with self.session_factory.begin() as session:
            store = PostgresStore(session)
            store.lock_environment(environment_id)
            yield store

    @contextmanager
    def bootstrap(self) -> Iterator[PostgresStore]:
        with self.session_factory.begin() as session:
            yield PostgresStore(session)


def position_key(position: Position) -> tuple[str, str]:
    return (position.account_id, position.instrument_id)


def _validate_financial_precision(
    ledger: AccountLedger,
    orders: OrderService,
    executions: tuple[ExecutionRecord, ...],
    portfolio: PortfolioEngine,
) -> None:
    values: list[Decimal] = []
    for entry in ledger.entries:
        values.extend((entry.available_delta, entry.locked_delta))
    for balance in ledger.balances():
        values.extend((balance.available, balance.locked))
    for order in orders.orders():
        values.extend(
            (
                order.quantity,
                order.reference_price,
                order.reserved_amount,
                order.filled_quantity,
                order.cumulative_quote_amount,
                order.cumulative_fee,
                order.reserved_fee_rate,
            )
        )
        values.extend(
            value
            for value in (order.limit_price, order.max_quote_budget, order.average_fill_price)
            if value is not None
        )
    for execution in executions:
        values.extend(
            (
                execution.price,
                execution.quantity,
                execution.quote_amount,
                execution.fee_amount,
            )
        )
    for position in portfolio.positions():
        values.extend(
            (
                position.quantity,
                position.cost_basis,
                position.realized_pnl,
                position.cumulative_fees,
            )
        )
        if position.average_cost is not None:
            values.append(position.average_cost)
    for value in values:
        _require_numeric_50_24(value)


def _require_numeric_50_24(value: Decimal) -> None:
    _, digits, exponent = value.as_tuple()
    fractional_digits = max(0, -exponent)
    integer_digits = max(0, len(digits) + exponent)
    if fractional_digits > 24 or integer_digits > 26:
        raise PersistenceError(f"Decimal value exceeds NUMERIC(50,24): {value}")


def _decimal_levels(values: dict[Decimal, Decimal]) -> list[list[str]]:
    return [[str(price), str(quantity)] for price, quantity in sorted(values.items())]


def _restore_decimal_levels(values: list[list[str]]) -> dict[Decimal, Decimal]:
    return {Decimal(price): Decimal(quantity) for price, quantity in values}


def _serialize_book(book: OrderBookView) -> dict[str, object]:
    return {
        "exchange_id": book.exchange_id.value,
        "instrument_id": book.instrument_id,
        "bids": [[str(level.price), str(level.quantity)] for level in book.bids],
        "asks": [[str(level.price), str(level.quantity)] for level in book.asks],
        "depth": book.depth,
        "sequence_id": book.sequence_id,
        "source_event_id": book.source_event_id,
        "exchange_ts_ms": book.exchange_ts_ms,
        "received_ts_ms": book.received_ts_ms,
        "quality_status": book.quality_status.value,
        "synchronized": book.synchronized,
        "source_connected": book.source_connected,
        "synchronization_generation": book.synchronization_generation,
    }


def _deserialize_book(value: dict[str, object]) -> OrderBookView:
    bids = value["bids"]
    asks = value["asks"]
    assert isinstance(bids, list) and isinstance(asks, list)
    return OrderBookView(
        exchange_id=ExchangeId(str(value["exchange_id"])),
        instrument_id=str(value["instrument_id"]),
        bids=tuple(PriceLevel(price=row[0], quantity=row[1]) for row in bids),
        asks=tuple(PriceLevel(price=row[0], quantity=row[1]) for row in asks),
        depth=int(str(value["depth"])),
        sequence_id=(str(value["sequence_id"]) if value["sequence_id"] is not None else None),
        source_event_id=str(value["source_event_id"]),
        exchange_ts_ms=(
            int(str(value["exchange_ts_ms"])) if value["exchange_ts_ms"] is not None else None
        ),
        received_ts_ms=int(str(value["received_ts_ms"])),
        quality_status=DataQualityStatus(str(value["quality_status"])),
        synchronized=bool(value["synchronized"]),
        source_connected=bool(value["source_connected"]),
        synchronization_generation=int(str(value["synchronization_generation"])),
    )
