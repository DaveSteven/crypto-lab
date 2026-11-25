"""Paper-trading domain services."""

from crypto_lab.trading.execution import ExecutionAttempt, ExecutionRecord, ExecutionSimulator
from crypto_lab.trading.ledger import (
    AccountLedger,
    InsufficientBalanceError,
    create_paper_account,
)
from crypto_lab.trading.matching import (
    FillLeg,
    MatchPlan,
    MatchStatus,
    SlippageMetrics,
    match_market_order,
)
from crypto_lab.trading.models import AssetBalance, LedgerEntry, LedgerReason, PaperAccount
from crypto_lab.trading.order_service import InvalidOrderTransitionError, OrderService
from crypto_lab.trading.orders import OrderSide, OrderStatus, OrderType, PaperOrder
from crypto_lab.trading.portfolio import (
    InsufficientPositionError,
    PortfolioEngine,
    Position,
    PositionValuation,
)

__all__ = [
    "AccountLedger",
    "AssetBalance",
    "ExecutionAttempt",
    "ExecutionRecord",
    "ExecutionSimulator",
    "FillLeg",
    "InsufficientBalanceError",
    "InsufficientPositionError",
    "InvalidOrderTransitionError",
    "LedgerEntry",
    "LedgerReason",
    "MatchPlan",
    "MatchStatus",
    "OrderService",
    "OrderSide",
    "OrderStatus",
    "OrderType",
    "PaperAccount",
    "PaperOrder",
    "PortfolioEngine",
    "Position",
    "PositionValuation",
    "SlippageMetrics",
    "create_paper_account",
    "match_market_order",
]
