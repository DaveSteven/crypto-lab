#!/usr/bin/env python3
"""Run the deterministic Task 1.13 multi-environment performance baseline."""

from __future__ import annotations

import argparse
import json
import os
import platform
import resource
import statistics
import time
import tracemalloc
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, event, select
from sqlalchemy.engine import Engine, make_url

from crypto_lab.api.schemas import AccountCreate, EnvironmentCreate, OrderCreate
from crypto_lab.api.service import ApplicationService
from crypto_lab.market_data import OrderBookView
from crypto_lab.models import DataQualityStatus, ExchangeId, PriceLevel
from crypto_lab.persistence import schema
from crypto_lab.realtime import EnvironmentMarketDispatcher
from crypto_lab.trading import FeeSchedule, MarketRules

INSTRUMENT = "okx:SPOT:BTC/USDT"
DEFAULT_SCALES = (1, 3, 5, 10, 20)
FEES = FeeSchedule(
    schedule_id="phase1-performance-v1",
    maker_rate=Decimal("0.001"),
    taker_rate=Decimal("0.001"),
)
RULES = MarketRules(
    rules_id="OKX:PHASE1-PERFORMANCE",
    price_increment=Decimal("0.1"),
    quantity_increment=Decimal("0.00000001"),
    min_quantity=Decimal("0.00001"),
    min_notional=None,
)


class ManualMilliseconds:
    def __init__(self, value: int = 1_000) -> None:
        self.value = value

    def __call__(self) -> int:
        return self.value


@dataclass
class TransactionTimer:
    durations_ms: list[float] = field(default_factory=list)

    def install(self, engine: Engine) -> None:
        @event.listens_for(engine, "begin")
        def begin(connection: Any) -> None:
            connection.info["phase1_transaction_started"] = time.perf_counter_ns()

        def finish(connection: Any) -> None:
            started = connection.info.pop("phase1_transaction_started", None)
            if started is not None:
                self.durations_ms.append((time.perf_counter_ns() - started) / 1_000_000)

        event.listen(engine, "commit", finish)
        event.listen(engine, "rollback", finish)

    def reset(self) -> None:
        self.durations_ms.clear()


def _book(sequence: int, received_ts_ms: int) -> OrderBookView:
    return OrderBookView(
        exchange_id=ExchangeId.OKX,
        instrument_id=INSTRUMENT,
        bids=(
            PriceLevel(price=Decimal("100"), quantity=Decimal("20")),
            PriceLevel(price=Decimal("99"), quantity=Decimal("20")),
        ),
        asks=(
            PriceLevel(price=Decimal("101"), quantity=Decimal("20")),
            PriceLevel(price=Decimal("102"), quantity=Decimal("20")),
        ),
        depth=5,
        sequence_id=f"baseline-{sequence}",
        source_event_id=f"baseline-book-{sequence}",
        exchange_ts_ms=received_ts_ms - 1,
        received_ts_ms=received_ts_ms,
        quality_status=DataQualityStatus.VALID,
        synchronized=True,
        source_connected=True,
    )


def _reset_test_database(engine: Engine) -> None:
    with engine.begin() as connection:
        for table in reversed(schema.metadata.sorted_tables):
            connection.execute(table.delete())


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = round((len(ordered) - 1) * percentile)
    return ordered[index]


def _rss_bytes() -> int:
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return value if platform.system() == "Darwin" else value * 1024


