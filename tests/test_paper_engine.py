"""Day 18 paper decision engine acceptance tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from onchain_arb.paper_engine import (
    AlertKind,
    Allowance,
    AllowanceRequirement,
    PaperCandidate,
    PaperDecisionEngine,
    PaperState,
    decision_to_dict,
    load_paper_fixture,
    make_candidate_id,
)
from onchain_arb.replay import (
    InventoryBalance,
    InventoryDelta,
    ReplayCostItem,
    ReplayCostLedger,
    ReplayEvidence,
    ReplaySimulation,
)

T0 = datetime(2026, 8, 18, 8, 0, tzinfo=UTC)
FIXTURE = Path(__file__).parent / "fixtures" / "paper" / "day18_candidate.json"


def _evidence(stage: str, seconds: int) -> ReplayEvidence:
    observed = T0 + timedelta(seconds=seconds)
    return ReplayEvidence(f"req-{stage}", f"raw://day18/{stage}", stage, observed,
                          observed + timedelta(milliseconds=100), 100)


def _candidate(*, rebalance: bool = True, simulation: bool = True) -> PaperCandidate:
    detected = _evidence("detected", 0)
    candidate_id = make_candidate_id("BASE_ARB", "BUY_BASE", 100_000_000,
                                     detected.request_id)
    return PaperCandidate(
        candidate_id=candidate_id,
        opportunity_key="BASE_ARB",
        direction="BUY_BASE",
        target_size_raw=100_000_000,
        detected=detected,
        requote=_evidence("requote", 1),
        original_route="aerodrome-v2",
        refreshed_route="aerodrome-v2",
        expires_at=T0 + timedelta(seconds=10),
        ledger_ref="derived://day18/ledger/1",
        cost_ledger=ReplayCostLedger(
            gross_edge_raw=3_000_000,
            costs=(ReplayCostItem("base_gas", 500_000),),
            required_cost_kinds=frozenset({"base_gas"}),
            cost_uncertainty_buffer_raw=200_000,
            latency_deterioration_buffer_raw=300_000,
            inventory_rebalance_buffer_raw=400_000,
            minimum_economic_profit_raw=500_000,
        ),
        inventory_deltas=(
            InventoryDelta(8453, "USDC", -100_000_000),
            InventoryDelta(42161, "USDC", 103_000_000),
        ),
        allowance_requirements=(AllowanceRequirement(8453, "USDC", "router", 100_000_000),),
        simulation_required=simulation,
        simulation=(ReplaySimulation(_evidence("simulation", 2), True, True)
                    if simulation else None),
        rebalance_deltas=(
            InventoryDelta(8453, "USDC", 100_000_000),
            InventoryDelta(42161, "USDC", -103_000_000),
        ) if rebalance else (),
        rebalance_evidence=_evidence("rebalance", 5) if rebalance else None,
    )


def _engine(*, allowance: int = 200_000_000) -> PaperDecisionEngine:
    return PaperDecisionEngine(
        (InventoryBalance(8453, "USDC", 1_000_000_000),
         InventoryBalance(42161, "USDC", 1_000_000_000)),
        (Allowance(8453, "USDC", "router", allowance),),
    )


def test_fill_is_idempotent_and_has_complete_lineage() -> None:
    engine = _engine()
    candidate = _candidate()
    first = engine.process(candidate, now=T0 + timedelta(seconds=6))
    balances_after_first = engine.balances
    audit_length = len(engine.audit_log)
    second = engine.process(candidate, now=T0 + timedelta(seconds=7))

    assert first is second
    assert first.state is PaperState.CLOSED
    assert first.filled
    assert first.raw_quote_ref == "raw://day18/detected"
    assert first.requote_ref == "raw://day18/requote"
    assert first.ledger_ref == "derived://day18/ledger/1"
    assert first.simulation_ref == "raw://day18/simulation"
    assert engine.balances == balances_after_first
    assert len(engine.audit_log) == audit_length
    assert [event.to_state for event in first.transitions] == [
        PaperState.DETECTED, PaperState.REQUOTING, PaperState.COSTED,
        PaperState.INVENTORY_CHECKED, PaperState.SIMULATED, PaperState.PAPER_READY,
        PaperState.PAPER_FILLED, PaperState.REBALANCE_PENDING, PaperState.CLOSED,
    ]
    assert [alert.kind for alert in engine.alerts] == [AlertKind.PAPER_READY]
    payload = decision_to_dict(first)
    assert payload["transitions"][0]["occurred_at"].endswith("Z")


def test_route_change_expiry_and_allowance_are_explicit_rejections() -> None:
    route = _engine().process(
        replace(_candidate(), refreshed_route="uniswap-v3"),
        now=T0 + timedelta(seconds=3),
    )
    expired = _engine().process(_candidate(), now=T0 + timedelta(seconds=11))
    allowance = _engine(allowance=99_999_999).process(
        _candidate(), now=T0 + timedelta(seconds=3)
    )

    assert (route.state, route.reject_reason) == (PaperState.REJECTED, "ROUTE_CHANGED")
    assert (expired.state, expired.reject_reason) == (PaperState.EXPIRED, "QUOTE_EXPIRED")
    assert allowance.state is PaperState.REJECTED
    assert allowance.reject_reason.startswith("INSUFFICIENT_VIRTUAL_ALLOWANCE")
    assert not route.alerts and not expired.alerts and not allowance.alerts


def test_simulation_na_is_audited_and_candidate_id_conflict_alerts() -> None:
    engine = _engine()
    candidate = _candidate(rebalance=False, simulation=False)
    decision = engine.process(candidate, now=T0 + timedelta(seconds=3))
    conflict = engine.process(replace(candidate, direction="SELL_BASE"),
                              now=T0 + timedelta(seconds=4))

    assert decision.state is PaperState.PAPER_FILLED
    assert PaperState.SIMULATION_NA in [event.to_state for event in decision.transitions]
    assert conflict.state is PaperState.ERROR
    assert conflict.alerts[0].kind is AlertKind.SYSTEM_ERROR
    assert all(alert.kind in (AlertKind.PAPER_READY, AlertKind.SYSTEM_ERROR)
               for alert in engine.alerts)


def test_saved_fixture_runs_end_to_end_without_inferred_fields() -> None:
    candidates, balances, allowances = load_paper_fixture(FIXTURE)
    engine = PaperDecisionEngine(balances, allowances)
    decision = engine.process(candidates[0], now=T0 + timedelta(seconds=6))

    assert decision.state is PaperState.CLOSED
    assert decision.net_edge_raw == 700_000
    assert engine.balances == balances


def test_future_rebalance_stays_pending_then_closes_without_second_fill() -> None:
    engine = _engine()
    initial = engine.balances
    candidate = _candidate()
    pending = engine.process(candidate, now=T0 + timedelta(seconds=3))
    after_fill = engine.balances
    closed = engine.process(candidate, now=T0 + timedelta(seconds=6))

    assert pending.state is PaperState.REBALANCE_PENDING
    assert after_fill != initial
    assert closed.state is PaperState.CLOSED
    assert engine.balances == initial
    states = [item.to_state for item in engine.audit_log]
    assert states.count(PaperState.PAPER_FILLED) == 1
    assert states.count(PaperState.CLOSED) == 1
