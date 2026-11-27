"""Synchronous application service and PostgreSQL transaction orchestration."""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable, Sequence
from decimal import Decimal
from typing import Any
from uuid import uuid4

from pydantic import BaseModel
from sqlalchemy import Select, delete, func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from crypto_lab.api.errors import ApplicationError
from crypto_lab.api.schemas import (
    AccountCreate,
    EnvironmentCreate,
    JournalCreate,
    JournalOrderLink,
    JournalOrderUnlink,
    JournalPatch,
    JournalTransition,
    OrderCreate,
    PlanRevisionCreate,
    TradePlannerPreview,
)
from crypto_lab.api.trade_planner import calculate_plan
from crypto_lab.market_data import OkxCandleClient
from crypto_lab.models import ExchangeId
from crypto_lab.persistence import PostgresUnitOfWork, schema
from crypto_lab.persistence.store import PostgresStore
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
from crypto_lab.trading.portfolio import realized_pnl_summary

logger = logging.getLogger(__name__)


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
        candle_client: OkxCandleClient | None = None,
        market_rules: dict[str, Any] | None = None,
        max_market_age_ms: int = 5_000,
    ) -> None:
        self.engine = engine
        self.realtime_publisher = realtime_publisher
        self.candle_client = candle_client
        self.market_rules = market_rules or {}
        self.max_market_age_ms = max_market_age_ms
        self.uow = PostgresUnitOfWork(
            engine,
            after_commit=(
                realtime_publisher.publish_committed if realtime_publisher else None
            ),
        )
        self.fee_schedule = fee_schedule
        self.now_ms = now_ms

    def fee_schedule_view(self) -> dict[str, Any]:
        if self.fee_schedule is None:
            raise ApplicationError(
                "FEE_SCHEDULE_UNAVAILABLE", "fee schedule is not configured", status_code=503
            )
        return {
            "schedule_id": self.fee_schedule.schedule_id,
            "maker_fee_rate": str(self.fee_schedule.maker_rate),
            "taker_fee_rate": str(self.fee_schedule.taker_rate),
            "conservative_fee_rate": str(self.fee_schedule.maximum_rate),
            "fee_asset_mode": "QUOTE_ASSET",
        }

    def market_rules_view(self, instrument_id: str) -> dict[str, Any]:
        rules = self.market_rules.get(instrument_id)
        if rules is None:
            raise ApplicationError(
                "MARKET_RULES_UNAVAILABLE", "market rules are not configured", status_code=503
            )
        return _json_value(rules.model_dump(mode="python")) | {"instrument_id": instrument_id}

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

    def list_environments(self, limit: int = 50) -> list[dict[str, Any]]:
        """Existing simulation environments, newest first (read-only listing)."""
        return self._many(
            select(schema.simulation_environments)
            .order_by(schema.simulation_environments.c.created_ts_ms.desc(),
                      schema.simulation_environments.c.environment_id)
            .limit(limit)
        )

    def environments_with_due_executions(self, now_ms: int) -> set[str]:
        """Environments that have scheduled executions due (one light, lock-free query)."""
        with self.engine.connect() as connection:
            rows = connection.execute(
                select(schema.scheduled_executions.c.environment_id)
                .where(schema.scheduled_executions.c.scheduled_execution_ts_ms <= now_ms)
                .distinct()
            )
            return {row[0] for row in rows}

    def list_environment_ids(self) -> list[str]:
        """All persisted environment ids, oldest first (used to restore dispatch after restart)."""
        with self.engine.connect() as connection:
            rows = connection.execute(
                select(schema.simulation_environments.c.environment_id).order_by(
                    schema.simulation_environments.c.created_ts_ms
                )
            )
            return [row[0] for row in rows]

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

    def pnl_summary(self, environment_id: str, account_id: str) -> dict[str, Any]:
        """Account lifetime realized PnL / fees, rebuilt from the full Fill History."""
        with self.uow.session_factory.begin() as session:
            session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
            self._require_account(session, environment_id, account_id)
            return self._pnl_view(session, environment_id, account_id)

    def _require_account(self, session: Any, environment_id: str, account_id: str) -> Any:
        environment = session.execute(
            select(schema.simulation_environments).where(
                schema.simulation_environments.c.environment_id == environment_id
            )
        ).mappings().one_or_none()
        if environment is None:
            raise ApplicationError(
                "ENVIRONMENT_NOT_FOUND", "simulation environment was not found", status_code=404
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
        return environment

    def _pnl_view(self, session: Any, environment_id: str, account_id: str) -> dict[str, Any]:
        environment = session.execute(
            select(schema.simulation_environments).where(
                schema.simulation_environments.c.environment_id == environment_id
            )
        ).mappings().one()
        base: dict[str, Any] = {
            "environment_id": environment_id,
            "account_id": account_id,
            "state_version": int(environment["state_version"]),
            "as_of_ts_ms": int(self.now_ms()),
            "scope": "ACCOUNT_LIFETIME_FILL_HISTORY",
            "cost_method": "MOVING_AVERAGE",
        }
        try:
            executions = PostgresStore(session).restore_executions(environment_id)
            summary = realized_pnl_summary(executions, account_id)
        except Exception as exc:  # unavailable is explicit, never masked as zero
            logger.exception("realized PnL rebuild failed for %s/%s", environment_id, account_id)
            return {**base, "status": "UNAVAILABLE", "reason": f"{type(exc).__name__}: {exc}"}
        return _json_value({**base, "status": "AVAILABLE", **summary})

    def snapshot(self, environment_id: str, account_id: str) -> dict[str, Any]:
        with self.uow.session_factory.begin() as session:
            # One consistent read view: orders, fills, balances, positions and PnL
            # all belong to the same state_version.
            session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
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
                "pnl": self._pnl_view(session, environment_id, account_id),
            }

    def candle_history(
        self,
        instrument_id: str,
        interval: str,
        limit: int,
        before: int | None,
        after: int | None,
    ) -> dict[str, Any]:
        if self.candle_client is None:
            raise ApplicationError(
                "TOPIC_UNAVAILABLE", "real candle source is not configured", status_code=503
            )
        try:
            events = self.candle_client.history(
                instrument_id, interval, limit=limit, before=before, after=after
            )
        except ValueError as exc:
            raise ApplicationError("INVALID_REQUEST", str(exc), status_code=400) from exc
        except OSError as exc:
            raise ApplicationError(
                "MARKET_DATA_UNAVAILABLE", "OKX candle source is unavailable", status_code=503
            ) from exc
        return {
            "items": [event.model_dump(mode="json") for event in events],
            "source": "OKX_PUBLIC_REST",
        }

    def create_journal(
        self,
        environment_id: str,
        account_id: str,
        request: JournalCreate,
        idempotency_key: str,
    ) -> tuple[int, dict[str, Any]]:
        payload = request.model_dump(mode="json") | {"account_id": account_id}
        with self.uow.bootstrap() as store:
            self._require_account(store.session, environment_id, account_id)
            replay = self._idempotent_replay(
                store, environment_id, f"create-journal:{account_id}", idempotency_key, payload
            )
            if replay:
                return replay
            now = self.now_ms()
            journal_id = f"journal_{uuid4().hex}"
            values = {
                "journal_id": journal_id,
                "environment_id": environment_id,
                "account_id": account_id,
                "instrument_id": request.instrument_id,
                "title": request.title,
                "status": "DRAFT",
                "version": 1,
                "timeframe": request.timeframe,
                "market_trend": request.market_trend,
                "trade_reason": request.trade_reason,
                "entry_conditions": request.entry_conditions,
                "created_ts_ms": now,
                "updated_ts_ms": now,
            }
            store.session.execute(schema.trading_journals.insert().values(**values))
            self._audit_journal(store, journal_id, "CREATED", 1, now, details={})
            response = _json_value(values)
            self._record_idempotency(
                store,
                environment_id,
                f"create-journal:{account_id}",
                idempotency_key,
                payload,
                201,
                response,
            )
            return 201, response

    def list_journals(
        self,
        environment_id: str,
        account_id: str,
        limit: int,
        status: str | None = None,
        instrument_id: str | None = None,
    ) -> list[dict[str, Any]]:
        with self.engine.connect() as connection:
            self._require_account(connection, environment_id, account_id)
            statement = select(schema.trading_journals).where(
                schema.trading_journals.c.environment_id == environment_id,
                schema.trading_journals.c.account_id == account_id,
            )
            if status:
                statement = statement.where(schema.trading_journals.c.status == status)
            if instrument_id:
                statement = statement.where(
                    schema.trading_journals.c.instrument_id == instrument_id
                )
            rows = connection.execute(
                statement.order_by(
                    schema.trading_journals.c.updated_ts_ms.desc(),
                    schema.trading_journals.c.journal_id,
                ).limit(limit)
            ).mappings()
            return [_row(row) for row in rows]

    def get_journal(
        self, environment_id: str, account_id: str, journal_id: str
    ) -> dict[str, Any]:
        with self.engine.connect() as connection:
            journal = self._journal_row(
                connection, environment_id, account_id, journal_id, for_update=False
            )
            revisions = connection.execute(
                select(schema.trade_plan_revisions)
                .where(schema.trade_plan_revisions.c.journal_id == journal_id)
                .order_by(schema.trade_plan_revisions.c.revision_number)
            ).mappings()
            links = connection.execute(
                select(schema.journal_order_links)
                .where(schema.journal_order_links.c.journal_id == journal_id)
                .order_by(schema.journal_order_links.c.link_sequence)
            ).mappings()
            linked_orders = connection.execute(
                select(schema.paper_orders)
                .join(
                    schema.journal_order_links,
                    schema.journal_order_links.c.order_id == schema.paper_orders.c.order_id,
                )
                .where(schema.journal_order_links.c.journal_id == journal_id)
                .order_by(schema.paper_orders.c.order_sequence)
            ).mappings()
            linked_executions = connection.execute(
                select(schema.executions)
                .join(
                    schema.journal_order_links,
                    schema.journal_order_links.c.order_id == schema.executions.c.order_id,
                )
                .where(schema.journal_order_links.c.journal_id == journal_id)
                .order_by(schema.executions.c.execution_sequence)
            ).mappings()
            return _row(journal) | {
                "plan_revisions": [_row(row) for row in revisions],
                "order_links": [_row(row) for row in links],
                "linked_orders": [_row(row) for row in linked_orders],
                "linked_executions": [_row(row) for row in linked_executions],
                "metrics": self._journal_metrics(connection, journal),
            }

    def link_journal_order(
        self,
        environment_id: str,
        account_id: str,
        journal_id: str,
        order_id: str,
        request: JournalOrderLink,
        idempotency_key: str,
    ) -> tuple[int, dict[str, Any]]:
        payload = request.model_dump(mode="json") | {"order_id": order_id}
        scope = f"journal-order-link:{journal_id}:{order_id}"
        try:
            with self.uow.bootstrap() as store:
                replay = self._idempotent_replay(
                    store, environment_id, scope, idempotency_key, payload
                )
                if replay:
                    return replay
                journal = self._journal_row(
                    store.session, environment_id, account_id, journal_id, for_update=True
                )
                existing = store.session.execute(
                    select(schema.journal_order_links).where(
                        schema.journal_order_links.c.order_id == order_id
                    )
                ).mappings().one_or_none()
                if existing is not None and existing["journal_id"] == journal_id:
                    response = _row(existing) | {
                        "journal_version": journal["version"],
                        "journal_status": journal["status"],
                    }
                    self._record_idempotency(
                        store,
                        environment_id,
                        scope,
                        idempotency_key,
                        payload,
                        200,
                        response,
                    )
                    return 200, response
                self._require_journal_version(journal, request.journal_version)
                if journal["status"] not in {"READY", "ACTIVE"}:
                    raise ApplicationError(
                        "INVALID_JOURNAL_STATE",
                        "orders can only be linked to READY or ACTIVE journals",
                        status_code=409,
                    )
                order = store.session.execute(
                    select(schema.paper_orders).where(schema.paper_orders.c.order_id == order_id)
                ).mappings().one_or_none()
                if order is None:
                    raise ApplicationError(
                        "ORDER_NOT_FOUND", "paper order was not found", status_code=404
                    )
                if order["environment_id"] != environment_id or order["account_id"] != account_id:
                    raise ApplicationError(
                        "ORDER_SCOPE_MISMATCH",
                        "order does not belong to the Journal environment and account",
                        status_code=409,
                    )
                if order["instrument_id"] != journal["instrument_id"]:
                    raise ApplicationError(
                        "INSTRUMENT_MISMATCH",
                        "order instrument does not match the Journal instrument",
                        status_code=409,
                    )
                if existing is not None:
                    raise ApplicationError(
                        "ORDER_ALREADY_LINKED",
                        "order is already linked to a Journal",
                        status_code=409,
                        details={"journal_id": existing["journal_id"]},
                    )
                sequence = int(
                    store.session.execute(
                        select(
                            func.coalesce(
                                func.max(schema.journal_order_links.c.link_sequence), 0
                            )
                        )
                        .where(schema.journal_order_links.c.journal_id == journal_id)
                    ).scalar_one()
                ) + 1
                now = self.now_ms()
                link = {
                    "journal_id": journal_id,
                    "order_id": order_id,
                    "environment_id": environment_id,
                    "account_id": account_id,
                    "linked_ts_ms": now,
                    "note": request.note,
                    "link_sequence": sequence,
                }
                store.session.execute(schema.journal_order_links.insert().values(**link))
                next_version = request.journal_version + 1
                values: dict[str, Any] = {"version": next_version, "updated_ts_ms": now}
                if journal["status"] == "READY":
                    values |= {"status": "ACTIVE", "activated_ts_ms": now}
                store.session.execute(
                    update(schema.trading_journals)
                    .where(schema.trading_journals.c.journal_id == journal_id)
                    .values(**values)
                )
                self._audit_journal(
                    store,
                    journal_id,
                    "ORDER_LINKED",
                    next_version,
                    now,
                    from_status=journal["status"],
                    to_status=values.get("status", journal["status"]),
                    reason=request.note,
                    details={"order_id": order_id},
                )
                response = _json_value(link) | {
                    "journal_version": next_version,
                    "journal_status": values.get("status", journal["status"]),
                }
                self._record_idempotency(
                    store, environment_id, scope, idempotency_key, payload, 200, response
                )
                return 200, response
        except IntegrityError as exc:
            raise ApplicationError(
                "ORDER_ALREADY_LINKED",
                "order is already linked to a Journal",
                status_code=409,
            ) from exc

    def unlink_journal_order(
        self,
        environment_id: str,
        account_id: str,
        journal_id: str,
        order_id: str,
        request: JournalOrderUnlink,
        idempotency_key: str,
    ) -> tuple[int, dict[str, Any]]:
        payload = request.model_dump(mode="json") | {"order_id": order_id}
        scope = f"journal-order-unlink:{journal_id}:{order_id}"
        with self.uow.bootstrap() as store:
            replay = self._idempotent_replay(
                store, environment_id, scope, idempotency_key, payload
            )
            if replay:
                return replay
            journal = self._journal_row(
                store.session, environment_id, account_id, journal_id, for_update=True
            )
            self._require_journal_version(journal, request.journal_version)
            link = store.session.execute(
                select(schema.journal_order_links).where(
                    schema.journal_order_links.c.journal_id == journal_id,
                    schema.journal_order_links.c.order_id == order_id,
                )
            ).mappings().one_or_none()
            if link is None:
                raise ApplicationError(
                    "JOURNAL_ORDER_LINK_NOT_FOUND",
                    "Journal order link was not found",
                    status_code=404,
                )
            now = self.now_ms()
            store.session.execute(
                delete(schema.journal_order_links).where(
                    schema.journal_order_links.c.journal_id == journal_id,
                    schema.journal_order_links.c.order_id == order_id,
                )
            )
            next_version = request.journal_version + 1
            store.session.execute(
                update(schema.trading_journals)
                .where(schema.trading_journals.c.journal_id == journal_id)
                .values(version=next_version, updated_ts_ms=now)
            )
            self._audit_journal(
                store,
                journal_id,
                "ORDER_UNLINKED",
                next_version,
                now,
                from_status=journal["status"],
                to_status=journal["status"],
                reason=request.reason,
                details={"order_id": order_id},
            )
            response = {
                "journal_id": journal_id,
                "order_id": order_id,
                "journal_version": next_version,
            }
            self._record_idempotency(
                store, environment_id, scope, idempotency_key, payload, 200, response
            )
            return 200, response

    def journal_metrics(
        self, environment_id: str, account_id: str, journal_id: str
    ) -> dict[str, Any]:
        with self.engine.connect() as connection:
            journal = self._journal_row(
                connection, environment_id, account_id, journal_id, for_update=False
            )
            return self._journal_metrics(connection, journal)

    def patch_journal(
        self,
        environment_id: str,
        account_id: str,
        journal_id: str,
        request: JournalPatch,
    ) -> dict[str, Any]:
        with self.uow.bootstrap() as store:
            row = self._journal_row(
                store.session, environment_id, account_id, journal_id, for_update=True
            )
            self._require_journal_version(row, request.version)
            changes = request.model_dump(exclude={"version", "change_reason"}, exclude_unset=True)
            if not changes:
                raise ApplicationError(
                    "INVALID_REQUEST", "no journal fields were supplied", status_code=400
                )
            now = self.now_ms()
            next_version = request.version + 1
            store.session.execute(
                update(schema.trading_journals)
                .where(schema.trading_journals.c.journal_id == journal_id)
                .values(**changes, version=next_version, updated_ts_ms=now)
            )
            self._audit_journal(
                store,
                journal_id,
                "UPDATED",
                next_version,
                now,
                reason=request.change_reason,
                details={"fields": sorted(changes)},
            )
            return self._journal_response(store.session, journal_id)

    def planner_context(
        self, environment_id: str, account_id: str, instrument_id: str
    ) -> dict[str, Any]:
        with self.uow.session_factory.begin() as session:
            session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
            return self._planner_context(session, environment_id, account_id, instrument_id)

    def preview_trade_plan(
        self, environment_id: str, account_id: str, request: TradePlannerPreview
    ) -> dict[str, Any]:
        with self.uow.session_factory.begin() as session:
            session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
            context = self._planner_context(
                session, environment_id, account_id, request.instrument_id
            )
            return self._calculate_plan(request, context) | {"context": context}

    def create_plan_revision(
        self,
        environment_id: str,
        account_id: str,
        journal_id: str,
        request: PlanRevisionCreate,
        idempotency_key: str,
    ) -> tuple[int, dict[str, Any]]:
        payload = request.model_dump(mode="json")
        scope = f"create-plan-revision:{journal_id}"
        with self.uow.bootstrap() as store:
            replay = self._idempotent_replay(
                store, environment_id, scope, idempotency_key, payload
            )
            if replay:
                return replay
            journal = self._journal_row(
                store.session, environment_id, account_id, journal_id, for_update=True
            )
            self._require_journal_version(journal, request.journal_version)
            if journal["status"] in {"CANCELLED", "REVIEWED"}:
                raise ApplicationError(
                    "INVALID_JOURNAL_STATE",
                    "journal cannot accept a plan revision",
                    status_code=409,
                )
            context = self._planner_context(
                store.session, environment_id, account_id, journal["instrument_id"]
            )
            result = self._calculate_plan(request, context)
            number = int(
                store.session.execute(
                    select(
                        func.coalesce(
                            func.max(schema.trade_plan_revisions.c.revision_number), 0
                        )
                    )
                    .where(schema.trade_plan_revisions.c.journal_id == journal_id)
                ).scalar_one()
            ) + 1
            now = self.now_ms()
            revision_id = f"planrev_{uuid4().hex}"
            revision = {
                "plan_revision_id": revision_id,
                "journal_id": journal_id,
                "revision_number": number,
                "entry_price": request.entry_price,
                "planned_position_notional": request.planned_position_notional,
                "stop_loss_price": request.stop_loss_price,
                "take_profit_price": request.take_profit_price,
                "max_position_notional": request.max_position_notional,
                "max_account_risk_rate": request.max_account_risk_rate,
                "min_reward_risk_ratio": request.min_reward_risk_ratio,
                "context_json": context,
                "calculation_json": result["calculation"],
                "validation_results_json": result["validations"],
                "validation_status": result["validation_status"],
                "calculator_version": result["calculator_version"],
                "revision_reason": request.revision_reason,
                "is_initial_confirmed": False,
                "created_ts_ms": now,
            }
            store.session.execute(schema.trade_plan_revisions.insert().values(**revision))
            next_version = request.journal_version + 1
            store.session.execute(
                update(schema.trading_journals)
                .where(schema.trading_journals.c.journal_id == journal_id)
                .values(
                    current_plan_revision_id=revision_id,
                    version=next_version,
                    updated_ts_ms=now,
                )
            )
            self._audit_journal(
                store,
                journal_id,
                "PLAN_REVISION_CREATED",
                next_version,
                now,
                reason=request.revision_reason,
                details={"plan_revision_id": revision_id, "revision_number": number},
            )
            response = _json_value(revision) | {"journal_version": next_version}
            self._record_idempotency(
                store, environment_id, scope, idempotency_key, payload, 201, response
            )
            return 201, response

    def transition_journal(
        self,
        environment_id: str,
        account_id: str,
        journal_id: str,
        target: str,
        request: JournalTransition,
        idempotency_key: str,
    ) -> tuple[int, dict[str, Any]]:
        payload = request.model_dump(mode="json")
        scope = f"journal-transition:{journal_id}:{target}"
        with self.uow.bootstrap() as store:
            replay = self._idempotent_replay(
                store, environment_id, scope, idempotency_key, payload
            )
            if replay:
                return replay
            journal = self._journal_row(
                store.session, environment_id, account_id, journal_id, for_update=True
            )
            self._require_journal_version(journal, request.version)
            allowed = {("DRAFT", "READY"), ("DRAFT", "CANCELLED"), ("READY", "CANCELLED")}
            if (journal["status"], target) not in allowed:
                raise ApplicationError(
                    "INVALID_JOURNAL_STATE",
                    "journal state transition is not allowed",
                    status_code=409,
                )
            revision = None
            if target == "READY":
                revision_id = journal["current_plan_revision_id"]
                if revision_id is None:
                    raise ApplicationError(
                        "INVALID_JOURNAL_STATE",
                        "a validated plan revision is required",
                        status_code=409,
                    )
                revision = store.session.execute(
                    select(schema.trade_plan_revisions).where(
                        schema.trade_plan_revisions.c.plan_revision_id == revision_id
                    )
                ).mappings().one()
                if revision["validation_status"] != "PASS":
                    raise ApplicationError(
                        "PLAN_VALIDATION_FAILED",
                        "plan revision has not passed validation",
                        status_code=409,
                    )
            now = self.now_ms()
            next_version = request.version + 1
            timestamp_field = "ready_ts_ms" if target == "READY" else "cancelled_ts_ms"
            confirmed_revision_id = journal["current_plan_revision_id"]
            if target == "READY" and revision is not None:
                confirmed_revision_id = f"planrev_{uuid4().hex}"
                confirmed_values = {
                    key: revision[key]
                    for key in (
                        "entry_price",
                        "planned_position_notional",
                        "stop_loss_price",
                        "take_profit_price",
                        "max_position_notional",
                        "max_account_risk_rate",
                        "min_reward_risk_ratio",
                        "context_json",
                        "calculation_json",
                        "validation_results_json",
                        "validation_status",
                        "calculator_version",
                    )
                }
                store.session.execute(
                    schema.trade_plan_revisions.insert().values(
                        **confirmed_values,
                        plan_revision_id=confirmed_revision_id,
                        journal_id=journal_id,
                        revision_number=int(revision["revision_number"]) + 1,
                        revision_reason=f"initial confirmation: {request.reason}",
                        is_initial_confirmed=True,
                        created_ts_ms=now,
                        confirmed_ts_ms=now,
                    )
                )
            store.session.execute(
                update(schema.trading_journals)
                .where(schema.trading_journals.c.journal_id == journal_id)
                .values(
                    status=target,
                    version=next_version,
                    updated_ts_ms=now,
                    current_plan_revision_id=confirmed_revision_id,
                    **{timestamp_field: now},
                )
            )
            self._audit_journal(
                store,
                journal_id,
                "STATUS_CHANGED",
                next_version,
                now,
                from_status=journal["status"],
                to_status=target,
                reason=request.reason,
                details={},
            )
            response = self._journal_response(store.session, journal_id)
            self._record_idempotency(
                store, environment_id, scope, idempotency_key, payload, 200, response
            )
            return 200, response

    def _planner_context(
        self, session: Any, environment_id: str, account_id: str, instrument_id: str
    ) -> dict[str, Any]:
        self._require_account(session, environment_id, account_id)
        rules = self.market_rules.get(instrument_id)
        if rules is None:
            raise ApplicationError(
                "MARKET_RULES_UNAVAILABLE", "market rules are not configured", status_code=503
            )
        if self.fee_schedule is None:
            raise ApplicationError(
                "FEE_SCHEDULE_UNAVAILABLE", "fee schedule is not configured", status_code=503
            )
        exchange_id, market_type, symbol = instrument_id.split(":", 2)
        if market_type != "SPOT":
            raise ApplicationError(
                "INVALID_REQUEST", "only SPOT instruments are supported", status_code=400
            )
        _, quote_asset = symbol.split("/", 1)
        balances = list(
            session.execute(
                select(schema.asset_balances)
                .where(schema.asset_balances.c.account_id == account_id)
                .order_by(schema.asset_balances.c.asset)
            ).mappings()
        )
        available_quote = Decimal(0)
        effective_equity = Decimal(0)
        unavailable_assets: list[str] = []
        valuation_quotes: list[dict[str, Any]] = []
        for balance in balances:
            total = Decimal(balance["available"]) + Decimal(balance["locked"])
            asset = balance["asset"]
            if asset == quote_asset:
                available_quote = Decimal(balance["available"])
                effective_equity += total
                continue
            if total == 0:
                continue
            valuation_instrument = f"{exchange_id}:SPOT:{asset}/{quote_asset}"
            liquidity = session.execute(
                select(schema.simulated_liquidity).where(
                    schema.simulated_liquidity.c.environment_id == environment_id,
                    schema.simulated_liquidity.c.exchange_id == exchange_id,
                    schema.simulated_liquidity.c.instrument_id == valuation_instrument,
                )
            ).mappings().one_or_none()
            if liquidity is None or not liquidity["residual_bids_json"]:
                unavailable_assets.append(asset)
                continue
            age_ms = self.now_ms() - int(liquidity["updated_ts_ms"])
            if age_ms < 0 or age_ms > self.max_market_age_ms:
                unavailable_assets.append(asset)
                continue
            bid = Decimal(liquidity["residual_bids_json"][0][0])
            effective_equity += total * bid
            valuation_quotes.append(
                {
                    "asset": asset,
                    "instrument_id": valuation_instrument,
                    "bid": str(bid),
                    "event_id": liquidity["source_book_event_id"],
                    "updated_ts_ms": int(liquidity["updated_ts_ms"]),
                }
            )
        market = session.execute(
            select(schema.simulated_liquidity).where(
                schema.simulated_liquidity.c.environment_id == environment_id,
                schema.simulated_liquidity.c.exchange_id == exchange_id,
                schema.simulated_liquidity.c.instrument_id == instrument_id,
            )
        ).mappings().one_or_none()
        market_status = "UNAVAILABLE"
        market_event_id = None
        market_updated_ts_ms = None
        if market is not None and market["residual_bids_json"] and market["residual_asks_json"]:
            age_ms = self.now_ms() - int(market["updated_ts_ms"])
            if 0 <= age_ms <= self.max_market_age_ms:
                market_status = "VALID"
                market_event_id = market["source_book_event_id"]
                market_updated_ts_ms = int(market["updated_ts_ms"])
        valuation_status = "COMPLETE" if not unavailable_assets else "INCOMPLETE"
        return {
            "environment_id": environment_id,
            "account_id": account_id,
            "instrument_id": instrument_id,
            "as_of_ts_ms": self.now_ms(),
            "quote_asset": quote_asset,
            "available_quote_balance": str(available_quote),
            "effective_account_equity": (
                str(effective_equity) if valuation_status == "COMPLETE" else None
            ),
            "valuation_status": valuation_status,
            "unavailable_assets": unavailable_assets,
            "valuation_quotes": valuation_quotes,
            "fee_schedule": self.fee_schedule_view(),
            "market_rules": self.market_rules_view(instrument_id),
            "market_status": market_status,
            "market_event_id": market_event_id,
            "market_updated_ts_ms": market_updated_ts_ms,
        }

    @staticmethod
    def _journal_metrics(session: Any, journal: Any) -> dict[str, Any]:
        links = list(
            session.execute(
                select(schema.journal_order_links.c.order_id).where(
                    schema.journal_order_links.c.journal_id == journal["journal_id"]
                )
            ).scalars()
        )
        linked_ids = set(links)
        if not linked_ids:
            return {
                "status": "AVAILABLE",
                "attribution_scope": "LINKED_SELL_FILL_REALIZED_PNL_INCREMENT",
                "linked_order_count": 0,
                "linked_execution_count": 0,
                "net_base_quantity": "0",
                "fees_by_asset": {},
                "attributed_realized_pnl_by_currency": {},
                "trade_complete": False,
                "incomplete_reasons": ["NO_LINKED_ORDERS"],
            }
        order_rows = list(
            session.execute(
                select(schema.paper_orders).where(schema.paper_orders.c.order_id.in_(linked_ids))
            ).mappings()
        )
        active_statuses = {"PENDING_EXECUTION", "OPEN", "PARTIALLY_FILLED"}
        has_active_orders = any(row["status"] in active_statuses for row in order_rows)
        executions = tuple(
            execution
            for execution in PostgresStore(session).restore_executions(journal["environment_id"])
            if execution.account_id == journal["account_id"]
        )
        portfolio = PortfolioEngine()
        fees: dict[str, Decimal] = {}
        pnl: dict[str, Decimal] = {}
        net_base = Decimal(0)
        linked_execution_count = 0
        try:
            for execution in executions:
                before = portfolio.position(
                    execution.account_id, execution.instrument_id
                ).realized_pnl
                after = portfolio.apply(execution).realized_pnl
                if execution.order_id not in linked_ids:
                    continue
                linked_execution_count += 1
                fees[execution.fee_asset] = (
                    fees.get(execution.fee_asset, Decimal(0)) + execution.fee_amount
                )
                if execution.instrument_id == journal["instrument_id"]:
                    if execution.side is OrderSide.BUY:
                        net_base += execution.quantity
                    else:
                        net_base -= execution.quantity
                        quote_asset = execution.instrument_id.rsplit("/", 1)[1]
                        pnl[quote_asset] = pnl.get(quote_asset, Decimal(0)) + after - before
        except Exception as exc:
            logger.exception("Journal metric rebuild failed for %s", journal["journal_id"])
            return {
                "status": "UNAVAILABLE",
                "reason": f"{type(exc).__name__}: {exc}",
                "attribution_scope": "LINKED_SELL_FILL_REALIZED_PNL_INCREMENT",
            }
        reasons: list[str] = []
        if linked_execution_count == 0:
            reasons.append("NO_LINKED_EXECUTIONS")
        if net_base != 0:
            reasons.append("LINKED_BASE_QUANTITY_NOT_CLOSED")
        if has_active_orders:
            reasons.append("ACTIVE_LINKED_ORDERS")
        return {
            "status": "AVAILABLE",
            "attribution_scope": "LINKED_SELL_FILL_REALIZED_PNL_INCREMENT",
            "cost_method": "ACCOUNT_MOVING_AVERAGE_FULL_HISTORY_REPLAY",
            "linked_order_count": len(linked_ids),
            "linked_execution_count": linked_execution_count,
            "net_base_quantity": str(net_base),
            "fees_by_asset": {asset: str(value) for asset, value in sorted(fees.items())},
            "attributed_realized_pnl_by_currency": {
                asset: str(value) for asset, value in sorted(pnl.items())
            },
            "trade_complete": linked_execution_count > 0 and not reasons,
            "incomplete_reasons": reasons,
        }

    @staticmethod
    def _calculate_plan(request: Any, context: dict[str, Any]) -> dict[str, Any]:
        rules = context["market_rules"]
        fee = context["fee_schedule"]
        equity = context["effective_account_equity"]
        return calculate_plan(
            entry_price=request.entry_price,
            planned_position_notional=request.planned_position_notional,
            stop_loss_price=request.stop_loss_price,
            take_profit_price=request.take_profit_price,
            effective_equity=Decimal(equity) if equity is not None else None,
            available_quote_balance=Decimal(context["available_quote_balance"]),
            fee_rate=Decimal(fee["conservative_fee_rate"]),
            price_increment=Decimal(rules["price_increment"]),
            quantity_increment=Decimal(rules["quantity_increment"]),
            min_quantity=Decimal(rules["min_quantity"]),
            min_notional=(
                Decimal(rules["min_notional"])
                if rules["min_notional"] is not None
                else None
            ),
            max_position_notional=request.max_position_notional,
            max_account_risk_rate=request.max_account_risk_rate,
            min_reward_risk_ratio=request.min_reward_risk_ratio,
            market_status=context["market_status"],
            valuation_status=context["valuation_status"],
        )

    @staticmethod
    def _require_journal_version(row: Any, expected: int) -> None:
        if int(row["version"]) != expected:
            raise ApplicationError(
                "JOURNAL_VERSION_CONFLICT",
                "journal version does not match the current version",
                status_code=409,
                details={"current_version": int(row["version"])},
            )

    @staticmethod
    def _journal_row(
        session: Any,
        environment_id: str,
        account_id: str,
        journal_id: str,
        *,
        for_update: bool,
    ) -> Any:
        statement = select(schema.trading_journals).where(
            schema.trading_journals.c.environment_id == environment_id,
            schema.trading_journals.c.account_id == account_id,
            schema.trading_journals.c.journal_id == journal_id,
        )
        if for_update:
            statement = statement.with_for_update()
        row = session.execute(statement).mappings().one_or_none()
        if row is None:
            raise ApplicationError(
                "JOURNAL_NOT_FOUND", "trading journal was not found", status_code=404
            )
        return row

    @staticmethod
    def _journal_response(session: Any, journal_id: str) -> dict[str, Any]:
        row = session.execute(
            select(schema.trading_journals).where(
                schema.trading_journals.c.journal_id == journal_id
            )
        ).mappings().one()
        return _row(row)

    @staticmethod
    def _audit_journal(
        store: Any,
        journal_id: str,
        event_type: str,
        version: int,
        timestamp: int,
        *,
        from_status: str | None = None,
        to_status: str | None = None,
        reason: str | None = None,
        details: dict[str, Any],
    ) -> None:
        store.session.execute(
            schema.journal_audit_events.insert().values(
                audit_event_id=f"jaudit_{uuid4().hex}",
                journal_id=journal_id,
                event_type=event_type,
                from_status=from_status,
                to_status=to_status,
                reason=reason,
                journal_version=version,
                details_json=details,
                created_ts_ms=timestamp,
            )
        )

    def ready(self) -> bool:
        try:
            with self.engine.connect() as connection:
                revision = connection.execute(
                    text("SELECT version_num FROM alembic_version")
                ).scalar_one_or_none()
                return revision == "0005_journal_order_links"
        except Exception:
            # Reason is logged without secrets so operators can diagnose a
            # 503 from /health/ready; the response itself stays opaque.
            logger.warning("readiness check failed", exc_info=True)
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
