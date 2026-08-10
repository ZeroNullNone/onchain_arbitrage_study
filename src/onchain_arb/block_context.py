"""Verified chain-head context aligned to an optional direct quote observation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
import json
from pathlib import Path
import re
import tomllib
from typing import Any, Mapping

from onchain_arb.adapters.rpc import (
    RpcChainConfig,
    RpcTransport,
    capture_raw_chain_head,
)
from onchain_arb.storage import append_raw_envelope


_HEX_QUANTITY = re.compile(r"^0x(?:0|[1-9a-fA-F][0-9a-fA-F]*)$")
_BLOCK_HASH = re.compile(r"^0x[0-9a-fA-F]{64}$")


@dataclass(frozen=True, slots=True)
class BlockContext:
    observation_id: str
    raw_ref: str
    chain_name: str
    chain_id: int
    chain_head_block_number: int
    block_number: int
    block_hash: str
    block_timestamp: datetime
    base_fee_per_gas_wei: int
    observed_at: datetime
    latency_ms: Decimal
    quote_request_id: str | None
    quote_observed_at: datetime | None
    quote_to_rpc_ms: Decimal | None

    def __post_init__(self) -> None:
        if not self.observation_id or not self.raw_ref or not self.chain_name:
            raise ValueError("block context IDs, raw_ref, and chain name are required")
        if self.chain_id <= 0 or self.chain_head_block_number < 0:
            raise ValueError("chain ID and head block number are invalid")
        if self.block_number != self.chain_head_block_number:
            raise ValueError("exact block does not match the reported chain head")
        if _BLOCK_HASH.fullmatch(self.block_hash) is None:
            raise ValueError("block hash is invalid")
        if self.base_fee_per_gas_wei < 0 or self.latency_ms < 0:
            raise ValueError("base fee and latency must be non-negative")
        _require_utc(self.block_timestamp, "block_timestamp")
        _require_utc(self.observed_at, "observed_at")
        if (self.quote_request_id is None) != (self.quote_observed_at is None):
            raise ValueError("quote ID and timestamp must either both exist or both be absent")
        if (self.quote_request_id is None) != (self.quote_to_rpc_ms is None):
            raise ValueError("quote alignment is incomplete")
        if self.quote_observed_at is not None:
            _require_utc(self.quote_observed_at, "quote_observed_at")


async def capture_block_context(
    chain: RpcChainConfig,
    rpc_url: str,
    raw_dir: Path,
    *,
    quote_request_id: str | None = None,
    quote_observed_at: datetime | None = None,
    timeout_seconds: float = 10.0,
    transport: RpcTransport | None = None,
) -> BlockContext:
    """Persist raw RPC evidence first, then return its verified normalized context."""

    envelope = await capture_raw_chain_head(
        chain,
        rpc_url,
        quote_request_id=quote_request_id,
        quote_observed_at=quote_observed_at,
        timeout_seconds=timeout_seconds,
        transport=transport,
    )
    raw_ref = append_raw_envelope(raw_dir, envelope)
    return load_raw_block_context(raw_ref)


def load_raw_block_context(path: str | Path) -> BlockContext:
    """Rebuild and validate one block context from append-only RPC evidence."""

    raw_path = Path(path)
    envelope = json.loads(raw_path.read_text(), parse_float=Decimal)
    if envelope.get("schema_version") != 1 or envelope.get("source") != "evm_rpc":
        raise ValueError("unsupported EVM RPC raw envelope")
    if "collection_error" in envelope:
        raise ValueError(f"RPC collection failed: {envelope['collection_error']!r}")

    chain = _mapping(envelope, "chain")
    exchanges = envelope.get("exchanges")
    if not isinstance(exchanges, list) or len(exchanges) != 3:
        raise ValueError("RPC block context requires exactly three exchanges")
    expected_methods = (
        "eth_chainId",
        "eth_blockNumber",
        "eth_getBlockByNumber",
    )
    results: list[Any] = []
    request_payloads: list[Mapping[str, Any]] = []
    for exchange, expected_method in zip(exchanges, expected_methods, strict=True):
        request_payload, result = _parse_exchange(exchange, expected_method)
        request_payloads.append(request_payload)
        results.append(result)

    chain_id = _hex_quantity(results[0], "chain ID")
    expected_chain_id = _positive_integer(chain, "expected_chain_id")
    if chain_id != expected_chain_id:
        raise ValueError(
            f"RPC chain ID {chain_id} does not match configured {expected_chain_id}"
        )
    head_block_number = _hex_quantity(results[1], "chain head")
    block = results[2]
    if not isinstance(block, dict):
        raise TypeError("eth_getBlockByNumber result must be an object")
    block_number = _hex_quantity(block.get("number"), "block number")
    if block_number != head_block_number:
        raise ValueError("returned block does not match eth_blockNumber head")
    block_request_params = request_payloads[2].get("params")
    if block_request_params != [results[1], False]:
        raise ValueError("exact head block was not requested")

    block_hash = block.get("hash")
    if not isinstance(block_hash, str):
        raise TypeError("block hash must be a string")
    block_timestamp = datetime.fromtimestamp(
        _hex_quantity(block.get("timestamp"), "block timestamp"),
        tz=UTC,
    )
    base_fee = _hex_quantity(block.get("baseFeePerGas"), "base fee")
    observed_at = _utc_datetime(envelope.get("observed_at"), "observed_at")
    quote_anchor = envelope.get("quote_anchor")
    quote_request_id: str | None = None
    quote_observed_at: datetime | None = None
    quote_to_rpc_ms: Decimal | None = None
    if quote_anchor is not None:
        if not isinstance(quote_anchor, dict):
            raise TypeError("quote_anchor must be an object or null")
        quote_request_id = _nonempty_string(quote_anchor, "request_id")
        quote_observed_at = _utc_datetime(
            quote_anchor.get("observed_at"), "quote observed_at"
        )
        difference = observed_at - quote_observed_at
        quote_to_rpc_ms = Decimal(
            difference.days * 86_400_000 + difference.seconds * 1_000
        ) + Decimal(difference.microseconds) / Decimal(1_000)

    return BlockContext(
        observation_id=_nonempty_string(envelope, "request_id"),
        raw_ref=str(raw_path),
        chain_name=_nonempty_string(chain, "name"),
        chain_id=chain_id,
        chain_head_block_number=head_block_number,
        block_number=block_number,
        block_hash=block_hash,
        block_timestamp=block_timestamp,
        base_fee_per_gas_wei=base_fee,
        observed_at=observed_at,
        latency_ms=Decimal(str(envelope["latency_ms"])),
        quote_request_id=quote_request_id,
        quote_observed_at=quote_observed_at,
        quote_to_rpc_ms=quote_to_rpc_ms,
    )


def load_chain_config(path: str | Path) -> tuple[RpcChainConfig, ...]:
    """Load the committed non-secret three-chain RPC configuration."""

    with Path(path).open("rb") as source:
        document = tomllib.load(source)
    values = document.get("chains")
    if not isinstance(values, list) or not values:
        raise ValueError("RPC config must contain [[chains]] entries")
    configs = tuple(
        RpcChainConfig(
            name=_nonempty_string(value, "name"),
            chain_id=_positive_integer(value, "chain_id"),
            rpc_url_env=_nonempty_string(value, "rpc_url_env"),
        )
        for value in values
        if isinstance(value, dict)
    )
    if len(configs) != len(values):
        raise TypeError("each RPC chain config must be an object")
    if len({item.name for item in configs}) != len(configs):
        raise ValueError("RPC chain names must be unique")
    if len({item.chain_id for item in configs}) != len(configs):
        raise ValueError("RPC chain IDs must be unique")
    return configs


def _parse_exchange(
    value: Any, expected_method: str
) -> tuple[Mapping[str, Any], Any]:
    if not isinstance(value, dict):
        raise TypeError("RPC exchange must be an object")
    if "transport_error" in value:
        raise ValueError(f"RPC transport failed: {value['transport_error']!r}")
    request = _mapping(value, "request")
    response = _mapping(value, "response")
    if response.get("status") != 200:
        raise ValueError(f"{expected_method} HTTP status is {response.get('status')!r}")
    request_payload = json.loads(_nonempty_string(request, "body"))
    response_payload = json.loads(_nonempty_string(response, "body"))
    if not isinstance(request_payload, dict) or not isinstance(response_payload, dict):
        raise TypeError("JSON-RPC request and response bodies must be objects")
    if request_payload.get("method") != expected_method:
        raise ValueError(f"expected {expected_method} RPC request")
    if response_payload.get("id") != request_payload.get("id"):
        raise ValueError(f"{expected_method} response ID mismatch")
    if response_payload.get("jsonrpc") != "2.0":
        raise ValueError(f"{expected_method} JSON-RPC version mismatch")
    if "error" in response_payload:
        raise ValueError(f"{expected_method} RPC error: {response_payload['error']!r}")
    if "result" not in response_payload:
        raise ValueError(f"{expected_method} response has no result")
    return request_payload, response_payload["result"]


def _hex_quantity(value: Any, label: str) -> int:
    if not isinstance(value, str) or _HEX_QUANTITY.fullmatch(value) is None:
        raise ValueError(f"{label} must be a canonical hex quantity")
    return int(value, 16)


def _mapping(value: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    nested = value.get(key)
    if not isinstance(nested, dict):
        raise TypeError(f"{key} must be an object")
    return nested


def _nonempty_string(value: Mapping[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise ValueError(f"{key} must be a non-empty string")
    return item


def _positive_integer(value: Mapping[str, Any], key: str) -> int:
    item = value.get(key)
    if not isinstance(item, int) or isinstance(item, bool) or item <= 0:
        raise ValueError(f"{key} must be a positive integer")
    return item


def _utc_datetime(value: Any, label: str) -> datetime:
    if not isinstance(value, str):
        raise TypeError(f"{label} must be a timestamp string")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    _require_utc(result, label)
    return result


def _require_utc(value: datetime, label: str) -> None:
    offset = value.utcoffset()
    if offset is None or offset.total_seconds() != 0:
        raise ValueError(f"{label} must be UTC")
