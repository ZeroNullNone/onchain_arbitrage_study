"""Day 4 offline reconstruction tests for saved LI.FI quote evidence."""

from decimal import Decimal
import json
from pathlib import Path

import pytest

from onchain_arb.adapters.lifi import load_raw_quote


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "lifi"
FIXTURE_PATHS = sorted(FIXTURE_DIR.glob("*.json"))


@pytest.mark.parametrize("path", FIXTURE_PATHS, ids=lambda path: path.stem)
def test_raw_fixture_reconstructs_request_route_output_and_costs(path: Path) -> None:
    envelope = json.loads(path.read_text())
    payload = json.loads(envelope["response"]["body"])
    quote = load_raw_quote(path)

    assert envelope["request"]["method"] == "GET"
    assert envelope["request"]["url"] == "https://li.quest/v1/quote"
    assert quote.request.to_query() == envelope["request"]["query"]
    assert quote.request_id == envelope["request_id"]
    assert quote.latency_ms == Decimal(envelope["latency_ms"])

    assert quote.input_amount.raw_amount == int(payload["action"]["fromAmount"])
    assert quote.input_amount.token.chain_id == payload["action"]["fromChainId"]
    assert quote.output_amount.raw_amount == int(payload["estimate"]["toAmount"])
    assert quote.minimum_output_amount.raw_amount == int(
        payload["estimate"]["toAmountMin"]
    )
    assert quote.minimum_output_amount.raw_amount <= quote.output_amount.raw_amount

    assert quote.tool == payload["tool"]
    assert quote.duration_seconds == Decimal(
        str(payload["estimate"]["executionDuration"])
    )
    assert quote.approval_address == payload["estimate"]["approvalAddress"]
    assert [step.tool for step in quote.route_steps] == [
        step["tool"] for step in payload["includedSteps"]
    ]
    assert [step.step_type for step in quote.route_steps] == [
        step["type"] for step in payload["includedSteps"]
    ]
    assert quote.transaction_request == payload["transactionRequest"]
    assert quote.transaction_request["from"].lower() == quote.request.from_address.lower()

    assert quote.fee_costs
    assert quote.gas_costs
    assert all(cost.amount.raw_amount > 0 for cost in quote.fee_costs + quote.gas_costs)
    assert all(cost.included_in_quote_output is True for cost in quote.fee_costs)
    assert all(cost.included_in_quote_output is None for cost in quote.gas_costs)


def test_probe_has_three_routes_at_three_exact_input_sizes() -> None:
    assert len(FIXTURE_PATHS) == 9
    quotes = [load_raw_quote(path) for path in FIXTURE_PATHS]
    route_and_size = {
        (
            quote.request.from_chain_id,
            quote.request.to_chain_id,
            quote.input_amount.token.symbol,
            quote.output_amount.token.symbol,
            quote.input_amount.raw_amount,
        )
        for quote in quotes
    }

    assert route_and_size == {
        (from_chain, to_chain, from_symbol, to_symbol, size * 1_000_000)
        for from_chain, to_chain, from_symbol, to_symbol in (
            (8453, 8453, "USDC", "WETH"),
            (42161, 42161, "USDC", "WETH"),
            (8453, 42161, "USDC", "USDC"),
        )
        for size in (100, 500, 1_000)
    }


def test_route_fingerprint_is_stable_for_same_semantic_steps() -> None:
    quotes = [load_raw_quote(path) for path in FIXTURE_PATHS]
    cross_chain = [
        quote
        for quote in quotes
        if quote.request.from_chain_id == 8453 and quote.request.to_chain_id == 42161
    ]
    arbitrum_swaps = [
        quote
        for quote in quotes
        if quote.request.from_chain_id == quote.request.to_chain_id == 42161
    ]

    assert len({quote.route_fingerprint for quote in cross_chain}) == 1
    assert len({quote.route_fingerprint for quote in arbitrum_swaps}) == 1
    assert cross_chain[0].route_fingerprint != arbitrum_swaps[0].route_fingerprint
    assert len(cross_chain[0].route_fingerprint) == 64


def test_source_costs_remain_raw_integer_token_amounts() -> None:
    quote = load_raw_quote(FIXTURE_DIR / "base_arbitrum_usdc_100_usdc.json")

    fee = quote.fee_costs[0]
    gas = quote.gas_costs[0]
    assert fee.amount.raw_amount == 250_000
    assert fee.amount.token.symbol == "USDC"
    assert fee.amount.decimal_amount == Decimal("0.25")
    assert fee.included_in_quote_output is True
    assert gas.amount.token.symbol == "ETH"
    assert gas.included_in_quote_output is None


def test_non_success_raw_response_is_rejected_explicitly(tmp_path: Path) -> None:
    fixture = json.loads(FIXTURE_PATHS[0].read_text())
    fixture["response"]["status"] = 404
    path = tmp_path / "failed_quote.json"
    path.write_text(json.dumps(fixture))

    with pytest.raises(ValueError, match="status is 404"):
        load_raw_quote(path)

