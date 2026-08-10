"""Read-only EVM JSON-RPC capture with complete raw exchanges."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
import json
import time
from typing import Any, Awaitable, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4


SENSITIVE_HEADER_FRAGMENTS = ("authorization", "cookie", "api-key", "token")


@dataclass(frozen=True, slots=True)
class RpcChainConfig:
    name: str
    chain_id: int
    rpc_url_env: str

    def __post_init__(self) -> None:
        if not self.name or self.chain_id <= 0 or not self.rpc_url_env:
            raise ValueError("RPC chain name, positive chain ID, and URL env are required")


@dataclass(frozen=True, slots=True)
class RpcHttpResponse:
    status: int
    headers: Mapping[str, str]
    body: str


RpcTransport = Callable[
    [str, Mapping[str, str], str, float], Awaitable[RpcHttpResponse]
]


async def capture_raw_chain_head(
    chain: RpcChainConfig,
    rpc_url: str,
    *,
    quote_request_id: str | None = None,
    quote_observed_at: datetime | None = None,
    timeout_seconds: float = 10.0,
    transport: RpcTransport | None = None,
) -> dict[str, Any]:
    """Capture chain ID, reported head, and that exact block without persisting secrets."""

    if not rpc_url:
        raise ValueError(f"RPC URL from {chain.rpc_url_env} is empty")
    if timeout_seconds <= 0:
        raise ValueError("RPC timeout must be positive")
    if (quote_request_id is None) != (quote_observed_at is None):
        raise ValueError("quote request ID and observed_at must be supplied together")
    if quote_observed_at is not None:
        if quote_observed_at.utcoffset() is None:
            raise ValueError("quote observed_at must be timezone-aware")
        quote_observed_at = quote_observed_at.astimezone(UTC)

    rpc_transport = transport or urllib_rpc_transport
    request_id = str(uuid4())
    observed_at = datetime.now(UTC)
    started_ns = time.perf_counter_ns()
    envelope: dict[str, Any] = {
        "schema_version": 1,
        "source": "evm_rpc",
        "request_id": request_id,
        "observed_at": _utc_text(observed_at),
        "chain": {
            "name": chain.name,
            "expected_chain_id": chain.chain_id,
            "rpc_url_env": chain.rpc_url_env,
        },
        "quote_anchor": (
            None
            if quote_request_id is None
            else {
                "request_id": quote_request_id,
                "observed_at": _utc_text(quote_observed_at),
            }
        ),
        "exchanges": [],
    }

    async def call(method: str, params: list[Any]) -> Any:
        rpc_id = f"{request_id}:{len(envelope['exchanges']) + 1}"
        payload = {"jsonrpc": "2.0", "id": rpc_id, "method": method, "params": params}
        response, exchange = await _capture_exchange(
            rpc_url,
            chain.rpc_url_env,
            request_id,
            payload,
            timeout_seconds,
            rpc_transport,
        )
        envelope["exchanges"].append(exchange)
        if response is None:
            raise ValueError(f"{method} transport failed")
        return _response_result(response, rpc_id, method)

    try:
        await call("eth_chainId", [])
        head_hex = await call("eth_blockNumber", [])
        if not isinstance(head_hex, str):
            raise ValueError("eth_blockNumber result must be a hex string")
        await call("eth_getBlockByNumber", [head_hex, False])
    except (json.JSONDecodeError, TypeError, ValueError) as error:
        envelope["collection_error"] = {
            "type": type(error).__name__,
            "message": str(error),
        }

    envelope["latency_ms"] = f"{(time.perf_counter_ns() - started_ns) / 1_000_000:.3f}"
    return envelope


async def _capture_exchange(
    rpc_url: str,
    rpc_url_env: str,
    request_id: str,
    payload: Mapping[str, Any],
    timeout_seconds: float,
    transport: RpcTransport,
) -> tuple[RpcHttpResponse | None, dict[str, Any]]:
    requested_at = datetime.now(UTC)
    started_ns = time.perf_counter_ns()
    response: RpcHttpResponse | None = None
    transport_error: BaseException | None = None
    body = json.dumps(payload, separators=(",", ":"))
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "onchain-arbitrage-study/0.1",
        "X-Request-ID": request_id,
    }
    try:
        response = await asyncio.wait_for(
            transport(rpc_url, headers, body, timeout_seconds),
            timeout=timeout_seconds,
        )
    except TimeoutError as error:
        transport_error = error
    except (URLError, OSError) as error:
        transport_error = error

    exchange: dict[str, Any] = {
        "requested_at": _utc_text(requested_at),
        "latency_ms": f"{(time.perf_counter_ns() - started_ns) / 1_000_000:.3f}",
        "request": {
            "method": "POST",
            "endpoint_env": rpc_url_env,
            "headers": headers,
            "body": body,
        },
    }
    if response is not None:
        exchange["response"] = {
            "status": response.status,
            "headers": _redact_headers(response.headers),
            "body": response.body,
        }
    if transport_error is not None:
        exchange["transport_error"] = {
            "type": type(transport_error).__name__,
            "message": str(transport_error).replace(rpc_url, "<redacted>"),
        }
    return response, exchange


def _response_result(response: RpcHttpResponse, rpc_id: str, method: str) -> Any:
    if response.status != 200:
        raise ValueError(f"{method} HTTP status is {response.status}")
    payload = json.loads(response.body)
    if not isinstance(payload, dict):
        raise TypeError(f"{method} response must be an object")
    if payload.get("id") != rpc_id or payload.get("jsonrpc") != "2.0":
        raise ValueError(f"{method} response identity mismatch")
    if "error" in payload:
        raise ValueError(f"{method} RPC error: {payload['error']!r}")
    if "result" not in payload:
        raise ValueError(f"{method} response has no result")
    return payload["result"]


async def urllib_rpc_transport(
    url: str, headers: Mapping[str, str], body: str, timeout_seconds: float
) -> RpcHttpResponse:
    return await asyncio.to_thread(_urlopen, url, headers, body, timeout_seconds)


def _urlopen(
    url: str, headers: Mapping[str, str], body: str, timeout_seconds: float
) -> RpcHttpResponse:
    request = Request(
        url,
        data=body.encode("utf-8"),
        headers=dict(headers),
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            return RpcHttpResponse(
                status=response.status,
                headers=dict(response.headers.items()),
                body=response.read().decode("utf-8", errors="replace"),
            )
    except HTTPError as error:
        return RpcHttpResponse(
            status=error.code,
            headers=dict(error.headers.items()),
            body=error.read().decode("utf-8", errors="replace"),
        )


def _redact_headers(headers: Mapping[str, str]) -> dict[str, str]:
    return {
        key: (
            "<redacted>"
            if any(fragment in key.lower() for fragment in SENSITIVE_HEADER_FRAGMENTS)
            else value
        )
        for key, value in headers.items()
    }


def _utc_text(value: datetime | None) -> str:
    assert value is not None
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
