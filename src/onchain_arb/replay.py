"""Latency-aware, paper-only event-time replay for the frozen Day 16 strategy.

The replay consumes captured snapshots rather than candles.  Every external fact has
an observation time and an arrival time; a decision may only use evidence whose
arrival time is at or before the replay cutoff.  Economic values remain integer raw
units and are converted to :class:`~decimal.Decimal` only for reporting.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
import json
from pathlib import Path
from typing import Iterable, Mapping

from onchain_arb.models import _require_utc


def _raw_int(value: object, name: str, *, allow_negative: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer raw-unit value")
    if not allow_negative and value < 0:
        raise ValueError(f"{name} must be non-negative")
    return value


@dataclass(frozen=True, slots=True)
class ReplayEvidence:
    """One append-only external observation with measured end-to-end latency."""

    request_id: str
    raw_ref: str
    source: str
    observed_at: datetime
    arrived_at: datetime
    latency_ms: int

    def __post_init__(self) -> None:
        if not self.request_id or not self.raw_ref or not self.source:
            raise ValueError("request_id, raw_ref, and source are required")
        _require_utc(self.observed_at, "observed_at")
        _require_utc(self.arrived_at, "arrived_at")
        _raw_int(self.latency_ms, "latency_ms")
        if self.arrived_at < self.observed_at:
            raise ValueError("evidence cannot arrive before it was observed")
        elapsed_us = (self.arrived_at - self.observed_at) // timedelta(microseconds=1)
        if elapsed_us % 1000:
            raise ValueError("evidence latency must be representable as integer milliseconds")
        elapsed_ms = elapsed_us // 1000
        if elapsed_ms != self.latency_ms:
            raise ValueError("latency_ms must equal arrived_at - observed_at")


@dataclass(frozen=True, slots=True)
class ReplayCostItem:
    kind: str
    raw_amount: int

    def __post_init__(self) -> None:
        if not self.kind:
            raise ValueError("cost kind is required")
        _raw_int(self.raw_amount, "raw_amount")


@dataclass(frozen=True, slots=True)
class ReplayCostLedger:
    """Single owner of replay PnL and all Required Edge semantics."""

    gross_edge_raw: int
    costs: tuple[ReplayCostItem, ...]
    required_cost_kinds: frozenset[str]
    cost_uncertainty_buffer_raw: int
    latency_deterioration_buffer_raw: int
    inventory_rebalance_buffer_raw: int
    minimum_economic_profit_raw: int

    def __post_init__(self) -> None:
        _raw_int(self.gross_edge_raw, "gross_edge_raw", allow_negative=True)
        for name in (
            "cost_uncertainty_buffer_raw",
            "latency_deterioration_buffer_raw",
            "inventory_rebalance_buffer_raw",
            "minimum_economic_profit_raw",
        ):
            _raw_int(getattr(self, name), name)
        if not self.required_cost_kinds or any(not kind for kind in self.required_cost_kinds):
            raise ValueError("required_cost_kinds must be explicit and non-empty")
        kinds = [item.kind for item in self.costs]
        if len(kinds) != len(set(kinds)):
            raise ValueError("cost ledger kinds must be unique")

    @property
    def missing_cost_kinds(self) -> frozenset[str]:
        return self.required_cost_kinds - {item.kind for item in self.costs}

    @property
    def required_edge_raw(self) -> int | None:
        if self.missing_cost_kinds:
            return None
        return (
            sum(item.raw_amount for item in self.costs)
            + self.cost_uncertainty_buffer_raw
            + self.latency_deterioration_buffer_raw
            + self.inventory_rebalance_buffer_raw
            + self.minimum_economic_profit_raw
        )

    @property
    def net_edge_raw(self) -> int | None:
        required = self.required_edge_raw
        return None if required is None else self.gross_edge_raw - required


@dataclass(frozen=True, slots=True)
class InventoryBalance:
    chain_id: int
    asset_id: str
    raw_amount: int

    def __post_init__(self) -> None:
        if self.chain_id <= 0 or not self.asset_id:
            raise ValueError("inventory chain_id and asset_id are required")
        _raw_int(self.raw_amount, "raw_amount")

    @property
    def key(self) -> tuple[int, str]:
        return (self.chain_id, self.asset_id)


@dataclass(frozen=True, slots=True)
class InventoryDelta:
    chain_id: int
    asset_id: str
    raw_delta: int

    def __post_init__(self) -> None:
        if self.chain_id <= 0 or not self.asset_id:
            raise ValueError("inventory delta chain_id and asset_id are required")
        _raw_int(self.raw_delta, "raw_delta", allow_negative=True)
        if self.raw_delta == 0:
            raise ValueError("inventory delta cannot be zero")

    @property
    def key(self) -> tuple[int, str]:
        return (self.chain_id, self.asset_id)


@dataclass(frozen=True, slots=True)
class ReplaySimulation:
    evidence: ReplayEvidence
    success: bool
    minimum_output_satisfied: bool

    def __post_init__(self) -> None:
        if not isinstance(self.success, bool) or not isinstance(self.minimum_output_satisfied, bool):
            raise TypeError("simulation flags must be bool")


@dataclass(frozen=True, slots=True)
class ReplayRebalance:
    evidence: ReplayEvidence
    inventory_deltas: tuple[InventoryDelta, ...]

    def __post_init__(self) -> None:
        if not self.inventory_deltas:
            raise ValueError("a rebalance requires explicit inventory deltas")


@dataclass(frozen=True, slots=True)
class ReplaySnapshot:
    candidate_id: str
    opportunity_key: str
    direction: str
    accounting_decimals: int
    target_size_raw: int
    initial_gross_edge_raw: int
    detected: ReplayEvidence
    requote: ReplayEvidence | None
    requote_ledger: ReplayCostLedger | None
    simulation: ReplaySimulation | None
    inventory_deltas: tuple[InventoryDelta, ...]
    capital_occupied_raw: int
    capital_lock_ms: int
    rebalance: ReplayRebalance | None = None

    def __post_init__(self) -> None:
        if not self.candidate_id or not self.opportunity_key or not self.direction:
            raise ValueError("candidate_id, opportunity_key, and direction are required")
        if not 0 <= self.accounting_decimals <= 255:
            raise ValueError("accounting_decimals must be between 0 and 255")
        _raw_int(self.target_size_raw, "target_size_raw")
        _raw_int(self.initial_gross_edge_raw, "initial_gross_edge_raw", allow_negative=True)
        _raw_int(self.capital_occupied_raw, "capital_occupied_raw")
        _raw_int(self.capital_lock_ms, "capital_lock_ms")
        if self.target_size_raw == 0 or self.capital_occupied_raw == 0 or self.capital_lock_ms == 0:
            raise ValueError("target size, occupied capital, and capital lock must be positive")
        if (self.requote is None) != (self.requote_ledger is None):
            raise ValueError("requote evidence and ledger must be present together")
        if not self.inventory_deltas:
            raise ValueError("a replay snapshot requires explicit inventory deltas")
        evidence = [self.detected]
        if self.requote is not None:
            evidence.append(self.requote)
        if self.simulation is not None:
            evidence.append(self.simulation.evidence)
        if self.rebalance is not None:
            evidence.append(self.rebalance.evidence)
        request_ids = [item.request_id for item in evidence]
        raw_refs = [item.raw_ref for item in evidence]
        if len(set(request_ids)) != len(request_ids) or len(set(raw_refs)) != len(raw_refs):
            raise ValueError("each replay stage requires independent request IDs and Raw refs")
        if self.requote is not None and self.requote.observed_at < self.detected.arrived_at:
            raise ValueError("requote cannot be requested before detection evidence arrives")
        if self.simulation is not None:
            if self.requote is None:
                raise ValueError("simulation requires re-quote evidence")
            if self.simulation.evidence.observed_at < self.requote.arrived_at:
                raise ValueError("simulation cannot be requested before re-quote evidence arrives")
        if self.rebalance is not None:
            if self.simulation is None:
                raise ValueError("rebalance lifecycle requires simulation evidence")
            if self.rebalance.evidence.observed_at < self.simulation.evidence.arrived_at:
                raise ValueError("rebalance cannot be requested before simulation evidence arrives")


class ReplayState(StrEnum):
    WAITING_REQUOTE = "WAITING_REQUOTE"
    WAITING_SIMULATION = "WAITING_SIMULATION"
    REJECTED = "REJECTED"
    PAPER_FILLED = "PAPER_FILLED"


@dataclass(frozen=True, slots=True)
class ReplayDecision:
    candidate_id: str
    state: ReplayState
    decided_at: datetime
    reject_reasons: tuple[str, ...]
    net_edge_raw: int | None
    inventory_applied: bool
    raw_refs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class OpportunityCluster:
    cluster_id: str
    opportunity_key: str
    candidate_ids: tuple[str, ...]
    started_at: datetime
    ended_at: datetime
    lifetime_ms: int


@dataclass(frozen=True, slots=True)
class LatencyDecayPoint:
    latency_ms: int
    samples: int
    median_decay_raw: Decimal


@dataclass(frozen=True, slots=True)
class RebalanceLifecycleEvent:
    candidate_id: str
    status: str
    occurred_at: datetime
    raw_ref: str | None


@dataclass(frozen=True, slots=True)
class ReplayMetrics:
    detected_candidates: int
    unique_clusters: int
    requote_survivors: int
    requote_survival_rate: Decimal
    simulation_survivors: int
    simulation_survival_rate: Decimal
    paper_fills: int
    net_edge_p05: Decimal | None
    net_edge_p50: Decimal | None
    net_edge_p95: Decimal | None
    worst_case_net_edge: Decimal | None
    latency_p05_ms: Decimal | None
    latency_p50_ms: Decimal | None
    latency_p95_ms: Decimal | None
    lifetime_p50_ms: Decimal | None
    profitable_capacity: Decimal | None
    capital_hour_return: Decimal | None
    edge_decay_by_latency: tuple[LatencyDecayPoint, ...]


@dataclass(frozen=True, slots=True)
class ReplayReport:
    as_of: datetime
    decisions: tuple[ReplayDecision, ...]
    clusters: tuple[OpportunityCluster, ...]
    metrics: ReplayMetrics
    ending_inventory: tuple[InventoryBalance, ...]
    rebalance_events: tuple[RebalanceLifecycleEvent, ...]


def run_event_time_replay(
    snapshots: Iterable[ReplaySnapshot],
    initial_inventory: Iterable[InventoryBalance],
    *,
    requote_window_ms: int,
    cluster_gap_ms: int,
    as_of: datetime | None = None,
) -> ReplayReport:
    """Replay snapshots using only evidence that had arrived by ``as_of``."""

    items = tuple(snapshots)
    if not items:
        raise ValueError("at least one replay snapshot is required")
    if requote_window_ms <= 0 or cluster_gap_ms < 0:
        raise ValueError("requote_window_ms must be positive and cluster_gap_ms non-negative")
    if len({item.candidate_id for item in items}) != len(items):
        raise ValueError("candidate_id must be unique")
    decimals = {item.accounting_decimals for item in items}
    if len(decimals) != 1:
        raise ValueError("all replay snapshots must use one accounting precision")

    all_arrivals = [item.detected.arrived_at for item in items]
    for item in items:
        if item.requote is not None:
            all_arrivals.append(item.requote.arrived_at)
        if item.simulation is not None:
            all_arrivals.append(item.simulation.evidence.arrived_at)
        if item.rebalance is not None:
            all_arrivals.append(item.rebalance.evidence.arrived_at)
    cutoff = as_of or max(all_arrivals)
    _require_utc(cutoff, "as_of")

    visible = tuple(item for item in items if item.detected.arrived_at <= cutoff)
    clusters = _cluster(visible, cluster_gap_ms)
    balances = _inventory_map(initial_inventory)
    decisions: list[ReplayDecision] = []
    lifecycle: list[RebalanceLifecycleEvent] = []
    scheduled: list[tuple[datetime, ReplaySnapshot]] = []

    def apply_due(until: datetime) -> None:
        due = sorted(
            (pair for pair in scheduled if pair[0] <= until), key=lambda pair: pair[0]
        )
        for arrived_at, item in due:
            assert item.rebalance is not None
            if _apply_inventory(balances, item.rebalance.inventory_deltas):
                lifecycle.append(RebalanceLifecycleEvent(
                    item.candidate_id, "COMPLETE", arrived_at, item.rebalance.evidence.raw_ref
                ))
            else:
                lifecycle.append(RebalanceLifecycleEvent(
                    item.candidate_id, "REJECTED_NEGATIVE_BALANCE", arrived_at,
                    item.rebalance.evidence.raw_ref,
                ))
            scheduled.remove((arrived_at, item))

    ordered = sorted(visible, key=lambda item: (_decision_sort_time(item, cutoff), item.candidate_id))
    for item in ordered:
        decision_time = _decision_sort_time(item, cutoff)
        apply_due(decision_time)
        decision = _evaluate_snapshot(item, cutoff, requote_window_ms)
        if decision.state is ReplayState.PAPER_FILLED:
            applied = _apply_inventory(balances, item.inventory_deltas)
            if not applied:
                decision = replace(
                    decision,
                    state=ReplayState.REJECTED,
                    reject_reasons=("INSUFFICIENT_VIRTUAL_INVENTORY",),
                    inventory_applied=False,
                )
            elif item.rebalance is not None:
                lifecycle.append(RebalanceLifecycleEvent(
                    item.candidate_id, "PENDING", decision.decided_at, None
                ))
                scheduled.append((item.rebalance.evidence.arrived_at, item))
        decisions.append(decision)

    apply_due(cutoff)
    metrics = _metrics(visible, tuple(decisions), clusters, decimals.pop(), cutoff)
    return ReplayReport(
        as_of=cutoff,
        decisions=tuple(decisions),
        clusters=clusters,
        metrics=metrics,
        ending_inventory=tuple(
            InventoryBalance(chain_id, asset_id, raw)
            for (chain_id, asset_id), raw in sorted(balances.items())
        ),
        rebalance_events=tuple(lifecycle),
    )


def _evaluate_snapshot(item: ReplaySnapshot, cutoff: datetime, window_ms: int) -> ReplayDecision:
    deadline = item.detected.arrived_at + timedelta(milliseconds=window_ms)
    refs = [item.detected.raw_ref]
    if item.requote is None or item.requote.arrived_at > cutoff:
        state = ReplayState.REJECTED if cutoff >= deadline else ReplayState.WAITING_REQUOTE
        reason = "REQUOTE_TIMEOUT" if state is ReplayState.REJECTED else "REQUOTE_NOT_YET_ARRIVED"
        return ReplayDecision(item.candidate_id, state, min(cutoff, deadline), (reason,), None, False, tuple(refs))
    refs.append(item.requote.raw_ref)
    if item.requote.arrived_at > deadline:
        return ReplayDecision(item.candidate_id, ReplayState.REJECTED, item.requote.arrived_at,
                              ("REQUOTE_TIMEOUT",), None, False, tuple(refs))
    assert item.requote_ledger is not None
    net = item.requote_ledger.net_edge_raw
    if net is None:
        missing = ",".join(sorted(item.requote_ledger.missing_cost_kinds))
        return ReplayDecision(item.candidate_id, ReplayState.REJECTED, item.requote.arrived_at,
                              (f"COST_LEDGER_INCOMPLETE:{missing}",), None, False, tuple(refs))
    if net < 0:
        return ReplayDecision(item.candidate_id, ReplayState.REJECTED, item.requote.arrived_at,
                              ("REQUIRED_EDGE_NOT_MET",), net, False, tuple(refs))
    if item.simulation is None or item.simulation.evidence.arrived_at > cutoff:
        return ReplayDecision(item.candidate_id, ReplayState.WAITING_SIMULATION, cutoff,
                              ("SIMULATION_NOT_YET_ARRIVED",), net, False, tuple(refs))
    refs.append(item.simulation.evidence.raw_ref)
    sim = item.simulation
    if not sim.success or not sim.minimum_output_satisfied:
        return ReplayDecision(item.candidate_id, ReplayState.REJECTED, sim.evidence.arrived_at,
                              ("SIMULATION_REJECTED",), net, False, tuple(refs))
    return ReplayDecision(item.candidate_id, ReplayState.PAPER_FILLED, sim.evidence.arrived_at,
                          (), net, True, tuple(refs))


def _decision_sort_time(item: ReplaySnapshot, cutoff: datetime) -> datetime:
    if item.requote is None or item.requote.arrived_at > cutoff:
        return min(cutoff, item.detected.arrived_at)
    if item.simulation is None or item.simulation.evidence.arrived_at > cutoff:
        return item.requote.arrived_at
    return item.simulation.evidence.arrived_at


def _inventory_map(initial: Iterable[InventoryBalance]) -> dict[tuple[int, str], int]:
    items = tuple(initial)
    if not items:
        raise ValueError("initial virtual inventory is required")
    if len({item.key for item in items}) != len(items):
        raise ValueError("initial inventory keys must be unique")
    return {item.key: item.raw_amount for item in items}


def _apply_inventory(
    balances: dict[tuple[int, str], int], deltas: Iterable[InventoryDelta]
) -> bool:
    changes: dict[tuple[int, str], int] = defaultdict(int)
    for delta in deltas:
        if delta.key not in balances:
            raise KeyError(f"missing virtual inventory position: {delta.key}")
        changes[delta.key] += delta.raw_delta
    if any(balances[key] + raw < 0 for key, raw in changes.items()):
        return False
    for key, raw in changes.items():
        balances[key] += raw
    return True


def _cluster(items: tuple[ReplaySnapshot, ...], gap_ms: int) -> tuple[OpportunityCluster, ...]:
    grouped: dict[tuple[str, str, int], list[ReplaySnapshot]] = defaultdict(list)
    for item in items:
        grouped[(item.opportunity_key, item.direction, item.target_size_raw)].append(item)
    result: list[OpportunityCluster] = []
    for key in sorted(grouped):
        current: list[ReplaySnapshot] = []
        for item in sorted(grouped[key], key=lambda value: value.detected.observed_at):
            gap = None if not current else int(
                (item.detected.observed_at - current[-1].detected.observed_at).total_seconds() * 1000
            )
            if current and gap is not None and gap > gap_ms:
                result.append(_make_cluster(key[0], current, len(result) + 1))
                current = []
            current.append(item)
        if current:
            result.append(_make_cluster(key[0], current, len(result) + 1))
    return tuple(sorted(result, key=lambda cluster: cluster.started_at))


def _make_cluster(key: str, items: list[ReplaySnapshot], number: int) -> OpportunityCluster:
    start = items[0].detected.observed_at
    end = items[-1].detected.observed_at
    return OpportunityCluster(
        cluster_id=f"cluster-{number:04d}", opportunity_key=key,
        candidate_ids=tuple(item.candidate_id for item in items),
        started_at=start, ended_at=end,
        lifetime_ms=int((end - start).total_seconds() * 1000),
    )


def _percentile(values: Iterable[int | Decimal], q: Decimal) -> Decimal | None:
    ordered = sorted(Decimal(value) for value in values)
    if not ordered:
        return None
    position = Decimal(len(ordered) - 1) * q
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - Decimal(lower)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _metrics(
    items: tuple[ReplaySnapshot, ...], decisions: tuple[ReplayDecision, ...],
    clusters: tuple[OpportunityCluster, ...], decimals: int, cutoff: datetime,
) -> ReplayMetrics:
    by_id = {item.candidate_id: item for item in items}
    decision_by_id = {decision.candidate_id: decision for decision in decisions}
    completed_requotes = [
        item for item in items
        if item.requote is not None and item.requote_ledger is not None
        and any(dec.candidate_id == item.candidate_id and dec.state is not ReplayState.WAITING_REQUOTE for dec in decisions)
    ]
    requote_survivors = [
        item for item in completed_requotes
        if item.requote_ledger.net_edge_raw is not None
        and item.requote_ledger.net_edge_raw >= 0
        and "REQUOTE_TIMEOUT" not in decision_by_id[item.candidate_id].reject_reasons
        and not any(reason.startswith("COST_LEDGER_INCOMPLETE")
                    for reason in decision_by_id[item.candidate_id].reject_reasons)
    ]
    simulated = [item for item in requote_survivors if item.simulation is not None
                 and any(item.simulation.evidence.raw_ref in dec.raw_refs for dec in decisions)]
    simulation_survivors = [item for item in simulated if item.simulation is not None
                            and item.simulation.success and item.simulation.minimum_output_satisfied]
    fills = [dec for dec in decisions if dec.state is ReplayState.PAPER_FILLED]
    all_nets = [item.requote_ledger.net_edge_raw for item in completed_requotes
                if item.requote_ledger is not None and item.requote_ledger.net_edge_raw is not None]
    fill_nets = [dec.net_edge_raw for dec in fills if dec.net_edge_raw is not None]
    scale = Decimal(1).scaleb(-decimals)
    latencies = [e.latency_ms for item in items for e in _decision_evidence(item)
                 if e.arrived_at <= cutoff]
    decay_groups: dict[int, list[int]] = defaultdict(list)
    for item in completed_requotes:
        assert item.requote is not None and item.requote_ledger is not None
        decay_groups[item.requote.latency_ms].append(
            item.initial_gross_edge_raw - item.requote_ledger.gross_edge_raw
        )
    capital_hours = sum(
        Decimal(by_id[dec.candidate_id].capital_occupied_raw)
        * Decimal(by_id[dec.candidate_id].capital_lock_ms) / Decimal(3_600_000)
        for dec in fills
    )
    capital_return = None if not capital_hours else Decimal(sum(fill_nets)) / capital_hours
    capacities = [by_id[dec.candidate_id].target_size_raw for dec in fills]
    return ReplayMetrics(
        detected_candidates=len(items), unique_clusters=len(clusters),
        requote_survivors=len(requote_survivors),
        requote_survival_rate=Decimal(len(requote_survivors)) / Decimal(len(items)),
        simulation_survivors=len(simulation_survivors),
        simulation_survival_rate=(Decimal(len(simulation_survivors)) / Decimal(len(requote_survivors))
                                  if requote_survivors else Decimal(0)),
        paper_fills=len(fills),
        net_edge_p05=None if not fill_nets else _percentile(fill_nets, Decimal("0.05")) * scale,
        net_edge_p50=None if not fill_nets else _percentile(fill_nets, Decimal("0.50")) * scale,
        net_edge_p95=None if not fill_nets else _percentile(fill_nets, Decimal("0.95")) * scale,
        worst_case_net_edge=None if not all_nets else Decimal(min(all_nets)) * scale,
        latency_p05_ms=_percentile(latencies, Decimal("0.05")),
        latency_p50_ms=_percentile(latencies, Decimal("0.50")),
        latency_p95_ms=_percentile(latencies, Decimal("0.95")),
        lifetime_p50_ms=_percentile((cluster.lifetime_ms for cluster in clusters), Decimal("0.50")),
        profitable_capacity=None if not capacities else Decimal(max(capacities)) * scale,
        capital_hour_return=capital_return,
        edge_decay_by_latency=tuple(
            LatencyDecayPoint(latency, len(values), _percentile(values, Decimal("0.50")) or Decimal(0))
            for latency, values in sorted(decay_groups.items())
        ),
    )


def _decision_evidence(item: ReplaySnapshot) -> tuple[ReplayEvidence, ...]:
    evidence = [item.detected]
    if item.requote is not None:
        evidence.append(item.requote)
    if item.simulation is not None:
        evidence.append(item.simulation.evidence)
    return tuple(evidence)


def load_replay_fixture(path: str | Path) -> tuple[tuple[ReplaySnapshot, ...], tuple[InventoryBalance, ...]]:
    """Load the saved Day 17 raw replay envelope without guessing missing fields."""

    raw_path = Path(path)
    data = json.loads(raw_path.read_text())
    if data.get("schema_version") != 1 or data.get("source") != "captured_replay_evidence":
        raise ValueError("unsupported replay fixture envelope")
    _timestamp(data, "captured_at")
    inventory = tuple(
        InventoryBalance(_positive(row, "chain_id"), _text(row, "asset_id"), _nonnegative(row, "raw_amount"))
        for row in _list(data, "initial_inventory")
    )
    snapshots = tuple(_parse_snapshot(row) for row in _list(data, "snapshots"))
    return snapshots, inventory


def _parse_snapshot(row: Mapping[str, object]) -> ReplaySnapshot:
    requote_row = row.get("requote")
    simulation_row = row.get("simulation")
    rebalance_row = row.get("rebalance")
    if (requote_row is None) != (row.get("cost_ledger") is None):
        raise ValueError("requote evidence and cost_ledger must be present together")
    requote = _evidence(_mapping(requote_row, "requote")) if requote_row is not None else None
    ledger = _ledger(_mapping(row.get("cost_ledger"), "cost_ledger")) if requote is not None else None
    simulation = None if simulation_row is None else ReplaySimulation(
        _evidence(_mapping(simulation_row, "simulation")),
        _bool(_mapping(simulation_row, "simulation"), "success"),
        _bool(_mapping(simulation_row, "simulation"), "minimum_output_satisfied"),
    )
    rebalance = None if rebalance_row is None else ReplayRebalance(
        _evidence(_mapping(rebalance_row, "rebalance")),
        _deltas(_list(_mapping(rebalance_row, "rebalance"), "inventory_deltas")),
    )
    return ReplaySnapshot(
        candidate_id=_text(row, "candidate_id"), opportunity_key=_text(row, "opportunity_key"),
        direction=_text(row, "direction"), accounting_decimals=_nonnegative(row, "accounting_decimals"),
        target_size_raw=_positive(row, "target_size_raw"),
        initial_gross_edge_raw=_integer(row, "initial_gross_edge_raw"),
        detected=_evidence(_mapping(row.get("detected"), "detected")),
        requote=requote, requote_ledger=ledger, simulation=simulation,
        inventory_deltas=_deltas(_list(row, "inventory_deltas")),
        capital_occupied_raw=_positive(row, "capital_occupied_raw"),
        capital_lock_ms=_positive(row, "capital_lock_ms"), rebalance=rebalance,
    )


def _evidence(row: Mapping[str, object]) -> ReplayEvidence:
    return ReplayEvidence(
        _text(row, "request_id"), _text(row, "raw_ref"), _text(row, "source"),
        _timestamp(row, "observed_at"), _timestamp(row, "arrived_at"),
        _nonnegative(row, "latency_ms"),
    )


def _ledger(row: Mapping[str, object]) -> ReplayCostLedger:
    costs = tuple(ReplayCostItem(_text(item, "kind"), _nonnegative(item, "raw_amount"))
                  for item in _list(row, "costs"))
    required = frozenset(_text_value(value, "required_cost_kinds") for value in _list(row, "required_cost_kinds"))
    return ReplayCostLedger(
        _integer(row, "gross_edge_raw"), costs, required,
        _nonnegative(row, "cost_uncertainty_buffer_raw"),
        _nonnegative(row, "latency_deterioration_buffer_raw"),
        _nonnegative(row, "inventory_rebalance_buffer_raw"),
        _nonnegative(row, "minimum_economic_profit_raw"),
    )


def _deltas(rows: list[Mapping[str, object]]) -> tuple[InventoryDelta, ...]:
    return tuple(InventoryDelta(_positive(row, "chain_id"), _text(row, "asset_id"),
                                _integer(row, "raw_delta")) for row in rows)


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise TypeError(f"{name} must be an object")
    return value


def _list(row: Mapping[str, object], name: str) -> list:
    value = row.get(name)
    if not isinstance(value, list):
        raise TypeError(f"{name} must be a list")
    return value


def _text(row: Mapping[str, object], name: str) -> str:
    return _text_value(row.get(name), name)


def _text_value(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise TypeError(f"{name} must be a non-empty string")
    return value


def _integer(row: Mapping[str, object], name: str) -> int:
    return _raw_int(row.get(name), name, allow_negative=True)


def _nonnegative(row: Mapping[str, object], name: str) -> int:
    return _raw_int(row.get(name), name)


def _positive(row: Mapping[str, object], name: str) -> int:
    value = _nonnegative(row, name)
    if value == 0:
        raise ValueError(f"{name} must be positive")
    return value


def _bool(row: Mapping[str, object], name: str) -> bool:
    value = row.get(name)
    if not isinstance(value, bool):
        raise TypeError(f"{name} must be bool")
    return value


def _timestamp(row: Mapping[str, object], name: str) -> datetime:
    value = _text(row, name)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ValueError(f"{name} must be UTC")
    return parsed.astimezone(UTC)


def report_to_dict(report: ReplayReport) -> dict[str, object]:
    """Return a JSON-safe, reviewable derived report."""

    def scalar(value: object) -> object:
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, datetime):
            return value.isoformat().replace("+00:00", "Z")
        if isinstance(value, StrEnum):
            return value.value
        return value

    return {
        "schema_version": 1,
        "as_of": scalar(report.as_of),
        "metrics": {name: scalar(getattr(report.metrics, name))
                    for name in report.metrics.__dataclass_fields__ if name != "edge_decay_by_latency"}
        | {"edge_decay_by_latency": [
            {name: scalar(getattr(point, name)) for name in point.__dataclass_fields__}
            for point in report.metrics.edge_decay_by_latency
        ]},
        "clusters": [
            {name: scalar(getattr(cluster, name)) for name in cluster.__dataclass_fields__}
            for cluster in report.clusters
        ],
        "decisions": [
            {name: scalar(getattr(decision, name)) for name in decision.__dataclass_fields__}
            for decision in report.decisions
        ],
        "ending_inventory": [
            {name: scalar(getattr(item, name)) for name in item.__dataclass_fields__}
            for item in report.ending_inventory
        ],
        "rebalance_events": [
            {name: scalar(getattr(item, name)) for name in item.__dataclass_fields__}
            for item in report.rebalance_events
        ],
    }
