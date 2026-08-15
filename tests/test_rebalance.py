"""Day 11 acceptance tests for deterministic rebalance economics."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from onchain_arb.models import TokenAmount, TokenDelta, TokenRef
from onchain_arb.rebalance import (
    CapacityScenario,
    PaperTrade,
    RebalanceCostObservation,
    RebalancePolicy,
    RebalancePolicyKind,
    RebalanceStatus,
    build_capacity_curve,
    evaluate_rebalance,
)


OBSERVED_AT = datetime(2026, 8, 15, 2, 0, tzinfo=UTC)
BASE_USDC = TokenRef(8453, "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913", "USDC", 6)
BASE_WETH = TokenRef(8453, "0x4200000000000000000000000000000000000006", "WETH", 18)
RAW_COST_FIXTURE = Path(__file__).parent / "fixtures/day11/rebalance_costs.json"


def amount(token: TokenRef, value: str) -> TokenAmount:
    return TokenAmount.from_decimal(token, Decimal(value))


def delta(token: TokenRef, value: str) -> TokenDelta:
    return TokenDelta.from_decimal(token, Decimal(value))


def trades(count: int = 4) -> tuple[PaperTrade, ...]:
    return tuple(
        PaperTrade(
            trade_id=f"day11-trade-{index + 1}",
            local_trade_pnl=delta(BASE_USDC, "5"),
            inventory_delta=delta(BASE_WETH, "0.25"),
            observed_at=OBSERVED_AT + timedelta(minutes=index),
        )
        for index in range(count)
    )


def quotes(
    transfer: str, cost: str, count: int = 1
) -> tuple[RebalanceCostObservation, ...]:
    fixture = json.loads(RAW_COST_FIXTURE.read_text())
    transfer_raw = amount(BASE_WETH, transfer).raw_amount
    cost_raw = amount(BASE_USDC, cost).raw_amount
    matches = [
        (index, observation)
        for index, observation in enumerate(fixture["observations"])
        if observation["request"]["transfer_amount_raw"] == transfer_raw
        and observation["response"]["cost_amount_raw"] == cost_raw
    ]
    assert len(matches) >= count
    return tuple(
        RebalanceCostObservation(
            request_id=observation["request"]["request_id"],
            raw_ref=f"{RAW_COST_FIXTURE}#/observations/{index}",
            source=fixture["source"],
            transfer_amount=TokenAmount(BASE_WETH, transfer_raw),
            cost=TokenAmount(BASE_USDC, cost_raw),
            observed_at=datetime.fromisoformat(
                fixture["observed_at"].replace("Z", "+00:00")
            ),
            latency_ms=Decimal(observation["latency_ms"]),
        )
        for index, observation in matches[:count]
    )


def probabilities(result: object) -> dict[Decimal, Decimal]:
    return {
        level.amount.decimal_amount: level.probability
        for level in result.imbalance_distribution  # type: ignore[attr-defined]
    }


def test_immediate_can_turn_positive_local_pnl_into_negative_cycle_pnl() -> None:
    result = evaluate_rebalance(
        trades(),
        RebalancePolicy(RebalancePolicyKind.IMMEDIATE),
        quotes("0.25", "7", 4),
    )

    assert result.status is RebalanceStatus.COMPLETE
    assert result.local_trade_pnl == Decimal("20")
    assert result.rebalance_cost == Decimal("28")
    assert result.cycle_pnl == Decimal("-8")
    assert result.rebalance_count == 4
    assert result.rebalance_frequency == Decimal("1")
    assert result.break_even_rebalance_cost == Decimal("20")
    assert result.break_even_cost_per_rebalance == Decimal("5")
    assert result.ending_imbalance.decimal_delta == Decimal("0")
    assert probabilities(result) == {Decimal("0"): Decimal("1")}


def test_threshold_policy_accumulates_then_restores_inventory() -> None:
    result = evaluate_rebalance(
        trades(),
        RebalancePolicy(
            RebalancePolicyKind.THRESHOLD,
            threshold=amount(BASE_WETH, "0.5"),
        ),
        quotes("0.5", "9", 2),
    )

    assert result.cycle_pnl == Decimal("2")
    assert result.rebalance_count == 2
    assert result.rebalance_frequency == Decimal("0.5")
    assert probabilities(result) == {
        Decimal("0"): Decimal("0.5"),
        Decimal("0.25"): Decimal("0.5"),
    }


def test_batch_policy_settles_residual_at_cycle_end() -> None:
    result = evaluate_rebalance(
        trades(),
        RebalancePolicy(RebalancePolicyKind.BATCH, batch_size=4),
        quotes("1", "16"),
    )

    assert result.cycle_pnl == Decimal("4")
    assert result.rebalance_count == 1
    assert result.rebalance_frequency == Decimal("0.25")
    assert probabilities(result) == {
        Decimal("0"): Decimal("0.25"),
        Decimal("0.25"): Decimal("0.25"),
        Decimal("0.5"): Decimal("0.25"),
        Decimal("0.75"): Decimal("0.25"),
    }


def test_missing_exact_size_cost_is_explicitly_incomplete() -> None:
    result = evaluate_rebalance(
        trades(),
        RebalancePolicy(RebalancePolicyKind.BATCH, batch_size=4),
        quotes("0.5", "9"),
    )

    assert result.status is RebalanceStatus.COST_INCOMPLETE
    assert result.reject_reasons == ("MISSING_REBALANCE_COST:1000000000000000000",)
    assert result.rebalance_cost is None
    assert result.cycle_pnl is None
    assert result.ending_imbalance.decimal_delta == Decimal("1")


def test_one_cost_observation_cannot_be_reused_across_events() -> None:
    result = evaluate_rebalance(
        trades(2),
        RebalancePolicy(RebalancePolicyKind.IMMEDIATE),
        quotes("0.25", "7"),
    )

    assert result.status is RebalanceStatus.COST_INCOMPLETE
    assert "MISSING_REBALANCE_COST:250000000000000000" in result.reject_reasons
    assert result.cycle_pnl is None


def test_capacity_curve_shows_edge_decay_and_largest_profitable_size() -> None:
    curve = build_capacity_curve(
        (
            CapacityScenario(amount(BASE_USDC, "100"), delta(BASE_USDC, "4"), amount(BASE_USDC, "2")),
            CapacityScenario(amount(BASE_USDC, "500"), delta(BASE_USDC, "8"), amount(BASE_USDC, "7")),
            CapacityScenario(amount(BASE_USDC, "1000"), delta(BASE_USDC, "10"), amount(BASE_USDC, "12")),
        )
    )

    assert [point.cycle_pnl for point in curve.points] == [
        Decimal("2"),
        Decimal("1"),
        Decimal("-2"),
    ]
    assert [point.edge_bps for point in curve.points] == [
        Decimal("200"),
        Decimal("20"),
        Decimal("-20"),
    ]
    assert curve.profitable_capacity is not None
    assert curve.profitable_capacity.decimal_amount == Decimal("500")
