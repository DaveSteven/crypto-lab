"""Simulation-scoped residual order-book liquidity."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from crypto_lab.market_data import OrderBookView
from crypto_lab.models import PriceLevel
from crypto_lab.trading.matching import MatchPlan
from crypto_lab.trading.orders import OrderSide


class LiquidityError(ValueError):
    pass


class SimulatedLiquidityView:
    def __init__(self, simulation_environment_id: str) -> None:
        if not simulation_environment_id:
            raise ValueError("simulation environment ID is required")
        self.simulation_environment_id = simulation_environment_id
        self._market_book: OrderBookView | None = None
        self._residual_bids: dict[Decimal, Decimal] = {}
        self._residual_asks: dict[Decimal, Decimal] = {}
        self._consumption_ids: set[str] = set()

    def synchronize(self, market_book: OrderBookView) -> OrderBookView:
        current = self._market_book
        if current is None:
            self._market_book = market_book
            self._residual_bids = _quantities(market_book.bids)
            self._residual_asks = _quantities(market_book.asks)
            return self.available_book()
        if (
            current.exchange_id != market_book.exchange_id
            or current.instrument_id != market_book.instrument_id
        ):
            raise LiquidityError("liquidity view cannot change market identity")
        if current.synchronization_generation != market_book.synchronization_generation:
            raise LiquidityError(
                "new synchronization generation requires an explicit liquidity reset"
            )
        if current.source_event_id == market_book.source_event_id:
            return self.available_book()

        self._residual_bids = _update_residual(
            current.bids,
            market_book.bids,
            self._residual_bids,
        )
        self._residual_asks = _update_residual(
            current.asks,
            market_book.asks,
            self._residual_asks,
        )
        self._market_book = market_book
        return self.available_book()

    def reset_for_resynchronized_book(self, market_book: OrderBookView) -> OrderBookView:
        current = self._market_book
        if current is not None and (
            current.exchange_id != market_book.exchange_id
            or current.instrument_id != market_book.instrument_id
        ):
            raise LiquidityError("liquidity view cannot change market identity")
        if current is not None and (
            market_book.synchronization_generation <= current.synchronization_generation
        ):
            raise LiquidityError("liquidity reset requires a newer synchronization generation")
        self._market_book = market_book
        self._residual_bids = _quantities(market_book.bids)
        self._residual_asks = _quantities(market_book.asks)
        return self.available_book()

    def available_book(self) -> OrderBookView:
        if self._market_book is None:
            raise LiquidityError("liquidity view has not been initialized")
        return replace(
            self._market_book,
            bids=_levels(self._residual_bids, descending=True),
            asks=_levels(self._residual_asks, descending=False),
        )

    def consume(self, plan: MatchPlan, *, consumption_id: str) -> None:
        candidate = self._validated_candidate(plan, consumption_id=consumption_id)
        if plan.side is OrderSide.BUY:
            self._residual_asks = candidate
        else:
            self._residual_bids = candidate
        self._consumption_ids.add(consumption_id)

    def validate_consumption(self, plan: MatchPlan, *, consumption_id: str) -> None:
        self._validated_candidate(plan, consumption_id=consumption_id)

    def _validated_candidate(
        self,
        plan: MatchPlan,
        *,
        consumption_id: str,
    ) -> dict[Decimal, Decimal]:
        if not consumption_id:
            raise ValueError("consumption ID is required")
        if consumption_id in self._consumption_ids:
            raise LiquidityError("duplicate liquidity consumption ID")
        if self._market_book is None:
            raise LiquidityError("liquidity view has not been initialized")
        if plan.book_event_id != self._market_book.source_event_id:
            raise LiquidityError("match plan uses a different order-book event")

        residual = self._residual_asks if plan.side is OrderSide.BUY else self._residual_bids
        candidate = residual.copy()
        for fill in plan.fills:
            available = candidate.get(fill.price, Decimal(0))
            if fill.quantity > available:
                raise LiquidityError("match plan exceeds residual liquidity")
            remaining = available - fill.quantity
            if remaining == 0:
                candidate.pop(fill.price, None)
            else:
                candidate[fill.price] = remaining
        return candidate


def _quantities(levels: tuple[PriceLevel, ...]) -> dict[Decimal, Decimal]:
    return {level.price: level.quantity for level in levels}


def _levels(values: dict[Decimal, Decimal], *, descending: bool) -> tuple[PriceLevel, ...]:
    return tuple(
        PriceLevel(price=price, quantity=quantity)
        for price, quantity in sorted(values.items(), reverse=descending)
        if quantity > 0
    )


def _update_residual(
    old_levels: tuple[PriceLevel, ...],
    new_levels: tuple[PriceLevel, ...],
    residual: dict[Decimal, Decimal],
) -> dict[Decimal, Decimal]:
    old = _quantities(old_levels)
    new = _quantities(new_levels)
    updated: dict[Decimal, Decimal] = {}
    for price, new_quantity in new.items():
        old_quantity = old.get(price, Decimal(0))
        remaining = max(Decimal(0), residual.get(price, Decimal(0)) + new_quantity - old_quantity)
        if remaining > 0:
            updated[price] = remaining
    return updated
