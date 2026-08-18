"""Candidate state definitions, reject reasons, and decision records for Scanner v1."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from onchain_arb.costs import CostEvaluation, CrossChainCostEvaluation
from onchain_arb.inventory import InventoryEvaluation
from onchain_arb.models import TokenAmount, TokenDelta, _require_utc
from onchain_arb.simulation import SimulationComparison


class CandidateState(StrEnum):
    """The six formal states of an arbitrage opportunity candidate in Scanner v1."""

    DETECTED = "DETECTED"
    REQUOTE_FAILED = "REQUOTE_FAILED"
    NET_NEGATIVE = "NET_NEGATIVE"
    INVENTORY_BLOCKED = "INVENTORY_BLOCKED"
    SIMULATION_FAILED = "SIMULATION_FAILED"
    PAPER_READY = "PAPER_READY"


class CandidateRejectReason(StrEnum):
    """Canonical reject reasons across all scanner evaluation gates."""

    # Initial detection / path
    INVALID_INITIAL_PATH = "invalid_initial_path"
    INITIAL_GROSS_NOT_POSITIVE = "initial_gross_not_positive"
    DUPLICATE_OPPORTUNITY = "duplicate_opportunity"

    # Re-quote gate
    REQUOTE_MISSING = "requote_missing"
    NOT_REFRESHED = "requote_not_refreshed"
    VENUE_CHANGED = "requote_venue_changed"
    TARGET_SIZE_CHANGED = "requote_target_size_changed"
    TOKEN_PATH_CHANGED = "requote_token_path_changed"
    LEG_INPUT_NOT_GUARANTEED = "leg_two_input_not_leg_one_minimum"
    REQUOTE_GROSS_NOT_POSITIVE = "requote_gross_not_positive"
    REQUOTE_MINIMUM_NOT_POSITIVE = "requote_minimum_not_positive"
    APPROVAL_UNKNOWN = "approval_unknown"
    LEG_OBSERVATION_SKEW_EXCEEDED = "leg_observation_skew_exceeded"

    # Cost gate
    COST_CURRENCY_MISMATCH = "cost_currency_mismatch"
    COST_LEDGER_INCOMPLETE = "cost_ledger_incomplete"
    NET_NOT_POSITIVE = "net_not_positive"

    # Inventory gate
    INVENTORY_BLOCKED = "inventory_blocked"
    INVENTORY_MISSING_BALANCE_SHEET = "inventory_missing_balance_sheet"
    INSUFFICIENT_BALANCE = "insufficient_balance"
    MAX_IMBALANCE_EXCEEDED = "max_imbalance_exceeded"

    # Simulation gate
    SIMULATION_MISSING = "simulation_missing"
    SIMULATION_REVERTED = "simulation_reverted"
    SIMULATION_OUTPUT_BELOW_QUOTED = "output_below_quoted"
    SIMULATION_OUTPUT_BELOW_MINIMUM = "output_below_minimum"
    SIMULATION_OUTPUT_MISSING = "output_missing"
    SIMULATION_INSUFFICIENT_ALLOWANCE = "insufficient_allowance"
    SIMULATION_STALE_BLOCK = "stale_block"
    SIMULATION_TOKEN_MISMATCH = "token_mismatch"


@dataclass(frozen=True, slots=True)
class ScanDecision:
    """The auditable final decision for a scanned opportunity candidate."""

    candidate_id: str
    candidate_type: str
    state: CandidateState
    reject_reasons: tuple[str, ...]
    target_size: TokenAmount
    gross_pnl: TokenDelta | None
    net_pnl: Decimal | None
    cost_evaluation: CostEvaluation | CrossChainCostEvaluation | None
    inventory_evaluation: InventoryEvaluation | None
    simulation_comparison: SimulationComparison | None
    raw_refs: tuple[str, ...]
    detected_at: datetime
    decided_at: datetime
    decision_latency_ms: Decimal
    opportunity_lifetime_ms: Decimal | None

    def __post_init__(self) -> None:
        if not self.candidate_id:
            raise ValueError("candidate_id is required")
        if self.candidate_type not in ("same_chain", "cross_chain"):
            raise ValueError("candidate_type must be 'same_chain' or 'cross_chain'")
        if not isinstance(self.state, CandidateState):
            raise TypeError("state must be a CandidateState enum")
        if not isinstance(self.decision_latency_ms, Decimal) or not self.decision_latency_ms.is_finite():
            raise TypeError("decision_latency_ms must be a finite Decimal")
        if self.decision_latency_ms < 0:
            raise ValueError("decision_latency_ms must be non-negative")
        if self.opportunity_lifetime_ms is not None:
            if not isinstance(self.opportunity_lifetime_ms, Decimal) or not self.opportunity_lifetime_ms.is_finite():
                raise TypeError("opportunity_lifetime_ms must be a finite Decimal")
            if self.opportunity_lifetime_ms < 0:
                raise ValueError("opportunity_lifetime_ms must be non-negative")
        _require_utc(self.detected_at, "detected_at")
        _require_utc(self.decided_at, "decided_at")

        if self.state is CandidateState.PAPER_READY and self.reject_reasons:
            raise ValueError("PAPER_READY candidate cannot have reject reasons")
        if self.state is not CandidateState.PAPER_READY and not self.reject_reasons:
            raise ValueError("rejected candidate must have at least one reject reason")

    @property
    def accepted(self) -> bool:
        return self.state is CandidateState.PAPER_READY

    @property
    def has_complete_costs(self) -> bool:
        return self.cost_evaluation is not None and self.cost_evaluation.is_complete

    @property
    def has_raw_refs(self) -> bool:
        return len(self.raw_refs) > 0 and all(bool(ref) for ref in self.raw_refs)
