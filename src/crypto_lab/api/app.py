"""FastAPI composition root for the versioned REST contract."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from decimal import Decimal
from typing import Annotated, Any
from uuid import uuid4

from fastapi import FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from crypto_lab.api.errors import ApplicationError
from crypto_lab.api.schemas import AccountCreate, EnvironmentCreate, OrderCreate
from crypto_lab.api.service import ApplicationService
from crypto_lab.persistence import PersistenceError
from crypto_lab.trading import FeeSchedule

IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=200)]


def create_app(
    *,
    database_url: str | None = None,
    engine: Engine | None = None,
    service: Any | None = None,
) -> FastAPI:
    owns_engine = engine is None and service is None
    actual_engine = engine
    if service is None:
        url = database_url or os.getenv("CRYPTO_LAB_DATABASE_URL")
        if actual_engine is None:
            if not url:
                raise RuntimeError("CRYPTO_LAB_DATABASE_URL is required")
            actual_engine = create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=5)
        service = ApplicationService(
            actual_engine,
            fee_schedule=FeeSchedule(
                schedule_id="phase1-default-v1",
                maker_rate=Decimal("0.001"),
                taker_rate=Decimal("0.001"),
            ),
        )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        if owns_engine and actual_engine is not None:
            actual_engine.dispose()

    app = FastAPI(
        title="Crypto Lab Paper Trading API",
        version="1.0.0",
        description="Local-only simulated trading API. It never places real-money orders.",
        lifespan=lifespan,
    )
    app.state.service = service

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

    @app.get("/health/ready")
    def ready() -> JSONResponse:
        if service.ready():
            return JSONResponse({"status": "ready"})
        return JSONResponse({"status": "unavailable"}, status_code=503)

    @app.post("/api/v1/environments", status_code=201)
    def create_environment(body: EnvironmentCreate, key: IdempotencyKey) -> JSONResponse:
        status, result = service.create_environment(body, key)
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

    return app


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