def _business_fingerprint(
    service: ApplicationService,
    engine: Engine,
    environment_id: str,
    account_id: str,
) -> dict[str, Any]:
    snapshot = service.snapshot(environment_id, account_id)
    with engine.connect() as connection:
        liquidity = connection.execute(
            select(schema.simulated_liquidity).where(
                schema.simulated_liquidity.c.environment_id == environment_id
            )
        ).mappings().one()
    return {
        "balances": [
            {
                "asset": item["asset"],
                "available": item["available"],
                "locked": item["locked"],
            }
            for item in snapshot["balances"]
        ],
        "orders": [
            {
                "sequence": item["order_sequence"],
                "status": item["status"],
                "filled_quantity": item["filled_quantity"],
                "remaining_quantity": str(
                    Decimal(item["quantity"]) - Decimal(item["filled_quantity"])
                ),
                "average_fill_price": item["average_fill_price"],
                "scheduler_lag_ms": item["scheduler_lag_ms"],
            }
            for item in snapshot["orders"]
        ],
        "executions": [
            {
                "sequence": item["execution_sequence"],
                "price": item["price"],
                "quantity": item["quantity"],
                "fee": item["fee_amount"],
                "liquidity_role": item["liquidity_role"],
            }
            for item in snapshot["executions"]
        ],
        "positions": [
            {
                "instrument_id": item["instrument_id"],
                "quantity": item["quantity"],
                "average_cost": item["average_cost"],
                "total_cost": item["cost_basis"],
            }
            for item in snapshot["positions"]
        ],
        "liquidity": {
            "residual_bids": liquidity["residual_bids_json"],
            "residual_asks": liquidity["residual_asks_json"],
            "consumption_count": len(liquidity["consumption_ids_json"]),
        },
    }


