import pytest
from pydantic import ValidationError

from crypto_lab.models import APIProbeResult, TransportType
from scripts.probe_rest import payload_error


def valid_probe() -> APIProbeResult:
    return APIProbeResult(
        probe_id="probe-1",
        exchange_id="mock-exchange",
        endpoint_type="ticker",
        endpoint="https://example.test/ticker",
        transport=TransportType.REST,
        started_ts_ms=1_000,
        completed_ts_ms=1_025,
        duration_ms=25,
        success=True,
        status_code=200,
    )


def test_probe_serializes_schema_and_transport() -> None:
    payload = valid_probe().model_dump(mode="json")

    assert payload["schema_version"] == "1.0.0"
    assert payload["transport"] == "REST"


def test_probe_rejects_invalid_http_status() -> None:
    with pytest.raises(ValidationError):
        APIProbeResult(
            probe_id="probe-1",
            exchange_id="mock-exchange",
            endpoint_type="ticker",
            transport=TransportType.REST,
            started_ts_ms=1_000,
            success=False,
            status_code=99,
        )


@pytest.mark.parametrize(
    ("exchange_id", "payload"),
    [
        ("binance", {"code": -1121, "msg": "Invalid symbol."}),
        ("okx", {"code": "51001", "msg": "Instrument ID does not exist"}),
        ("bybit", {"retCode": 10001, "retMsg": "Request parameter error"}),
        ("kraken", {"error": ["EQuery:Unknown asset pair"]}),
        ("coinbase", {"message": "NotFound"}),
        ("bitbank", {"success": 0, "data": {"code": 10000}}),
    ],
)
def test_payload_error_detects_exchange_level_failure(
    exchange_id: str, payload: object
) -> None:
    assert payload_error(exchange_id, payload) is not None
