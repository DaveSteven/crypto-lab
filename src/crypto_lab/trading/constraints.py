"""Explicit exchange market constraints for simulated execution."""

from decimal import Decimal

from pydantic import Field

from crypto_lab.trading.matching import MatchPlan
from crypto_lab.trading.models import FrozenModel


class MarketRuleViolation(ValueError):
    pass


class MarketRules(FrozenModel):
    rules_id: str = Field(min_length=1)
    price_increment: Decimal = Field(gt=0)
    quantity_increment: Decimal = Field(gt=0)
    min_quantity: Decimal = Field(gt=0)
    min_notional: Decimal | None = Field(default=None, gt=0)

    def validate(self, plan: MatchPlan) -> None:
        if plan.requested_quantity < self.min_quantity:
            raise MarketRuleViolation("order quantity is below the market minimum")
        _require_increment(
            plan.requested_quantity,
            self.quantity_increment,
            "order quantity",
        )
        for fill in plan.fills:
            _require_increment(fill.price, self.price_increment, "fill price")
            _require_increment(fill.quantity, self.quantity_increment, "fill quantity")

        reference_price = (
            plan.slippage.submission_reference_price or plan.slippage.execution_reference_price
        )
        if self.min_notional is not None:
            if reference_price is None:
                raise MarketRuleViolation("minimum notional requires a reference price")
            if reference_price * plan.requested_quantity < self.min_notional:
                raise MarketRuleViolation("order notional is below the market minimum")


def _require_increment(value: Decimal, increment: Decimal, name: str) -> None:
    if value % increment != 0:
        raise MarketRuleViolation(f"{name} does not align with the configured increment")