def _run_scale(
    engine: Engine,
    timer: TransactionTimer,
    environment_count: int,
    book_events: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    _reset_test_database(engine)
    clock = ManualMilliseconds()
    service = ApplicationService(engine, fee_schedule=FEES, now_ms=clock)
    dispatcher = EnvironmentMarketDispatcher(
        transaction=service.uow.transaction,
        environment_exists=lambda environment_id: bool(
            service.get_environment(environment_id)
        ),
        fee_schedule=FEES,
        market_rules=RULES,
        instruments=(INSTRUMENT,),
        now_ms=clock,
        max_book_age_ms=5_000,
        due_environments=service.environments_with_due_executions,
    )
    identities: list[tuple[str, str]] = []
    for index in range(environment_count):
        _, environment = service.create_environment(
            EnvironmentCreate(name=f"baseline-{index}"),
            f"baseline-environment-{environment_count}-{index}",
        )
        environment_id = environment["environment_id"]
        _, account = service.create_account(
            environment_id,
            AccountCreate(
                exchange_id="okx",
                name="baseline",
                initial_asset="USDT",
                initial_amount="10000",
            ),
            f"baseline-account-{environment_count}-{index}",
        )
        assert dispatcher.register_environment(environment_id)
        identities.append((environment_id, account["account_id"]))

    dispatcher.apply_order_book_view(_book(0, clock.value))
    for index, (environment_id, account_id) in enumerate(identities):
        status, _ = service.create_order(
            environment_id,
            OrderCreate(
                account_id=account_id,
                instrument_id=INSTRUMENT,
                side="BUY",
                order_type="MARKET",
                quantity="1",
                max_quote_budget="105",
                latency_preset="CUSTOM",
                custom_latency_ms=100,
            ),
            f"baseline-order-{environment_count}-{index}",
        )
        assert status == 201

    clock.value = 1_125
    dispatcher.apply_order_book_view(_book(1, 1_100))
    outcome = dispatcher.run_due()
    if len(outcome["executed"]) != environment_count:
        raise RuntimeError("not every deterministic baseline order executed")

    timer.reset()
    tracemalloc.start()
    rss_before = _rss_bytes()
    cpu_before = time.process_time_ns()
    event_durations_ms: list[float] = []
    wall_before = time.perf_counter_ns()
    for sequence in range(2, book_events + 2):
        clock.value += 10
        started = time.perf_counter_ns()
        dispatcher.apply_order_book_view(_book(sequence, clock.value))
        event_durations_ms.append((time.perf_counter_ns() - started) / 1_000_000)
    wall_ns = time.perf_counter_ns() - wall_before
    cpu_ns = time.process_time_ns() - cpu_before
    _, python_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    rss_after = _rss_bytes()
    transaction_values = timer.durations_ms.copy()

    fingerprints = [
        _business_fingerprint(service, engine, environment_id, account_id)
        for environment_id, account_id in identities
    ]
    within_scale_consistent = all(item == fingerprints[0] for item in fingerprints[1:])
    scheduler_lags = [
        item["orders"][0]["scheduler_lag_ms"] for item in fingerprints
    ]
    wall_seconds = wall_ns / 1_000_000_000
    metrics = {
        "environment_count": environment_count,
        "book_event_count": book_events,
        "environment_updates": environment_count * book_events,
        "cpu_usage_percent_of_one_core": round((cpu_ns / wall_ns) * 100, 3),
        "peak_rss_growth_bytes": max(0, rss_after - rss_before),
        "python_peak_traced_bytes": python_peak,
        "order_book_processing_ms": {
            "total": round(sum(event_durations_ms), 3),
            "mean": round(statistics.fmean(event_durations_ms), 3),
            "p50": round(_percentile(event_durations_ms, 0.50), 3),
            "p95": round(_percentile(event_durations_ms, 0.95), 3),
            "max": round(max(event_durations_ms), 3),
        },
        "event_processing_throughput_environment_updates_per_second": round(
            environment_count * book_events / wall_seconds, 3
        ),
        "event_queue_backlog": 0,
        "event_queue_model": "synchronous serial dispatcher; no internal input queue",
        "scheduler_lag_ms": {
            "min": min(scheduler_lags),
            "max": max(scheduler_lags),
        },
        "database_transaction_time_ms": {
            "count": len(transaction_values),
            "total": round(sum(transaction_values), 3),
            "mean": round(statistics.fmean(transaction_values), 3),
            "p95": round(_percentile(transaction_values, 0.95), 3),
            "max": round(max(transaction_values), 3),
        },
        "within_scale_business_results_consistent": within_scale_consistent,
        "dispatcher_errors": dispatcher.stats["dispatch_errors"],
    }
    return metrics, fingerprints[0]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url",
        default=os.getenv("CRYPTO_LAB_TEST_DATABASE_URL"),
        help="PostgreSQL test database URL (or CRYPTO_LAB_TEST_DATABASE_URL)",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--book-events", type=int, default=20)
    parser.add_argument("--scales", nargs="+", type=int, default=DEFAULT_SCALES)
    parser.add_argument("--confirm-reset-test-database", action="store_true")
    return parser.parse_args()


def _validate_database_target(database_url: str | None, confirmed: bool) -> str:
    if not database_url:
        raise ValueError("a PostgreSQL test database URL is required")
    database_name = make_url(database_url).database or ""
    if "test" not in database_name.lower():
        raise ValueError(
            "refusing to reset a database whose name does not contain 'test'"
        )
    if not confirmed:
        raise ValueError(
            "pass --confirm-reset-test-database to reset the test database"
        )
    return database_url


def main() -> None:
    args = _parse_args()
    try:
        database_url = _validate_database_target(
            args.database_url, args.confirm_reset_test_database
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    if args.book_events < 1 or any(scale < 1 for scale in args.scales):
        raise SystemExit("book event count and every scale must be positive")

    engine = create_engine(database_url, pool_pre_ping=True)
    timer = TransactionTimer()
    timer.install(engine)
    results: list[dict[str, Any]] = []
    reference: dict[str, Any] | None = None
    cross_scale_consistent = True
    try:
        for scale in args.scales:
            metrics, fingerprint = _run_scale(engine, timer, scale, args.book_events)
            if reference is None:
                reference = fingerprint
            else:
                matches = fingerprint == reference
                metrics["matches_single_environment_business_result"] = matches
                cross_scale_consistent = cross_scale_consistent and matches
            results.append(metrics)
    finally:
        engine.dispose()

    report = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "benchmark": "phase-1-task-1.13-order-book-scalability",
        "platform": {
            "system": platform.system(),
            "machine": platform.machine(),
            "python": platform.python_version(),
        },
        "method": {
            "database": "PostgreSQL test database",
            "market_input": "deterministic two-level canonical order book",
            "order_per_environment": "delayed market buy, quantity 1, budget 105",
            "configured_latency_ms": 100,
            "execution_delay_ms": 125,
            "warmup_book_events": 2,
            "measured_book_events": args.book_events,
        },
        "results": results,
        "business_results_consistent_across_scales": cross_scale_consistent,
        "decision": (
            "retain accepted Phase 1 serial per-environment processing limitation; "
            "do not change matching or liquidity semantics"
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
