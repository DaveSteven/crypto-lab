"""Append-only in-memory ledger for paper accounts."""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal
from uuid import uuid4

from crypto_lab.models import ExchangeId
from crypto_lab.trading.models import (
    AssetBalance,
    LedgerEntry,
    LedgerReason,
    PaperAccount,
    utc_now_ms,
)


class InsufficientBalanceError(ValueError):
    pass


class AccountLedger:
    def __init__(self, account: PaperAccount, entries: Iterable[LedgerEntry] = ()) -> None:
        self.account = account
        self._entries: list[LedgerEntry] = []
        self._entry_ids: set[str] = set()
        self._balances: dict[str, AssetBalance] = {}
        for entry in entries:
            self.append(entry)

    @property
    def entries(self) -> tuple[LedgerEntry, ...]:
        return tuple(self._entries)

    def balance(self, asset: str) -> AssetBalance:
        normalized = AssetBalance.normalize_asset(asset)
        return self._balances.get(
            normalized,
            AssetBalance(asset=normalized, available=Decimal(0), locked=Decimal(0)),
        )

    def balances(self) -> tuple[AssetBalance, ...]:
        return tuple(self._balances[asset] for asset in sorted(self._balances))

    def append(self, entry: LedgerEntry) -> None:
        if entry.entry_id in self._entry_ids:
            raise ValueError(f"duplicate ledger entry ID: {entry.entry_id}")
        if entry.account_id != self.account.account_id:
            raise ValueError("ledger entry belongs to a different account")
        if entry.exchange_id is not self.account.exchange_id:
            raise ValueError("ledger entry belongs to a different exchange")

        current = self.balance(entry.asset)
        updated_available = current.available + entry.available_delta
        updated_locked = current.locked + entry.locked_delta
        if updated_available < 0 or updated_locked < 0:
            raise InsufficientBalanceError(
                f"insufficient {current.asset} balance for ledger entry {entry.entry_id}"
            )
        updated = AssetBalance(
            asset=current.asset,
            available=updated_available,
            locked=updated_locked,
        )
        self._balances[current.asset] = updated
        self._entries.append(entry)
        self._entry_ids.add(entry.entry_id)

    def reserve(self, asset: str, amount: Decimal, reference_id: str) -> LedgerEntry:
        self._require_positive(amount)
        return self._append_change(
            asset,
            available_delta=-amount,
            locked_delta=amount,
            reason=LedgerReason.ORDER_RESERVE,
            reference_id=reference_id,
        )

    def release(self, asset: str, amount: Decimal, reference_id: str) -> LedgerEntry:
        self._require_positive(amount)
        return self._append_change(
            asset,
            available_delta=amount,
            locked_delta=-amount,
            reason=LedgerReason.ORDER_RELEASE,
            reference_id=reference_id,
        )

    def _append_change(
        self,
        asset: str,
        *,
        available_delta: Decimal,
        locked_delta: Decimal,
        reason: LedgerReason,
        reference_id: str | None,
    ) -> LedgerEntry:
        entry = LedgerEntry(
            entry_id=str(uuid4()),
            account_id=self.account.account_id,
            exchange_id=self.account.exchange_id,
            asset=asset,
            available_delta=available_delta,
            locked_delta=locked_delta,
            reason=reason,
            reference_id=reference_id,
            created_ts_ms=utc_now_ms(),
        )
        self.append(entry)
        return entry

    @staticmethod
    def _require_positive(amount: Decimal) -> None:
        if not isinstance(amount, Decimal):
            raise TypeError("amount must be Decimal")
        if amount <= 0:
            raise ValueError("amount must be positive")


def create_paper_account(
    exchange_id: ExchangeId,
    *,
    name: str = "Paper Account",
    initial_asset: str = "USDT",
    initial_amount: Decimal = Decimal("10000"),
) -> AccountLedger:
    AccountLedger._require_positive(initial_amount)
    account = PaperAccount(
        account_id=str(uuid4()),
        name=name,
        exchange_id=exchange_id,
        created_ts_ms=utc_now_ms(),
    )
    ledger = AccountLedger(account)
    ledger._append_change(
        initial_asset,
        available_delta=initial_amount,
        locked_delta=Decimal(0),
        reason=LedgerReason.INITIAL_FUNDING,
        reference_id=None,
    )
    return ledger
