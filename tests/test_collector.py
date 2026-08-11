"""Day 5 collector, lineage, restart, retry, and metrics tests."""

from __future__ import annotations

import asyncio
from decimal import Decimal
import json
from pathlib import Path
import time

import duckdb

from onchain_arb.adapters.lifi import LifiQuoteRequest
from onchain_arb.collector import CollectorConfig, HttpResponse, QuoteCollector
from onchain_arb.storage import QuoteStorage


FIXTURE = Path(__file__).parent / "fixtures/lifi/base_usdc_weth_100_usdc.json"


def _request() -> LifiQuoteRequest:
    query = json.loads(FIXTURE.read_text())["request"]["query"]
    return LifiQuoteRequest(
        from_chain_id=int(query["fromChain"]),
        to_chain_id=int(query["toChain"]),
        from_token=query["fromToken"],
        to_token=query["toToken"],
        from_amount_raw=int(query["fromAmount"]),
        from_address=query["fromAddress"],
        to_address=query.get("toAddress"),
        slippage=Decimal(query["slippage"]),
    )


def _storage(tmp_path: Path) -> QuoteStorage:
    return QuoteStorage(
        tmp_path / "raw", tmp_path / "normalized", tmp_path / "quotes.duckdb"
    )


def _config(max_attempts: int = 3) -> CollectorConfig:
    return CollectorConfig(
        timeout_seconds=1,
        max_attempts=max_attempts,
        backoff_seconds=0.01,
        min_request_interval_seconds=0,
        concurrency=2,
    )


def _success_response() -> HttpResponse:
    envelope = json.loads(FIXTURE.read_text())
    return HttpResponse(200, {}, envelope["response"]["body"])


def test_success_is_raw_first_and_has_duckdb_parquet_lineage(tmp_path: Path) -> None:
    async def transport(url: str, headers: dict[str, str], timeout: float) -> HttpResponse:
        return _success_response()

    storage = _storage(tmp_path)
    collector = QuoteCollector(storage, _config(), transport=transport)
    asyncio.run(collector.collect_round({"base_usdc_weth_100": _request()}))

    raw_paths = list((tmp_path / "raw").rglob("*.json"))
    parquet_paths = list((tmp_path / "normalized").rglob("*.parquet"))
    assert len(raw_paths) == len(parquet_paths) == 1
    raw_envelope = json.loads(raw_paths[0].read_text())

    with duckdb.connect(str(tmp_path / "quotes.duckdb")) as connection:
        connection.execute("SET TimeZone = 'UTC'")
        row = connection.execute(
            "SELECT request_id, raw_ref, from_amount_raw, observed_at FROM normalized_quotes"
        ).fetchone()
        parquet_row = connection.execute(
            "SELECT request_id, raw_ref FROM read_parquet(?)", [str(parquet_paths[0])]
        ).fetchone()
    assert row is not None
    assert row[0] == raw_envelope["request_id"]
    assert row[1] == str(raw_paths[0].resolve())
    assert row[2] == "100000000"
    assert row[3].utcoffset().total_seconds() == 0
    assert parquet_row == row[:2]
    assert storage.metrics().success_count == 1


def test_restart_appends_without_overwriting(tmp_path: Path) -> None:
    async def transport(url: str, headers: dict[str, str], timeout: float) -> HttpResponse:
        return _success_response()

    first = QuoteCollector(_storage(tmp_path), _config(), transport=transport)
    asyncio.run(first.collect_round({"route": _request()}))
    first_path = next((tmp_path / "raw").rglob("*.json"))
    first_raw = first_path.read_bytes()

    restarted_storage = _storage(tmp_path)
    restarted = QuoteCollector(restarted_storage, _config(), transport=transport)
    asyncio.run(restarted.collect_round({"route": _request()}))

    assert len(list((tmp_path / "raw").rglob("*.json"))) == 2
    assert len(list((tmp_path / "normalized").rglob("*.parquet"))) == 2
    assert first_path.read_bytes() == first_raw
    assert restarted_storage.metrics().request_count == 2


