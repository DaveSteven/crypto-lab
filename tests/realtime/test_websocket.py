import asyncio

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from crypto_lab.api import create_app
from crypto_lab.api.app import _client_timed_out
from crypto_lab.api.errors import ApplicationError
from crypto_lab.realtime import RealtimeEvent, RealtimeHubRegistry


class RealtimeStubService:
    def ready(self):
        return True

    def get_environment(self, environment_id):
        if environment_id == "missing":
            raise ApplicationError("ENVIRONMENT_NOT_FOUND", "missing", status_code=404)
        return {"environment_id": environment_id}

    def get_account(self, environment_id, account_id):
        if account_id == "other":
            raise ApplicationError("ACCOUNT_NOT_FOUND", "missing", status_code=404)
        return {"environment_id": environment_id, "account_id": account_id}


def app_and_registry():
    registry = RealtimeHubRegistry()
    return create_app(service=RealtimeStubService(), realtime=registry), registry


def test_heartbeat_timeout_uses_controllable_timestamps() -> None:
    assert not _client_timed_out(44_999, 0, 45_000)
    assert _client_timed_out(45_000, 0, 45_000)


def test_websocket_requires_protocol_and_valid_environment() -> None:
    app, _ = app_and_registry()
    client = TestClient(app)
    with (
        pytest.raises(WebSocketDisconnect) as error,
        client.websocket_connect("/api/v1/ws/environments/env-1"),
    ):
        pass
    assert error.value.code == 1008

    with (
        pytest.raises(WebSocketDisconnect) as error,
        client.websocket_connect(
            "/api/v1/ws/environments/missing", subprotocols=["crypto-lab.v1"]
        ),
    ):
        pass
    assert error.value.code == 1008


def test_subscribe_ping_validation_and_disconnect_cleanup() -> None:
    app, registry = app_and_registry()
    client = TestClient(app)
    with client.websocket_connect(
        "/api/v1/ws/environments/env-1", subprotocols=["crypto-lab.v1"]
    ) as websocket:
        ready = websocket.receive_json()
        assert ready["type"] == "session.ready"
        assert websocket.accepted_subprotocol == "crypto-lab.v1"
        websocket.send_json(
            {
                "type": "subscribe",
                "request_id": "subscribe-1",
                "topics": [{"name": "orders", "account_id": "account-1"}],
            }
        )
        assert websocket.receive_json() == {
            "type": "subscription.ack",
            "request_id": "subscribe-1",
            "replayed": 0,
        }
        websocket.send_json({"type": "ping", "request_id": "ping-1"})
        assert websocket.receive_json() == {"type": "pong", "request_id": "ping-1"}
        websocket.send_json({"type": "unknown"})
        assert websocket.receive_json()["code"] == "INVALID_CONTROL_MESSAGE"
    assert registry.hub("env-1").stats()["connections"] == 0


def test_replay_uses_subscription_filter_and_delivery_sequence() -> None:
    app, registry = app_and_registry()
    hub = registry.hub("env-1")

    async def seed():
        await hub.publish(
            RealtimeEvent(
                topic="orders",
                event_id="account-1-order",
                event_ts_ms=1,
                payload={"status": "OPEN"},
                account_id="account-1",
            )
        )
        await hub.publish(
            RealtimeEvent(
                topic="orders",
                event_id="account-2-order",
                event_ts_ms=2,
                payload={"status": "OPEN"},
                account_id="account-2",
            )
        )

    asyncio.run(seed())
    client = TestClient(app)
    with client.websocket_connect(
        "/api/v1/ws/environments/env-1", subprotocols=["crypto-lab.v1"]
    ) as websocket:
        ready = websocket.receive_json()
        websocket.send_json(
            {
                "type": "subscribe",
                "request_id": "resume-1",
                "topics": [{"name": "orders", "account_id": "account-1"}],
                "resume_from": {
                    "stream_id": ready["stream_id"],
                    "stream_sequence": 0,
                },
            }
        )
        first = websocket.receive_json()
        second = websocket.receive_json()
        messages = {first["type"]: first, second["type"]: second}
        assert messages["subscription.ack"]["replayed"] == 1
        assert messages["orders"]["event_id"] == "account-1-order"
        assert messages["orders"]["delivery_sequence"] == 1


def test_old_stream_requests_resync_without_closing_connection() -> None:
    app, _ = app_and_registry()
    client = TestClient(app)
    with client.websocket_connect(
        "/api/v1/ws/environments/env-1", subprotocols=["crypto-lab.v1"]
    ) as websocket:
        websocket.receive_json()
        websocket.send_json(
            {
                "type": "subscribe",
                "request_id": "resume-old",
                "topics": [{"name": "orders"}],
                "resume_from": {"stream_id": "old", "stream_sequence": 0},
            }
        )
        assert websocket.receive_json()["type"] == "resync.required"
        websocket.send_json({"type": "ping", "request_id": "still-open"})
        assert websocket.receive_json()["type"] == "pong"
