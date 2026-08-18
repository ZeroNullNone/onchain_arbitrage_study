"""End-to-end scanner pipeline connecting detection, requote, cost, inventory, simulation, and persistence."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import json
import math
import os
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from uuid import uuid4

from onchain_arb.costs import CostEvaluation, CostLedger, CrossChainCostEvaluation
from onchain_arb.decision import CandidateRejectReason, CandidateState, ScanDecision
from onchain_arb.detectors.same_chain import RejectReason as BaselineRejectReason
from onchain_arb.inventory import (
    CrossChainSignal,
    InventoryEvaluation,
    InventoryStatus,
    VirtualBalanceSheet,
    evaluate_inventory,
)
from onchain_arb.models import (
    CostConfidence,
    CostItem,
    CostScope,
    QuoteObservation,
    TokenAmount,
    TokenDelta,
    _require_utc,
)
from onchain_arb.requote import (
    ApprovalStatus,
    DirectQuote,
    RequoteRejectReason,
    RoundTripQuotes,
    validate_requote,
    validate_round_trip,
)
from onchain_arb.simulation import (
    SimulationComparison,
    SimulationEvidence,
    SimulationRejectReason,
    compare_quote_and_simulation,
)


@dataclass(frozen=True, slots=True)
class SameChainScanAttempt:
    """One same-chain round-trip opportunity candidate for scanner evaluation."""

    candidate_id: str
    initial: RoundTripQuotes
    refreshed: RoundTripQuotes | None = None
    simulation: SimulationEvidence | None = None
    detected_at: datetime | None = None
    decided_at: datetime | None = None
    expiry_at: datetime | None = None
    raw_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.candidate_id:
            raise ValueError("candidate_id is required")


@dataclass(frozen=True, slots=True)
class CrossChainScanAttempt:
    """One cross-chain inventory opportunity candidate for scanner evaluation."""

    candidate_id: str
    signal: CrossChainSignal
    refreshed_signal: CrossChainSignal | None = None
    balance_sheet: VirtualBalanceSheet | None = None
    detected_at: datetime | None = None
    decided_at: datetime | None = None
    expiry_at: datetime | None = None
    raw_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.candidate_id:
            raise ValueError("candidate_id is required")


class CandidateDeduplicator:
    """Sliding-window opportunity deduplicator to prevent repeat fills on identical signals."""

    def __init__(self, window_seconds: float = 60.0) -> None:
        if window_seconds < 0:
            raise ValueError("window_seconds must be non-negative")
        self._window = timedelta(seconds=window_seconds)
        self._seen: dict[str, datetime] = {}

    def is_duplicate(self, fingerprint: str, observed_at: datetime) -> bool:
        _require_utc(observed_at, "observed_at")
        if self._window.total_seconds() == 0:
            return False
        last_seen = self._seen.get(fingerprint)
        if last_seen is None:
            return False
        if observed_at - last_seen <= self._window:
            return True
        return False

    def record(self, fingerprint: str, observed_at: datetime) -> None:
        _require_utc(observed_at, "observed_at")
        self._seen[fingerprint] = observed_at


@dataclass(frozen=True, slots=True)
class ScannerMetrics:
    """Consolidated execution and funnel metrics for a scanner run."""

    total_detected: int
    duplicates_filtered: int
    evaluated_count: int
    requote_survivors: int
    requote_survivor_ratio: float
    net_positive_survivors: int
    simulation_attempted: int
    simulation_survivors: int
    simulation_survivor_ratio: float
    inventory_attempted: int
    inventory_survivors: int
    paper_ready_count: int
    cost_completeness_ratio: float
    raw_ref_coverage_ratio: float
    mean_decision_latency_ms: float | None
    p50_decision_latency_ms: float | None
    p95_decision_latency_ms: float | None
    mean_opportunity_lifetime_ms: float | None
    is_sparse: bool
    state_counts: tuple[tuple[str, int], ...]
    reject_counts: tuple[tuple[str, int], ...]
    largest_reject_reason: str | None


@dataclass(frozen=True, slots=True)
class ScannerReport:
    """Immutable report containing all decisions and metrics from a scan run."""

    decisions: tuple[ScanDecision, ...]
    metrics: ScannerMetrics
    generated_at: datetime

    def __post_init__(self) -> None:
        _require_utc(self.generated_at, "generated_at")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "generated_at": self.generated_at.isoformat(),
            "metrics": {
                "total_detected": self.metrics.total_detected,
                "duplicates_filtered": self.metrics.duplicates_filtered,
                "evaluated_count": self.metrics.evaluated_count,
                "requote_survivors": self.metrics.requote_survivors,
                "requote_survivor_ratio": self.metrics.requote_survivor_ratio,
                "net_positive_survivors": self.metrics.net_positive_survivors,
                "simulation_attempted": self.metrics.simulation_attempted,
                "simulation_survivors": self.metrics.simulation_survivors,
                "simulation_survivor_ratio": self.metrics.simulation_survivor_ratio,
                "inventory_attempted": self.metrics.inventory_attempted,
                "inventory_survivors": self.metrics.inventory_survivors,
                "paper_ready_count": self.metrics.paper_ready_count,
                "cost_completeness_ratio": self.metrics.cost_completeness_ratio,
                "raw_ref_coverage_ratio": self.metrics.raw_ref_coverage_ratio,
                "mean_decision_latency_ms": self.metrics.mean_decision_latency_ms,
                "p50_decision_latency_ms": self.metrics.p50_decision_latency_ms,
                "p95_decision_latency_ms": self.metrics.p95_decision_latency_ms,
                "mean_opportunity_lifetime_ms": self.metrics.mean_opportunity_lifetime_ms,
                "is_sparse": self.metrics.is_sparse,
                "state_counts": dict(self.metrics.state_counts),
                "reject_counts": dict(self.metrics.reject_counts),
                "largest_reject_reason": self.metrics.largest_reject_reason,
            },
            "decisions": [
                {
                    "candidate_id": d.candidate_id,
                    "candidate_type": d.candidate_type,
                    "state": d.state.value,
                    "reject_reasons": list(d.reject_reasons),
                    "target_size": {
                        "symbol": d.target_size.token.symbol,
                        "raw": d.target_size.raw_amount,
                        "decimal": str(d.target_size.decimal_amount),
                    },
                    "gross_pnl": None
                    if d.gross_pnl is None
                    else {
                        "symbol": d.gross_pnl.token.symbol,
                        "raw": d.gross_pnl.raw_delta,
                        "decimal": str(d.gross_pnl.decimal_delta),
                    },
                    "net_pnl": None if d.net_pnl is None else str(d.net_pnl),
                    "raw_refs": list(d.raw_refs),
                    "detected_at": d.detected_at.isoformat(),
                    "decided_at": d.decided_at.isoformat(),
                    "decision_latency_ms": str(d.decision_latency_ms),
                    "opportunity_lifetime_ms": None
                    if d.opportunity_lifetime_ms is None
                    else str(d.opportunity_lifetime_ms),
                }
                for d in self.decisions
            ],
        }


class ScannerPipeline:
    """Conservative research loop evaluating candidate opportunities across all gates."""

    def __init__(
        self,
        *,
        deduplicator: CandidateDeduplicator | None = None,
        dedup_window_seconds: float = 60.0,
    ) -> None:
        self._deduplicator = deduplicator or CandidateDeduplicator(dedup_window_seconds)

    def evaluate_same_chain(self, attempt: SameChainScanAttempt) -> ScanDecision:
        """Evaluate a same-chain candidate across the full 10-step gate pipeline."""

        detected_at = (
            attempt.detected_at
            or attempt.initial.first_leg.observed_at
        )
        _require_utc(detected_at, "detected_at")

        raw_refs: list[str] = list(attempt.raw_refs)
        raw_refs.append(attempt.initial.first_leg.raw_ref)
        raw_refs.append(attempt.initial.second_leg.raw_ref)
        if attempt.refreshed is not None:
            raw_refs.append(attempt.refreshed.first_leg.raw_ref)
            raw_refs.append(attempt.refreshed.second_leg.raw_ref)
        if attempt.simulation is not None:
            raw_refs.append(attempt.simulation.raw_ref)
        deduped_raw_refs = tuple(dict.fromkeys(filter(bool, raw_refs)))

        target_size = attempt.initial.target_size
        reasons: list[str] = []

        # 1. Path & Initial Gross Gate
        path_reasons = validate_round_trip(attempt.initial)
        if path_reasons:
            reasons.append(CandidateRejectReason.INVALID_INITIAL_PATH)
            reasons.extend(r.value for r in path_reasons)
        if attempt.initial.final_output.raw_amount <= target_size.raw_amount:
            reasons.append(CandidateRejectReason.INITIAL_GROSS_NOT_POSITIVE)

        # 2. Deduplication Gate
        fp = (
            f"same_chain:{attempt.initial.first_leg.input_amount.token.chain_id}:"
            f"{attempt.initial.first_leg.venue}:{attempt.initial.second_leg.venue}:"
            f"{target_size.token.contract_address}:{target_size.raw_amount}"
        )
        if self._deduplicator.is_duplicate(fp, detected_at):
            reasons.append(CandidateRejectReason.DUPLICATE_OPPORTUNITY)
        else:
            self._deduplicator.record(fp, detected_at)

        # 3. Re-quote Gate
        refreshed = attempt.refreshed
        if refreshed is None:
            reasons.append(CandidateRejectReason.REQUOTE_MISSING)
            decided_at = attempt.decided_at or datetime.now(UTC)
            _require_utc(decided_at, "decided_at")
            latency = self._latency_ms(detected_at, decided_at)
            lifetime = self._lifetime_ms(detected_at, attempt.expiry_at)
            return ScanDecision(
                candidate_id=attempt.candidate_id,
                candidate_type="same_chain",
                state=CandidateState.REQUOTE_FAILED,
                reject_reasons=tuple(dict.fromkeys(reasons)),
                target_size=target_size,
                gross_pnl=None,
                net_pnl=None,
                cost_evaluation=None,
                inventory_evaluation=None,
                simulation_comparison=None,
                raw_refs=deduped_raw_refs,
                detected_at=detected_at,
                decided_at=decided_at,
                decision_latency_ms=latency,
                opportunity_lifetime_ms=lifetime,
            )

        requote_errors = validate_requote(attempt.initial, refreshed)
        if requote_errors:
            reasons.extend(r.value for r in requote_errors)
        if refreshed.final_output.raw_amount <= refreshed.target_size.raw_amount:
            reasons.append(CandidateRejectReason.REQUOTE_GROSS_NOT_POSITIVE)
        if refreshed.minimum_final_output.raw_amount <= refreshed.target_size.raw_amount:
            reasons.append(CandidateRejectReason.REQUOTE_MINIMUM_NOT_POSITIVE)

        quotes = (refreshed.first_leg, refreshed.second_leg)
        if any(q.approval_status is ApprovalStatus.UNKNOWN for q in quotes):
            reasons.append(CandidateRejectReason.APPROVAL_UNKNOWN)

        # If any requote failure exists up to here
        has_requote_failure = any(
            r in reasons
            for r in (
                CandidateRejectReason.REQUOTE_MISSING,
                CandidateRejectReason.NOT_REFRESHED,
                CandidateRejectReason.VENUE_CHANGED,
                CandidateRejectReason.TARGET_SIZE_CHANGED,
                CandidateRejectReason.TOKEN_PATH_CHANGED,
                CandidateRejectReason.LEG_INPUT_NOT_GUARANTEED,
                CandidateRejectReason.REQUOTE_GROSS_NOT_POSITIVE,
                CandidateRejectReason.REQUOTE_MINIMUM_NOT_POSITIVE,
                CandidateRejectReason.APPROVAL_UNKNOWN,
                RequoteRejectReason.NOT_REFRESHED.value,
                RequoteRejectReason.VENUE_CHANGED.value,
                RequoteRejectReason.TARGET_SIZE_CHANGED.value,
                RequoteRejectReason.TOKEN_PATH_CHANGED.value,
                RequoteRejectReason.LEG_INPUT_NOT_GUARANTEED.value,
            )
        )

        # 4. Cost Ledger Gate
        costs: list[CostItem] = [q.gas_cost for q in quotes]
        costs.extend(q.approval_cost for q in quotes if q.approval_cost is not None)

        cost_eval: CostEvaluation | None = None
        gross_delta: TokenDelta | None = None
        if any(item.amount.token != refreshed.target_size.token for item in costs):
            reasons.append(CandidateRejectReason.COST_CURRENCY_MISMATCH)
        else:
            required_kinds = {q.gas_cost.kind for q in quotes}
            required_kinds.update(
                q.approval_cost.kind
                for q in quotes
                if q.approval_status is ApprovalStatus.REQUIRED and q.approval_cost is not None
            )
            gross_delta = TokenDelta(
                token=refreshed.target_size.token,
                raw_delta=(
                    refreshed.minimum_final_output.raw_amount
                    - refreshed.target_size.raw_amount
                ),
            )
            cost_eval = CostLedger(required_cost_kinds=required_kinds).evaluate(
                candidate_id=attempt.candidate_id,
                gross_pnl=gross_delta,
                costs=costs,
            )
            if not cost_eval.is_complete:
                reasons.append(CandidateRejectReason.COST_LEDGER_INCOMPLETE)
            if cost_eval.local_trade_pnl <= 0:
                reasons.append(CandidateRejectReason.NET_NOT_POSITIVE)

        # 5. Simulation Gate
        sim_comp: SimulationComparison | None = None
        if attempt.simulation is None:
            reasons.append(CandidateRejectReason.SIMULATION_MISSING)
        else:
            # Map simulation output token to the appropriate leg in the round trip
            sim_output_token = (
                attempt.simulation.simulated_output.token
                if attempt.simulation.simulated_output is not None
                else refreshed.first_leg.output_amount.token
            )
            if sim_output_token == refreshed.first_leg.output_amount.token:
                target_leg = refreshed.first_leg
            elif sim_output_token == refreshed.second_leg.output_amount.token:
                target_leg = refreshed.second_leg
            else:
                target_leg = refreshed.first_leg

            sim_quote = QuoteObservation(
                observation_id=f"quote-{target_leg.quote_id}",
                raw_ref=target_leg.raw_ref,
                source=target_leg.venue,
                input_amount=target_leg.input_amount,
                output_amount=target_leg.output_amount,
                minimum_output_amount=target_leg.minimum_output_amount,
                observed_at=target_leg.observed_at,
            )
            sim_comp = compare_quote_and_simulation(
                quote=sim_quote,
                simulation=attempt.simulation,
                block_number=attempt.simulation.result.block_number,
            )
            if not sim_comp.executable:
                reasons.extend(r.value for r in sim_comp.reject_reasons)

        decided_at = attempt.decided_at or (
            attempt.simulation.observed_at
            if attempt.simulation is not None
            else (refreshed.second_leg.observed_at if refreshed else datetime.now(UTC))
        )
        _require_utc(decided_at, "decided_at")
        latency = self._latency_ms(detected_at, decided_at)
        lifetime = self._lifetime_ms(detected_at, attempt.expiry_at)

        # Determine CandidateState
        ordered_reasons = tuple(dict.fromkeys(reasons))
        if not ordered_reasons:
            state = CandidateState.PAPER_READY
        elif has_requote_failure:
            state = CandidateState.REQUOTE_FAILED
        elif (
            CandidateRejectReason.COST_CURRENCY_MISMATCH in ordered_reasons
            or CandidateRejectReason.COST_LEDGER_INCOMPLETE in ordered_reasons
            or CandidateRejectReason.NET_NOT_POSITIVE in ordered_reasons
            or CandidateRejectReason.INITIAL_GROSS_NOT_POSITIVE in ordered_reasons
        ):
            state = CandidateState.NET_NEGATIVE
        elif (
            attempt.simulation is None
            or (sim_comp is not None and not sim_comp.executable)
            or any(
                r in ordered_reasons
                for r in (
                    CandidateRejectReason.SIMULATION_MISSING,
                    CandidateRejectReason.SIMULATION_REVERTED,
                    CandidateRejectReason.SIMULATION_OUTPUT_BELOW_MINIMUM,
                    CandidateRejectReason.SIMULATION_OUTPUT_BELOW_QUOTED,
                    CandidateRejectReason.SIMULATION_INSUFFICIENT_ALLOWANCE,
                    CandidateRejectReason.SIMULATION_STALE_BLOCK,
                    CandidateRejectReason.SIMULATION_TOKEN_MISMATCH,
                    SimulationRejectReason.REVERTED.value,
                    SimulationRejectReason.OUTPUT_BELOW_MINIMUM.value,
                    SimulationRejectReason.OUTPUT_BELOW_QUOTED.value,
                    SimulationRejectReason.INSUFFICIENT_ALLOWANCE.value,
                    SimulationRejectReason.STALE_BLOCK.value,
                    SimulationRejectReason.TOKEN_MISMATCH.value,
                    SimulationRejectReason.OUTPUT_MISSING.value,
                )
            )
        ):
            state = CandidateState.SIMULATION_FAILED
        else:
            state = CandidateState.REQUOTE_FAILED

        return ScanDecision(
            candidate_id=attempt.candidate_id,
            candidate_type="same_chain",
            state=state,
            reject_reasons=ordered_reasons,
            target_size=target_size,
            gross_pnl=gross_delta,
            net_pnl=None if cost_eval is None else cost_eval.local_trade_pnl,
            cost_evaluation=cost_eval,
            inventory_evaluation=None,
            simulation_comparison=sim_comp,
            raw_refs=deduped_raw_refs,
            detected_at=detected_at,
            decided_at=decided_at,
            decision_latency_ms=latency,
            opportunity_lifetime_ms=lifetime,
        )

    def evaluate_cross_chain(self, attempt: CrossChainScanAttempt) -> ScanDecision:
        """Evaluate a cross-chain inventory candidate across the full gate pipeline."""

        signal = attempt.signal
        detected_at = attempt.detected_at or signal.cheap_chain_buy.observed_at
        _require_utc(detected_at, "detected_at")

        raw_refs: list[str] = list(attempt.raw_refs)
        raw_refs.append(signal.cheap_chain_buy.raw_ref)
        raw_refs.append(signal.expensive_chain_sell.raw_ref)
        if attempt.refreshed_signal is not None:
            raw_refs.append(attempt.refreshed_signal.cheap_chain_buy.raw_ref)
            raw_refs.append(attempt.refreshed_signal.expensive_chain_sell.raw_ref)
        deduped_raw_refs = tuple(dict.fromkeys(filter(bool, raw_refs)))

        target_size = signal.cheap_chain_buy.input_amount
        reasons: list[str] = []

        # 1. Path & Gross Gate
        if signal.expensive_chain_sell.minimum_output_amount.raw_amount <= signal.cheap_chain_buy.input_amount.raw_amount:
            reasons.append(CandidateRejectReason.INITIAL_GROSS_NOT_POSITIVE)

        # 2. Deduplication Gate
        fp = (
            f"cross_chain:{signal.cheap_chain_buy.input_amount.token.chain_id}:"
            f"{signal.expensive_chain_sell.input_amount.token.chain_id}:"
            f"{signal.stable_asset_id}:{signal.trade_asset_id}:{target_size.raw_amount}"
        )
        if self._deduplicator.is_duplicate(fp, detected_at):
            reasons.append(CandidateRejectReason.DUPLICATE_OPPORTUNITY)
        else:
            self._deduplicator.record(fp, detected_at)

        # 3. Refresh / Skew Gate
        active_signal = attempt.refreshed_signal or signal
        if active_signal.leg_skew > active_signal.max_leg_skew:
            reasons.append(CandidateRejectReason.LEG_OBSERVATION_SKEW_EXCEEDED)

        # 4. Balance Sheet & Inventory Gate
        inv_eval: InventoryEvaluation | None = None
        if attempt.balance_sheet is None:
            reasons.append(CandidateRejectReason.INVENTORY_MISSING_BALANCE_SHEET)
            reasons.append(CandidateRejectReason.INVENTORY_BLOCKED)
        else:
            inv_eval = evaluate_inventory(active_signal, attempt.balance_sheet)
            if not inv_eval.accepted:
                if inv_eval.status == InventoryStatus.COST_INCOMPLETE:
                    reasons.append(CandidateRejectReason.COST_LEDGER_INCOMPLETE)
                elif inv_eval.status == InventoryStatus.SIGNAL_NOT_LOCKED:
                    reasons.append(CandidateRejectReason.LEG_OBSERVATION_SKEW_EXCEEDED)
                elif inv_eval.status == InventoryStatus.INVENTORY_BLOCKED:
                    reasons.append(CandidateRejectReason.INVENTORY_BLOCKED)
                reasons.extend(inv_eval.reject_reasons)

        decided_at = attempt.decided_at or active_signal.condition_locked_at
        _require_utc(decided_at, "decided_at")
        latency = self._latency_ms(detected_at, decided_at)
        lifetime = self._lifetime_ms(detected_at, attempt.expiry_at)

        cost_eval: CrossChainCostEvaluation | None = (
            inv_eval.cost_evaluation if inv_eval is not None else None
        )
        gross_delta: TokenDelta | None = TokenDelta(
            token=signal.cheap_chain_buy.input_amount.token,
            raw_delta=(
                active_signal.expensive_chain_sell.minimum_output_amount.raw_amount
                - active_signal.cheap_chain_buy.input_amount.raw_amount
            ),
        )

        ordered_reasons = tuple(dict.fromkeys(reasons))
        if not ordered_reasons:
            state = CandidateState.PAPER_READY
        elif (
            CandidateRejectReason.REQUOTE_MISSING in ordered_reasons
            or CandidateRejectReason.LEG_OBSERVATION_SKEW_EXCEEDED in ordered_reasons
        ):
            state = CandidateState.REQUOTE_FAILED
        elif (
            CandidateRejectReason.COST_LEDGER_INCOMPLETE in ordered_reasons
            or CandidateRejectReason.NET_NOT_POSITIVE in ordered_reasons
            or CandidateRejectReason.INITIAL_GROSS_NOT_POSITIVE in ordered_reasons
            or (cost_eval is not None and cost_eval.local_trade_pnl <= 0)
        ):
            state = CandidateState.NET_NEGATIVE
        elif (
            CandidateRejectReason.INVENTORY_BLOCKED in ordered_reasons
            or CandidateRejectReason.INVENTORY_MISSING_BALANCE_SHEET in ordered_reasons
            or any(r.startswith("INSUFFICIENT_BALANCE") or r.startswith("MAX_IMBALANCE_EXCEEDED") for r in ordered_reasons)
        ):
            state = CandidateState.INVENTORY_BLOCKED
        else:
            state = CandidateState.REQUOTE_FAILED

        return ScanDecision(
            candidate_id=attempt.candidate_id,
            candidate_type="cross_chain",
            state=state,
            reject_reasons=ordered_reasons,
            target_size=target_size,
            gross_pnl=gross_delta,
            net_pnl=None if cost_eval is None else cost_eval.local_trade_pnl,
            cost_evaluation=cost_eval,
            inventory_evaluation=inv_eval,
            simulation_comparison=None,
            raw_refs=deduped_raw_refs,
            detected_at=detected_at,
            decided_at=decided_at,
            decision_latency_ms=latency,
            opportunity_lifetime_ms=lifetime,
        )

    def scan(
        self, items: Iterable[SameChainScanAttempt | CrossChainScanAttempt]
    ) -> ScannerReport:
        """Scan a batch of attempts and compute all funnel and survivor metrics."""

        decisions: list[ScanDecision] = []
        for item in items:
            if isinstance(item, SameChainScanAttempt):
                decisions.append(self.evaluate_same_chain(item))
            elif isinstance(item, CrossChainScanAttempt):
                decisions.append(self.evaluate_cross_chain(item))
            else:
                raise TypeError(f"unsupported attempt type: {type(item)}")

        metrics = self._compute_metrics(decisions)
        return ScannerReport(
            decisions=tuple(decisions),
            metrics=metrics,
            generated_at=datetime.now(UTC),
        )

    @staticmethod
    def _latency_ms(start: datetime, end: datetime) -> Decimal:
        diff_ms = Decimal(str(abs((end - start).total_seconds() * 1000)))
        return max(Decimal(0), diff_ms)

    @staticmethod
    def _lifetime_ms(start: datetime, expiry: datetime | None) -> Decimal | None:
        if expiry is None:
            return None
        diff_ms = Decimal(str(abs((expiry - start).total_seconds() * 1000)))
        return max(Decimal(0), diff_ms)

    def _compute_metrics(self, decisions: Sequence[ScanDecision]) -> ScannerMetrics:
        total = len(decisions)
        duplicates = sum(
            CandidateRejectReason.DUPLICATE_OPPORTUNITY in d.reject_reasons
            for d in decisions
        )
        evaluated = total - duplicates

        # Funnel stages
        requote_survivors = sum(
            d.state in (
                CandidateState.NET_NEGATIVE,
                CandidateState.INVENTORY_BLOCKED,
                CandidateState.SIMULATION_FAILED,
                CandidateState.PAPER_READY,
            )
            for d in decisions
        )
        net_survivors = sum(
            d.state in (
                CandidateState.INVENTORY_BLOCKED,
                CandidateState.SIMULATION_FAILED,
                CandidateState.PAPER_READY,
            )
            for d in decisions
        )

        same_chain_decisions = [d for d in decisions if d.candidate_type == "same_chain"]
        cross_chain_decisions = [d for d in decisions if d.candidate_type == "cross_chain"]

        sim_attempted = sum(
            d.state in (CandidateState.SIMULATION_FAILED, CandidateState.PAPER_READY)
            for d in same_chain_decisions
        )
        sim_survivors = sum(
            d.state == CandidateState.PAPER_READY for d in same_chain_decisions
        )

        inv_attempted = sum(
            d.state in (CandidateState.INVENTORY_BLOCKED, CandidateState.PAPER_READY)
            for d in cross_chain_decisions
        )
        inv_survivors = sum(
            d.state == CandidateState.PAPER_READY for d in cross_chain_decisions
        )

        paper_ready = sum(d.accepted for d in decisions)

        requote_ratio = 0.0 if total == 0 else requote_survivors / total
        sim_ratio = 0.0 if sim_attempted == 0 else sim_survivors / sim_attempted

        # Cost completeness & raw coverage
        cost_complete_count = sum(d.has_complete_costs for d in decisions if d.cost_evaluation is not None)
        evaluated_with_costs = sum(1 for d in decisions if d.cost_evaluation is not None)
        cost_ratio = (
            1.0 if evaluated_with_costs == 0 else cost_complete_count / evaluated_with_costs
        )

        raw_covered_count = sum(d.has_raw_refs for d in decisions)
        raw_ratio = 1.0 if total == 0 else raw_covered_count / total

        # Latency & Lifetime stats
        latencies = sorted(float(d.decision_latency_ms) for d in decisions)
        mean_lat = sum(latencies) / len(latencies) if latencies else None
        p50_lat = _quantile(latencies, 0.50) if latencies else None
        p95_lat = _quantile(latencies, 0.95) if latencies else None

        lifetimes = [
            float(d.opportunity_lifetime_ms)
            for d in decisions
            if d.opportunity_lifetime_ms is not None
        ]
        mean_life = sum(lifetimes) / len(lifetimes) if lifetimes else None

        is_sparse = total < 20

        state_counter = Counter(d.state.value for d in decisions)
        ordered_states = tuple(sorted(state_counter.items(), key=lambda x: x[0]))

        reject_counter = Counter(r for d in decisions for r in d.reject_reasons)
        ordered_rejects = tuple(sorted(reject_counter.items(), key=lambda x: (-x[1], x[0])))

        largest_reject = ordered_rejects[0][0] if ordered_rejects else None

        return ScannerMetrics(
            total_detected=total,
            duplicates_filtered=duplicates,
            evaluated_count=evaluated,
            requote_survivors=requote_survivors,
            requote_survivor_ratio=requote_ratio,
            net_positive_survivors=net_survivors,
            simulation_attempted=sim_attempted,
            simulation_survivors=sim_survivors,
            simulation_survivor_ratio=sim_ratio,
            inventory_attempted=inv_attempted,
            inventory_survivors=inv_survivors,
            paper_ready_count=paper_ready,
            cost_completeness_ratio=cost_ratio,
            raw_ref_coverage_ratio=raw_ratio,
            mean_decision_latency_ms=mean_lat,
            p50_decision_latency_ms=p50_lat,
            p95_decision_latency_ms=p95_lat,
            mean_opportunity_lifetime_ms=mean_life,
            is_sparse=is_sparse,
            state_counts=ordered_states,
            reject_counts=ordered_rejects,
            largest_reject_reason=largest_reject,
        )


def _quantile(sorted_values: Sequence[float], q: float) -> float:
    if not sorted_values:
        raise ValueError("cannot compute quantile of empty sequence")
    if len(sorted_values) == 1:
        return sorted_values[0]
    index = (len(sorted_values) - 1) * q
    low = int(math.floor(index))
    high = int(math.ceil(index))
    if low == high:
        return sorted_values[low]
    weight = index - low
    return sorted_values[low] * (1.0 - weight) + sorted_values[high] * weight


def persist_scanner_report(report: ScannerReport, output_dir: Path) -> Path:
    """Atomically write one immutable scanner run report to the output directory."""

    output_dir.mkdir(parents=True, exist_ok=True)
    ts = report.generated_at.strftime("%Y%m%dT%H%M%S%fZ")
    uid = uuid4().hex[:8]
    final_path = (output_dir / f"scan_report_{ts}_{uid}.json").resolve()
    temp_path = (output_dir / f".tmp_scan_report_{ts}_{uid}.tmp").resolve()

    serialized = json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n"
    with temp_path.open("x", encoding="utf-8") as file:
        file.write(serialized)
        file.flush()
        os.fsync(file.fileno())
    os.replace(temp_path, final_path)
    return final_path
