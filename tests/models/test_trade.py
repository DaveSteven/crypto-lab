from decimal import Decimal

import pytest
from pydantic import ValidationError

from crypto_lab.models import Trade, TradeSide


def test_trade_preserves_decimal_values_and_unknown_side() -> None:
    trade = Trade(
        price="100.12345678",
        quantity="0.00000001",
        quote_amount="0.0000010012345678",
        side=TradeSide.UNKNOWN,
    )

    assert trade.price == Decimal("100.12345678")
    assert trade.side is TradeSide.UNKNOWN


@pytest.mark.parametrize("field", ["price", "quantity", "quote_amount"])
def test_trade_rejects_nonpositive_values(field: str) -> None:
    values: dict[str, object] = {
        "price": "100",
        "quantity": "1",
        "quote_amount": "100",
        "side": TradeSide.BUY,
    }
    values[field] = "0"
    with pytest.raises(ValidationError):
        Trade(**values)
