"""Paper-trading domain services."""

from crypto_lab.trading.constraints import MarketRules, MarketRuleViolation
from crypto_lab.trading.execution import (
    ExecutionAttempt,
    ExecutionRecord,
    ExecutionSimulator,
    LiquidityRole,
)
from crypto_lab.trading.fees import FeeSchedule
from crypto_lab.trading.ledger import (
    AccountLedger,
    InsufficientBalanceError,
    create_paper_account,
)
from crypto_lab.trading.limit_execution import (
    LimitOrderEntryResult,
    LimitOrderExecutionService,
)
from crypto_lab.trading.liquidity import LiquidityError, SimulatedLiquidityView
from crypto_lab.trading.market_execution import (
    MarketExecutionResult,
    OrderBookExecutionService,
)
from crypto_lab.trading.matching import (
    FillLeg,
    MatchPlan,
    MatchStatus,
    SlippageMetrics,
    match_limit_order,
    match_market_order,
)
from crypto_lab.trading.models import AssetBalance, LedgerEntry, LedgerReason, PaperAccount
from crypto_lab.trading.okx_rules import normalize_okx_spot_rules
from crypto_lab.trading.order_service import InvalidOrderTransitionError, OrderService
from crypto_lab.trading.orders import OrderSide, OrderStatus, OrderType, PaperOrder, TimeInForce
from crypto_lab.trading.portfolio import (
    InsufficientPositionError,
    PortfolioEngine,
    Position,
    PositionValuation,
)
from crypto_lab.trading.trade_through import (
    TradeAllocation,
    TradeProcessingResult,
    TradeProcessingStatus,
    TradeThroughEngine,
)

__all__ = [
    "AccountLedger",
    "AssetBalance",
    "ExecutionAttempt",
    "ExecutionRecord",
    "ExecutionSimulator",
    "FeeSchedule",
    "FillLeg",
    "InsufficientBalanceError",
    "InsufficientPositionError",
    "InvalidOrderTransitionError",
    "LedgerEntry",
    "LedgerReason",
    "LiquidityError",
    "LiquidityRole",
    "LimitOrderEntryResult",
    "LimitOrderExecutionService",
    "MatchPlan",
    "MatchStatus",
    "MarketRules",
    "MarketRuleViolation",
    "MarketExecutionResult",
    "OrderService",
    "OrderBookExecutionService",
    "OrderSide",
    "OrderStatus",
    "OrderType",
    "PaperAccount",
    "PaperOrder",
    "PortfolioEngine",
    "Position",
    "PositionValuation",
    "SlippageMetrics",
    "SimulatedLiquidityView",
    "TimeInForce",
    "TradeAllocation",
    "TradeProcessingResult",
    "TradeProcessingStatus",
    "TradeThroughEngine",
    "create_paper_account",
    "match_market_order",
    "match_limit_order",
    "normalize_okx_spot_rules",
]
