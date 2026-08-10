#!/usr/bin/env python3
"""Capture read-only EVM head context, optionally anchored to a fresh LI.FI quote."""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal
import json
import os
from pathlib import Path
from typing import Any

from onchain_arb.adapters.lifi import LifiQuote, load_raw_quote
from onchain_arb.adapters.rpc import RpcChainConfig
from onchain_arb.block_context import capture_block_context, load_chain_config


async def capture(args: argparse.Namespace) -> None:
    configs = load_chain_config(args.config)
    quote = _load_fresh_quote(args.quote_raw, args.max_quote_age)
    selected = _select_chains(configs, args.chain, quote)
    rpc_urls = _rpc_urls(selected)

    contexts = []
    for chain in selected:
        contexts.append(
            await capture_block_context(
                chain,
                rpc_urls[chain.name],
                args.raw_dir,
                quote_request_id=None if quote is None else quote.request_id,
                quote_observed_at=None if quote is None else quote.observed_at,
                timeout_seconds=args.timeout,
            )
        )
    print(json.dumps([_json_context(item) for item in contexts], indent=2))


def _load_fresh_quote(
    path: Path | None, max_age_seconds: float | None
) -> LifiQuote | None:
    if path is None:
        return None
    if max_age_seconds is None or max_age_seconds <= 0:
        raise ValueError("a positive --max-quote-age is required with --quote-raw")
    quote = load_raw_quote(path)
    age_seconds = (datetime.now(UTC) - quote.observed_at).total_seconds()
    if age_seconds < 0 or age_seconds > max_age_seconds:
        raise ValueError(
            f"quote is {age_seconds:.3f}s old; maximum is {max_age_seconds:.3f}s"
        )
    return quote


def _select_chains(
    configs: tuple[RpcChainConfig, ...],
    requested_names: list[str] | None,
    quote: LifiQuote | None,
) -> tuple[RpcChainConfig, ...]:
    by_name = {item.name: item for item in configs}
    by_id = {item.chain_id: item for item in configs}
    if requested_names:
        unknown = sorted(set(requested_names) - by_name.keys())
        if unknown:
            raise ValueError(f"unknown configured chains: {', '.join(unknown)}")
        return tuple(by_name[name] for name in dict.fromkeys(requested_names))
    if quote is None:
        return configs
    quote_chain_ids = dict.fromkeys(
        (quote.request.from_chain_id, quote.request.to_chain_id)
    )
    missing = [chain_id for chain_id in quote_chain_ids if chain_id not in by_id]
    if missing:
        raise ValueError(f"quote chain IDs are not configured: {missing}")
    return tuple(by_id[chain_id] for chain_id in quote_chain_ids)


def _rpc_urls(configs: tuple[RpcChainConfig, ...]) -> dict[str, str]:
    missing = [
        item.rpc_url_env for item in configs if not os.environ.get(item.rpc_url_env)
    ]
    if missing:
        raise ValueError(f"missing RPC URL environment variables: {', '.join(missing)}")
    return {item.name: os.environ[item.rpc_url_env] for item in configs}


def _json_context(context: Any) -> dict[str, Any]:
    result = asdict(context)
    for key, value in tuple(result.items()):
        if isinstance(value, datetime):
            result[key] = value.isoformat().replace("+00:00", "Z")
        elif isinstance(value, Decimal):
            result[key] = str(value)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("config/rpc.toml"))
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw/rpc"))
    parser.add_argument(
        "--quote-raw",
        type=Path,
        help="fresh raw LI.FI quote; defaults to its involved chains",
    )
    parser.add_argument(
        "--chain",
        action="append",
        help="configured chain name; repeat as needed (defaults to all without a quote)",
    )
    parser.add_argument(
        "--max-quote-age",
        type=float,
        help="required explicit freshness bound in seconds when --quote-raw is used",
    )
    parser.add_argument("--timeout", type=float, default=10.0)
    asyncio.run(capture(parser.parse_args()))


if __name__ == "__main__":
    main()
