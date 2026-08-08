#!/usr/bin/env python3
"""Fetch one synchronous, read-only 3-route x 3-size LI.FI quote probe."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import uuid4


API_URL = "https://li.quest/v1/quote"
FROM_ADDRESS = "0x000000000000000000000000000000000000dEaD"
SIZES_USDC = (100, 500, 1_000)
ROUTES = {
    "base_usdc_weth": (8453, 8453, "USDC", "WETH"),
    "arbitrum_usdc_weth": (42161, 42161, "USDC", "WETH"),
    "base_arbitrum_usdc": (8453, 42161, "USDC", "USDC"),
}
SENSITIVE_HEADERS = {"authorization", "proxy-authorization", "set-cookie"}


def _request_headers(request_id: str) -> tuple[dict[str, str], dict[str, str]]:
    sent = {
        "Accept": "application/json",
        "User-Agent": "onchain-arbitrage-study/0.1",
        "X-Request-ID": request_id,
    }
    recorded = dict(sent)
    api_key = os.environ.get("LIFI_API_KEY")
    if api_key:
        sent["x-lifi-api-key"] = api_key
        recorded["x-lifi-api-key"] = "<redacted>"
    return sent, recorded


def _recorded_response_headers(headers: Any) -> dict[str, str]:
    return {
        key: "<redacted>" if key.lower() in SENSITIVE_HEADERS else value
        for key, value in headers.items()
    }


def fetch_quote(query: dict[str, str], output_path: Path) -> None:
    request_id = str(uuid4())
    sent_headers, recorded_headers = _request_headers(request_id)
    request_url = f"{API_URL}?{urlencode(query)}"
    request = Request(request_url, headers=sent_headers, method="GET")
    started_at = datetime.now(UTC)
    start = time.perf_counter_ns()
    response_record: dict[str, Any] | None = None
    transport_error: dict[str, str] | None = None

    try:
        with urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8")
            response_record = {
                "status": response.status,
                "headers": _recorded_response_headers(response.headers),
                "body": body,
            }
    except HTTPError as error:
        response_record = {
            "status": error.code,
            "headers": _recorded_response_headers(error.headers),
            "body": error.read().decode("utf-8", errors="replace"),
        }
    except (URLError, TimeoutError) as error:
        transport_error = {"type": type(error).__name__, "message": str(error)}

    latency_ms = (time.perf_counter_ns() - start) / 1_000_000
    envelope: dict[str, Any] = {
        "schema_version": 1,
        "request_id": request_id,
        "source": "lifi",
        "observed_at": started_at.isoformat().replace("+00:00", "Z"),
        "latency_ms": f"{latency_ms:.3f}",
        "request": {
            "method": "GET",
            "url": API_URL,
            "query": query,
            "headers": recorded_headers,
        },
    }
    if response_record is not None:
        envelope["response"] = response_record
    if transport_error is not None:
        envelope["transport_error"] = transport_error

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("x") as raw_file:
        json.dump(envelope, raw_file, indent=2, sort_keys=True)
        raw_file.write("\n")

    if transport_error is not None:
        raise RuntimeError(f"transport failure saved to {output_path}")
    if response_record is None or response_record["status"] != 200:
        status = None if response_record is None else response_record["status"]
        raise RuntimeError(f"HTTP {status} saved to {output_path}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/raw/lifi"),
        help="append-only raw evidence directory",
    )
    parser.add_argument(
        "--fixture-names",
        action="store_true",
        help="use stable route/size names; refuses to overwrite existing fixtures",
    )
    args = parser.parse_args()

    failures = 0
    for route_name, (from_chain, to_chain, from_token, to_token) in ROUTES.items():
        for size_usdc in SIZES_USDC:
            query = {
                "fromChain": str(from_chain),
                "toChain": str(to_chain),
                "fromToken": from_token,
                "toToken": to_token,
                "fromAmount": str(size_usdc * 1_000_000),
                "fromAddress": FROM_ADDRESS,
                "slippage": "0.005",
            }
            if args.fixture_names:
                filename = f"{route_name}_{size_usdc}_usdc.json"
            else:
                timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
                filename = f"{timestamp}_{route_name}_{size_usdc}_usdc.json"
            path = args.output_dir / filename
            try:
                fetch_quote(query, path)
                print(f"saved {path}")
            except RuntimeError as error:
                failures += 1
                print(f"failed: {error}")

    if failures:
        raise SystemExit(f"{failures} of 9 quote requests failed")


if __name__ == "__main__":
    main()
