"""Append-only in-memory ledger for paper accounts."""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal

from crypto_lab.models import ExchangeId
from crypto_lab.trading.clock import Clock, SystemClock
from crypto_lab.trading.identity import IdGenerator, RandomIdGenerator
from crypto_lab.trading.models import (
    AssetBalance,
    LedgerEntry,
    LedgerReason,
    PaperAccount,
)


class InsufficientBalanceError(ValueError):
    pass


class AccountLedger:
    def __init__(
        self,
        account: PaperAccount,
        entries: Iterable[LedgerEntry] = (),
        *,
        id_generator: IdGenerator | None = None,
        clock: Clock | None = None,
    ) -> None:
        self.account = account
        self.id_generator = id_generator or RandomIdGenerator()
        self.clock = clock or SystemClock()
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

    def snapshot_state(self) -> tuple[list[LedgerEntry], set[str], dict[str, AssetBalance]]:
        return (self._entries.copy(), self._entry_ids.copy(), self._balances.copy())

    def restore_state(
        self,
        state: tuple[list[LedgerEntry], set[str], dict[str, AssetBalance]],
    ) -> None:
        entries, entry_ids, balances = state
        self._entries = entries.copy()
        self._entry_ids = entry_ids.copy()
        self._balances = balances.copy()

    def append(self, entry: LedgerEntry) -> None:
        self.append_many((entry,))

    def append_many(self, entries: Iterable[LedgerEntry]) -> None:
        pending = tuple(entries)
        if not pending:
            raise ValueError("at least one ledger entry is required")
        pending_ids = [entry.entry_id for entry in pending]
        if len(set(pending_ids)) != len(pending_ids):
            raise ValueError("duplicate ledger entry ID within batch")
        duplicate_ids = self._entry_ids.intersection(pending_ids)
        if duplicate_ids:
            raise ValueError(f"duplicate ledger entry ID: {sorted(duplicate_ids)[0]}")

        simulated = dict(self._balances)
        for entry in pending:
            if entry.account_id != self.account.account_id:
                raise ValueError("ledger entry belongs to a different account")
            if entry.exchange_id is not self.account.exchange_id:
                raise ValueError("ledger entry belongs to a different exchange")
            current = simulated.get(
                entry.asset,
                AssetBalance(asset=entry.asset, available=Decimal(0), locked=Decimal(0)),
            )
            updated_available = current.available + entry.available_delta
            updated_locked = current.locked + entry.locked_delta
            if updated_available < 0 or updated_locked < 0:
                raise InsufficientBalanceError(
                    f"insufficient {current.asset} balance for ledger entry {entry.entry_id}"
                )
            simulated[current.asset] = AssetBalance(
                asset=current.asset,
                available=updated_available,
                locked=updated_locked,
            )

        self._balances = simulated
        self._entries.extend(pending)
        self._entry_ids.update(pending_ids)

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
            entry_id=self.id_generator.next_id("ledger-entry"),
            account_id=self.account.account_id,
            exchange_id=self.account.exchange_id,
            asset=asset,
            available_delta=available_delta,
            locked_delta=locked_delta,
            reason=reason,
            reference_id=reference_id,
            created_ts_ms=self.clock.now_utc_ms(),
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
    id_generator: IdGenerator | None = None,
    clock: Clock | None = None,
) -> AccountLedger:
    AccountLedger._require_positive(initial_amount)
    generator = id_generator or RandomIdGenerator()
    effective_clock = clock or SystemClock()
    account = PaperAccount(
        account_id=generator.next_id("account"),
        name=name,
        exchange_id=exchange_id,
        created_ts_ms=effective_clock.now_utc_ms(),
    )
    ledger = AccountLedger(account, id_generator=generator, clock=effective_clock)
    ledger._append_change(
        initial_asset,
        available_delta=initial_amount,
        locked_delta=Decimal(0),
        reason=LedgerReason.INITIAL_FUNDING,
        reference_id=None,
    )
    return ledger
