"""Day 17 event-time replay acceptance tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from onchain_arb.replay import (
    InventoryBalance,
    InventoryDelta,
    ReplayCostItem,
    ReplayCostLedger,
    ReplayEvidence,
    ReplayRebalance,
    ReplaySimulation,
    ReplaySnapshot,
    ReplayState,
    load_replay_fixture,
    report_to_dict,
    run_event_time_replay,
)

T0 = datetime(2026, 8, 17, 8, 0, tzinfo=UTC)
FIXTURE = Path(__file__).parent / "fixtures" / "replay" / "day17_event_stream.json"


def _evidence(candidate: str, stage: str, observed_at: datetime, latency_ms: int) -> ReplayEvidence:
    return ReplayEvidence(
        request_id=f"req-{candidate}-{stage}",
        raw_ref=f"raw://day17/{candidate}/{stage}",
        source=f"captured_{stage}",
        observed_at=observed_at,
        arrived_at=observed_at + timedelta(milliseconds=latency_ms),
        latency_ms=latency_ms,
    )


def _ledger(gross_raw: int) -> ReplayCostLedger:
    return ReplayCostLedger(
        gross_edge_raw=gross_raw,
        costs=(ReplayCostItem("base_gas", 400_000), ReplayCostItem("arb_gas", 400_000)),
        required_cost_kinds=frozenset({"base_gas", "arb_gas"}),
        cost_uncertainty_buffer_raw=100_000,
        latency_deterioration_buffer_raw=500_000,
        inventory_rebalance_buffer_raw=400_000,
        minimum_economic_profit_raw=500_000,
    )


def _snapshot(
    candidate: str,
    offset_seconds: int,
    *,
    gross_raw: int = 3_000_000,
    simulation_success: bool = True,
    target_raw: int = 100_000_000,
    rebalance: bool = False,
) -> ReplaySnapshot:
    observed = T0 + timedelta(seconds=offset_seconds)
    requote = _evidence(candidate, "requote", observed + timedelta(seconds=1), 250)
    sim = ReplaySimulation(
        evidence=_evidence(candidate, "simulation", observed + timedelta(seconds=2), 400),
        success=simulation_success,
        minimum_output_satisfied=simulation_success,
    )
    restoration = None
    if rebalance:
        restoration = ReplayRebalance(
            evidence=_evidence(candidate, "rebalance", observed + timedelta(seconds=5), 500),
            inventory_deltas=(
                InventoryDelta(8453, "USDC", target_raw),
                InventoryDelta(42161, "USDC", -(target_raw + gross_raw)),
            ),
        )
    return ReplaySnapshot(
        candidate_id=candidate,
        opportunity_key="BASE_ARB_USDC_WETH",
        direction="BUY_BASE_SELL_ARBITRUM",
        accounting_decimals=6,
        target_size_raw=target_raw,
        initial_gross_edge_raw=4_000_000,
        detected=_evidence(candidate, "detected", observed, 100),
        requote=requote,
        requote_ledger=_ledger(gross_raw),
        simulation=sim,
        inventory_deltas=(
            InventoryDelta(8453, "USDC", -target_raw),
            InventoryDelta(42161, "USDC", target_raw + gross_raw),
        ),
        capital_occupied_raw=4_000_000_000,
        capital_lock_ms=3_600_000,
        rebalance=restoration,
    )


def _inventory() -> tuple[InventoryBalance, ...]:
    return (
        InventoryBalance(8453, "USDC", 2_000_000_000),
        InventoryBalance(42161, "USDC", 2_000_000_000),
    )


def test_replay_clusters_snapshots_and_reports_required_metrics() -> None:
    snapshots = (
        _snapshot("c1", 0, rebalance=True),
        _snapshot("c2", 20, gross_raw=2_000_000),  # required edge is not met
        _snapshot("c3", 40, simulation_success=False),
        _snapshot("c4", 150, gross_raw=3_200_000, target_raw=500_000_000),
    )

    report = run_event_time_replay(
        snapshots, _inventory(), requote_window_ms=3_000, cluster_gap_ms=60_000
    )

    assert report.metrics.detected_candidates == 4
    assert report.metrics.unique_clusters == 2
    assert report.metrics.requote_survivors == 3
    assert report.metrics.requote_survival_rate == Decimal("0.75")
    assert report.metrics.simulation_survivors == 2
    assert report.metrics.simulation_survival_rate == Decimal(2) / Decimal(3)
    assert report.metrics.paper_fills == 2
    assert report.metrics.net_edge_p05 == Decimal("0.71")
    assert report.metrics.net_edge_p50 == Decimal("0.80")
    assert report.metrics.net_edge_p95 == Decimal("0.89")
    assert report.metrics.worst_case_net_edge == Decimal("-0.3")
    assert report.metrics.profitable_capacity == Decimal("500")
    assert report.metrics.capital_hour_return == Decimal("0.0002")
    assert [cluster.candidate_ids for cluster in report.clusters] == [
        ("c1", "c2", "c3"), ("c4",)
    ]
    assert [event.status for event in report.rebalance_events] == ["PENDING", "COMPLETE"]
    assert all(point.samples >= 1 for point in report.metrics.edge_decay_by_latency)


def test_future_evidence_is_not_visible_or_applied() -> None:
    snapshot = _snapshot("no-lookahead", 0)
    cutoff = T0 + timedelta(seconds=1, milliseconds=500)

    partial = run_event_time_replay(
        (snapshot,), _inventory(), requote_window_ms=3_000,
        cluster_gap_ms=60_000, as_of=cutoff,
    )

    assert partial.decisions[0].state is ReplayState.WAITING_SIMULATION
    assert partial.decisions[0].raw_refs == (
        "raw://day17/no-lookahead/detected",
        "raw://day17/no-lookahead/requote",
    )
    assert partial.ending_inventory == _inventory()
    assert partial.metrics.paper_fills == 0
    assert partial.metrics.latency_p95_ms == Decimal("242.5")

    complete = run_event_time_replay(
        (snapshot,), _inventory(), requote_window_ms=3_000, cluster_gap_ms=60_000
    )
    assert complete.decisions[0].state is ReplayState.PAPER_FILLED
    assert complete.ending_inventory != _inventory()


def test_late_requote_is_rejected_using_measured_arrival_time() -> None:
    snapshot = _snapshot("late", 0)
    late = _evidence("late", "requote-late", T0 + timedelta(seconds=1), 2_500)
    snapshot = ReplaySnapshot(
        candidate_id=snapshot.candidate_id,
        opportunity_key=snapshot.opportunity_key,
        direction=snapshot.direction,
        accounting_decimals=snapshot.accounting_decimals,
        target_size_raw=snapshot.target_size_raw,
        initial_gross_edge_raw=snapshot.initial_gross_edge_raw,
        detected=snapshot.detected,
        requote=late,
        requote_ledger=snapshot.requote_ledger,
        simulation=None,
        inventory_deltas=snapshot.inventory_deltas,
        capital_occupied_raw=snapshot.capital_occupied_raw,
        capital_lock_ms=snapshot.capital_lock_ms,
    )
    report = run_event_time_replay(
        (snapshot,), _inventory(), requote_window_ms=3_000, cluster_gap_ms=60_000
    )
    assert report.decisions[0].reject_reasons == ("REQUOTE_TIMEOUT",)
    assert report.metrics.requote_survivors == 0


def test_raw_fixture_loads_and_report_is_json_safe() -> None:
    snapshots, inventory = load_replay_fixture(FIXTURE)
    report = run_event_time_replay(
        snapshots, inventory, requote_window_ms=3_000, cluster_gap_ms=60_000
    )
    payload = report_to_dict(report)
    assert payload["schema_version"] == 1
    assert payload["metrics"]["detected_candidates"] == 2
    assert payload["metrics"]["unique_clusters"] == 1


def test_fixture_parser_rejects_latency_that_does_not_match_timestamps(tmp_path: Path) -> None:
    malformed = FIXTURE.read_text().replace('"latency_ms": 100', '"latency_ms": 101', 1)
    path = tmp_path / "malformed.json"
    path.write_text(malformed)
    with pytest.raises(ValueError, match="latency_ms must equal"):
        load_replay_fixture(path)
