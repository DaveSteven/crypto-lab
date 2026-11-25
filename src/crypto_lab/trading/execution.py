"""Deterministic spot execution simulator for paper orders."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from uuid import uuid4

from pydantic import Field, model_validator

from crypto_lab.models import DataQualityStatus, MarketEventEnvelope, Ticker
from crypto_lab.trading.constraints import MarketRules
from crypto_lab.trading.ledger import InsufficientBalanceError
from crypto_lab.trading.liquidity import SimulatedLiquidityView
from crypto_lab.trading.matching import MatchPlan, MatchStatus
from crypto_lab.trading.models import FrozenModel, LedgerEntry, LedgerReason, utc_now_ms
from crypto_lab.trading.order_service import OrderService, split_instrument
from crypto_lab.trading.orders import OrderSide, OrderStatus, OrderType, PaperOrder


class LiquidityRole(StrEnum):
    MAKER = "MAKER"
    TAKER = "TAKER"


class ExecutionRecord(FrozenModel):
    execution_id: str = Field(min_length=1)
    order_id: str = Field(min_length=1)
    account_id: str = Field(min_length=1)
    instrument_id: str = Field(min_length=1)
    side: OrderSide
    price: Decimal = Field(gt=0)
    quantity: Decimal = Field(gt=0)
    quote_amount: Decimal = Field(gt=0)
    fee_asset: str = Field(min_length=1)
    fee_amount: Decimal = Field(ge=0)
    executed_ts_ms: int = Field(ge=0)
    liquidity_role: LiquidityRole = LiquidityRole.TAKER
    market_event_id: str | None = Field(default=None, min_length=1)


class ExecutionAttempt(FrozenModel):
    success: bool
    execution: ExecutionRecord | None = None
    error_type: str | None = None
    error_message: str | None = None

    @model_validator(mode="after")
    def validate_result(self) -> ExecutionAttempt:
        if self.success != (self.execution is not None):
            raise ValueError("success must match execution presence")
        if self.success and (self.error_type is not None or self.error_message is not None):
            raise ValueError("successful execution cannot contain an error")
        if not self.success and not self.error_type:
            raise ValueError("failed execution requires an error type")
        return self


class ExecutionSimulator:
    def __init__(self, orders: OrderService) -> None:
        self.orders = orders
        self._executions: list[ExecutionRecord] = []

    def executions(self) -> tuple[ExecutionRecord, ...]:
        return tuple(self._executions)

    def execute_from_ticker(
        self,
        order_id: str,
        ticker_event: MarketEventEnvelope[Ticker],
        *,
        quantity: Decimal,
        fee_rate: Decimal,
    ) -> ExecutionRecord:
        order = self.orders.get(order_id)
        if ticker_event.instrument_id != order.instrument_id:
            raise ValueError("ticker instrument does not match order instrument")
        if ticker_event.quality_status is not DataQualityStatus.VALID:
            raise ValueError("ticker is not valid for execution")
        if order.side is OrderSide.BUY:
            price = ticker_event.payload.ask
            if price is None:
                raise ValueError("buy execution requires Ask")
        else:
            price = ticker_event.payload.bid
            if price is None:
                raise ValueError("sell execution requires Bid")
        return self.execute(order_id, price=price, quantity=quantity, fee_rate=fee_rate)

    def try_execute_from_ticker(
        self,
        order_id: str,
        ticker_event: MarketEventEnvelope[Ticker],
        *,
        quantity: Decimal,
        fee_rate: Decimal,
    ) -> ExecutionAttempt:
        try:
            execution = self.execute_from_ticker(
                order_id,
                ticker_event,
                quantity=quantity,
                fee_rate=fee_rate,
            )
            return ExecutionAttempt(success=True, execution=execution)
        except (KeyError, TypeError, ValueError) as exc:
            return ExecutionAttempt(
                success=False,
                error_type=type(exc).__name__,
                error_message=str(exc),
            )

    def execute_match_plan(
        self,
        order_id: str,
        plan: MatchPlan,
        *,
        fee_rate: Decimal,
        market_rules: MarketRules,
        liquidity: SimulatedLiquidityView,
        consumption_id: str,
    ) -> tuple[ExecutionRecord, ...]:
        self._require_fee_rate(fee_rate)
        order = self.orders.get(order_id)
        if order.order_type is not OrderType.MARKET:
            raise ValueError("order-book market match requires a market order")
        if order.status not in {OrderStatus.OPEN, OrderStatus.PARTIALLY_FILLED}:
            raise ValueError(f"order in {order.status} state cannot execute")
        if plan.side is not order.side:
            raise ValueError("match-plan side does not match order side")
        remaining_order_quantity = order.quantity - order.filled_quantity
        if plan.requested_quantity != remaining_order_quantity:
            raise ValueError("match plan must cover the remaining order quantity")
        liquidity_book = liquidity.available_book()
        if liquidity_book.instrument_id != order.instrument_id:
            raise ValueError("liquidity instrument does not match order instrument")
        market_rules.validate(plan)
        liquidity.validate_consumption(plan, consumption_id=consumption_id)
        if plan.status is MatchStatus.NO_FILL:
            self.orders.cancel(order_id)
            return ()

        _, base_asset, quote_asset = split_instrument(order.instrument_id)
        executed_ts_ms = utc_now_ms()
        records: list[ExecutionRecord] = []
        entries: list[LedgerEntry] = []
        for fill in plan.fills:
            execution_id = str(uuid4())
            fee_amount = fill.quote_amount * fee_rate
            records.append(
                ExecutionRecord(
                    execution_id=execution_id,
                    order_id=order.order_id,
                    account_id=order.account_id,
                    instrument_id=order.instrument_id,
                    side=order.side,
                    price=fill.price,
                    quantity=fill.quantity,
                    quote_amount=fill.quote_amount,
                    fee_asset=quote_asset,
                    fee_amount=fee_amount,
                    executed_ts_ms=executed_ts_ms,
                )
            )
            entries.extend(
                self._settlement_entries(
                    order,
                    execution_id,
                    base_asset,
                    quote_asset,
                    fill.quantity,
                    fill.quote_amount,
                    fee_amount,
                    executed_ts_ms,
                )
            )

        new_filled_quantity = order.filled_quantity + plan.filled_quantity
        new_quote_amount = order.cumulative_quote_amount + plan.total_notional
        plan_fee = sum((record.fee_amount for record in records), Decimal(0))
        new_fee = order.cumulative_fee + plan_fee
        final_fill = new_filled_quantity == order.quantity
        new_status = OrderStatus.FILLED if final_fill else OrderStatus.CANCELED
        updated_order = order.model_copy(
            update={
                "filled_quantity": new_filled_quantity,
                "cumulative_quote_amount": new_quote_amount,
                "cumulative_fee": new_fee,
                "average_fill_price": new_quote_amount / new_filled_quantity,
                "status": new_status,
                "updated_ts_ms": executed_ts_ms,
            }
        )
        try:
            remaining_reservation = self.orders.remaining_reservation(updated_order)
        except ValueError as exc:
            raise InsufficientBalanceError("execution cost exceeds the order reservation") from exc
        if remaining_reservation > 0:
            entries.append(
                self._entry(
                    order,
                    consumption_id,
                    order.reserved_asset,
                    available_delta=remaining_reservation,
                    locked_delta=-remaining_reservation,
                    reason=LedgerReason.ORDER_RELEASE,
                    created_ts_ms=executed_ts_ms,
                )
            )

        self.orders.ledger.append_many(entries)
        self.orders.replace_after_execution(updated_order)
        liquidity.consume(plan, consumption_id=consumption_id)
        self._executions.extend(records)
        return tuple(records)

    def execute_limit_match_plan(
        self,
        order_id: str,
        plan: MatchPlan,
        *,
        fee_rate: Decimal,
        market_rules: MarketRules,
        liquidity: SimulatedLiquidityView,
        consumption_id: str,
    ) -> tuple[ExecutionRecord, ...]:
        self._require_fee_rate(fee_rate)
        order = self.orders.get(order_id)
        if order.order_type is not OrderType.LIMIT:
            raise ValueError("limit match requires a limit order")
        if order.status not in {OrderStatus.OPEN, OrderStatus.PARTIALLY_FILLED}:
            raise ValueError(f"order in {order.status} state cannot execute")
        if plan.side is not order.side:
            raise ValueError("match-plan side does not match order side")
        remaining_order_quantity = order.quantity - order.filled_quantity
        if plan.requested_quantity != remaining_order_quantity:
            raise ValueError("match plan must cover the remaining order quantity")
        liquidity_book = liquidity.available_book()
        if liquidity_book.instrument_id != order.instrument_id:
            raise ValueError("liquidity instrument does not match order instrument")
        market_rules.validate(plan)
        liquidity.validate_consumption(plan, consumption_id=consumption_id)
        for fill in plan.fills:
            self._validate_limit_price(order, fill.price)
        if plan.status is MatchStatus.NO_FILL:
            return ()

        _, base_asset, quote_asset = split_instrument(order.instrument_id)
        executed_ts_ms = utc_now_ms()
        records: list[ExecutionRecord] = []
        entries: list[LedgerEntry] = []
        for fill in plan.fills:
            execution_id = str(uuid4())
            fee_amount = fill.quote_amount * fee_rate
            records.append(
                ExecutionRecord(
                    execution_id=execution_id,
                    order_id=order.order_id,
                    account_id=order.account_id,
                    instrument_id=order.instrument_id,
                    side=order.side,
                    price=fill.price,
                    quantity=fill.quantity,
                    quote_amount=fill.quote_amount,
                    fee_asset=quote_asset,
                    fee_amount=fee_amount,
                    executed_ts_ms=executed_ts_ms,
                    liquidity_role=LiquidityRole.TAKER,
                    market_event_id=plan.book_event_id,
                )
            )
            entries.extend(
                self._settlement_entries(
                    order,
                    execution_id,
                    base_asset,
                    quote_asset,
                    fill.quantity,
                    fill.quote_amount,
                    fee_amount,
                    executed_ts_ms,
                )
            )

        new_filled_quantity = order.filled_quantity + plan.filled_quantity
        new_quote_amount = order.cumulative_quote_amount + plan.total_notional
        plan_fee = sum((record.fee_amount for record in records), Decimal(0))
        new_fee = order.cumulative_fee + plan_fee
        final_fill = new_filled_quantity == order.quantity
        updated_order = order.model_copy(
            update={
                "filled_quantity": new_filled_quantity,
                "cumulative_quote_amount": new_quote_amount,
                "cumulative_fee": new_fee,
                "average_fill_price": new_quote_amount / new_filled_quantity,
                "status": OrderStatus.FILLED if final_fill else OrderStatus.PARTIALLY_FILLED,
                "updated_ts_ms": executed_ts_ms,
            }
        )
        try:
            remaining_reservation = self.orders.remaining_reservation(updated_order)
        except ValueError as exc:
            raise InsufficientBalanceError("execution cost exceeds the order reservation") from exc
        if final_fill and remaining_reservation > 0:
            entries.append(
                self._entry(
                    order,
                    consumption_id,
                    order.reserved_asset,
                    available_delta=remaining_reservation,
                    locked_delta=-remaining_reservation,
                    reason=LedgerReason.ORDER_RELEASE,
                    created_ts_ms=executed_ts_ms,
                )
            )

        self.orders.ledger.append_many(entries)
        self.orders.replace_after_execution(updated_order)
        liquidity.consume(plan, consumption_id=consumption_id)
        self._executions.extend(records)
        return tuple(records)

    def execute(
        self,
        order_id: str,
        *,
        price: Decimal,
        quantity: Decimal,
        fee_rate: Decimal,
    ) -> ExecutionRecord:
        self._require_decimal_positive(price, "price")
        self._require_decimal_positive(quantity, "quantity")
        self._require_fee_rate(fee_rate)
        order = self.orders.get(order_id)
        if order.status not in {OrderStatus.OPEN, OrderStatus.PARTIALLY_FILLED}:
            raise ValueError(f"order in {order.status} state cannot execute")
        remaining_quantity = order.quantity - order.filled_quantity
        if quantity > remaining_quantity:
            raise ValueError("execution quantity exceeds remaining order quantity")
        self._validate_limit_price(order, price)

        _, base_asset, quote_asset = split_instrument(order.instrument_id)
        execution_id = str(uuid4())
        executed_ts_ms = utc_now_ms()
        quote_amount = price * quantity
        fee_amount = quote_amount * fee_rate
        new_filled_quantity = order.filled_quantity + quantity
        new_quote_amount = order.cumulative_quote_amount + quote_amount
        new_fee = order.cumulative_fee + fee_amount
        final_fill = new_filled_quantity == order.quantity
        new_status = OrderStatus.FILLED if final_fill else OrderStatus.PARTIALLY_FILLED
        updated_order = order.model_copy(
            update={
                "filled_quantity": new_filled_quantity,
                "cumulative_quote_amount": new_quote_amount,
                "cumulative_fee": new_fee,
                "average_fill_price": new_quote_amount / new_filled_quantity,
                "status": new_status,
                "updated_ts_ms": executed_ts_ms,
            }
        )
        entries = self._settlement_entries(
            order,
            execution_id,
            base_asset,
            quote_asset,
            quantity,
            quote_amount,
            fee_amount,
            executed_ts_ms,
        )
        if final_fill:
            try:
                remaining_reservation = self.orders.remaining_reservation(updated_order)
            except ValueError as exc:
                raise InsufficientBalanceError(
                    "execution cost exceeds the order reservation"
                ) from exc
            if remaining_reservation > 0:
                entries.append(
                    self._entry(
                        order,
                        execution_id,
                        order.reserved_asset,
                        available_delta=remaining_reservation,
                        locked_delta=-remaining_reservation,
                        reason=LedgerReason.ORDER_RELEASE,
                        created_ts_ms=executed_ts_ms,
                    )
                )

        record = ExecutionRecord(
            execution_id=execution_id,
            order_id=order.order_id,
            account_id=order.account_id,
            instrument_id=order.instrument_id,
            side=order.side,
            price=price,
            quantity=quantity,
            quote_amount=quote_amount,
            fee_asset=quote_asset,
            fee_amount=fee_amount,
            executed_ts_ms=executed_ts_ms,
        )
        self.orders.ledger.append_many(entries)
        self.orders.replace_after_execution(updated_order)
        self._executions.append(record)
        return record

    def execute_passive_fill(
        self,
        order_id: str,
        *,
        quantity: Decimal,
        fee_rate: Decimal,
        market_event_id: str,
        execution_id: str,
        executed_ts_ms: int,
    ) -> ExecutionRecord:
        self._require_decimal_positive(quantity, "quantity")
        self._require_fee_rate(fee_rate)
        if not market_event_id or not execution_id:
            raise ValueError("market event ID and execution ID are required")
        if executed_ts_ms < 0:
            raise ValueError("executed_ts_ms cannot be negative")
        order = self.orders.get(order_id)
        if order.order_type is not OrderType.LIMIT or order.limit_price is None:
            raise ValueError("passive fill requires a limit order")
        if order.market_entry_ts_ms is None:
            raise ValueError("passive fill requires an order that entered the market")
        if order.status not in {OrderStatus.OPEN, OrderStatus.PARTIALLY_FILLED}:
            raise ValueError(f"order in {order.status} state cannot execute")
        remaining_quantity = order.quantity - order.filled_quantity
        if quantity > remaining_quantity:
            raise ValueError("execution quantity exceeds remaining order quantity")

        price = order.limit_price
        _, base_asset, quote_asset = split_instrument(order.instrument_id)
        quote_amount = price * quantity
        fee_amount = quote_amount * fee_rate
        new_filled_quantity = order.filled_quantity + quantity
        new_quote_amount = order.cumulative_quote_amount + quote_amount
        new_fee = order.cumulative_fee + fee_amount
        final_fill = new_filled_quantity == order.quantity
        updated_order = order.model_copy(
            update={
                "filled_quantity": new_filled_quantity,
                "cumulative_quote_amount": new_quote_amount,
                "cumulative_fee": new_fee,
                "average_fill_price": new_quote_amount / new_filled_quantity,
                "status": OrderStatus.FILLED if final_fill else OrderStatus.PARTIALLY_FILLED,
                "updated_ts_ms": executed_ts_ms,
            }
        )
        entries = self._settlement_entries(
            order,
            execution_id,
            base_asset,
            quote_asset,
            quantity,
            quote_amount,
            fee_amount,
            executed_ts_ms,
        )
        try:
            remaining_reservation = self.orders.remaining_reservation(updated_order)
        except ValueError as exc:
            raise InsufficientBalanceError("execution cost exceeds the order reservation") from exc
        if final_fill and remaining_reservation > 0:
            entries.append(
                self._entry(
                    order,
                    execution_id,
                    order.reserved_asset,
                    available_delta=remaining_reservation,
                    locked_delta=-remaining_reservation,
                    reason=LedgerReason.ORDER_RELEASE,
                    created_ts_ms=executed_ts_ms,
                )
            )

        record = ExecutionRecord(
            execution_id=execution_id,
            order_id=order.order_id,
            account_id=order.account_id,
            instrument_id=order.instrument_id,
            side=order.side,
            price=price,
            quantity=quantity,
            quote_amount=quote_amount,
            fee_asset=quote_asset,
            fee_amount=fee_amount,
            executed_ts_ms=executed_ts_ms,
            liquidity_role=LiquidityRole.MAKER,
            market_event_id=market_event_id,
        )
        self.orders.ledger.append_many(entries)
        self.orders.replace_after_execution(updated_order)
        self._executions.append(record)
        return record

    @staticmethod
    def _settlement_entries(
        order: PaperOrder,
        execution_id: str,
        base_asset: str,
        quote_asset: str,
        quantity: Decimal,
        quote_amount: Decimal,
        fee_amount: Decimal,
        executed_ts_ms: int,
    ) -> list[LedgerEntry]:
        if order.side is OrderSide.BUY:
            entries = [
                ExecutionSimulator._entry(
                    order,
                    execution_id,
                    quote_asset,
                    locked_delta=-quote_amount,
                    reason=LedgerReason.TRADE_SETTLEMENT,
                    created_ts_ms=executed_ts_ms,
                ),
                ExecutionSimulator._entry(
                    order,
                    execution_id,
                    base_asset,
                    available_delta=quantity,
                    reason=LedgerReason.TRADE_SETTLEMENT,
                    created_ts_ms=executed_ts_ms,
                ),
            ]
            if fee_amount > 0:
                entries.insert(
                    1,
                    ExecutionSimulator._entry(
                        order,
                        execution_id,
                        quote_asset,
                        locked_delta=-fee_amount,
                        reason=LedgerReason.FEE,
                        created_ts_ms=executed_ts_ms,
                    ),
                )
            return entries
        entries = [
            ExecutionSimulator._entry(
                order,
                execution_id,
                base_asset,
                locked_delta=-quantity,
                reason=LedgerReason.TRADE_SETTLEMENT,
                created_ts_ms=executed_ts_ms,
            ),
            ExecutionSimulator._entry(
                order,
                execution_id,
                quote_asset,
                available_delta=quote_amount,
                reason=LedgerReason.TRADE_SETTLEMENT,
                created_ts_ms=executed_ts_ms,
            ),
        ]
        if fee_amount > 0:
            entries.append(
                ExecutionSimulator._entry(
                    order,
                    execution_id,
                    quote_asset,
                    available_delta=-fee_amount,
                    reason=LedgerReason.FEE,
                    created_ts_ms=executed_ts_ms,
                )
            )
        return entries

    @staticmethod
    def _entry(
        order: PaperOrder,
        execution_id: str,
        asset: str,
        *,
        available_delta: Decimal = Decimal(0),
        locked_delta: Decimal = Decimal(0),
        reason: LedgerReason,
        created_ts_ms: int,
    ) -> LedgerEntry:
        return LedgerEntry(
            entry_id=str(uuid4()),
            account_id=order.account_id,
            exchange_id=order.instrument_id.split(":", maxsplit=1)[0],
            asset=asset,
            available_delta=available_delta,
            locked_delta=locked_delta,
            reason=reason,
            reference_id=execution_id,
            created_ts_ms=created_ts_ms,
        )

    @staticmethod
    def _validate_limit_price(order: PaperOrder, execution_price: Decimal) -> None:
        if order.order_type is not OrderType.LIMIT:
            return
        assert order.limit_price is not None
        if order.side is OrderSide.BUY and execution_price > order.limit_price:
            raise ValueError("buy limit order cannot fill above its limit price")
        if order.side is OrderSide.SELL and execution_price < order.limit_price:
            raise ValueError("sell limit order cannot fill below its limit price")

    @staticmethod
    def _require_decimal_positive(value: Decimal, name: str) -> None:
        if not isinstance(value, Decimal):
            raise TypeError(f"{name} must be Decimal")
        if value <= 0:
            raise ValueError(f"{name} must be positive")

    @staticmethod
    def _require_fee_rate(value: Decimal) -> None:
        if not isinstance(value, Decimal):
            raise TypeError("fee_rate must be Decimal")
        if value < 0 or value > 1:
            raise ValueError("fee_rate must be between 0 and 1")
