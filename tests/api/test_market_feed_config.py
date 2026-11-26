import asyncio

from crypto_lab.api.market_feed import MarketFeedSettings, build_market_feed
from crypto_lab.realtime import MarketRealtimeBridge, RealtimeHubRegistry, Subscription


def test_settings_default_to_enabled_okx_btc_usdt() -> None:
    settings = MarketFeedSettings.from_env({})
    assert settings.enabled is True
    assert settings.exchange == "okx"
    assert settings.instruments == ("okx:SPOT:BTC/USDT",)
    assert settings.reconnect_enabled is True
    assert settings.dispatch_interval_ms == 200


def test_settings_parse_env_overrides() -> None:
    settings = MarketFeedSettings.from_env(
        {
            "CRYPTO_LAB_FEED_ENABLED": "false",
            "CRYPTO_LAB_FEED_EXCHANGE": "okx",
            "CRYPTO_LAB_FEED_INSTRUMENTS": "BTC/USDT, ETH/USDT",
            "CRYPTO_LAB_FEED_RECONNECT_ENABLED": "0",
            "CRYPTO_LAB_FEED_CANDLE_INTERVAL": "5m",
            "CRYPTO_LAB_FEED_DISPATCH_INTERVAL_MS": "500",
        }
    )
    assert settings.enabled is False
    assert settings.instruments == ("okx:SPOT:BTC/USDT", "okx:SPOT:ETH/USDT")
    assert settings.reconnect_enabled is False
    assert settings.candle_interval == "5m"
    assert settings.dispatch_interval_ms == 500


def test_settings_reject_invalid_interval() -> None:
    try:
        MarketFeedSettings.from_env({"CRYPTO_LAB_FEED_DISPATCH_INTERVAL_MS": "0"})
    except ValueError:
        pass
    else:
        raise AssertionError("zero dispatch interval must be rejected")


def test_broadcast_bridge_fans_out_to_every_environment_hub() -> None:
    async def scenario():
        registry = RealtimeHubRegistry()
        connections = []
        for environment_id in ("env-a", "env-b"):
            hub = registry.hub(environment_id)
            connection = hub.connect()
            hub.subscribe(connection, {Subscription(name="market.ticker")})
            connections.append(connection)
        settings = MarketFeedSettings.from_env({})
        feed = build_market_feed(settings, registry, connection_factory=_blocked_factory)
        await feed.bridge.publish_canonical("ignored", _ticker_event())
        for connection in connections:
            queued = connection.buffer.snapshot()
            assert [event.type for event in queued] == ["market.ticker"]
            assert queued[0].environment_id in {"env-a", "env-b"}

    asyncio.run(scenario())


async def _blocked_factory(url: str):
    raise OSError("no network in tests")


def _ticker_event():
    from crypto_lab.models import (
        DataQualityStatus,
        DataSourceType,
        ExchangeId,
        MarketEventEnvelope,
        Ticker,
        TransportType,
    )

    return MarketEventEnvelope[Ticker](
        event_id="evt-1",
        event_type="TICKER",
        exchange_id=ExchangeId.OKX,
        instrument_id="okx:SPOT:BTC/USDT",
        source_type=DataSourceType.LIVE,
        transport=TransportType.WEBSOCKET,
        exchange_ts_ms=1_000,
        received_ts_ms=1_000,
        quality_status=DataQualityStatus.VALID,
        payload=Ticker(bid="100", ask="101"),
    )


def test_build_market_feed_rejects_unsupported_exchange() -> None:
    settings = MarketFeedSettings(exchange="binance")
    try:
        build_market_feed(settings, RealtimeHubRegistry())
    except ValueError as exc:
        assert "okx" in str(exc)
    else:
        raise AssertionError("non-okx exchange must be rejected")


def test_bridge_import_surface_unchanged() -> None:
    # MarketRealtimeBridge remains importable for existing consumers.
    assert MarketRealtimeBridge is not None
