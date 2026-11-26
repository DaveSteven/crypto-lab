"""Configuration and composition for the shared OKX market feed process.

One API process runs at most one logical feed instance regardless of how
many simulation environments or browser connections exist. Feed lifecycle
belongs to the FastAPI lifespan; startup never blocks on exchange network
access because the feed runs as a background task.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass

from crypto_lab.realtime import OKX_PUBLIC_WS_URL, OkxMarketFeed, RealtimeHubRegistry
from crypto_lab.realtime.market import MarketRealtimeBridge
from crypto_lab.trading.constraints import MarketRules

DEFAULT_INSTRUMENT = "BTC/USDT"

# OKX BTC-USDT SPOT rules documented in the official instruments endpoint
# research (docs/03-EXCHANGE-API-RESEARCH.md). Status: Documented, not
# Verified per run; refresh from OKX public instruments before production use.
DOCUMENTED_OKX_SPOT_RULES = MarketRules(
    rules_id="OKX:DOCUMENTED:SPOT:V1",
    price_increment="0.1",
    quantity_increment="0.00000001",
    min_quantity="0.00001",
    min_notional=None,
)


@dataclass(frozen=True)
class MarketFeedSettings:
    enabled: bool = True
    exchange: str = "okx"
    instruments: tuple[str, ...] = (f"okx:SPOT:{DEFAULT_INSTRUMENT}",)
    reconnect_enabled: bool = True
    candle_interval: str = "1m"
    candle_intervals: tuple[str, ...] = ("1m",)
    dispatch_interval_ms: int = 200
    max_book_age_ms: int = 5_000

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> MarketFeedSettings:
        values = os.environ if env is None else env

        def flag(name: str, default: bool) -> bool:
            raw = values.get(name)
            if raw is None or raw.strip() == "":
                return default
            return raw.strip().lower() in {"1", "true", "yes", "on"}

        enabled = flag("CRYPTO_LAB_FEED_ENABLED", True)
        exchange = (values.get("CRYPTO_LAB_FEED_EXCHANGE") or "okx").strip().lower()
        raw_instruments = (
            values.get("CRYPTO_LAB_FEED_INSTRUMENTS") or DEFAULT_INSTRUMENT
        ).strip()
        instruments = tuple(
            _canonical_instrument(exchange, item)
            for item in raw_instruments.split(",")
            if item.strip()
        )
        if not instruments:
            instruments = (f"okx:SPOT:{DEFAULT_INSTRUMENT}",)
        candle_interval = (values.get("CRYPTO_LAB_FEED_CANDLE_INTERVAL") or "1m").strip()
        raw_intervals = values.get("CRYPTO_LAB_FEED_CANDLE_INTERVALS")
        if raw_intervals is None or not raw_intervals.strip():
            candle_intervals = (candle_interval,)
        else:
            candle_intervals = tuple(
                item.strip() for item in raw_intervals.split(",") if item.strip()
            ) or (candle_interval,)
        dispatch_interval_ms = _positive_int(
            values.get("CRYPTO_LAB_FEED_DISPATCH_INTERVAL_MS"), 200
        )
        max_book_age_ms = _positive_int(values.get("CRYPTO_LAB_FEED_MAX_BOOK_AGE_MS"), 5_000)
        return cls(
            enabled=enabled,
            exchange=exchange,
            instruments=instruments,
            reconnect_enabled=flag("CRYPTO_LAB_FEED_RECONNECT_ENABLED", True),
            candle_interval=candle_interval,
            candle_intervals=candle_intervals,
            dispatch_interval_ms=dispatch_interval_ms,
            max_book_age_ms=max_book_age_ms,
        )


def _canonical_instrument(exchange: str, raw: str) -> str:
    symbol = raw.strip().upper().replace("-", "/")
    if ":" in symbol:
        return symbol
    if "/" not in symbol:
        raise ValueError(f"invalid feed instrument: {raw}")
    return f"{exchange}:SPOT:{symbol}"


def _positive_int(raw: str | None, default: int) -> int:
    if raw is None or not raw.strip():
        return default
    value = int(raw)
    if value <= 0:
        raise ValueError("feed intervals must be positive")
    return value


def build_market_feed(
    settings: MarketFeedSettings,
    registry: RealtimeHubRegistry,
    *,
    on_canonical: Callable[[object], object] | None = None,
    on_order_book_view: Callable[[object], object] | None = None,
    connection_factory: Callable[[str], object] | None = None,
) -> OkxMarketFeed:
    """Compose the shared feed with fan-out market publication to all hubs."""
    if settings.exchange != "okx":
        raise ValueError("only the okx feed exchange is supported in Phase 1")
    bridge = MarketRealtimeBridge(registry)
    broadcaster = _BroadcastingBridge(bridge, registry)
    return OkxMarketFeed(
        broadcaster,
        environment_id="shared",
        instruments=settings.instruments,
        channels=("ticker", "trade", "candle", "order_book"),
        candle_interval=settings.candle_interval,
        candle_intervals=settings.candle_intervals,
        url=OKX_PUBLIC_WS_URL,
        reconnect_delays_seconds=(1.0, 2.0, 5.0, 10.0) if settings.reconnect_enabled else (),
        on_canonical=on_canonical,  # type: ignore[arg-type]
        on_order_book_view=on_order_book_view,  # type: ignore[arg-type]
        **({"connection_factory": connection_factory} if connection_factory else {}),
    )


class _BroadcastingBridge:
    """Publish market events to every environment hub in the registry."""

    def __init__(self, bridge: MarketRealtimeBridge, registry: RealtimeHubRegistry) -> None:
        self._bridge = bridge
        self._registry = registry

    async def publish_canonical(self, environment_id: str, event: object) -> None:
        for environment in self._registry.environment_ids():
            await self._bridge.publish_canonical(environment, event)

    async def publish_order_book_view(
        self, environment_id: str, view: object, *, now_ms: int, stale_after_ms: int = 2_000
    ) -> None:
        for environment in self._registry.environment_ids():
            await self._bridge.publish_order_book_view(
                environment, view, now_ms=now_ms, stale_after_ms=stale_after_ms
            )

    async def publish_quality(
        self,
        environment_id: str,
        *,
        instrument_id: str,
        event_id: str,
        event_ts_ms: int,
        quality_status: object,
        reason: str,
    ) -> None:
        for environment in self._registry.environment_ids():
            await self._bridge.publish_quality(
                environment,
                instrument_id=instrument_id,
                event_id=event_id,
                event_ts_ms=event_ts_ms,
                quality_status=quality_status,
                reason=reason,
            )
