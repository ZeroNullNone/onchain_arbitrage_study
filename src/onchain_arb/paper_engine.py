"""Idempotent, paper-only decision and virtual-fill state machine.

The engine deliberately performs no wallet, signing, broadcast, or notification I/O.
Its inputs are already-captured evidence and its outputs are an append-only audit log,
virtual balances, and alert intents for a caller to persist.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import StrEnum
import hashlib
import json
from pathlib import Path
from typing import Iterable

from onchain_arb.models import _require_utc
from onchain_arb.replay import (
    InventoryBalance,
    InventoryDelta,
    ReplayCostItem,
    ReplayCostLedger,
    ReplayEvidence,
    ReplaySimulation,
)


class PaperState(StrEnum):
    DETECTED = "DETECTED"
    REQUOTING = "REQUOTING"
    COSTED = "COSTED"
    INVENTORY_CHECKED = "INVENTORY_CHECKED"
    SIMULATED = "SIMULATED"
    SIMULATION_NA = "SIMULATION_NA"
    PAPER_READY = "PAPER_READY"
    PAPER_FILLED = "PAPER_FILLED"
    REBALANCE_PENDING = "REBALANCE_PENDING"
    CLOSED = "CLOSED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    ERROR = "ERROR"


class AlertKind(StrEnum):
    PAPER_READY = "PAPER_READY"
    SYSTEM_ERROR = "SYSTEM_ERROR"


@dataclass(frozen=True, slots=True)
class Allowance:
    chain_id: int
    asset_id: str
    spender: str
    raw_amount: int

    def __post_init__(self) -> None:
        if self.chain_id <= 0 or not self.asset_id or not self.spender:
            raise ValueError("allowance chain, asset, and spender are required")
        if isinstance(self.raw_amount, bool) or not isinstance(self.raw_amount, int):
            raise TypeError("allowance raw_amount must be an integer")
        if self.raw_amount < 0:
            raise ValueError("allowance raw_amount must be non-negative")

    @property
    def key(self) -> tuple[int, str, str]:
        return (self.chain_id, self.asset_id, self.spender)


@dataclass(frozen=True, slots=True)
class AllowanceRequirement:
    chain_id: int
    asset_id: str
    spender: str
    raw_amount: int

    def __post_init__(self) -> None:
        Allowance(self.chain_id, self.asset_id, self.spender, self.raw_amount)
        if self.raw_amount == 0:
            raise ValueError("required allowance must be positive")

    @property
    def key(self) -> tuple[int, str, str]:
        return (self.chain_id, self.asset_id, self.spender)


@dataclass(frozen=True, slots=True)
class PaperCandidate:
    candidate_id: str
    opportunity_key: str
    direction: str
    target_size_raw: int
    detected: ReplayEvidence
    requote: ReplayEvidence
    original_route: str
    refreshed_route: str
    expires_at: datetime
    ledger_ref: str
    cost_ledger: ReplayCostLedger
    inventory_deltas: tuple[InventoryDelta, ...]
    allowance_requirements: tuple[AllowanceRequirement, ...]
    simulation_required: bool
    simulation: ReplaySimulation | None
    rebalance_deltas: tuple[InventoryDelta, ...] = ()
    rebalance_evidence: ReplayEvidence | None = None

    def __post_init__(self) -> None:
        if not all((self.candidate_id, self.opportunity_key, self.direction,
                    self.original_route, self.refreshed_route, self.ledger_ref)):
            raise ValueError("candidate identity, routes, and ledger_ref are required")
        if isinstance(self.target_size_raw, bool) or not isinstance(self.target_size_raw, int):
            raise TypeError("target_size_raw must be an integer")
        if self.target_size_raw <= 0 or not self.inventory_deltas:
            raise ValueError("target size and inventory deltas must be present")
        _require_utc(self.expires_at, "expires_at")
        if self.expires_at < self.detected.arrived_at:
            raise ValueError("candidate cannot expire before detection arrives")
        if self.requote.observed_at < self.detected.arrived_at:
            raise ValueError("requote cannot precede detection arrival")
        if not isinstance(self.simulation_required, bool):
            raise TypeError("simulation_required must be bool")
        if self.simulation_required != (self.simulation is not None):
            raise ValueError("required simulation evidence must be explicitly present")
        if self.simulation is not None and self.simulation.evidence.observed_at < self.requote.arrived_at:
            raise ValueError("simulation cannot precede requote arrival")
        if bool(self.rebalance_deltas) != (self.rebalance_evidence is not None):
            raise ValueError("rebalance deltas and evidence must be present together")
        refs = self.evidence_refs
        if len(refs) != len(set(refs)):
            raise ValueError("every evidence stage requires a distinct Raw ref")

    @property
    def evidence_refs(self) -> tuple[str, ...]:
        refs = [self.detected.raw_ref, self.requote.raw_ref, self.ledger_ref]
        if self.simulation is not None:
            refs.append(self.simulation.evidence.raw_ref)
        if self.rebalance_evidence is not None:
            refs.append(self.rebalance_evidence.raw_ref)
        return tuple(refs)

    @property
    def fill_evidence_refs(self) -> tuple[str, ...]:
        """Evidence available at fill time; later rebalance evidence is excluded."""
        refs = [self.detected.raw_ref, self.requote.raw_ref, self.ledger_ref]
        if self.simulation is not None:
            refs.append(self.simulation.evidence.raw_ref)
        return tuple(refs)

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(repr(self).encode()).hexdigest()


def make_candidate_id(
    opportunity_key: str, direction: str, target_size_raw: int, detection_request_id: str
) -> str:
    """Build a stable ID from immutable detection identity, never current time."""
    if isinstance(target_size_raw, bool) or not isinstance(target_size_raw, int):
        raise TypeError("target_size_raw must be an integer")
    if not opportunity_key or not direction or not detection_request_id or target_size_raw <= 0:
        raise ValueError("complete candidate identity is required")
    payload = f"{opportunity_key}\x1f{direction}\x1f{target_size_raw}\x1f{detection_request_id}"
    return "paper-" + hashlib.sha256(payload.encode()).hexdigest()[:24]


@dataclass(frozen=True, slots=True)
class StateTransition:
    sequence: int
    candidate_id: str
    from_state: PaperState | None
    to_state: PaperState
    occurred_at: datetime
    latency_ms: int
    reason: str | None
    raw_refs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AlertIntent:
    kind: AlertKind
    candidate_id: str
    occurred_at: datetime
    message: str


@dataclass(frozen=True, slots=True)
class PaperDecision:
    candidate_id: str
    state: PaperState
    reject_reason: str | None
    net_edge_raw: int | None
    filled: bool
    raw_quote_ref: str
    requote_ref: str
    ledger_ref: str
    simulation_ref: str | None
    transitions: tuple[StateTransition, ...]
    alerts: tuple[AlertIntent, ...]


class PaperDecisionEngine:
    """Single-process virtual executor; repeated candidate IDs return one decision."""

    def __init__(self, balances: Iterable[InventoryBalance], allowances: Iterable[Allowance]) -> None:
        balance_items = tuple(balances)
        allowance_items = tuple(allowances)
        if not balance_items:
            raise ValueError("initial virtual balances are required")
        if len({item.key for item in balance_items}) != len(balance_items):
            raise ValueError("virtual balance keys must be unique")
        if len({item.key for item in allowance_items}) != len(allowance_items):
            raise ValueError("virtual allowance keys must be unique")
        self._balances = {item.key: item.raw_amount for item in balance_items}
        self._allowances = {item.key: item.raw_amount for item in allowance_items}
        self._decisions: dict[str, PaperDecision] = {}
        self._fingerprints: dict[str, str] = {}
        self._audit: list[StateTransition] = []
        self._alerts: list[AlertIntent] = []

    @property
    def audit_log(self) -> tuple[StateTransition, ...]:
        return tuple(self._audit)

    @property
    def alerts(self) -> tuple[AlertIntent, ...]:
        return tuple(self._alerts)

    @property
    def balances(self) -> tuple[InventoryBalance, ...]:
        return tuple(InventoryBalance(chain, asset, raw)
                     for (chain, asset), raw in sorted(self._balances.items()))

    def process(self, candidate: PaperCandidate, *, now: datetime) -> PaperDecision:
        _require_utc(now, "now")
        prior = self._decisions.get(candidate.candidate_id)
        if prior is not None:
            if self._fingerprints[candidate.candidate_id] != candidate.fingerprint:
                return self._identity_conflict(candidate, now)
            if (prior.state is PaperState.REBALANCE_PENDING
                    and candidate.rebalance_evidence is not None
                    and candidate.rebalance_evidence.arrived_at <= now):
                return self._complete_rebalance(candidate, prior)
            return prior

        if now < candidate.detected.arrived_at:
            raise ValueError("detection evidence has not arrived at decision time")
        if now < candidate.expires_at and now < candidate.requote.arrived_at:
            raise ValueError("requote evidence has not arrived at decision time")
        if (now < candidate.expires_at and candidate.simulation is not None
                and now < candidate.simulation.evidence.arrived_at):
            raise ValueError("simulation evidence has not arrived at decision time")

        local: list[StateTransition] = []
        local_alerts: list[AlertIntent] = []

        def move(state: PaperState, at: datetime, reason: str | None = None,
                 refs: tuple[str, ...] = ()) -> None:
            previous = local[-1].to_state if local else None
            latency = max(0, int((at - candidate.detected.arrived_at).total_seconds() * 1000))
            event = StateTransition(len(self._audit) + len(local) + 1, candidate.candidate_id,
                                    previous, state, at, latency, reason, refs)
            local.append(event)

        move(PaperState.DETECTED, candidate.detected.arrived_at, refs=(candidate.detected.raw_ref,))
        if now >= candidate.expires_at:
            move(PaperState.EXPIRED, now, "QUOTE_EXPIRED")
            return self._finish(candidate, local, local_alerts, "QUOTE_EXPIRED", None, False)

        move(PaperState.REQUOTING, candidate.requote.observed_at)
        if candidate.requote.arrived_at >= candidate.expires_at:
            move(PaperState.EXPIRED, candidate.requote.arrived_at, "REQUOTE_ARRIVED_AFTER_EXPIRY",
                 (candidate.requote.raw_ref,))
            return self._finish(candidate, local, local_alerts,
                                "REQUOTE_ARRIVED_AFTER_EXPIRY", None, False)
        if candidate.original_route != candidate.refreshed_route:
            move(PaperState.REJECTED, candidate.requote.arrived_at, "ROUTE_CHANGED",
                 (candidate.requote.raw_ref,))
            return self._finish(candidate, local, local_alerts, "ROUTE_CHANGED", None, False)

        net = candidate.cost_ledger.net_edge_raw
        if net is None:
            missing = ",".join(sorted(candidate.cost_ledger.missing_cost_kinds))
            reason = f"COST_LEDGER_INCOMPLETE:{missing}"
            move(PaperState.REJECTED, candidate.requote.arrived_at, reason,
                 (candidate.requote.raw_ref, candidate.ledger_ref))
            return self._finish(candidate, local, local_alerts, reason, None, False)
        move(PaperState.COSTED, candidate.requote.arrived_at,
             refs=(candidate.requote.raw_ref, candidate.ledger_ref))
        if net < 0:
            move(PaperState.REJECTED, candidate.requote.arrived_at, "REQUIRED_EDGE_NOT_MET")
            return self._finish(candidate, local, local_alerts, "REQUIRED_EDGE_NOT_MET", net, False)

        inventory_reason = self._inventory_failure(candidate.inventory_deltas)
        allowance_reason = self._allowance_failure(candidate.allowance_requirements)
        if inventory_reason or allowance_reason:
            reason = inventory_reason or allowance_reason
            move(PaperState.REJECTED, candidate.requote.arrived_at, reason)
            return self._finish(candidate, local, local_alerts, reason, net, False)
        move(PaperState.INVENTORY_CHECKED, candidate.requote.arrived_at)

        if candidate.simulation is None:
            move(PaperState.SIMULATION_NA, candidate.requote.arrived_at)
        else:
            sim = candidate.simulation
            if not sim.success or not sim.minimum_output_satisfied:
                move(PaperState.REJECTED, sim.evidence.arrived_at, "SIMULATION_REJECTED",
                     (sim.evidence.raw_ref,))
                return self._finish(candidate, local, local_alerts, "SIMULATION_REJECTED", net, False)
            move(PaperState.SIMULATED, sim.evidence.arrived_at, refs=(sim.evidence.raw_ref,))

        ready_at = local[-1].occurred_at
        move(PaperState.PAPER_READY, ready_at)
        alert = AlertIntent(AlertKind.PAPER_READY, candidate.candidate_id, ready_at,
                            "candidate passed every paper gate")
        local_alerts.append(alert)
        self._apply(candidate.inventory_deltas)
        move(PaperState.PAPER_FILLED, ready_at, refs=candidate.fill_evidence_refs)
        if candidate.rebalance_evidence is not None:
            move(PaperState.REBALANCE_PENDING, ready_at)
            if candidate.rebalance_evidence.arrived_at > now:
                return self._finish(candidate, local, local_alerts, None, net, True)
            reason = self._inventory_failure(candidate.rebalance_deltas)
            if reason:
                move(PaperState.ERROR, candidate.rebalance_evidence.arrived_at,
                     f"REBALANCE_{reason}", (candidate.rebalance_evidence.raw_ref,))
                error = AlertIntent(AlertKind.SYSTEM_ERROR, candidate.candidate_id,
                                    candidate.rebalance_evidence.arrived_at,
                                    f"paper rebalance failed: {reason}")
                local_alerts.append(error)
                return self._finish(candidate, local, local_alerts,
                                    f"REBALANCE_{reason}", net, True)
            self._apply(candidate.rebalance_deltas)
            move(PaperState.CLOSED, candidate.rebalance_evidence.arrived_at,
                 refs=(candidate.rebalance_evidence.raw_ref,))
        return self._finish(candidate, local, local_alerts, None, net, True)

    def _complete_rebalance(
        self, candidate: PaperCandidate, prior: PaperDecision
    ) -> PaperDecision:
        assert candidate.rebalance_evidence is not None
        reason = self._inventory_failure(candidate.rebalance_deltas)
        state = PaperState.ERROR if reason else PaperState.CLOSED
        full_reason = None if reason is None else f"REBALANCE_{reason}"
        transition = StateTransition(
            len(self._audit) + 1, candidate.candidate_id, PaperState.REBALANCE_PENDING,
            state, candidate.rebalance_evidence.arrived_at,
            int((candidate.rebalance_evidence.arrived_at
                 - candidate.detected.arrived_at).total_seconds() * 1000),
            full_reason, (candidate.rebalance_evidence.raw_ref,),
        )
        alerts = prior.alerts
        if reason is None:
            self._apply(candidate.rebalance_deltas)
        else:
            error = AlertIntent(AlertKind.SYSTEM_ERROR, candidate.candidate_id,
                                candidate.rebalance_evidence.arrived_at,
                                f"paper rebalance failed: {reason}")
            alerts += (error,)
            self._alerts.append(error)
        decision = PaperDecision(
            prior.candidate_id, state, full_reason, prior.net_edge_raw, True,
            prior.raw_quote_ref, prior.requote_ref, prior.ledger_ref, prior.simulation_ref,
            prior.transitions + (transition,), alerts,
        )
        self._decisions[candidate.candidate_id] = decision
        self._audit.append(transition)
        return decision

    def _inventory_failure(self, deltas: Iterable[InventoryDelta]) -> str | None:
        changes: dict[tuple[int, str], int] = defaultdict(int)
        for delta in deltas:
            if delta.key not in self._balances:
                return f"MISSING_VIRTUAL_BALANCE:{delta.chain_id}:{delta.asset_id}"
            changes[delta.key] += delta.raw_delta
        for key, raw in changes.items():
            if self._balances[key] + raw < 0:
                return f"INSUFFICIENT_VIRTUAL_BALANCE:{key[0]}:{key[1]}"
        return None

    def _allowance_failure(self, requirements: Iterable[AllowanceRequirement]) -> str | None:
        for item in requirements:
            available = self._allowances.get(item.key)
            if available is None:
                return f"MISSING_VIRTUAL_ALLOWANCE:{item.chain_id}:{item.asset_id}:{item.spender}"
            if available < item.raw_amount:
                return f"INSUFFICIENT_VIRTUAL_ALLOWANCE:{item.chain_id}:{item.asset_id}:{item.spender}"
        return None

    def _apply(self, deltas: Iterable[InventoryDelta]) -> None:
        for delta in deltas:
            self._balances[delta.key] += delta.raw_delta

    def _finish(self, candidate: PaperCandidate, transitions: list[StateTransition],
                alerts: list[AlertIntent], reason: str | None, net: int | None,
                filled: bool) -> PaperDecision:
        decision = PaperDecision(
            candidate.candidate_id, transitions[-1].to_state, reason, net, filled,
            candidate.detected.raw_ref, candidate.requote.raw_ref, candidate.ledger_ref,
            None if candidate.simulation is None else candidate.simulation.evidence.raw_ref,
            tuple(transitions), tuple(alerts),
        )
        self._fingerprints[candidate.candidate_id] = candidate.fingerprint
        self._decisions[candidate.candidate_id] = decision
        self._audit.extend(transitions)
        self._alerts.extend(alerts)
        return decision

    def _identity_conflict(self, candidate: PaperCandidate, now: datetime) -> PaperDecision:
        prior = self._decisions[candidate.candidate_id]
        latency_ms = max(0, int((now - candidate.detected.arrived_at).total_seconds() * 1000))
        transition = StateTransition(len(self._audit) + 1, candidate.candidate_id, prior.state,
                                     PaperState.ERROR, now, latency_ms,
                                     "CANDIDATE_ID_CONFLICT", ())
        alert = AlertIntent(AlertKind.SYSTEM_ERROR, candidate.candidate_id, now,
                            "candidate ID was reused for different evidence")
        self._audit.append(transition)
        self._alerts.append(alert)
        return PaperDecision(candidate.candidate_id, PaperState.ERROR, "CANDIDATE_ID_CONFLICT",
                             None, False, candidate.detected.raw_ref, candidate.requote.raw_ref,
                             candidate.ledger_ref, None, (transition,), (alert,))


def decision_to_dict(decision: PaperDecision) -> dict[str, object]:
    """Serialize one immutable decision without dropping evidence lineage."""
    return json.loads(json.dumps(asdict(decision), default=lambda value: (
        value.isoformat().replace("+00:00", "Z") if isinstance(value, datetime)
        else value.value if isinstance(value, StrEnum)
        else value
    )))


def load_paper_fixture(
    path: str | Path,
) -> tuple[tuple[PaperCandidate, ...], tuple[InventoryBalance, ...], tuple[Allowance, ...]]:
    """Load a complete saved Day 18 envelope; absent fields are never inferred."""
    data = json.loads(Path(path).read_text())
    if data.get("schema_version") != 1 or data.get("source") != "captured_paper_evidence":
        raise ValueError("unsupported paper evidence envelope")

    def rows(parent: dict, key: str) -> list[dict]:
        value = parent.get(key)
        if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
            raise TypeError(f"{key} must be a list of objects")
        return value

    def text_value(parent: dict, key: str) -> str:
        value = parent.get(key)
        if not isinstance(value, str) or not value:
            raise TypeError(f"{key} must be a non-empty string")
        return value

    def integer(parent: dict, key: str, *, nonnegative: bool = False) -> int:
        value = parent.get(key)
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"{key} must be an integer")
        if nonnegative and value < 0:
            raise ValueError(f"{key} must be non-negative")
        return value

    def timestamp(parent: dict, key: str) -> datetime:
        parsed = datetime.fromisoformat(text_value(parent, key).replace("Z", "+00:00"))
        _require_utc(parsed, key)
        return parsed

    def evidence(row: dict) -> ReplayEvidence:
        return ReplayEvidence(
            text_value(row, "request_id"), text_value(row, "raw_ref"),
            text_value(row, "source"), timestamp(row, "observed_at"),
            timestamp(row, "arrived_at"), integer(row, "latency_ms", nonnegative=True),
        )

    timestamp(data, "captured_at")

    def deltas(parent: dict, key: str) -> tuple[InventoryDelta, ...]:
        return tuple(InventoryDelta(integer(row, "chain_id", nonnegative=True),
                                    text_value(row, "asset_id"), integer(row, "raw_delta"))
                     for row in rows(parent, key))

    balances = tuple(InventoryBalance(integer(row, "chain_id", nonnegative=True),
                                      text_value(row, "asset_id"),
                                      integer(row, "raw_amount", nonnegative=True))
                     for row in rows(data, "initial_balances"))
    allowances = tuple(Allowance(integer(row, "chain_id", nonnegative=True),
                                 text_value(row, "asset_id"), text_value(row, "spender"),
                                 integer(row, "raw_amount", nonnegative=True))
                       for row in rows(data, "initial_allowances"))
    candidates: list[PaperCandidate] = []
    for row in rows(data, "candidates"):
        detected = evidence(row["detected"])
        requote = evidence(row["requote"])
        ledger_row = row["cost_ledger"]
        if not isinstance(ledger_row, dict):
            raise TypeError("cost_ledger must be an object")
        required_kinds = ledger_row.get("required_cost_kinds")
        if not isinstance(required_kinds, list):
            raise TypeError("required_cost_kinds must be a list")
        ledger = ReplayCostLedger(
            integer(ledger_row, "gross_edge_raw"),
            tuple(ReplayCostItem(text_value(item, "kind"),
                                 integer(item, "raw_amount", nonnegative=True))
                  for item in rows(ledger_row, "costs")),
            frozenset(text_value({"value": value}, "value") for value in required_kinds),
            integer(ledger_row, "cost_uncertainty_buffer_raw", nonnegative=True),
            integer(ledger_row, "latency_deterioration_buffer_raw", nonnegative=True),
            integer(ledger_row, "inventory_rebalance_buffer_raw", nonnegative=True),
            integer(ledger_row, "minimum_economic_profit_raw", nonnegative=True),
        )
        sim_row = row.get("simulation")
        simulation = None
        if sim_row is not None:
            if not isinstance(sim_row, dict):
                raise TypeError("simulation must be an object or null")
            success = sim_row.get("success")
            minimum = sim_row.get("minimum_output_satisfied")
            if not isinstance(success, bool) or not isinstance(minimum, bool):
                raise TypeError("simulation flags must be bool")
            simulation = ReplaySimulation(evidence(sim_row), success, minimum)
        rebalance_row = row.get("rebalance_evidence")
        rebalance_evidence = None if rebalance_row is None else evidence(rebalance_row)
        requirements = tuple(
            AllowanceRequirement(integer(item, "chain_id", nonnegative=True),
                                 text_value(item, "asset_id"), text_value(item, "spender"),
                                 integer(item, "raw_amount", nonnegative=True))
            for item in rows(row, "allowance_requirements")
        )
        target_size = integer(row, "target_size_raw", nonnegative=True)
        expected_id = make_candidate_id(text_value(row, "opportunity_key"),
                                        text_value(row, "direction"), target_size,
                                        detected.request_id)
        if text_value(row, "candidate_id") != expected_id:
            raise ValueError("candidate_id does not match immutable detection identity")
        candidates.append(PaperCandidate(
            expected_id, text_value(row, "opportunity_key"), text_value(row, "direction"),
            target_size, detected, requote, text_value(row, "original_route"),
            text_value(row, "refreshed_route"), timestamp(row, "expires_at"),
            text_value(row, "ledger_ref"), ledger, deltas(row, "inventory_deltas"),
            requirements, row.get("simulation_required"), simulation,
            deltas(row, "rebalance_deltas"), rebalance_evidence,
        ))
    return tuple(candidates), balances, allowances
