"""FastAPI composition root for the versioned REST contract."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import time
from collections.abc import Callable
from contextlib import asynccontextmanager
from decimal import Decimal
from typing import Annotated, Any
from uuid import uuid4

from fastapi import FastAPI, Header, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from crypto_lab.api.errors import ApplicationError
from crypto_lab.api.market_feed import (
    DOCUMENTED_OKX_SPOT_RULES,
    MarketFeedSettings,
    build_market_feed,
)
from crypto_lab.api.schemas import AccountCreate, EnvironmentCreate, OrderCreate
from crypto_lab.api.service import ApplicationService
from crypto_lab.market_data import OkxCandleClient
from crypto_lab.persistence import PersistenceError
from crypto_lab.realtime import (
    EnvironmentMarketDispatcher,
    RealtimeHubRegistry,
    RealtimePublisher,
    ReplayUnavailable,
    parse_client_message,
)
from crypto_lab.realtime.protocol import (
    PingMessage,
    PongMessage,
    SubscribeMessage,
    UnsubscribeMessage,
)
from crypto_lab.trading import FeeSchedule

IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=200)]

_LOGGER = logging.getLogger("crypto_lab.api.app")


def _environment_exists(service: Any) -> Any:
    def exists(environment_id: str) -> bool:
        try:
            service.get_environment(environment_id)
        except (ApplicationError, PersistenceError):
            return False
        return True

    return exists


def recover_environments(dispatcher: Any, service: Any, recovery_ts_ms: int) -> list[Any]:
    """Startup recovery: one baseline time for every persisted environment.

    Expires overdue PENDING_EXECUTION orders, restores the rest and registers the
    environments. Failures are isolated per environment and exposed through
    ``dispatcher.recovery_status()``.
    """
    return dispatcher.restore_environments(service.list_environment_ids(), recovery_ts_ms)


def _dispatch_canonical(dispatcher: Any) -> Any:
    async def consume(event: Any) -> None:
        await asyncio.to_thread(dispatcher.apply_trade, event)

    return consume


def _dispatch_book(dispatcher: Any) -> Any:
    async def consume(view: Any) -> None:
        await asyncio.to_thread(dispatcher.apply_order_book_view, view)

    return consume


def create_app(
    *,
    database_url: str | None = None,
    engine: Engine | None = None,
    service: Any | None = None,
    realtime: RealtimeHubRegistry | None = None,
    market_feed: Any | None = None,
    market_feed_settings: MarketFeedSettings | None = None,
    now_ms: Callable[[], int] | None = None,
) -> FastAPI:
    owns_engine = engine is None and service is None
    actual_engine = engine
    actual_realtime = realtime or RealtimeHubRegistry()
    publisher = RealtimePublisher(actual_realtime)
    feed_settings = market_feed_settings or MarketFeedSettings.from_env()
    dispatcher: EnvironmentMarketDispatcher | None = None
    actual_market_feed = market_feed
    if service is None:
        url = database_url or os.getenv("CRYPTO_LAB_DATABASE_URL")
        if actual_engine is None:
            if not url:
                raise RuntimeError("CRYPTO_LAB_DATABASE_URL is required")
            actual_engine = create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=5)
        fee_schedule = FeeSchedule(
            schedule_id="phase1-default-v1",
            maker_rate=Decimal("0.001"),
            taker_rate=Decimal("0.001"),
        )
        service = ApplicationService(
            actual_engine,
            fee_schedule=fee_schedule,
            realtime_publisher=publisher,
            candle_client=OkxCandleClient(),
            **({"now_ms": now_ms} if now_ms is not None else {}),
        )
        if feed_settings.enabled:
            dispatcher = EnvironmentMarketDispatcher(
                transaction=service.uow.transaction,
                environment_exists=_environment_exists(service),
                fee_schedule=fee_schedule,
                market_rules=DOCUMENTED_OKX_SPOT_RULES,
                instruments=feed_settings.instruments,
                now_ms=service.now_ms,
                max_book_age_ms=feed_settings.max_book_age_ms,
            )
            if actual_market_feed is None:
                actual_market_feed = build_market_feed(
                    feed_settings,
                    actual_realtime,
                    on_canonical=_dispatch_canonical(dispatcher),
                    on_order_book_view=_dispatch_book(dispatcher),
                )

    async def _dispatch_driver() -> None:
        assert dispatcher is not None
        interval = max(feed_settings.dispatch_interval_ms, 50) / 1_000
        last_retry = time.monotonic()
        while True:
            await asyncio.sleep(interval)
            await asyncio.to_thread(dispatcher.run_due)
            failed = dispatcher.recovery_status()["failed"]
            if failed and time.monotonic() - last_retry >= 5.0:
                last_retry = time.monotonic()
                # Retry isolated failures with a fresh baseline; never silent.
                await asyncio.to_thread(
                    dispatcher.restore_environments, tuple(failed), service.now_ms()
                )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        publisher.start(asyncio.get_running_loop())
        feed_task = None
        driver_task = None
        if dispatcher is not None:
            # Recovery completes before the feed or scheduler can touch any
            # environment, so start order cannot change financial outcomes.
            try:
                await asyncio.to_thread(
                    recover_environments, dispatcher, service, service.now_ms()
                )
            except Exception:
                _LOGGER.exception("startup recovery could not enumerate environments")
        if actual_market_feed is not None:
            feed_task = asyncio.create_task(actual_market_feed.run())
        if dispatcher is not None:
            driver_task = asyncio.create_task(_dispatch_driver())
        yield
        if feed_task is not None:
            await actual_market_feed.stop()
            # The feed may already have failed; its error must not break shutdown.
            with contextlib.suppress(Exception):
                await asyncio.wait_for(feed_task, timeout=5)
        if driver_task is not None:
            driver_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await driver_task
        publisher.stop()
        if owns_engine and actual_engine is not None:
            actual_engine.dispose()

    app = FastAPI(
        title="Crypto Lab Paper Trading API",
        version="1.0.0",
        description="Local-only simulated trading API. It never places real-money orders.",
        lifespan=lifespan,
    )
    app.state.service = service
    app.state.realtime = actual_realtime
    app.state.realtime_publisher = publisher
    app.state.market_feed = actual_market_feed
    app.state.market_feed_settings = feed_settings
    app.state.market_dispatcher = dispatcher

    @app.middleware("http")
    async def request_id(request: Request, call_next):
        value = request.headers.get("X-Request-ID") or uuid4().hex
        request.state.request_id = value[:128]
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    @app.exception_handler(ApplicationError)
    async def application_error(request: Request, exc: ApplicationError) -> JSONResponse:
        return _error_response(request, exc.status_code, exc.code, exc.message, exc.details)

    @app.exception_handler(PersistenceError)
    async def persistence_error(request: Request, exc: PersistenceError) -> JSONResponse:
        if "unknown simulation environment" in str(exc):
            return _error_response(
                request, 404, "ENVIRONMENT_NOT_FOUND", "simulation environment was not found"
            )
        return _error_response(request, 500, "PERSISTENCE_ERROR", "database operation failed")

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        details = {"errors": _safe_validation_errors(exc.errors())}
        return _error_response(
            request, 422, "VALIDATION_ERROR", "request validation failed", details
        )

    @app.get("/health/live")
    def live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/recovery")
    def recovery() -> dict[str, Any]:
        if dispatcher is None:
            return {"recovered": [], "failed": {}}
        return dispatcher.recovery_status()

    @app.get("/health/ready")
    def ready() -> JSONResponse:
        if service.ready():
            return JSONResponse({"status": "ready"})
        return JSONResponse({"status": "unavailable"}, status_code=503)

    @app.post("/api/v1/environments", status_code=201)
    def create_environment(body: EnvironmentCreate, key: IdempotencyKey) -> JSONResponse:
        status, result = service.create_environment(body, key)
        if status == 201:
            environment_id = result["environment_id"]
            # Register the hub and seed the environment with the current
            # valid market snapshot so it does not wait for the next delta.
            actual_realtime.hub(environment_id)
            if dispatcher is not None:
                try:
                    dispatcher.register_environment(environment_id)
                except Exception:
                    _LOGGER.exception(
                        "failed to register environment %s with market dispatcher",
                        environment_id,
                    )
        return JSONResponse(result, status_code=status)

    @app.get("/api/v1/environments/{environment_id}")
    def get_environment(environment_id: str) -> dict[str, Any]:
        return service.get_environment(environment_id)

    @app.post("/api/v1/environments/{environment_id}/accounts", status_code=201)
    def create_account(
        environment_id: str, body: AccountCreate, key: IdempotencyKey
    ) -> JSONResponse:
        status, result = service.create_account(environment_id, body, key)
        return JSONResponse(result, status_code=status)

    @app.get("/api/v1/environments/{environment_id}/accounts")
    def list_accounts(
        environment_id: str, limit: Annotated[int, Query(ge=1, le=200)] = 50
    ) -> dict[str, Any]:
        return {"items": service.list_accounts(environment_id, limit)}

    @app.get("/api/v1/environments/{environment_id}/accounts/{account_id}")
    def get_account(environment_id: str, account_id: str) -> dict[str, Any]:
        return service.get_account(environment_id, account_id)

    @app.get("/api/v1/environments/{environment_id}/accounts/{account_id}/balances")
    def balances(environment_id: str, account_id: str) -> dict[str, Any]:
        return {"items": service.balances(environment_id, account_id)}

    @app.get("/api/v1/environments/{environment_id}/accounts/{account_id}/positions")
    def positions(environment_id: str, account_id: str) -> dict[str, Any]:
        return {"items": service.positions(environment_id, account_id)}

    @app.post("/api/v1/environments/{environment_id}/orders", status_code=201)
    def create_order(
        environment_id: str, body: OrderCreate, key: IdempotencyKey
    ) -> JSONResponse:
        status, result = service.create_order(environment_id, body, key)
        return JSONResponse(result, status_code=status)

    @app.get("/api/v1/environments/{environment_id}/orders")
    def list_orders(
        environment_id: str,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        account_id: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        return {"items": service.list_orders(environment_id, limit, account_id, status)}

    @app.get("/api/v1/environments/{environment_id}/orders/{order_id}")
    def get_order(environment_id: str, order_id: str) -> dict[str, Any]:
        return service.get_order(environment_id, order_id)

    @app.post("/api/v1/environments/{environment_id}/orders/{order_id}/cancel")
    def cancel_order(environment_id: str, order_id: str, key: IdempotencyKey) -> JSONResponse:
        status, result = service.cancel_order(environment_id, order_id, key)
        return JSONResponse(result, status_code=status)

    @app.get("/api/v1/environments/{environment_id}/executions")
    def list_executions(
        environment_id: str,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        account_id: str | None = None,
        order_id: str | None = None,
    ) -> dict[str, Any]:
        return {
            "items": service.list_executions(environment_id, limit, account_id, order_id)
        }

    @app.get("/api/v1/environments/{environment_id}/executions/{execution_id}")
    def get_execution(environment_id: str, execution_id: str) -> dict[str, Any]:
        return service.get_execution(environment_id, execution_id)

    @app.get("/api/v1/environments/{environment_id}/snapshot")
    def snapshot(environment_id: str, account_id: str) -> dict[str, Any]:
        return service.snapshot(environment_id, account_id)

    @app.get("/api/v1/market/candles")
    def candle_history(
        instrument_id: str,
        interval: str,
        limit: Annotated[int, Query(ge=1, le=300)] = 100,
        before: int | None = None,
        after: int | None = None,
    ) -> dict[str, Any]:
        return service.candle_history(instrument_id, interval, limit, before, after)

    @app.websocket("/api/v1/ws/environments/{environment_id}")
    async def realtime_endpoint(websocket: WebSocket, environment_id: str) -> None:
        protocols = {
            value.strip()
            for value in websocket.headers.get("sec-websocket-protocol", "").split(",")
            if value.strip()
        }
        if "crypto-lab.v1" not in protocols or not _origin_allowed(websocket):
            await websocket.close(code=1008, reason="protocol or origin rejected")
            return
        try:
            service.get_environment(environment_id)
        except (ApplicationError, PersistenceError):
            await websocket.close(code=1008, reason="unknown environment")
            return
        hub = app.state.realtime.hub(environment_id)
        try:
            connection = hub.connect()
        except ConnectionError:
            await websocket.close(code=1013, reason="connection limit reached")
            return
        await websocket.accept(subprotocol="crypto-lab.v1")
        await websocket.send_json(
            {
                "protocol_version": "1.0.0",
                "type": "session.ready",
                "environment_id": environment_id,
                "stream_id": hub.stream_id,
                "stream_sequence": hub.stream_sequence,
            }
        )
        send_lock = asyncio.Lock()
        sender = asyncio.create_task(
            _send_realtime(websocket, connection, hub.config, send_lock)
        )
        heartbeat = asyncio.create_task(
            _heartbeat(websocket, connection, hub, send_lock)
        )
        try:
            while True:
                value = await websocket.receive_json()
                connection.last_client_message_ms = hub.clock.now_utc_ms()
                try:
                    message = parse_client_message(value)
                    if isinstance(message, SubscribeMessage):
                        for topic in message.topics:
                            if topic.account_id is not None:
                                service.get_account(environment_id, topic.account_id)
                        feed = app.state.market_feed
                        if feed is not None and hasattr(feed, "acquire_candle"):
                            for topic in message.topics:
                                if topic.name == "market.candle" and topic.interval is not None:
                                    if topic.instrument_id is None:
                                        raise ValueError(
                                            "candle interval subscription requires instrument_id"
                                        )
                                    await feed.acquire_candle(
                                        connection.connection_id,
                                        topic.instrument_id,
                                        topic.interval,
                                    )
                        hub.subscribe(connection, set(message.topics))
                        replayed = 0
                        if message.resume_from is not None:
                            replayed = await hub.replay(
                                connection,
                                stream_id=message.resume_from.stream_id,
                                after_sequence=message.resume_from.stream_sequence,
                            )
                        await _serial_send(
                            websocket,
                            send_lock,
                            {
                                "type": "subscription.ack",
                                "request_id": message.request_id,
                                "replayed": replayed,
                            }
                        )
                    elif isinstance(message, UnsubscribeMessage):
                        hub.unsubscribe(connection, set(message.topics))
                        feed = app.state.market_feed
                        if feed is not None and hasattr(feed, "release_candle"):
                            for topic in message.topics:
                                if (
                                    topic.name == "market.candle"
                                    and topic.interval is not None
                                    and topic.instrument_id is not None
                                ):
                                    feed.release_candle(
                                        connection.connection_id,
                                        topic.instrument_id,
                                        topic.interval,
                                    )
                        await _serial_send(
                            websocket,
                            send_lock,
                            {"type": "subscription.ack", "request_id": message.request_id}
                        )
                    elif isinstance(message, PingMessage):
                        await _serial_send(
                            websocket,
                            send_lock,
                            {"type": "pong", "request_id": message.request_id}
                        )
                    elif isinstance(message, PongMessage):
                        pass
                except ReplayUnavailable as exc:
                    await _serial_send(
                        websocket,
                        send_lock,
                        {"type": "resync.required", "reason": str(exc)}
                    )
                except (ApplicationError, ValueError) as exc:
                    await _serial_send(
                        websocket,
                        send_lock,
                        {
                            "type": "error",
                            "code": getattr(exc, "code", "INVALID_CONTROL_MESSAGE"),
                            "message": str(exc),
                        }
                    )
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            sender.cancel()
            heartbeat.cancel()
            feed = app.state.market_feed
            if feed is not None and hasattr(feed, "release_owner"):
                feed.release_owner(connection.connection_id)
            await hub.disconnect(connection)

    app.state.websocket_path = "/api/v1/ws/environments/{environment_id}"

    return app


async def _send_realtime(
    websocket: WebSocket, connection: Any, config: Any, send_lock: asyncio.Lock
) -> None:
    try:
        while True:
            if connection.requires_resync:
                try:
                    await asyncio.wait_for(
                        _serial_send(
                            websocket,
                            send_lock,
                            {"type": "resync.required", "reason": "slow consumer"},
                        ),
                        timeout=config.send_timeout_ms / 1_000,
                    )
                finally:
                    await websocket.close(code=1013, reason="slow consumer")
                return
            event = await connection.buffer.get()
            await asyncio.wait_for(
                _serial_send(websocket, send_lock, connection.deliver(event)),
                timeout=config.send_timeout_ms / 1_000,
            )
    except (asyncio.CancelledError, WebSocketDisconnect, RuntimeError, TimeoutError):
        return


async def _serial_send(
    websocket: WebSocket, send_lock: asyncio.Lock, value: dict[str, Any]
) -> None:
    async with send_lock:
        await websocket.send_json(value)


async def _heartbeat(
    websocket: WebSocket, connection: Any, hub: Any, send_lock: asyncio.Lock
) -> None:
    try:
        while True:
            await asyncio.sleep(hub.config.heartbeat_interval_ms / 1_000)
            now_ms = hub.clock.now_utc_ms()
            if _client_timed_out(
                now_ms, connection.last_client_message_ms, hub.config.client_timeout_ms
            ):
                await websocket.close(code=1008, reason="client heartbeat timeout")
                return
            await asyncio.wait_for(
                _serial_send(
                    websocket,
                    send_lock,
                    {"type": "heartbeat", "heartbeat_id": f"heartbeat-{now_ms}"},
                ),
                timeout=hub.config.send_timeout_ms / 1_000,
            )
    except (asyncio.CancelledError, WebSocketDisconnect, RuntimeError, TimeoutError):
        return


def _client_timed_out(now_ms: int, last_message_ms: int, timeout_ms: int) -> bool:
    return now_ms - last_message_ms >= timeout_ms


def _origin_allowed(websocket: WebSocket) -> bool:
    origin = websocket.headers.get("origin")
    if origin is None:
        return True
    return origin.startswith(("http://127.0.0.1", "http://localhost"))


def _error_response(
    request: Request,
    status: int,
    code: str,
    message: str,
    details: dict[str, object] | None = None,
) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "unknown")
    return JSONResponse(
        {
            "error": {
                "code": code,
                "message": message,
                "details": details or {},
                "request_id": request_id,
            }
        },
        status_code=status,
        headers={"X-Request-ID": request_id},
    )


def _safe_validation_errors(errors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {key: value for key, value in error.items() if key not in {"input", "ctx"}}
        for error in errors
    ]
