"""Synchronous application service and PostgreSQL transaction orchestration."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Sequence
from decimal import Decimal
from typing import Any
from uuid import uuid4

from pydantic import BaseModel
from sqlalchemy import Select, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import Engine

from crypto_lab.api.errors import ApplicationError
from crypto_lab.api.schemas import AccountCreate, EnvironmentCreate, OrderCreate
from crypto_lab.models import ExchangeId
from crypto_lab.persistence import PostgresUnitOfWork, schema
from crypto_lab.realtime import RealtimeEvent, RealtimePublisher
from crypto_lab.trading import (
    ExecutionLatency,
    FeeSchedule,
    LatencyPreset,
    ManualClock,
    OrderSide,
    OrderType,
    PortfolioEngine,
    create_paper_account,
)
from crypto_lab.trading.models import utc_now_ms


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, BaseModel):
        return _json_value(value.model_dump(mode="python"))
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _row(row: Any) -> dict[str, Any]:
    return _json_value(dict(row))


class ApplicationService:
    """Protects environment isolation and domain invariants from HTTP routes."""

    def __init__(
        self,
        engine: Engine,
        *,
        fee_schedule: FeeSchedule | None = None,
        now_ms: Callable[[], int] = utc_now_ms,
        realtime_publisher: RealtimePublisher | None = None,
    ) -> None:
        self.engine = engine
        self.realtime_publisher = realtime_publisher
        self.uow = PostgresUnitOfWork(
            engine,
            after_commit=(
                realtime_publisher.publish_committed if realtime_publisher else None
            ),
        )
        self.fee_schedule = fee_schedule
        self.now_ms = now_ms

    def create_environment(
        self, request: EnvironmentCreate, idempotency_key: str
    ) -> tuple[int, dict[str, Any]]:
        payload = request.model_dump(mode="json")
        with self.uow.bootstrap() as store:
            replay = self._idempotent_replay(
                store, "__system__", "create-environment", idempotency_key, payload
            )
            if replay:
                return replay
            environment_id = f"env_{uuid4().hex}"
            timestamp = self.now_ms()
            store.create_environment(
                environment_id=environment_id,
                name=request.name,
                id_namespace=environment_id,
                created_ts_ms=timestamp,
            )
            response = {
                "environment_id": environment_id,
                "name": request.name,
                "status": "ACTIVE",
                "created_ts_ms": timestamp,
                "updated_ts_ms": timestamp,
            }
            self._record_idempotency(
                store,
                "__system__",
                "create-environment",
                idempotency_key,
                payload,
                201,
                response,
            )
            return 201, response

    def get_environment(self, environment_id: str) -> dict[str, Any]:
        return self._one(
            select(schema.simulation_environments).where(
                schema.simulation_environments.c.environment_id == environment_id
            ),
            "ENVIRONMENT_NOT_FOUND",
            "simulation environment was not found",
        )

    def create_account(
        self, environment_id: str, request: AccountCreate, idempotency_key: str
    ) -> tuple[int, dict[str, Any]]:
        payload = request.model_dump(mode="json")
        with self.uow.transaction(environment_id) as store:
            replay = self._idempotent_replay(
                store, environment_id, "create-account", idempotency_key, payload
            )
            if replay:
                return replay
            environment = store.session.execute(
                select(schema.simulation_environments).where(
                    schema.simulation_environments.c.environment_id == environment_id
                )
            ).mappings().one()
            ids = store.restore_id_generator(environment_id, environment["id_namespace"])
            clock = ManualClock(self.now_ms())
            try:
                exchange_id = ExchangeId(request.exchange_id)
            except ValueError as exc:
                raise ApplicationError(
                    "INVALID_REQUEST", "unsupported exchange_id", status_code=400
                ) from exc
            ledger = create_paper_account(
                exchange_id,
                name=request.name,
                initial_asset=request.initial_asset,
                initial_amount=request.initial_amount,
                id_generator=ids,
                clock=clock,
            )
            from crypto_lab.trading import OrderService

            store.persist_trading_state(
                environment_id=environment_id,
                ledger=ledger,
                orders=OrderService(ledger, clock=clock),
                executions=(),
                portfolio=PortfolioEngine(),
            )
            store.persist_id_generator(environment_id, ids)
            response = _json_value(
                ledger.account.model_dump(mode="python")
                | {"environment_id": environment_id, "balances": ledger.balances()}
            )
            state_version = store.bump_state_version(environment_id, clock.now_utc_ms())
            response["state_version"] = state_version
            self._stage_account_events(
                store,
                environment_id=environment_id,
                account_id=ledger.account.account_id,
                state_version=state_version,
                transaction_id=f"account:{ledger.account.account_id}:{state_version}",
                orders=(),
                balances=[_json_value(item) for item in ledger.balances()],
            )
            self._record_idempotency(
                store,
                environment_id,
                "create-account",
                idempotency_key,
                payload,
                201,
                response,
            )
            return 201, response

    def list_accounts(self, environment_id: str, limit: int) -> list[dict[str, Any]]:
        self.get_environment(environment_id)
        return self._many(
            select(schema.paper_accounts)
            .where(schema.paper_accounts.c.environment_id == environment_id)
            .order_by(schema.paper_accounts.c.created_ts_ms, schema.paper_accounts.c.account_id)
            .limit(limit)
        )

    def get_account(self, environment_id: str, account_id: str) -> dict[str, Any]:
        return self._one(
            select(schema.paper_accounts).where(
                schema.paper_accounts.c.environment_id == environment_id,
                schema.paper_accounts.c.account_id == account_id,
            ),
            "ACCOUNT_NOT_FOUND",
            "paper account was not found",
        )

    def balances(self, environment_id: str, account_id: str) -> list[dict[str, Any]]:
        self.get_account(environment_id, account_id)
        return self._many(
            select(schema.asset_balances)
            .where(schema.asset_balances.c.account_id == account_id)
            .order_by(schema.asset_balances.c.asset)
        )

    def positions(self, environment_id: str, account_id: str) -> list[dict[str, Any]]:
        self.get_account(environment_id, account_id)
        return self._many(
            select(schema.positions)
            .where(schema.positions.c.account_id == account_id)
            .order_by(schema.positions.c.instrument_id)
        )

    def create_order(
        self, environment_id: str, request: OrderCreate, idempotency_key: str
    ) -> tuple[int, dict[str, Any]]:
        payload = request.model_dump(mode="json")
        with self.uow.transaction(environment_id) as store:
            replay = self._idempotent_replay(
                store, environment_id, "create-order", idempotency_key, payload
            )
            if replay:
                return replay
            account = store.session.execute(
                select(schema.paper_accounts).where(
                    schema.paper_accounts.c.environment_id == environment_id,
                    schema.paper_accounts.c.account_id == request.account_id,
                )
            ).mappings().one_or_none()
            if account is None:
                raise ApplicationError(
                    "ACCOUNT_NOT_FOUND", "paper account was not found", status_code=404
                )
            environment = store.session.execute(
                select(schema.simulation_environments).where(
                    schema.simulation_environments.c.environment_id == environment_id
                )
            ).mappings().one()
            ids = store.restore_id_generator(environment_id, environment["id_namespace"])
            clock = ManualClock(self.now_ms())
            ledger = store.restore_account_ledger(
                account_id=request.account_id, id_generator=ids, clock=clock
            )
            orders = store.restore_orders(ledger, environment_id)
            scheduler = store.restore_scheduler(
                environment_id=environment_id, orders=orders, clock=clock
            )
            market_reference, quote_event = self._market_reference(
                store, environment_id, request
            )
            if self.fee_schedule is None:
                raise ApplicationError(
                    "MARKET_CONFIGURATION_UNAVAILABLE",
                    "fee schedule is not configured",
                    status_code=503,
                )
            try:
                order = orders.place(
                    instrument_id=request.instrument_id,
                    side=OrderSide(request.side),
                    order_type=OrderType(request.order_type),
                    quantity=request.quantity,
                    limit_price=request.limit_price,
                    market_reference_price=market_reference,
                    max_quote_budget=request.max_quote_budget,
                    fee_schedule=self.fee_schedule,
                )
                latency = ExecutionLatency(
                    preset=LatencyPreset(request.latency_preset),
                    custom_ms=request.custom_latency_ms,
                )
                order = scheduler.schedule(
                    order.order_id,
                    latency=latency,
                    submission_quote_event_id=quote_event,
                )
            except (ValueError, KeyError) as exc:
                raise ApplicationError(
                    "INVALID_REQUEST", str(exc), status_code=400
                ) from exc
            executions = store.restore_executions(environment_id)
            store.persist_trading_state(
                environment_id=environment_id,
                ledger=ledger,
                orders=orders,
                executions=executions,
                portfolio=PortfolioEngine(executions),
                scheduler=scheduler,
            )
            store.persist_id_generator(environment_id, ids)
            response = _json_value(order.model_dump(mode="python"))
            state_version = store.bump_state_version(environment_id, clock.now_utc_ms())
            response["state_version"] = state_version
            self._stage_account_events(
                store,
                environment_id=environment_id,
                account_id=request.account_id,
                state_version=state_version,
                transaction_id=f"order:{order.order_id}:{state_version}",
                orders=[response],
                balances=[_json_value(item) for item in ledger.balances()],
            )
            self._record_idempotency(
                store,
                environment_id,
                "create-order",
                idempotency_key,
                payload,
                201,
                response,
            )
            return 201, response

    def list_orders(
        self, environment_id: str, limit: int, account_id: str | None, status: str | None
    ) -> list[dict[str, Any]]:
        self.get_environment(environment_id)
        statement = select(schema.paper_orders).where(
            schema.paper_orders.c.environment_id == environment_id
        )
        if account_id:
            statement = statement.where(schema.paper_orders.c.account_id == account_id)
        if status:
            statement = statement.where(schema.paper_orders.c.status == status)
        return self._many(statement.order_by(schema.paper_orders.c.order_sequence).limit(limit))

    def get_order(self, environment_id: str, order_id: str) -> dict[str, Any]:
        return self._one(
            select(schema.paper_orders).where(
                schema.paper_orders.c.environment_id == environment_id,
                schema.paper_orders.c.order_id == order_id,
            ),
            "ORDER_NOT_FOUND",
            "paper order was not found",
        )

    def cancel_order(
        self, environment_id: str, order_id: str, idempotency_key: str
    ) -> tuple[int, dict[str, Any]]:
        payload = {"order_id": order_id}
        with self.uow.transaction(environment_id) as store:
            replay = self._idempotent_replay(
                store, environment_id, f"cancel-order:{order_id}", idempotency_key, payload
            )
            if replay:
                return replay
            order_row = store.session.execute(
                select(schema.paper_orders).where(
                    schema.paper_orders.c.environment_id == environment_id,
                    schema.paper_orders.c.order_id == order_id,
                )
            ).mappings().one_or_none()
            if order_row is None:
                raise ApplicationError(
                    "ORDER_NOT_FOUND", "paper order was not found", status_code=404
                )
            environment = store.session.execute(
                select(schema.simulation_environments).where(
                    schema.simulation_environments.c.environment_id == environment_id
                )
            ).mappings().one()
            ids = store.restore_id_generator(environment_id, environment["id_namespace"])
            clock = ManualClock(self.now_ms())
            ledger = store.restore_account_ledger(
                account_id=order_row["account_id"], id_generator=ids, clock=clock
            )
            orders = store.restore_orders(ledger, environment_id)
            scheduler = store.restore_scheduler(
                environment_id=environment_id, orders=orders, clock=clock
            )
            try:
                if order_row["status"] == "PENDING_EXECUTION":
                    canceled = scheduler.cancel(order_id)
                else:
                    canceled = orders.cancel(order_id)
            except (ValueError, KeyError) as exc:
                raise ApplicationError("INVALID_ORDER_STATE", str(exc), status_code=409) from exc
            executions = store.restore_executions(environment_id)
            store.persist_trading_state(
                environment_id=environment_id,
                ledger=ledger,
                orders=orders,
                executions=executions,
                portfolio=PortfolioEngine(executions),
                scheduler=scheduler,
            )
            store.persist_id_generator(environment_id, ids)
            response = _json_value(canceled.model_dump(mode="python"))
            state_version = store.bump_state_version(environment_id, clock.now_utc_ms())
            response["state_version"] = state_version
            self._stage_account_events(
                store,
                environment_id=environment_id,
                account_id=order_row["account_id"],
                state_version=state_version,
                transaction_id=f"cancel:{order_id}:{state_version}",
                orders=[response],
                balances=[_json_value(item) for item in ledger.balances()],
            )
            self._record_idempotency(
                store,
                environment_id,
                f"cancel-order:{order_id}",
                idempotency_key,
                payload,
                200,
                response,
            )
            return 200, response

    def list_executions(
        self, environment_id: str, limit: int, account_id: str | None, order_id: str | None
    ) -> list[dict[str, Any]]:
        self.get_environment(environment_id)
        statement = select(schema.executions).where(
            schema.executions.c.environment_id == environment_id
        )
        if account_id:
            statement = statement.where(schema.executions.c.account_id == account_id)
        if order_id:
            statement = statement.where(schema.executions.c.order_id == order_id)
        return self._many(statement.order_by(schema.executions.c.execution_sequence).limit(limit))

    def get_execution(self, environment_id: str, execution_id: str) -> dict[str, Any]:
        return self._one(
            select(schema.executions).where(
                schema.executions.c.environment_id == environment_id,
                schema.executions.c.execution_id == execution_id,
            ),
            "EXECUTION_NOT_FOUND",
            "execution was not found",
        )

    def snapshot(self, environment_id: str, account_id: str) -> dict[str, Any]:
        with self.uow.session_factory.begin() as session:
            environment = session.execute(
                select(schema.simulation_environments).where(
                    schema.simulation_environments.c.environment_id == environment_id
                )
            ).mappings().one_or_none()
            if environment is None:
                raise ApplicationError(
                    "ENVIRONMENT_NOT_FOUND",
                    "simulation environment was not found",
                    status_code=404,
                )
            account = session.execute(
                select(schema.paper_accounts).where(
                    schema.paper_accounts.c.environment_id == environment_id,
                    schema.paper_accounts.c.account_id == account_id,
                )
            ).mappings().one_or_none()
            if account is None:
                raise ApplicationError(
                    "ACCOUNT_NOT_FOUND", "paper account was not found", status_code=404
                )
            def rows(table: Any, condition: Any, order_by: Any) -> list[dict[str, Any]]:
                result = session.execute(
                    select(table).where(condition).order_by(order_by)
                ).mappings()
                return [_row(item) for item in result]

            return {
                "environment_id": environment_id,
                "account_id": account_id,
                "state_version": int(environment["state_version"]),
                "account": _row(account),
                "balances": rows(
                    schema.asset_balances,
                    schema.asset_balances.c.account_id == account_id,
                    schema.asset_balances.c.asset,
                ),
                "orders": rows(
                    schema.paper_orders,
                    schema.paper_orders.c.account_id == account_id,
                    schema.paper_orders.c.order_sequence,
                ),
                "executions": rows(
                    schema.executions,
                    schema.executions.c.account_id == account_id,
                    schema.executions.c.execution_sequence,
                ),
                "positions": rows(
                    schema.positions,
                    schema.positions.c.account_id == account_id,
                    schema.positions.c.instrument_id,
                ),
            }

    def ready(self) -> bool:
        try:
            with self.engine.connect() as connection:
                revision = connection.execute(
                    text("SELECT version_num FROM alembic_version")
                ).scalar_one_or_none()
                return revision == "0003_realtime_state_version"
        except Exception:
            return False

    def _market_reference(
        self, store: Any, environment_id: str, request: OrderCreate
    ) -> tuple[Decimal | None, str | None]:
        if request.order_type == "LIMIT":
            return None, None
        exchange_id = request.instrument_id.split(":", 1)[0]
        row = store.session.execute(
            select(schema.simulated_liquidity).where(
                schema.simulated_liquidity.c.environment_id == environment_id,
                schema.simulated_liquidity.c.exchange_id == exchange_id,
                schema.simulated_liquidity.c.instrument_id == request.instrument_id,
            )
        ).mappings().one_or_none()
        if row is None:
            raise ApplicationError(
                "MARKET_DATA_UNAVAILABLE", "valid order book is unavailable", status_code=503
            )
        levels = row["residual_asks_json"] if request.side == "BUY" else row["residual_bids_json"]
        if not levels:
            raise ApplicationError(
                "MARKET_DATA_UNAVAILABLE", "executable quote is unavailable", status_code=503
            )
        return Decimal(levels[0][0]), row["source_book_event_id"]

    def _one(self, statement: Select[Any], code: str, message: str) -> dict[str, Any]:
        with self.engine.connect() as connection:
            result = connection.execute(statement).mappings().one_or_none()
        if result is None:
            raise ApplicationError(code, message, status_code=404)
        return _row(result)

    def _many(self, statement: Select[Any]) -> list[dict[str, Any]]:
        with self.engine.connect() as connection:
            return [_row(row) for row in connection.execute(statement).mappings()]

    @staticmethod
    def _hash(payload: dict[str, Any]) -> str:
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()

    def _idempotent_replay(
        self,
        store: Any,
        environment_id: str,
        scope: str,
        key: str,
        payload: dict[str, Any],
    ) -> tuple[int, dict[str, Any]] | None:
        existing = store.session.execute(
            select(schema.api_idempotency_keys).where(
                schema.api_idempotency_keys.c.environment_id == environment_id,
                schema.api_idempotency_keys.c.scope == scope,
                schema.api_idempotency_keys.c.idempotency_key == key,
            )
        ).mappings().one_or_none()
        if existing is None:
            return None
        if existing["request_hash"] != self._hash(payload):
            raise ApplicationError(
                "IDEMPOTENCY_KEY_REUSED",
                "idempotency key was reused with a different request",
                status_code=409,
            )
        return int(existing["response_status"]), dict(existing["response_json"])

    def _record_idempotency(
        self,
        store: Any,
        environment_id: str,
        scope: str,
        key: str,
        payload: dict[str, Any],
        status: int,
        response: dict[str, Any],
    ) -> None:
        store.session.execute(
            insert(schema.api_idempotency_keys).values(
                environment_id=environment_id,
                scope=scope,
                idempotency_key=key,
                request_hash=self._hash(payload),
                response_status=status,
                response_json=response,
                created_ts_ms=self.now_ms(),
            )
        )

    def _stage_account_events(
        self,
        store: Any,
        *,
        environment_id: str,
        account_id: str,
        state_version: int,
        transaction_id: str,
        orders: Sequence[dict[str, Any]],
        balances: list[dict[str, Any]],
    ) -> None:
        event_index = 0
        for order in orders:
            store.stage_realtime_event(
                RealtimeEvent(
                    topic="orders",
                    event_id=f"{transaction_id}:order:{order['order_id']}",
                    event_ts_ms=self.now_ms(),
                    payload=order,
                    account_id=account_id,
                    order_id=str(order["order_id"]),
                    state_version=state_version,
                    transaction_id=transaction_id,
                    event_index=event_index,
                )
            )
            event_index += 1
        for balance in balances:
            store.stage_realtime_event(
                RealtimeEvent(
                    topic="balances",
                    event_id=f"{transaction_id}:balance:{balance['asset']}",
                    event_ts_ms=self.now_ms(),
                    payload=balance,
                    account_id=account_id,
                    state_version=state_version,
                    transaction_id=transaction_id,
                    event_index=event_index,
                )
            )
            event_index += 1
