"""In-memory canonical order-book state with execution-safety gates."""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal

from crypto_lab.models import (
    DataQualityStatus,
    ExchangeId,
    MarketEventEnvelope,
    OrderBookDelta,
    OrderBookSnapshot,
    PriceLevel,
)


class InvalidOrderBookStateError(ValueError):
    pass


@dataclass(frozen=True)
class OrderBookView:
    exchange_id: ExchangeId
    instrument_id: str
    bids: tuple[PriceLevel, ...]
    asks: tuple[PriceLevel, ...]
    depth: int
    sequence_id: str | None
    source_event_id: str
    exchange_ts_ms: int | None
    received_ts_ms: int
    quality_status: DataQualityStatus
    synchronized: bool
    source_connected: bool
    synchronization_generation: int = 1


class OrderBookMarketState:
    def __init__(self) -> None:
        self._books: dict[tuple[ExchangeId, str], OrderBookView] = {}

    def snapshot_state(self) -> dict[tuple[ExchangeId, str], OrderBookView]:
        return self._books.copy()

    def restore_state(self, state: dict[tuple[ExchangeId, str], OrderBookView]) -> None:
        self._books = state.copy()

    def apply_snapshot(
        self,
        event: MarketEventEnvelope[OrderBookSnapshot],
    ) -> OrderBookView:
        if event.event_type != "ORDER_BOOK_SNAPSHOT":
            raise ValueError("snapshot event requires ORDER_BOOK_SNAPSHOT type")
        payload = event.payload
        previous = self._books.get((event.exchange_id, event.instrument_id))
        view = OrderBookView(
            exchange_id=event.exchange_id,
            instrument_id=event.instrument_id,
            bids=payload.bids,
            asks=payload.asks,
            depth=payload.depth,
            sequence_id=payload.sequence_id,
            source_event_id=event.event_id,
            exchange_ts_ms=event.exchange_ts_ms,
            received_ts_ms=event.received_ts_ms,
            quality_status=event.quality_status,
            synchronized=payload.synchronized,
            source_connected=True,
            synchronization_generation=(
                previous.synchronization_generation + 1 if previous is not None else 1
            ),
        )
        self._books[(event.exchange_id, event.instrument_id)] = view
        return view

    def apply_delta(
        self,
        event: MarketEventEnvelope[OrderBookDelta],
    ) -> OrderBookView:
        if event.event_type != "ORDER_BOOK_DELTA":
            raise ValueError("delta event requires ORDER_BOOK_DELTA type")
        key = (event.exchange_id, event.instrument_id)
        current = self._books.get(key)
        if current is None:
            raise InvalidOrderBookStateError("order-book delta requires a snapshot")
        if not current.synchronized:
            raise InvalidOrderBookStateError("order book is not synchronized")

        payload = event.payload
        if (
            payload.previous_sequence_id is not None
            and current.sequence_id is not None
            and payload.previous_sequence_id != current.sequence_id
        ):
            invalid = replace(
                current,
                source_event_id=event.event_id,
                exchange_ts_ms=event.exchange_ts_ms,
                received_ts_ms=event.received_ts_ms,
                quality_status=DataQualityStatus.UNSYNCED,
                synchronized=False,
            )
            self._books[key] = invalid
            raise InvalidOrderBookStateError("order-book sequence gap detected")

        bids = _apply_updates(current.bids, payload.bid_updates, descending=True)
        asks = _apply_updates(current.asks, payload.ask_updates, descending=False)
        synchronized = event.quality_status is DataQualityStatus.VALID
        quality = event.quality_status if synchronized else DataQualityStatus.UNSYNCED
        if bids and asks and bids[0].price >= asks[0].price:
            synchronized = False
            quality = DataQualityStatus.INVALID

        view = OrderBookView(
            exchange_id=event.exchange_id,
            instrument_id=event.instrument_id,
            bids=bids[: current.depth],
            asks=asks[: current.depth],
            depth=current.depth,
            sequence_id=payload.last_sequence_id or current.sequence_id,
            source_event_id=event.event_id,
            exchange_ts_ms=event.exchange_ts_ms,
            received_ts_ms=event.received_ts_ms,
            quality_status=quality,
            synchronized=synchronized,
            source_connected=current.source_connected,
            synchronization_generation=current.synchronization_generation,
        )
        self._books[key] = view
        return view

    def mark_disconnected(self, exchange_id: ExchangeId, instrument_id: str) -> None:
        key = (exchange_id, instrument_id)
        current = self._books.get(key)
        if current is None:
            return
        self._books[key] = replace(current, source_connected=False)

    def executable_book(
        self,
        exchange_id: ExchangeId,
        instrument_id: str,
        *,
        decision_ts_ms: int,
        max_age_ms: int,
    ) -> OrderBookView:
        if decision_ts_ms < 0:
            raise ValueError("decision_ts_ms cannot be negative")
        if max_age_ms < 0:
            raise ValueError("max_age_ms cannot be negative")
        view = self._books.get((exchange_id, instrument_id))
        if view is None:
            raise InvalidOrderBookStateError("order book does not exist")
        if view.received_ts_ms > decision_ts_ms:
            raise InvalidOrderBookStateError("order book was received after decision time")
        if decision_ts_ms - view.received_ts_ms > max_age_ms:
            raise InvalidOrderBookStateError("order book is stale")
        if view.quality_status is not DataQualityStatus.VALID:
            raise InvalidOrderBookStateError("order-book quality is not valid")
        if not view.synchronized:
            raise InvalidOrderBookStateError("order book is not synchronized")
        if not view.source_connected:
            raise InvalidOrderBookStateError("order-book source is disconnected")
        if not view.bids or not view.asks:
            raise InvalidOrderBookStateError("order book requires both sides")
        return view


def _apply_updates(
    levels: tuple[PriceLevel, ...],
    updates: tuple[PriceLevel, ...],
    *,
    descending: bool,
) -> tuple[PriceLevel, ...]:
    by_price: dict[Decimal, PriceLevel] = {level.price: level for level in levels}
    for update in updates:
        if update.quantity == 0:
            by_price.pop(update.price, None)
        else:
            by_price[update.price] = update
    return tuple(sorted(by_price.values(), key=lambda level: level.price, reverse=descending))
