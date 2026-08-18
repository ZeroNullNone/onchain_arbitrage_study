"""Acceptance tests for Day 14 Scanner v1 pipeline, candidate state machine, and survivor metrics."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
import json
from pathlib import Path
import tempfile

import pytest

from onchain_arb.decision import CandidateRejectReason, CandidateState, ScanDecision
from onchain_arb.inventory import (
    CrossChainSignal,
    InventoryLeg,
    InventoryPosition,
    VirtualBalanceSheet,
)
from onchain_arb.models import (
    CostConfidence,
    CostItem,
    CostScope,
    QuoteObservation,
    TokenAmount,
    TokenRef,
)
from onchain_arb.requote import (
    ApprovalStatus,
    DirectQuote,
    RequoteRejectReason,
    RoundTripQuotes,
)
from onchain_arb.scanner import (
    CandidateDeduplicator,
    CrossChainScanAttempt,
    SameChainScanAttempt,
    ScannerPipeline,
    persist_scanner_report,
)
from onchain_arb.simulation import (
    SimulationEvidence,
    SimulationRejectReason,
    load_raw_simulation,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures"
SIM_FIXTURES = FIXTURE_DIR / "simulation"
OBSERVED_AT = datetime(2026, 8, 17, 8, 0, tzinfo=UTC)

BASE_USDC = TokenRef(8453, "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913", "USDC", 6)
BASE_WETH = TokenRef(8453, "0x4200000000000000000000000000000000000006", "WETH", 18)
ARB_USDC = TokenRef(42161, "0xaf88d065e77c8cC2239327C5EDb3A432268e5831", "USDC", 6)
ARB_WETH = TokenRef(42161, "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1", "WETH", 18)


def _cost(token: TokenRef, kind: str, raw_amount: int, observed_at: datetime) -> CostItem:
    return CostItem(
        kind=kind,
        amount=TokenAmount(token, raw_amount),
        scope=CostScope.ATOMIC,
        included_in_quote_output=False,
        confidence=CostConfidence.ESTIMATED,
        source="scanner_test",
        observed_at=observed_at,
    )


def _direct_quote(
    *,
    quote_id: str,
    venue: str,
    token_in: TokenRef,
    input_raw: int,
    token_out: TokenRef,
    output_raw: int,
    minimum_raw: int,
    gas_raw: int,
    accounting_token: TokenRef,
    observed_at: datetime,
    raw_ref: str = "raw://quote/test",
) -> DirectQuote:
    return DirectQuote(
        quote_id=quote_id,
        request_id=f"req-{quote_id}",
        raw_ref=raw_ref,
        venue=venue,
        input_amount=TokenAmount(token_in, input_raw),
        output_amount=TokenAmount(token_out, output_raw),
        minimum_output_amount=TokenAmount(token_out, minimum_raw),
        fee_amount=TokenAmount(token_in, input_raw * 30 // 10_000),
        gas_cost=_cost(accounting_token, f"gas_{venue}", gas_raw, observed_at),
        approval_status=ApprovalStatus.NOT_REQUIRED,
        approval_cost=None,
        observed_at=observed_at,
        latency_ms=Decimal("15.0"),
    )


def _make_same_chain_round_trip(
    *,
    prefix: str,
    size_raw: int,
    final_raw: int,
    min_final_raw: int,
    gas_raw_per_leg: int,
    observed_at: datetime,
    weth_output_raw: int | None = None,
    weth_minimum_raw: int | None = None,
) -> RoundTripQuotes:
    weth_out = (
        weth_output_raw
        if weth_output_raw is not None
        else size_raw * 520_000_000_000
    )
    weth_min = (
        weth_minimum_raw
        if weth_minimum_raw is not None
        else weth_out * 9_950 // 10_000
    )
    leg1 = _direct_quote(
        quote_id=f"{prefix}-leg1",
        venue="aerodrome",
        token_in=BASE_USDC,
        input_raw=size_raw,
        token_out=BASE_WETH,
        output_raw=weth_out,
        minimum_raw=weth_min,
        gas_raw=gas_raw_per_leg,
        accounting_token=BASE_USDC,
        observed_at=observed_at,
        raw_ref=f"raw://{prefix}/leg1",
    )
    leg2 = _direct_quote(
        quote_id=f"{prefix}-leg2",
        venue="uniswap_v3",
        token_in=BASE_WETH,
        input_raw=weth_min,
        token_out=BASE_USDC,
        output_raw=final_raw,
        minimum_raw=min_final_raw,
        gas_raw=gas_raw_per_leg,
        accounting_token=BASE_USDC,
        observed_at=observed_at + timedelta(milliseconds=20),
        raw_ref=f"raw://{prefix}/leg2",
    )
    return RoundTripQuotes(leg1, leg2)


def _make_cross_chain_signal(
    *,
    candidate_id: str,
    buy_input_raw: int,
    sell_min_output_raw: int,
    observed_at: datetime,
    skew_seconds: float = 0.5,
) -> CrossChainSignal:
    weth_amount_raw = 500_000_000_000_000_000  # 0.5 WETH
    buy_leg = InventoryLeg(
        request_id=f"req-buy-{candidate_id}",
        raw_ref=f"raw://{candidate_id}/buy",
        input_amount=TokenAmount(BASE_USDC, buy_input_raw),
        minimum_output_amount=TokenAmount(BASE_WETH, weth_amount_raw),
        observed_at=observed_at,
    )
    sell_leg = InventoryLeg(
        request_id=f"req-sell-{candidate_id}",
        raw_ref=f"raw://{candidate_id}/sell",
        input_amount=TokenAmount(ARB_WETH, weth_amount_raw),
        minimum_output_amount=TokenAmount(ARB_USDC, sell_min_output_raw),
        observed_at=observed_at + timedelta(seconds=skew_seconds),
    )
    costs = (
        _cost(BASE_USDC, "cheap_gas", 500_000, observed_at),
        _cost(ARB_USDC, "expensive_gas", 500_000, observed_at),
    )
    return CrossChainSignal(
        candidate_id=candidate_id,
        stable_asset_id="USDC",
        trade_asset_id="WETH",
        cheap_chain_buy=buy_leg,
        expensive_chain_sell=sell_leg,
        costs=costs,
        required_cost_kinds=frozenset({"cheap_gas", "expensive_gas"}),
        max_leg_skew=timedelta(seconds=2),
        capital_lock_hours=Decimal("1.0"),
    )


def _make_balance_sheet(
    *,
    base_usdc_balance: int = 50_000_000_000,
    base_weth_balance: int = 20_000_000_000_000_000_000,
    arb_usdc_balance: int = 50_000_000_000,
    arb_weth_balance: int = 20_000_000_000_000_000_000,
) -> VirtualBalanceSheet:
    positions = (
        InventoryPosition(
            asset_id="USDC",
            balance=TokenAmount(BASE_USDC, base_usdc_balance),
            target_minimum=TokenAmount(BASE_USDC, 10_000_000_000),
            target_maximum=TokenAmount(BASE_USDC, 100_000_000_000),
            max_imbalance=TokenAmount(BASE_USDC, 45_000_000_000),
            accounting_price=Decimal("1.0"),
        ),
        InventoryPosition(
            asset_id="WETH",
            balance=TokenAmount(BASE_WETH, base_weth_balance),
            target_minimum=TokenAmount(BASE_WETH, 5_000_000_000_000_000_000),
            target_maximum=TokenAmount(BASE_WETH, 50_000_000_000_000_000_000),
            max_imbalance=TokenAmount(BASE_WETH, 20_000_000_000_000_000_000),
            accounting_price=Decimal("2000.0"),
        ),
        InventoryPosition(
            asset_id="USDC",
            balance=TokenAmount(ARB_USDC, arb_usdc_balance),
            target_minimum=TokenAmount(ARB_USDC, 10_000_000_000),
            target_maximum=TokenAmount(ARB_USDC, 100_000_000_000),
            max_imbalance=TokenAmount(ARB_USDC, 45_000_000_000),
            accounting_price=Decimal("1.0"),
        ),
        InventoryPosition(
            asset_id="WETH",
            balance=TokenAmount(ARB_WETH, arb_weth_balance),
            target_minimum=TokenAmount(ARB_WETH, 5_000_000_000_000_000_000),
            target_maximum=TokenAmount(ARB_WETH, 50_000_000_000_000_000_000),
            max_imbalance=TokenAmount(ARB_WETH, 20_000_000_000_000_000_000),
            accounting_price=Decimal("2000.0"),
        ),
    )
    return VirtualBalanceSheet(positions=positions, observed_at=OBSERVED_AT)


def test_same_chain_paper_ready_full_pipeline() -> None:
    pipeline = ScannerPipeline()
    initial = _make_same_chain_round_trip(
        prefix="init",
        size_raw=100_000_000,
        final_raw=101_000_000,
        min_final_raw=100_800_000,
        gas_raw_per_leg=100_000,
        observed_at=OBSERVED_AT,
        weth_output_raw=52_000_000_000_000_000_000,
        weth_minimum_raw=51_000_000_000_000_000_000,
    )
    refreshed = _make_same_chain_round_trip(
        prefix="refresh",
        size_raw=100_000_000,
        final_raw=100_900_000,
        min_final_raw=100_700_000,
        gas_raw_per_leg=100_000,
        observed_at=OBSERVED_AT + timedelta(seconds=1),
        weth_output_raw=52_000_000_000_000_000_000,
        weth_minimum_raw=51_000_000_000_000_000_000,
    )
    sim = load_raw_simulation(SIM_FIXTURES / "day13_success.json")

    attempt = SameChainScanAttempt(
        candidate_id="sc-success-01",
        initial=initial,
        refreshed=refreshed,
        simulation=sim,
        detected_at=OBSERVED_AT,
        expiry_at=OBSERVED_AT + timedelta(seconds=10),
    )

    decision = pipeline.evaluate_same_chain(attempt)

    assert decision.state is CandidateState.PAPER_READY
    assert decision.accepted is True
    assert decision.reject_reasons == ()
    assert decision.has_complete_costs is True
    assert decision.has_raw_refs is True
    assert decision.net_pnl == Decimal("0.5")
    assert decision.opportunity_lifetime_ms == Decimal("10000")


def test_same_chain_requote_failed_when_missing() -> None:
    pipeline = ScannerPipeline()
    initial = _make_same_chain_round_trip(
        prefix="init",
        size_raw=100_000_000,
        final_raw=101_000_000,
        min_final_raw=100_800_000,
        gas_raw_per_leg=100_000,
        observed_at=OBSERVED_AT,
    )
    attempt = SameChainScanAttempt(
        candidate_id="sc-missing-requote",
        initial=initial,
        refreshed=None,
        detected_at=OBSERVED_AT,
    )

    decision = pipeline.evaluate_same_chain(attempt)

    assert decision.state is CandidateState.REQUOTE_FAILED
    assert decision.accepted is False
    assert CandidateRejectReason.REQUOTE_MISSING in decision.reject_reasons


def test_same_chain_net_negative_when_costs_exceed_gross() -> None:
    pipeline = ScannerPipeline()
    initial = _make_same_chain_round_trip(
        prefix="init",
        size_raw=100_000_000,
        final_raw=100_300_000,
        min_final_raw=100_200_000,
        gas_raw_per_leg=200_000,
        observed_at=OBSERVED_AT,
        weth_output_raw=52_000_000_000_000_000_000,
        weth_minimum_raw=51_000_000_000_000_000_000,
    )
    refreshed = _make_same_chain_round_trip(
        prefix="refresh",
        size_raw=100_000_000,
        final_raw=100_300_000,
        min_final_raw=100_200_000,
        gas_raw_per_leg=200_000,  # Total gas = 400_000 > gross 200_000
        observed_at=OBSERVED_AT + timedelta(seconds=1),
        weth_output_raw=52_000_000_000_000_000_000,
        weth_minimum_raw=51_000_000_000_000_000_000,
    )
    sim = load_raw_simulation(SIM_FIXTURES / "day13_success.json")

    attempt = SameChainScanAttempt(
        candidate_id="sc-net-neg",
        initial=initial,
        refreshed=refreshed,
        simulation=sim,
        detected_at=OBSERVED_AT,
    )

    decision = pipeline.evaluate_same_chain(attempt)

    assert decision.state is CandidateState.NET_NEGATIVE
    assert CandidateRejectReason.NET_NOT_POSITIVE in decision.reject_reasons
    assert decision.cost_evaluation is not None
    assert decision.cost_evaluation.local_trade_pnl == Decimal("-0.2")


def test_same_chain_simulation_failed_on_revert() -> None:
    pipeline = ScannerPipeline()
    initial = _make_same_chain_round_trip(
        prefix="init",
        size_raw=100_000_000,
        final_raw=101_000_000,
        min_final_raw=100_800_000,
        gas_raw_per_leg=100_000,
        observed_at=OBSERVED_AT,
        weth_output_raw=52_000_000_000_000_000_000,
        weth_minimum_raw=51_000_000_000_000_000_000,
    )
    refreshed = _make_same_chain_round_trip(
        prefix="refresh",
        size_raw=100_000_000,
        final_raw=100_900_000,
        min_final_raw=100_700_000,
        gas_raw_per_leg=100_000,
        observed_at=OBSERVED_AT + timedelta(seconds=1),
        weth_output_raw=52_000_000_000_000_000_000,
        weth_minimum_raw=51_000_000_000_000_000_000,
    )
    sim = load_raw_simulation(SIM_FIXTURES / "day13_min_output_revert.json")

    attempt = SameChainScanAttempt(
        candidate_id="sc-sim-revert",
        initial=initial,
        refreshed=refreshed,
        simulation=sim,
        detected_at=OBSERVED_AT,
    )

    decision = pipeline.evaluate_same_chain(attempt)

    assert decision.state is CandidateState.SIMULATION_FAILED
    assert SimulationRejectReason.REVERTED.value in decision.reject_reasons


def test_same_chain_simulation_missing_is_caught() -> None:
    pipeline = ScannerPipeline()
    initial = _make_same_chain_round_trip(
        prefix="init",
        size_raw=100_000_000,
        final_raw=101_000_000,
        min_final_raw=100_800_000,
        gas_raw_per_leg=100_000,
        observed_at=OBSERVED_AT,
        weth_output_raw=52_000_000_000_000_000_000,
        weth_minimum_raw=51_000_000_000_000_000_000,
    )
    refreshed = _make_same_chain_round_trip(
        prefix="refresh",
        size_raw=100_000_000,
        final_raw=100_900_000,
        min_final_raw=100_700_000,
        gas_raw_per_leg=100_000,
        observed_at=OBSERVED_AT + timedelta(seconds=1),
        weth_output_raw=52_000_000_000_000_000_000,
        weth_minimum_raw=51_000_000_000_000_000_000,
    )
    attempt = SameChainScanAttempt(
        candidate_id="sc-sim-missing",
        initial=initial,
        refreshed=refreshed,
        simulation=None,
        detected_at=OBSERVED_AT,
    )

    decision = pipeline.evaluate_same_chain(attempt)

    assert decision.state is CandidateState.SIMULATION_FAILED
    assert CandidateRejectReason.SIMULATION_MISSING in decision.reject_reasons


def test_cross_chain_paper_ready_success() -> None:
    pipeline = ScannerPipeline()
    signal = _make_cross_chain_signal(
        candidate_id="cc-success-01",
        buy_input_raw=1_000_000_000,       # 1000 USDC
        sell_min_output_raw=1_005_000_000, # 1005 USDC -> Gross 5 USDC - Cost 1 USDC = 4 USDC
        observed_at=OBSERVED_AT,
    )
    balance_sheet = _make_balance_sheet()

    attempt = CrossChainScanAttempt(
        candidate_id="cc-success-01",
        signal=signal,
        refreshed_signal=signal,
        balance_sheet=balance_sheet,
        detected_at=OBSERVED_AT,
        expiry_at=OBSERVED_AT + timedelta(seconds=30),
    )

    decision = pipeline.evaluate_cross_chain(attempt)

    assert decision.state is CandidateState.PAPER_READY
    assert decision.accepted is True
    assert decision.reject_reasons == ()
    assert decision.net_pnl == Decimal("4.0")
    assert decision.opportunity_lifetime_ms == Decimal("30000")


def test_cross_chain_inventory_blocked_when_balance_insufficient() -> None:
    pipeline = ScannerPipeline()
    signal = _make_cross_chain_signal(
        candidate_id="cc-inv-blocked",
        buy_input_raw=1_000_000_000,
        sell_min_output_raw=1_005_000_000,
        observed_at=OBSERVED_AT,
    )
    # Arb WETH balance is zero (less than required 0.5 WETH)
    balance_sheet = _make_balance_sheet(arb_weth_balance=0)

    attempt = CrossChainScanAttempt(
        candidate_id="cc-inv-blocked",
        signal=signal,
        balance_sheet=balance_sheet,
        detected_at=OBSERVED_AT,
    )

    decision = pipeline.evaluate_cross_chain(attempt)

    assert decision.state is CandidateState.INVENTORY_BLOCKED
    assert CandidateRejectReason.INVENTORY_BLOCKED in decision.reject_reasons


def test_deduplicator_prevents_duplicate_opportunity() -> None:
    dedup = CandidateDeduplicator(window_seconds=10.0)
    pipeline = ScannerPipeline(deduplicator=dedup)

    initial = _make_same_chain_round_trip(
        prefix="init",
        size_raw=100_000_000,
        final_raw=101_000_000,
        min_final_raw=100_800_000,
        gas_raw_per_leg=100_000,
        observed_at=OBSERVED_AT,
        weth_output_raw=52_000_000_000_000_000_000,
        weth_minimum_raw=51_000_000_000_000_000_000,
    )
    refreshed = _make_same_chain_round_trip(
        prefix="refresh",
        size_raw=100_000_000,
        final_raw=100_900_000,
        min_final_raw=100_700_000,
        gas_raw_per_leg=100_000,
        observed_at=OBSERVED_AT + timedelta(seconds=1),
        weth_output_raw=52_000_000_000_000_000_000,
        weth_minimum_raw=51_000_000_000_000_000_000,
    )
    sim = load_raw_simulation(SIM_FIXTURES / "day13_success.json")

    attempt1 = SameChainScanAttempt(
        candidate_id="sc-dup-1",
        initial=initial,
        refreshed=refreshed,
        simulation=sim,
        detected_at=OBSERVED_AT,
    )
    attempt2 = SameChainScanAttempt(
        candidate_id="sc-dup-2",
        initial=initial,
        refreshed=refreshed,
        simulation=sim,
        detected_at=OBSERVED_AT + timedelta(seconds=2),
    )

    dec1 = pipeline.evaluate_same_chain(attempt1)
    dec2 = pipeline.evaluate_same_chain(attempt2)

    assert dec1.state is CandidateState.PAPER_READY
    assert dec2.state is CandidateState.REQUOTE_FAILED
    assert CandidateRejectReason.DUPLICATE_OPPORTUNITY in dec2.reject_reasons


def test_batch_scan_computes_survivor_ratios_and_sparse_metrics() -> None:
    pipeline = ScannerPipeline(dedup_window_seconds=0.0)

    # 1. success (100 USDC)
    init1 = _make_same_chain_round_trip(
        prefix="init1",
        size_raw=100_000_000,
        final_raw=101_000_000,
        min_final_raw=100_800_000,
        gas_raw_per_leg=100_000,
        observed_at=OBSERVED_AT,
        weth_output_raw=52_000_000_000_000_000_000,
        weth_minimum_raw=51_000_000_000_000_000_000,
    )
    ref1 = _make_same_chain_round_trip(
        prefix="ref1",
        size_raw=100_000_000,
        final_raw=100_900_000,
        min_final_raw=100_700_000,
        gas_raw_per_leg=100_000,
        observed_at=OBSERVED_AT + timedelta(seconds=1),
        weth_output_raw=52_000_000_000_000_000_000,
        weth_minimum_raw=51_000_000_000_000_000_000,
    )
    sim1 = load_raw_simulation(SIM_FIXTURES / "day13_success.json")
    item1 = SameChainScanAttempt("item1", init1, ref1, sim1, detected_at=OBSERVED_AT)

    # 2. requote failed (missing) (200 USDC)
    init2 = _make_same_chain_round_trip(
        prefix="init2",
        size_raw=200_000_000,
        final_raw=202_000_000,
        min_final_raw=201_600_000,
        gas_raw_per_leg=100_000,
        observed_at=OBSERVED_AT + timedelta(seconds=10),
    )
    item2 = SameChainScanAttempt("item2", init2, None, None, detected_at=OBSERVED_AT + timedelta(seconds=10))

    # 3. net negative (300 USDC)
    init3 = _make_same_chain_round_trip(
        prefix="init3",
        size_raw=300_000_000,
        final_raw=300_500_000,
        min_final_raw=300_400_000,
        gas_raw_per_leg=400_000,
        observed_at=OBSERVED_AT + timedelta(seconds=20),
        weth_output_raw=52_000_000_000_000_000_000,
        weth_minimum_raw=51_000_000_000_000_000_000,
    )
    ref3 = _make_same_chain_round_trip(
        prefix="ref3",
        size_raw=300_000_000,
        final_raw=300_500_000,
        min_final_raw=300_400_000,
        gas_raw_per_leg=400_000,
        observed_at=OBSERVED_AT + timedelta(seconds=21),
        weth_output_raw=52_000_000_000_000_000_000,
        weth_minimum_raw=51_000_000_000_000_000_000,
    )
    item3 = SameChainScanAttempt("item3", init3, ref3, sim1, detected_at=OBSERVED_AT + timedelta(seconds=20))

    # 4. sim failed (400 USDC)
    init4 = _make_same_chain_round_trip(
        prefix="init4",
        size_raw=400_000_000,
        final_raw=403_000_000,
        min_final_raw=402_800_000,
        gas_raw_per_leg=100_000,
        observed_at=OBSERVED_AT + timedelta(seconds=30),
        weth_output_raw=52_000_000_000_000_000_000,
        weth_minimum_raw=51_000_000_000_000_000_000,
    )
    ref4 = _make_same_chain_round_trip(
        prefix="ref4",
        size_raw=400_000_000,
        final_raw=403_000_000,
        min_final_raw=402_800_000,
        gas_raw_per_leg=100_000,
        observed_at=OBSERVED_AT + timedelta(seconds=31),
        weth_output_raw=52_000_000_000_000_000_000,
        weth_minimum_raw=51_000_000_000_000_000_000,
    )
    sim4 = load_raw_simulation(SIM_FIXTURES / "day13_min_output_revert.json")
    item4 = SameChainScanAttempt("item4", init4, ref4, sim4, detected_at=OBSERVED_AT + timedelta(seconds=30))

    # 5. cross chain success (1000 USDC)
    sig5 = _make_cross_chain_signal(
        candidate_id="item5",
        buy_input_raw=1_000_000_000,
        sell_min_output_raw=1_005_000_000,
        observed_at=OBSERVED_AT + timedelta(seconds=40),
    )
    item5 = CrossChainScanAttempt(
        "item5",
        sig5,
        sig5,
        _make_balance_sheet(),
        detected_at=OBSERVED_AT + timedelta(seconds=40),
        expiry_at=OBSERVED_AT + timedelta(seconds=60),
    )

    # 6. cross chain inv blocked (2000 USDC)
    sig6 = _make_cross_chain_signal(
        candidate_id="item6",
        buy_input_raw=2_000_000_000,
        sell_min_output_raw=2_010_000_000,
        observed_at=OBSERVED_AT + timedelta(seconds=50),
    )
    item6 = CrossChainScanAttempt(
        "item6",
        sig6,
        sig6,
        _make_balance_sheet(arb_weth_balance=0),
        detected_at=OBSERVED_AT + timedelta(seconds=50),
    )

    report = pipeline.scan([item1, item2, item3, item4, item5, item6])

    metrics = report.metrics
    assert metrics.total_detected == 6
    assert metrics.is_sparse is True  # 6 < 20
    assert metrics.cost_completeness_ratio == 1.0
    assert metrics.raw_ref_coverage_ratio == 1.0

    # Funnel checks
    assert metrics.requote_survivors == 5  # item1, item3, item4, item5, item6
    assert metrics.requote_survivor_ratio == 5 / 6
    assert metrics.net_positive_survivors == 4  # item1, item4, item5, item6
    assert metrics.simulation_attempted == 2   # item1, item4
    assert metrics.simulation_survivors == 1   # item1
    assert metrics.simulation_survivor_ratio == 0.5
    assert metrics.inventory_attempted == 2    # item5, item6
    assert metrics.inventory_survivors == 1    # item5
    assert metrics.paper_ready_count == 2      # item1, item5


def test_report_persistence_and_serialization() -> None:
    pipeline = ScannerPipeline()
    init = _make_same_chain_round_trip(
        prefix="init",
        size_raw=100_000_000,
        final_raw=101_000_000,
        min_final_raw=100_800_000,
        gas_raw_per_leg=100_000,
        observed_at=OBSERVED_AT,
        weth_output_raw=52_000_000_000_000_000_000,
        weth_minimum_raw=51_000_000_000_000_000_000,
    )
    ref = _make_same_chain_round_trip(
        prefix="refresh",
        size_raw=100_000_000,
        final_raw=100_900_000,
        min_final_raw=100_700_000,
        gas_raw_per_leg=100_000,
        observed_at=OBSERVED_AT + timedelta(seconds=1),
        weth_output_raw=52_000_000_000_000_000_000,
        weth_minimum_raw=51_000_000_000_000_000_000,
    )
    sim = load_raw_simulation(SIM_FIXTURES / "day13_success.json")
    item = SameChainScanAttempt("persist-01", init, ref, sim, detected_at=OBSERVED_AT)

    report = pipeline.scan([item])

    with tempfile.TemporaryDirectory() as temp_dir:
        output_dir = Path(temp_dir)
        report_file = persist_scanner_report(report, output_dir)

        assert report_file.exists()
        content = json.loads(report_file.read_text())
        assert content["schema_version"] == 1
        assert content["metrics"]["paper_ready_count"] == 1
        assert len(content["decisions"]) == 1
        assert content["decisions"][0]["state"] == "PAPER_READY"
