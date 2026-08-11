"""Low-concurrency, read-only LI.FI quote collector."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
import email.utils
import json
import os
import time
from typing import Any, Awaitable, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import uuid4

from onchain_arb.adapters.lifi import LifiQuoteRequest, load_raw_quote
from onchain_arb.normalize import normalize_lifi_quote
from onchain_arb.storage import QuoteStorage


API_URL = "https://li.quest/v1/quote"
SENSITIVE_HEADERS = {"authorization", "proxy-authorization", "set-cookie"}
MAX_IN_ROUND_RETRY_DELAY_SECONDS = 30.0


@dataclass(frozen=True, slots=True)
class HttpResponse:
    status: int
    headers: Mapping[str, str]
    body: str


Transport = Callable[[str, Mapping[str, str], float], Awaitable[HttpResponse]]


@dataclass(frozen=True, slots=True)
class CollectorConfig:
    timeout_seconds: float = 30.0
    max_attempts: int = 3
    backoff_seconds: float = 1.0
    min_request_interval_seconds: float = 1.0
    concurrency: int = 2

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0 or self.backoff_seconds < 0:
            raise ValueError(
                "timeout must be positive and backoff must be non-negative"
            )
        if self.max_attempts < 1 or self.concurrency < 1:
            raise ValueError("max_attempts and concurrency must be positive")
        if self.min_request_interval_seconds < 0:
            raise ValueError("minimum request interval must be non-negative")


class _RateLimiter:
    def __init__(self, interval_seconds: float) -> None:
        self._interval_seconds = interval_seconds
        self._lock = asyncio.Lock()
        self._next_start = 0.0

    async def wait(self) -> None:
        async with self._lock:
            now = time.monotonic()
            await asyncio.sleep(max(0.0, self._next_start - now))
            self._next_start = time.monotonic() + self._interval_seconds


class QuoteCollector:
    def __init__(
        self,
        storage: QuoteStorage,
        config: CollectorConfig = CollectorConfig(),
        transport: Transport | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.storage = storage
        self.config = config
        self.transport = transport or urllib_transport
        self.sleep = sleep
        self._rate_limiter = _RateLimiter(config.min_request_interval_seconds)
        self._semaphore = asyncio.Semaphore(config.concurrency)
        self._route_cooldown_until: dict[str, float] = {}

    async def collect_round(
        self,
        universe: Mapping[str, LifiQuoteRequest],
        *,
        deadline: float | None = None,
    ) -> None:
        await asyncio.gather(
            *(
                self._collect_with_retries(route_key, request, deadline)
                for route_key, request in universe.items()
            )
        )

    async def run(
        self,
        universe: Mapping[str, LifiQuoteRequest],
        *,
        duration_seconds: float,
        polling_interval_seconds: float,
    ) -> None:
        if not 30 <= polling_interval_seconds <= 60:
            raise ValueError("polling interval must be between 30 and 60 seconds")
        if duration_seconds <= 0:
            raise ValueError("duration must be positive")
        deadline = time.monotonic() + duration_seconds
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            await self.collect_round(universe, deadline=deadline)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            await self.sleep(min(polling_interval_seconds, remaining))

    async def _collect_with_retries(
        self,
        route_key: str,
        quote_request: LifiQuoteRequest,
        deadline: float | None,
    ) -> None:
        cooldown_until = self._route_cooldown_until.get(route_key)
        if cooldown_until is not None:
            if cooldown_until > time.monotonic():
                return
            del self._route_cooldown_until[route_key]
        for attempt in range(1, self.config.max_attempts + 1):
            outcome, retry_after = await self._attempt(route_key, quote_request)
            if outcome == "success":
                self._route_cooldown_until.pop(route_key, None)
                return
            if outcome in {
                "unavailable",
                "http_error",
                "parse_failure",
            }:
                return
            if attempt == self.config.max_attempts:
                return
            delay = max(
                retry_after or 0.0,
                self.config.backoff_seconds * 2 ** (attempt - 1),
            )
            if retry_after is not None and delay > MAX_IN_ROUND_RETRY_DELAY_SECONDS:
                self._route_cooldown_until[route_key] = time.monotonic() + retry_after
                return
            if deadline is None:
                await self.sleep(delay)
                continue
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            await self.sleep(min(delay, remaining))
            if delay >= remaining:
                return

    async def _attempt(
        self, route_key: str, quote_request: LifiQuoteRequest
    ) -> tuple[str, float | None]:
        request_id = str(uuid4())
        sent_headers, recorded_headers = _request_headers(request_id)
        response: HttpResponse | None = None
        transport_error: BaseException | None = None

        async with self._semaphore:
            await self._rate_limiter.wait()
            observed_at = datetime.now(UTC)
            started_ns = time.perf_counter_ns()
            try:
                response = await asyncio.wait_for(
                    self.transport(
                        f"{API_URL}?{urlencode(quote_request.to_query())}",
                        sent_headers,
                        self.config.timeout_seconds,
                    ),
                    timeout=self.config.timeout_seconds,
                )
            except TimeoutError as error:
                transport_error = error
            except (URLError, OSError) as error:
                transport_error = error

        latency_ms = (time.perf_counter_ns() - started_ns) / 1_000_000
        envelope: dict[str, Any] = {
            "schema_version": 1,
            "request_id": request_id,
            "source": "lifi",
            "observed_at": observed_at.isoformat().replace("+00:00", "Z"),
            "latency_ms": f"{latency_ms:.3f}",
            "request": {
                "method": "GET",
                "url": API_URL,
                "query": quote_request.to_query(),
                "headers": recorded_headers,
            },
        }
        if response is not None:
            envelope["response"] = {
                "status": response.status,
                "headers": _redact_headers(response.headers),
                "body": response.body,
            }
        if transport_error is not None:
            envelope["transport_error"] = {
                "type": type(transport_error).__name__,
                "message": str(transport_error),
            }

        raw_ref = self.storage.write_raw(envelope)
        if transport_error is not None:
            outcome = (
                "timeout"
                if isinstance(transport_error, TimeoutError)
                else "transport_error"
            )
            self.storage.record_attempt(
                request_id=request_id,
                raw_ref=raw_ref,
                route_key=route_key,
                observed_at=observed_at,
                latency_ms=latency_ms,
                outcome=outcome,
                error=transport_error,
            )
            return outcome, None

        assert response is not None
        if response.status != 200:
            outcome = _http_outcome(response.status)
            self.storage.record_attempt(
                request_id=request_id,
                raw_ref=raw_ref,
                route_key=route_key,
                observed_at=observed_at,
                latency_ms=latency_ms,
                outcome=outcome,
                error=RuntimeError(f"HTTP {response.status}"),
            )
            retry_after = (
                _retry_after_seconds(response.headers)
                if response.status == 429
                else None
            )
            return outcome, retry_after

        try:
            quote = load_raw_quote(raw_ref)
            self.storage.write_normalized(normalize_lifi_quote(quote))
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            self.storage.record_attempt(
                request_id=request_id,
                raw_ref=raw_ref,
                route_key=route_key,
                observed_at=observed_at,
                latency_ms=latency_ms,
                outcome="parse_failure",
                error=error,
            )
            return "parse_failure", None

        self.storage.record_attempt(
            request_id=request_id,
            raw_ref=raw_ref,
            route_key=route_key,
            observed_at=observed_at,
            latency_ms=latency_ms,
            outcome="success",
        )
        return "success", None


async def urllib_transport(
    url: str, headers: Mapping[str, str], timeout_seconds: float
) -> HttpResponse:
    return await asyncio.to_thread(_urlopen, url, headers, timeout_seconds)


def _urlopen(
    url: str, headers: Mapping[str, str], timeout_seconds: float
) -> HttpResponse:
    request = Request(url, headers=dict(headers), method="GET")
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            return HttpResponse(
                status=response.status,
                headers=dict(response.headers.items()),
                body=response.read().decode("utf-8", errors="replace"),
            )
    except HTTPError as error:
        return HttpResponse(
            status=error.code,
            headers=dict(error.headers.items()),
            body=error.read().decode("utf-8", errors="replace"),
        )


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


def _redact_headers(headers: Mapping[str, str]) -> dict[str, str]:
    return {
        key: "<redacted>" if key.lower() in SENSITIVE_HEADERS else value
        for key, value in headers.items()
    }


def _retry_after_seconds(headers: Mapping[str, str]) -> float | None:
    value = next(
        (item for key, item in headers.items() if key.lower() == "retry-after"),
        None,
    )
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        try:
            parsed = email.utils.parsedate_to_datetime(value)
        except (TypeError, ValueError, OverflowError):
            return None
        if parsed is None:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return max(0.0, (parsed - datetime.now(UTC)).total_seconds())


def _http_outcome(status: int) -> str:
    if status == 404:
        return "unavailable"
    if status == 429:
        return "rate_limited"
    if status >= 500:
        return "server_error"
    return "http_error"
