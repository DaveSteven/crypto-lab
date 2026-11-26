"""Average-cost positions and conservative mark-to-market valuation."""

from __future__ import annotations

from decimal import Decimal

from pydantic import Field, model_validator

from crypto_lab.models import DataQualityStatus, MarketEventEnvelope, Ticker
from crypto_lab.trading.execution import ExecutionRecord
from crypto_lab.trading.models import FrozenModel
from crypto_lab.trading.order_service import split_instrument
from crypto_lab.trading.orders import OrderSide


class Position(FrozenModel):
    account_id: str = Field(min_length=1)
    instrument_id: str = Field(min_length=1)
    base_asset: str = Field(min_length=1)
    quote_asset: str = Field(min_length=1)
    quantity: Decimal = Field(ge=0)
    cost_basis: Decimal = Field(ge=0)
    average_cost: Decimal | None = Field(default=None, gt=0)
    realized_pnl: Decimal = Decimal(0)
    cumulative_fees: Decimal = Field(default=Decimal(0), ge=0)
    updated_ts_ms: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_cost_state(self) -> Position:
        if self.quantity == 0 and (self.cost_basis != 0 or self.average_cost is not None):
            raise ValueError("closed position must have zero cost basis and no average cost")
        if self.quantity > 0:
            if self.cost_basis <= 0 or self.average_cost is None:
                raise ValueError("open position requires positive cost basis and average cost")
            if self.average_cost != self.cost_basis / self.quantity:
                raise ValueError("average cost must equal cost basis divided by quantity")
        return self


class PositionValuation(FrozenModel):
    account_id: str = Field(min_length=1)
    instrument_id: str = Field(min_length=1)
    quantity: Decimal = Field(ge=0)
    mark_price: Decimal = Field(gt=0)
    price_basis: str = "BID"
    price_event_id: str = Field(min_length=1)
    price_received_ts_ms: int = Field(ge=0)
    market_value: Decimal = Field(ge=0)
    cost_basis: Decimal = Field(ge=0)
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    total_pnl: Decimal


class InsufficientPositionError(ValueError):
    pass


