from decimal import Decimal

import pytest

from crypto_lab.models import ExchangeId
from crypto_lab.trading import (
    AccountLedger,
    InsufficientBalanceError,
    LedgerEntry,
    LedgerReason,
    create_paper_account,
)


def test_account_starts_with_traceable_virtual_funding() -> None:
    ledger = create_paper_account(ExchangeId.BINANCE)

    assert ledger.balance("usdt").available == Decimal("10000")
    assert ledger.balance("USDT").locked == 0
    assert len(ledger.entries) == 1
    assert ledger.entries[0].reason is LedgerReason.INITIAL_FUNDING


def test_reserve_and_release_preserve_total_balance() -> None:
    ledger = create_paper_account(ExchangeId.OKX)

    ledger.reserve("USDT", Decimal("250"), "order-1")
    reserved = ledger.balance("USDT")
    assert reserved.available == Decimal("9750")
    assert reserved.locked == Decimal("250")
    assert reserved.total == Decimal("10000")

    ledger.release("USDT", Decimal("250"), "order-1")
    released = ledger.balance("USDT")
    assert released.available == Decimal("10000")
    assert released.locked == 0
    assert released.total == Decimal("10000")


def test_insufficient_available_balance_is_atomic() -> None:
    ledger = create_paper_account(ExchangeId.BYBIT, initial_amount=Decimal("10"))
    entry_count = len(ledger.entries)

    with pytest.raises(InsufficientBalanceError):
        ledger.reserve("USDT", Decimal("11"), "order-1")

    assert ledger.balance("USDT").available == Decimal("10")
    assert ledger.balance("USDT").locked == 0
    assert len(ledger.entries) == entry_count


def test_release_cannot_exceed_locked_balance() -> None:
    ledger = create_paper_account(ExchangeId.KRAKEN)

    with pytest.raises(InsufficientBalanceError):
        ledger.release("USDT", Decimal("1"), "order-1")

    assert ledger.balance("USDT").total == Decimal("10000")


def test_duplicate_entry_id_does_not_change_balance_twice() -> None:
    ledger = create_paper_account(ExchangeId.COINBASE)
    entry = LedgerEntry(
        entry_id="fixed-id",
        account_id=ledger.account.account_id,
        exchange_id=ledger.account.exchange_id,
        asset="BTC",
        available_delta=Decimal("1"),
        reason=LedgerReason.TRADE_SETTLEMENT,
        created_ts_ms=1,
    )
    ledger.append(entry)

    with pytest.raises(ValueError, match="duplicate"):
        ledger.append(entry)

    assert ledger.balance("BTC").available == Decimal("1")


def test_ledger_rebuilds_balances_from_entries() -> None:
    original = create_paper_account(
        ExchangeId.BITBANK,
        initial_asset="JPY",
        initial_amount=Decimal("1000"),
    )
    original.reserve("JPY", Decimal("200"), "order-1")

    rebuilt = AccountLedger(original.account, original.entries)

    assert rebuilt.balances() == original.balances()


def test_amount_must_be_decimal_and_positive() -> None:
    ledger = create_paper_account(ExchangeId.BINANCE)

    with pytest.raises(TypeError, match="Decimal"):
        ledger.reserve("USDT", 1, "order-1")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="positive"):
        ledger.reserve("USDT", Decimal("0"), "order-1")
