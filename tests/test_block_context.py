"""Day 6 raw RPC parsing, chain verification, UTC, and lineage tests."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import json
from pathlib import Path
from urllib.error import URLError

import pytest

from onchain_arb.adapters.rpc import RpcChainConfig, RpcHttpResponse
from onchain_arb.block_context import (
    capture_block_context,
    load_chain_config,
    load_raw_block_context,
)


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "rpc"
EXPECTED = {
    "base_head.json": ("base", 8453, 49_774_002, 5_000_000),
    "arbitrum_head.json": ("arbitrum", 42161, 492_968_364, 20_006_000),
    "optimism_head.json": ("optimism", 10, 155_369_288, 365),
}


@pytest.mark.parametrize("filename", EXPECTED)
def test_raw_fixture_verifies_hex_integer_utc_and_chain_id(filename: str) -> None:
    path = FIXTURE_DIR / filename
    context = load_raw_block_context(path)
    name, chain_id, block_number, base_fee = EXPECTED[filename]

    assert context.raw_ref == str(path)
    assert context.chain_name == name
    assert context.chain_id == chain_id
    assert context.chain_head_block_number == block_number
    assert context.block_number == block_number
    assert context.base_fee_per_gas_wei == base_fee
    assert len(context.block_hash) == 66
    assert context.block_timestamp.utcoffset().total_seconds() == 0
    assert context.observed_at.utcoffset().total_seconds() == 0
    assert context.quote_request_id is None
    assert context.quote_to_rpc_ms is None

    envelope = json.loads(path.read_text())
    methods = [
        json.loads(exchange["request"]["body"])["method"]
        for exchange in envelope["exchanges"]
    ]
    assert methods == ["eth_chainId", "eth_blockNumber", "eth_getBlockByNumber"]
    block_request = json.loads(envelope["exchanges"][2]["request"]["body"])
    head_result = json.loads(envelope["exchanges"][1]["response"]["body"])[
        "result"
    ]
    assert block_request["params"] == [head_result, False]


def test_capture_is_raw_first_quote_aligned_and_does_not_persist_rpc_url(
    tmp_path: Path,
) -> None:
    chain = RpcChainConfig("base", 8453, "BASE_RPC_URL")
    quote_observed_at = datetime.now(UTC)

    async def transport(
        url: str, headers: dict[str, str], body: str, timeout: float
    ) -> RpcHttpResponse:
        request = json.loads(body)
        results = {
            "eth_chainId": "0x2105",
            "eth_blockNumber": "0x10",
            "eth_getBlockByNumber": {
                "number": "0x10",
                "timestamp": "0x6a795847",
                "baseFeePerGas": "0x4c4b40",
                "hash": "0x" + "ab" * 32,
            },
        }
        response = {
            "jsonrpc": "2.0",
            "id": request["id"],
            "result": results[request["method"]],
        }
        return RpcHttpResponse(200, {"Set-Cookie": "secret"}, json.dumps(response))

    context = asyncio.run(
        capture_block_context(
            chain,
            "https://provider.example/v2/credential",
            tmp_path / "raw",
            quote_request_id="quote-123",
            quote_observed_at=quote_observed_at,
            transport=transport,
        )
    )

    raw_paths = list((tmp_path / "raw").rglob("*.json"))
    assert len(raw_paths) == 1
    raw_text = raw_paths[0].read_text()
    assert context.raw_ref == str(raw_paths[0].resolve())
    assert context.quote_request_id == "quote-123"
    assert context.quote_observed_at == quote_observed_at
    assert context.quote_to_rpc_ms is not None
    assert context.quote_to_rpc_ms >= 0
    assert "credential" not in raw_text
    assert '"rpc_url_env": "BASE_RPC_URL"' in raw_text
    assert '"Set-Cookie": "<redacted>"' in raw_text


def test_transport_failure_is_saved_before_explicit_failure(tmp_path: Path) -> None:
    async def transport(
        url: str, headers: dict[str, str], body: str, timeout: float
    ) -> RpcHttpResponse:
        raise URLError(url)

    with pytest.raises(ValueError, match="RPC collection failed"):
        asyncio.run(
            capture_block_context(
                RpcChainConfig("base", 8453, "BASE_RPC_URL"),
                "https://provider.example",
                tmp_path / "raw",
                transport=transport,
            )
        )

    raw_path = next((tmp_path / "raw").rglob("*.json"))
    envelope = json.loads(raw_path.read_text())
    assert envelope["collection_error"]
    assert envelope["exchanges"][0]["transport_error"]["type"] == "URLError"
    assert "provider.example" not in raw_path.read_text()


def test_chain_id_mismatch_is_rejected(tmp_path: Path) -> None:
    envelope = json.loads((FIXTURE_DIR / "base_head.json").read_text())
    envelope["chain"]["expected_chain_id"] = 10
    path = tmp_path / "wrong-chain.json"
    path.write_text(json.dumps(envelope))

    with pytest.raises(ValueError, match="does not match configured"):
        load_raw_block_context(path)


def test_noncanonical_hex_is_rejected(tmp_path: Path) -> None:
    envelope = json.loads((FIXTURE_DIR / "base_head.json").read_text())
    response = json.loads(envelope["exchanges"][1]["response"]["body"])
    response["result"] = "49774002"
    envelope["exchanges"][1]["response"]["body"] = json.dumps(response)
    path = tmp_path / "decimal-head.json"
    path.write_text(json.dumps(envelope))

    with pytest.raises(ValueError, match="canonical hex quantity"):
        load_raw_block_context(path)


def test_committed_config_is_exact_three_chain_universe() -> None:
    configs = load_chain_config(Path("config/rpc.toml"))

    assert {(item.name, item.chain_id, item.rpc_url_env) for item in configs} == {
        ("base", 8453, "BASE_RPC_URL"),
        ("arbitrum", 42161, "ARBITRUM_RPC_URL"),
        ("optimism", 10, "OPTIMISM_RPC_URL"),
    }
