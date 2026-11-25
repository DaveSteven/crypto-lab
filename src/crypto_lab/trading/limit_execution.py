"""Immediate order-book execution boundary for GTC limit orders."""

from crypto_lab.market_data import OrderBookMarketState
from crypto_lab.models import ExchangeId
from crypto_lab.trading.constraints import MarketRules
from crypto_lab.trading.execution import ExecutionRecord, ExecutionSimulator
from crypto_lab.trading.fees import FeeSchedule
from crypto_lab.trading.liquidity import SimulatedLiquidityView
from crypto_lab.trading.matching import MatchPlan, match_limit_order
from crypto_lab.trading.models import FrozenModel
from crypto_lab.trading.orders import OrderSide, OrderStatus, OrderType


class LimitOrderEntryResult(FrozenModel):
    plan: MatchPlan
    executions: tuple[ExecutionRecord, ...]
    resting: bool


class LimitOrderExecutionService:
    def __init__(
        self,
        market_state: OrderBookMarketState,
        simulator: ExecutionSimulator,
        liquidity: SimulatedLiquidityView,
    ) -> None:
        self.market_state = market_state
        self.simulator = simulator
        self.liquidity = liquidity

    def enter_limit_order(
        self,
        order_id: str,
        *,
        exchange_id: ExchangeId,
        instrument_id: str,
        market_entry_ts_ms: int,
        max_book_age_ms: int,
        fee_schedule: FeeSchedule,
        market_rules: MarketRules,
        consumption_id: str,
        executed_ts_ms: int | None = None,
    ) -> LimitOrderEntryResult:
        order = self.simulator.orders.get(order_id)
        if order.order_type is not OrderType.LIMIT:
            raise ValueError("limit-order entry requires a limit order")
        if order.instrument_id != instrument_id:
            raise ValueError("order instrument does not match requested market")
        if order.fee_schedule_id != fee_schedule.schedule_id:
            raise ValueError("fee schedule does not match order reservation")
        if order.market_entry_ts_ms is not None:
            raise ValueError("limit order has already entered the market")
        book = self.market_state.executable_book(
            exchange_id,
            instrument_id,
            decision_ts_ms=market_entry_ts_ms,
            max_age_ms=max_book_age_ms,
        )
        self.liquidity.synchronize(book)
        entered = self.simulator.orders.enter_market(
            order_id,
            market_entry_ts_ms=market_entry_ts_ms,
        )
        assert entered.limit_price is not None
        available_book = self.liquidity.available_book()
        reference_price = (
            available_book.asks[0].price
            if entered.side is OrderSide.BUY
            else available_book.bids[0].price
        )
        plan = match_limit_order(
            available_book,
            side=entered.side,
            quantity=entered.quantity - entered.filled_quantity,
            limit_price=entered.limit_price,
            submission_reference_price=reference_price,
        )
        executions = self.simulator.execute_limit_match_plan(
            order_id,
            plan,
            fee_rate=fee_schedule.taker_rate,
            market_rules=market_rules,
            liquidity=self.liquidity,
            consumption_id=consumption_id,
            executed_ts_ms=executed_ts_ms,
        )
        updated = self.simulator.orders.get(order_id)
        return LimitOrderEntryResult(
            plan=plan,
            executions=executions,
            resting=updated.status in {OrderStatus.OPEN, OrderStatus.PARTIALLY_FILLED},
        )
