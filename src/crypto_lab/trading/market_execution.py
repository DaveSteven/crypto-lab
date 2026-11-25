"""Application boundary for safe order-book market execution."""

from decimal import Decimal

from crypto_lab.market_data import OrderBookMarketState
from crypto_lab.models import ExchangeId
from crypto_lab.trading.constraints import MarketRules
from crypto_lab.trading.execution import ExecutionRecord, ExecutionSimulator
from crypto_lab.trading.liquidity import SimulatedLiquidityView
from crypto_lab.trading.matching import MatchPlan, match_market_order
from crypto_lab.trading.models import FrozenModel


class MarketExecutionResult(FrozenModel):
    plan: MatchPlan
    executions: tuple[ExecutionRecord, ...]


class OrderBookExecutionService:
    def __init__(
        self,
        market_state: OrderBookMarketState,
        simulator: ExecutionSimulator,
        liquidity: SimulatedLiquidityView,
    ) -> None:
        self.market_state = market_state
        self.simulator = simulator
        self.liquidity = liquidity

    def execute_market_order(
        self,
        order_id: str,
        *,
        exchange_id: ExchangeId,
        instrument_id: str,
        decision_ts_ms: int,
        max_book_age_ms: int,
        fee_rate: Decimal,
        market_rules: MarketRules,
        consumption_id: str,
    ) -> MarketExecutionResult:
        order = self.simulator.orders.get(order_id)
        if order.instrument_id != instrument_id:
            raise ValueError("order instrument does not match requested market")
        book = self.market_state.executable_book(
            exchange_id,
            instrument_id,
            decision_ts_ms=decision_ts_ms,
            max_age_ms=max_book_age_ms,
        )
        self.liquidity.synchronize(book)
        plan = match_market_order(
            self.liquidity.available_book(),
            side=order.side,
            quantity=order.quantity - order.filled_quantity,
            submission_reference_price=order.reference_price,
        )
        executions = self.simulator.execute_match_plan(
            order_id,
            plan,
            fee_rate=fee_rate,
            market_rules=market_rules,
            liquidity=self.liquidity,
            consumption_id=consumption_id,
        )
        return MarketExecutionResult(plan=plan, executions=executions)
