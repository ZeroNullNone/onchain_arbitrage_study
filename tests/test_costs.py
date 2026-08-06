"""Executable examples for the Day 2 PnL and cost semantics."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from onchain_arb.costs import CostLedger
from onchain_arb.models import (
    CostConfidence,
    CostItem,
    CostScope,
    TokenAmount,
    TokenDelta,
    TokenRef,
)


OBSERVED_AT = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)
USDC = TokenRef(
    chain_id=42161,
    contract_address="0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
    symbol="USDC",
    decimals=6,
)


def amount(value: str) -> TokenAmount:
    return TokenAmount.from_decimal(USDC, Decimal(value))


def pnl(value: str) -> TokenDelta:
    return TokenDelta.from_decimal(USDC, Decimal(value))


def cost(
    kind: str,
    value: str,
    *,
    scope: CostScope = CostScope.ATOMIC,
    included: bool = False,
) -> CostItem:
    return CostItem(
        kind=kind,
        amount=amount(value),
        scope=scope,
        included_in_quote_output=included,
        confidence=CostConfidence.EXACT,
        source="day02_test_fixture",
        observed_at=OBSERVED_AT,
    )


def test_gross_positive_becomes_negative_after_gas() -> None:
    # Arrange: a 0.30 USDC quoted edge and 0.40 USDC external gas cost.
    ledger = CostLedger(required_cost_kinds={"gas"})

    # Act.
    result = ledger.evaluate(
        candidate_id="candidate-gas",
        gross_pnl=pnl("0.30"),
        costs=(cost("gas", "0.40"),),
    )

    # Assert.
    assert result.gross_pnl.decimal_delta == Decimal("0.3")
    assert result.atomic_net_pnl == Decimal("-0.1")
    assert result.inventory_cycle_pnl == Decimal("-0.1")
    assert result.is_complete


def test_fee_included_in_quote_output_is_not_deducted_twice() -> None:
    # Arrange: gross PnL already uses LI.FI-style net quote output.
    ledger = CostLedger(required_cost_kinds={"swap_fee", "gas"})
    costs = (
        cost("swap_fee", "1.00", included=True),
        cost("gas", "0.25"),
    )

    # Act.
    result = ledger.evaluate(
        candidate_id="candidate-included-fee",
        gross_pnl=pnl("2.00"),
        costs=costs,
    )

    # Assert: only gas is deducted from the already-net quote output.
    assert result.included_cost_total == Decimal("1")
    assert result.atomic_deduction_total == Decimal("0.25")
    assert result.atomic_net_pnl == Decimal("1.75")


def test_local_trade_positive_becomes_cycle_negative_after_rebalance() -> None:
    # Arrange: the local legs clear gas but not the inventory restoration cost.
    ledger = CostLedger(required_cost_kinds={"gas", "rebalance"})
    costs = (
        cost("gas", "0.40"),
        cost("rebalance", "2.00", scope=CostScope.CYCLE),
    )

    # Act.
    result = ledger.evaluate(
        candidate_id="candidate-rebalance",
        gross_pnl=pnl("1.50"),
        costs=costs,
    )

    # Assert.
    assert result.local_trade_pnl == Decimal("1.1")
    assert result.inventory_cycle_pnl == Decimal("-0.9")


def test_missing_required_cost_is_explicit_not_zero() -> None:
    ledger = CostLedger(required_cost_kinds={"gas", "failure_allowance"})

    result = ledger.evaluate(
        candidate_id="candidate-incomplete",
        gross_pnl=pnl("1.00"),
        costs=(cost("gas", "0.10"),),
    )

    assert not result.is_complete
    assert result.missing_cost_kinds == frozenset({"failure_allowance"})


def test_ledger_rejects_mixed_cost_currencies() -> None:
    weth = TokenRef(
        chain_id=42161,
        contract_address="0x82aF49447D8a07e3bd95BD0d56f35241523fBab1",
        symbol="WETH",
        decimals=18,
    )
    weth_cost = CostItem(
        kind="gas",
        amount=TokenAmount.from_decimal(weth, Decimal("0.001")),
        scope=CostScope.ATOMIC,
        included_in_quote_output=False,
        confidence=CostConfidence.ESTIMATED,
        source="day02_test_fixture",
        observed_at=OBSERVED_AT,
    )

    with pytest.raises(ValueError, match="same accounting token"):
        CostLedger(required_cost_kinds={"gas"}).evaluate(
            candidate_id="candidate-mixed-currency",
            gross_pnl=pnl("1.00"),
            costs=(weth_cost,),
        )
