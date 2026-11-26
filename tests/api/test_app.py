from fastapi.testclient import TestClient

from crypto_lab.api import create_app
from crypto_lab.api.errors import ApplicationError


class StubService:
    def ready(self):
        return True

    def create_environment(self, body, key):
        return 201, {
            "environment_id": "env-1",
            "name": body.name,
            "status": "ACTIVE",
            "created_ts_ms": 1000,
            "updated_ts_ms": 1000,
        }

    def get_environment(self, environment_id):
        if environment_id == "missing":
            raise ApplicationError(
                "ENVIRONMENT_NOT_FOUND", "not found", status_code=404
            )
        return {"environment_id": environment_id}

    def create_order(self, environment_id, body, key):
        return 201, {
            "environment_id": environment_id,
            "order_id": "order-1",
            "quantity": str(body.quantity),
            "status": "PENDING_EXECUTION",
        }


client = TestClient(create_app(service=StubService()))


def test_health_and_openapi_publish_versioned_contract() -> None:
    assert client.get("/health/live").json() == {"status": "ok"}
    assert client.get("/health/ready").status_code == 200
    paths = client.get("/openapi.json").json()["paths"]
    assert "/api/v1/environments" in paths
    assert "/api/v1/environments/{environment_id}/orders/{order_id}/cancel" in paths
    assert not any(path.startswith("/ws") for path in paths)


def test_write_requires_idempotency_key_and_rejects_unknown_fields() -> None:
    response = client.post("/api/v1/environments", json={"name": "demo"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"

    response = client.post(
        "/api/v1/environments",
        headers={"Idempotency-Key": "key-1"},
        json={"name": "demo", "unknown": True},
    )
    assert response.status_code == 422


def test_decimal_values_must_be_strings_and_market_buy_requires_budget() -> None:
    base = {
        "account_id": "account-1",
        "instrument_id": "okx:SPOT:BTC/USDT",
        "side": "BUY",
        "order_type": "MARKET",
        "quantity": 1,
    }
    response = client.post(
        "/api/v1/environments/env-1/orders",
        headers={"Idempotency-Key": "key-1"},
        json=base,
    )
    assert response.status_code == 422

    base["quantity"] = "1"
    response = client.post(
        "/api/v1/environments/env-1/orders",
        headers={"Idempotency-Key": "key-2"},
        json=base,
    )
    assert response.status_code == 422


def test_decimal_response_is_string_and_request_id_is_propagated() -> None:
    response = client.post(
        "/api/v1/environments/env-1/orders",
        headers={"Idempotency-Key": "key-3", "X-Request-ID": "request-123"},
        json={
            "account_id": "account-1",
            "instrument_id": "okx:SPOT:BTC/USDT",
            "side": "BUY",
            "order_type": "LIMIT",
            "quantity": "0.25",
            "limit_price": "100.50",
        },
    )
    assert response.status_code == 201
    assert response.json()["quantity"] == "0.25"
    assert response.headers["X-Request-ID"] == "request-123"


def test_application_errors_use_stable_envelope() -> None:
    response = client.get("/api/v1/environments/missing")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ENVIRONMENT_NOT_FOUND"
    assert response.json()["error"]["request_id"] == response.headers["X-Request-ID"]


def test_list_limit_is_bounded_before_service_call() -> None:
    response = client.get("/api/v1/environments/env-1/accounts?limit=201")
    assert response.status_code == 422