def test_timeout_and_rate_limit_are_saved_and_retried(tmp_path: Path) -> None:
    responses: list[object] = [
        TimeoutError("timed out"),
        HttpResponse(429, {"Retry-After": "2"}, "rate limited"),
        _success_response(),
    ]
    sleeps: list[float] = []

    async def transport(url: str, headers: dict[str, str], timeout: float) -> HttpResponse:
        result = responses.pop(0)
        if isinstance(result, BaseException):
            raise result
        assert isinstance(result, HttpResponse)
        return result

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    storage = _storage(tmp_path)
    collector = QuoteCollector(storage, _config(), transport=transport, sleep=fake_sleep)
    asyncio.run(collector.collect_round({"route": _request()}))

    metrics = storage.metrics()
    assert metrics.request_count == 3
    assert metrics.timeout_count == 1
    assert metrics.rate_limited_count == 1
    assert metrics.success_count == 1
    assert sleeps == [0.01, 2.0]
    assert len(list((tmp_path / "raw").rglob("*.json"))) == 3


def test_parse_failure_is_explicit_and_not_normalized(tmp_path: Path) -> None:
    async def transport(url: str, headers: dict[str, str], timeout: float) -> HttpResponse:
        return HttpResponse(200, {}, "{not-json")

    storage = _storage(tmp_path)
    collector = QuoteCollector(storage, _config(), transport=transport)
    asyncio.run(collector.collect_round({"route": _request()}))

    metrics = storage.metrics()
    assert metrics.request_count == metrics.parse_failure_count == 1
    assert not list((tmp_path / "normalized").rglob("*.parquet"))
    assert len(list((tmp_path / "raw").rglob("*.json"))) == 1


def test_polling_interval_is_constrained_to_acceptance_range(tmp_path: Path) -> None:
    collector = QuoteCollector(_storage(tmp_path), _config())
    try:
        asyncio.run(
            collector.run({}, duration_seconds=1, polling_interval_seconds=29)
        )
    except ValueError as error:
        assert "between 30 and 60" in str(error)
    else:
        raise AssertionError("invalid polling interval was accepted")


def test_run_deadline_bounds_long_retry_after_without_losing_raw(tmp_path: Path) -> None:
    async def transport(url: str, headers: dict[str, str], timeout: float) -> HttpResponse:
        return HttpResponse(429, {"Retry-After": "3600"}, "rate limited")

    storage = _storage(tmp_path)
    collector = QuoteCollector(storage, _config(), transport=transport)
    started = time.monotonic()
    asyncio.run(
        collector.run(
            {"route": _request()},
            duration_seconds=0.01,
            polling_interval_seconds=30,
        )
    )

    assert time.monotonic() - started < 0.5
    assert storage.metrics().request_count == 1
    assert storage.metrics().rate_limited_count == 1
    assert len(list((tmp_path / "raw").rglob("*.json"))) == 1


def test_long_retry_after_cools_route_without_blocking_collection(tmp_path: Path) -> None:
    calls = 0

    async def transport(url: str, headers: dict[str, str], timeout: float) -> HttpResponse:
        nonlocal calls
        calls += 1
        return HttpResponse(429, {"Retry-After": "3600"}, "rate limited")

    storage = _storage(tmp_path)
    collector = QuoteCollector(storage, _config(), transport=transport)
    started = time.monotonic()
    asyncio.run(collector.collect_round({"cooling-route": _request()}))
    asyncio.run(collector.collect_round({"cooling-route": _request()}))

    assert time.monotonic() - started < 0.5
    assert calls == 1
    assert storage.metrics().request_count == 1
    assert storage.metrics().rate_limited_count == 1
    assert len(list((tmp_path / "raw").rglob("*.json"))) == 1
