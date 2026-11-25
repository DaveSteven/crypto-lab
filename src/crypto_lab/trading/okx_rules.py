"""OKX public spot-instrument rules adapter."""

from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import Any

from crypto_lab.trading.constraints import MarketRules


def normalize_okx_spot_rules(
    payload: object,
    *,
    instrument: str,
    observed_ts_ms: int,
) -> MarketRules:
    message = _mapping(payload, "OKX instruments response")
    if message.get("code") != "0":
        raise ValueError("OKX instruments response is not successful")
    data = _sequence(message.get("data"), "OKX instruments data")
    matches = [
        _mapping(item, "OKX instrument")
        for item in data
        if isinstance(item, Mapping) and item.get("instId") == instrument
    ]
    if len(matches) != 1:
        raise ValueError("OKX instruments response must contain exactly one requested instrument")
    item = matches[0]
    if item.get("instType") != "SPOT":
        raise ValueError("OKX market rules require a SPOT instrument")
    if item.get("state") != "live":
        raise ValueError("OKX instrument is not in live state")
    return MarketRules(
        rules_id=f"OKX:PUBLIC_INSTRUMENTS:{instrument}:{observed_ts_ms}",
        price_increment=_positive_decimal(item.get("tickSz"), "tickSz"),
        quantity_increment=_positive_decimal(item.get("lotSz"), "lotSz"),
        min_quantity=_positive_decimal(item.get("minSz"), "minSz"),
        min_notional=None,
    )


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be an object")
    return value


def _sequence(value: object, name: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise TypeError(f"{name} must be an array")
    return value


def _positive_decimal(value: object, name: str) -> Decimal:
    if not isinstance(value, (str, int)) or isinstance(value, bool):
        raise TypeError(f"OKX {name} must be a decimal string or integer")
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"OKX {name} is not a decimal") from exc
    if result <= 0:
        raise ValueError(f"OKX {name} must be positive")
    return result
