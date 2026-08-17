"""Day 13 acceptance tests for same-chain transaction simulation evidence."""

from datetime import UTC, datetime

from onchain_arb.models import QuoteObservation, TokenAmount, TokenRef
from onchain_arb.simulation import (
    SimulationRejectReason,
    SimulationEvidence,
    compare_quote_and_simulation,
    load_raw_simulation,
)

from pathlib import Path


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "simulation"
OBSERVED_AT = datetime(2026, 8, 16, 10, 0, tzinfo=UTC)

BASE_USDC = TokenRef(
    chain_id=8453,
    contract_address="0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
    symbol="USDC",
    decimals=6,
)
BASE_WETH = TokenRef(
    chain_id=8453,
    contract_address="0x4200000000000000000000000000000000000006",
    symbol="WETH",
    decimals=18,
)


QUOTE = QuoteObservation(
    observation_id="day13-day13-usdc-weth-100",
    raw_ref="day13_source_ref",
    source="day13_fixture",
    input_amount=TokenAmount(BASE_USDC, 100_000_000),
    output_amount=TokenAmount(BASE_WETH, 52_000_000000_000_000_000),
    minimum_output_amount=TokenAmount(BASE_WETH, 51_000_000000_000_000_000),
    observed_at=OBSERVED_AT,
)


def test_success_fixture_normalizes_eth_call_envelope_and_balances() -> None:
    simulation = load_raw_simulation(FIXTURE_DIR / "day13_success.json")

    assert simulation.result.success
    assert simulation.result.method == "eth_call"
    assert simulation.result.block_number == 0x12d68742
    assert simulation.tx_from == "0x000000000000000000000000000000000000dead"
    assert simulation.tx_to == "0x1111111111111111111111111111111111111111"
    assert simulation.simulated_output is not None
    assert simulation.simulated_output.raw_amount == 52_000_000000_000_000_000
    assert simulation.simulated_output.token == BASE_WETH
    assert len(simulation.balance_changes) == 2
    assert simulation.result.balance_changes[0].token == BASE_USDC
    assert simulation.result.gas_used == 20_000


def test_min_output_revert_is_caught_as_quote_comparison_fail() -> None:
    simulation = load_raw_simulation(FIXTURE_DIR / "day13_min_output_revert.json")

    comparison = compare_quote_and_simulation(QUOTE, simulation, block_number=simulation.result.block_number)

    assert not comparison.executable
    assert comparison.output_meets_quote is False
    assert comparison.output_meets_minimum is False
    assert SimulationRejectReason.REVERTED in comparison.reject_reasons
    assert SimulationRejectReason.OUTPUT_BELOW_MINIMUM in comparison.reject_reasons
    assert comparison.output_delta_from_quote == -10_000_000000_000_000_000


def test_insufficient_allowance_is_caught_even_with_revert() -> None:
    simulation = load_raw_simulation(FIXTURE_DIR / "day13_allowance_reject.json")
    comparison = compare_quote_and_simulation(
        QUOTE,
        simulation,
        block_number=simulation.result.block_number,
    )

    assert SimulationRejectReason.REVERTED in comparison.reject_reasons
    assert SimulationRejectReason.OUTPUT_MISSING in comparison.reject_reasons
    assert SimulationRejectReason.INSUFFICIENT_ALLOWANCE in comparison.reject_reasons
    assert comparison.allowance_sufficient is False
    assert comparison.simulated_output is None


def test_stale_block_is_marked_and_prevents_execution_gate() -> None:
    simulation = load_raw_simulation(FIXTURE_DIR / "day13_success.json")
    comparison = compare_quote_and_simulation(QUOTE, simulation, block_number=simulation.result.block_number + 1)

    assert SimulationRejectReason.STALE_BLOCK in comparison.reject_reasons
    assert comparison.stale_state
    assert comparison.executable is False