class PortfolioEngine:
    def __init__(self, executions: tuple[ExecutionRecord, ...] = ()) -> None:
        self._positions: dict[tuple[str, str], Position] = {}
        self._execution_ids: set[str] = set()
        for execution in executions:
            self.apply(execution)

    def position(self, account_id: str, instrument_id: str) -> Position:
        key = (account_id, instrument_id)
        existing = self._positions.get(key)
        if existing is not None:
            return existing
        _, base_asset, quote_asset = split_instrument(instrument_id)
        return Position(
            account_id=account_id,
            instrument_id=instrument_id,
            base_asset=base_asset,
            quote_asset=quote_asset,
            quantity=Decimal(0),
            cost_basis=Decimal(0),
            realized_pnl=Decimal(0),
            cumulative_fees=Decimal(0),
            updated_ts_ms=0,
        )

    def positions(self) -> tuple[Position, ...]:
        return tuple(self._positions[key] for key in sorted(self._positions))

    def snapshot_state(self) -> tuple[dict[tuple[str, str], Position], set[str]]:
        return (self._positions.copy(), self._execution_ids.copy())

    def restore_state(
        self,
        state: tuple[dict[tuple[str, str], Position], set[str]],
    ) -> None:
        positions, execution_ids = state
        self._positions = positions.copy()
        self._execution_ids = execution_ids.copy()

    def rebuild(self, executions: tuple[ExecutionRecord, ...]) -> None:
        rebuilt = PortfolioEngine(executions)
        self._positions = rebuilt._positions
        self._execution_ids = rebuilt._execution_ids

    def apply(self, execution: ExecutionRecord) -> Position:
        if execution.execution_id in self._execution_ids:
            raise ValueError(f"duplicate execution ID: {execution.execution_id}")
        _, base_asset, quote_asset = split_instrument(execution.instrument_id)
        if execution.fee_asset != quote_asset:
            raise ValueError("portfolio currently supports quote-asset fees only")
        current = self.position(execution.account_id, execution.instrument_id)
        if execution.executed_ts_ms < current.updated_ts_ms:
            raise ValueError("execution is older than the current position state")

        if execution.side is OrderSide.BUY:
            new_quantity = current.quantity + execution.quantity
            new_cost_basis = current.cost_basis + execution.quote_amount + execution.fee_amount
            new_realized_pnl = current.realized_pnl
        else:
            if execution.quantity > current.quantity:
                raise InsufficientPositionError("sell execution exceeds position quantity")
            assert current.average_cost is not None
            relieved_cost = current.average_cost * execution.quantity
            new_quantity = current.quantity - execution.quantity
            new_cost_basis = current.cost_basis - relieved_cost
            new_realized_pnl = (
                current.realized_pnl + execution.quote_amount - execution.fee_amount - relieved_cost
            )
            if new_quantity == 0:
                new_cost_basis = Decimal(0)

        updated = Position(
            account_id=execution.account_id,
            instrument_id=execution.instrument_id,
            base_asset=base_asset,
            quote_asset=quote_asset,
            quantity=new_quantity,
            cost_basis=new_cost_basis,
            average_cost=(new_cost_basis / new_quantity if new_quantity else None),
            realized_pnl=new_realized_pnl,
            cumulative_fees=current.cumulative_fees + execution.fee_amount,
            updated_ts_ms=execution.executed_ts_ms,
        )
        self._positions[(execution.account_id, execution.instrument_id)] = updated
        self._execution_ids.add(execution.execution_id)
        return updated

    def value(
        self,
        account_id: str,
        instrument_id: str,
        ticker_event: MarketEventEnvelope[Ticker],
    ) -> PositionValuation:
        position = self.position(account_id, instrument_id)
        if ticker_event.instrument_id != instrument_id:
            raise ValueError("ticker instrument does not match position instrument")
        if ticker_event.quality_status is not DataQualityStatus.VALID:
            raise ValueError("ticker is not valid for valuation")
        if ticker_event.payload.bid is None:
            raise ValueError("position valuation requires Bid")

        mark_price = ticker_event.payload.bid
        market_value = position.quantity * mark_price
        unrealized_pnl = market_value - position.cost_basis
        return PositionValuation(
            account_id=account_id,
            instrument_id=instrument_id,
            quantity=position.quantity,
            mark_price=mark_price,
            price_event_id=ticker_event.event_id,
            price_received_ts_ms=ticker_event.received_ts_ms,
            market_value=market_value,
            cost_basis=position.cost_basis,
            realized_pnl=position.realized_pnl,
            unrealized_pnl=unrealized_pnl,
            total_pnl=position.realized_pnl + unrealized_pnl,
        )


def realized_pnl_summary(
    executions: tuple[ExecutionRecord, ...], account_id: str
) -> dict[str, object]:
    """Cumulative realized PnL rebuilt from the account's full Fill History.

    Derived, never persisted: it replays the same moving-average-cost engine that
    backs the positions projection, so fully closed positions (which leave the
    projection) still contribute and no second authority for PnL exists. Amounts
    are summed only within one settlement currency; different currencies are never
    added together. Fees follow the engine's existing semantics (buy fees are part
    of cost basis, sell fees reduce realized PnL, each fill's fee counted once).
    """
    portfolio = PortfolioEngine(tuple(e for e in executions if e.account_id == account_id))
    instruments = [
        {
            "instrument_id": position.instrument_id,
            "base_asset": position.base_asset,
            "quote_asset": position.quote_asset,
            "quantity": position.quantity,
            "realized_pnl": position.realized_pnl,
            "cumulative_fees": position.cumulative_fees,
        }
        for position in portfolio.positions()
    ]
    realized: dict[str, Decimal] = {}
    fees: dict[str, Decimal] = {}
    for item in instruments:
        currency = str(item["quote_asset"])
        realized[currency] = realized.get(currency, Decimal(0)) + item["realized_pnl"]  # type: ignore[operator]
        fees[currency] = fees.get(currency, Decimal(0)) + item["cumulative_fees"]  # type: ignore[operator]
    return {
        "account_id": account_id,
        "cumulative_realized_pnl_by_currency": dict(sorted(realized.items())),
        "cumulative_fees_by_currency": dict(sorted(fees.items())),
        "instruments": instruments,
    }
