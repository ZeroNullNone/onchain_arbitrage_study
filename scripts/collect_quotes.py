#!/usr/bin/env python3
"""Run the Day 5 read-only fixed-universe LI.FI quote collector."""

from __future__ import annotations

import argparse
import asyncio
from decimal import Decimal
import json
from pathlib import Path

from onchain_arb.adapters.lifi import LifiQuoteRequest
from onchain_arb.collector import CollectorConfig, QuoteCollector
from onchain_arb.storage import QuoteStorage


FROM_ADDRESS = "0x000000000000000000000000000000000000dEaD"
SIZES_USDC = (100, 500, 1_000)
ROUTES = {
    "base_usdc_weth": (8453, 8453, "USDC", "WETH"),
    "arbitrum_usdc_weth": (42161, 42161, "USDC", "WETH"),
    "base_arbitrum_usdc": (8453, 42161, "USDC", "USDC"),
}


def fixed_universe() -> dict[str, LifiQuoteRequest]:
    return {
        f"{route_name}_{size}_usdc": LifiQuoteRequest(
            from_chain_id=from_chain,
            to_chain_id=to_chain,
            from_token=from_token,
            to_token=to_token,
            from_amount_raw=size * 1_000_000,
            from_address=FROM_ADDRESS,
            to_address=None,
            slippage=Decimal("0.005"),
        )
        for route_name, (from_chain, to_chain, from_token, to_token) in ROUTES.items()
        for size in SIZES_USDC
    }


async def collect(args: argparse.Namespace) -> None:
    storage = QuoteStorage(args.raw_dir, args.normalized_dir, args.database)
    collector = QuoteCollector(
        storage,
        CollectorConfig(
            timeout_seconds=args.timeout,
            max_attempts=args.max_attempts,
            backoff_seconds=args.backoff,
            min_request_interval_seconds=args.min_request_interval,
            concurrency=args.concurrency,
        ),
    )
    if args.once:
        await collector.collect_round(fixed_universe())
    else:
        await collector.run(
            fixed_universe(),
            duration_seconds=args.duration,
            polling_interval_seconds=args.poll_interval,
        )
    metrics = storage.metrics()
    print(
        json.dumps(
            {
                "request_count": metrics.request_count,
                "success_count": metrics.success_count,
                "success_rate": metrics.success_rate,
                "parse_failure_count": metrics.parse_failure_count,
                "timeout_count": metrics.timeout_count,
                "rate_limited_count": metrics.rate_limited_count,
                "p50_latency_ms": metrics.p50_latency_ms,
                "p95_latency_ms": metrics.p95_latency_ms,
                "unavailable_route_count": metrics.unavailable_route_count,
            },
            indent=2,
            sort_keys=True,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw/lifi"))
    parser.add_argument(
        "--normalized-dir", type=Path, default=Path("data/normalized/lifi")
    )
    parser.add_argument(
        "--database", type=Path, default=Path("data/normalized/quotes.duckdb")
    )
    parser.add_argument("--duration", type=float, default=2 * 60 * 60)
    parser.add_argument("--poll-interval", type=float, default=45.0)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--backoff", type=float, default=1.0)
    parser.add_argument("--min-request-interval", type=float, default=1.0)
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument(
        "--once", action="store_true", help="collect one round instead of two hours"
    )
    asyncio.run(collect(parser.parse_args()))


if __name__ == "__main__":
    main()
