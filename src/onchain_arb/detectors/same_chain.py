"""Day 8 same-chain, two-venue paper baseline."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable

from onchain_arb.costs import CostEvaluation, CostLedger
from onchain_arb.models import CostItem, TokenDelta
from onchain_arb.requote import (
    ApprovalStatus,
    RequoteRejectReason,
    RoundTripQuotes,
    validate_requote,
    validate_round_trip,
)


class RejectReason(StrEnum):
    INVALID_INITIAL_PATH = "invalid_initial_path"
    INITIAL_GROSS_NOT_POSITIVE = "initial_gross_not_positive"
    REQUOTE_MISSING = "requote_missing"
    REQUOTE_GROSS_NOT_POSITIVE = "requote_gross_not_positive"
    REQUOTE_MINIMUM_NOT_POSITIVE = "requote_minimum_not_positive"
    APPROVAL_UNKNOWN = "approval_unknown"
    COST_CURRENCY_MISMATCH = "cost_currency_mismatch"
    COST_LEDGER_INCOMPLETE = "cost_ledger_incomplete"
    NET_NOT_POSITIVE = "net_not_positive"


@dataclass(frozen=True, slots=True)
class RoundTripAttempt:
    candidate_id: str
    initial: RoundTripQuotes
    refreshed: RoundTripQuotes | None

    def __post_init__(self) -> None:
        if not self.candidate_id:
            raise ValueError("candidate_id is required")
        if self.initial.first_leg.venue == self.initial.second_leg.venue:
            raise ValueError("the round trip requires two distinct venues")


@dataclass(frozen=True, slots=True)
class BaselineDecision:
    candidate_id: str
    initial: RoundTripQuotes
    refreshed: RoundTripQuotes | None
    cost_evaluation: CostEvaluation | None
    reject_reasons: tuple[str, ...]

    @property
    def accepted(self) -> bool:
        return not self.reject_reasons


@dataclass(frozen=True, slots=True)
class BaselineMetrics:
    attempts: int
    gross_candidates: int
    requote_survivors: int
    net_positive_survivors: int
    reject_counts: tuple[tuple[str, int], ...]
    largest_false_positive_source: str | None


@dataclass(frozen=True, slots=True)
class BaselineReport:
    decisions: tuple[BaselineDecision, ...]
    metrics: BaselineMetrics


def scan_same_chain(attempts: Iterable[RoundTripAttempt]) -> BaselineReport:
    """Evaluate attempts conservatively and retain every applicable rejection."""

    decisions = tuple(_evaluate(attempt) for attempt in attempts)
    gross_candidates = sum(
        decision.initial.final_output.raw_amount
        > decision.initial.target_size.raw_amount
        and not validate_round_trip(decision.initial)
        for decision in decisions
    )
    requote_survivors = sum(
        decision.refreshed is not None
        and not validate_requote(decision.initial, decision.refreshed)
        and decision.refreshed.final_output.raw_amount
        > decision.refreshed.target_size.raw_amount
        and decision.refreshed.minimum_final_output.raw_amount
        > decision.refreshed.target_size.raw_amount
        for decision in decisions
    )
    reject_counts = Counter(
        reason for decision in decisions for reason in decision.reject_reasons
    )
    ordered_counts = tuple(sorted(reject_counts.items(), key=lambda item: item[0]))
    false_positive_counts = {
        reason: count
        for reason, count in reject_counts.items()
        if reason != RejectReason.INITIAL_GROSS_NOT_POSITIVE
    }
    largest = (
        min(
            false_positive_counts,
            key=lambda reason: (-false_positive_counts[reason], reason),
        )
        if false_positive_counts
        else None
    )
    return BaselineReport(
        decisions=decisions,
        metrics=BaselineMetrics(
            attempts=len(decisions),
            gross_candidates=gross_candidates,
            requote_survivors=requote_survivors,
            net_positive_survivors=sum(item.accepted for item in decisions),
            reject_counts=ordered_counts,
            largest_false_positive_source=largest,
        ),
    )


def _evaluate(attempt: RoundTripAttempt) -> BaselineDecision:
    reasons: list[str] = []
    initial_path_reasons = validate_round_trip(attempt.initial)
    if initial_path_reasons:
        reasons.append(RejectReason.INVALID_INITIAL_PATH)
        reasons.extend(reason.value for reason in initial_path_reasons)
    if attempt.initial.final_output.raw_amount <= attempt.initial.target_size.raw_amount:
        reasons.append(RejectReason.INITIAL_GROSS_NOT_POSITIVE)

    refreshed = attempt.refreshed
    if refreshed is None:
        reasons.append(RejectReason.REQUOTE_MISSING)
        return BaselineDecision(
            attempt.candidate_id, attempt.initial, None, None, tuple(dict.fromkeys(reasons))
        )

    reasons.extend(reason.value for reason in validate_requote(attempt.initial, refreshed))
    if refreshed.final_output.raw_amount <= refreshed.target_size.raw_amount:
        reasons.append(RejectReason.REQUOTE_GROSS_NOT_POSITIVE)
    if refreshed.minimum_final_output.raw_amount <= refreshed.target_size.raw_amount:
        reasons.append(RejectReason.REQUOTE_MINIMUM_NOT_POSITIVE)
    quotes = (refreshed.first_leg, refreshed.second_leg)
    if any(quote.approval_status is ApprovalStatus.UNKNOWN for quote in quotes):
        reasons.append(RejectReason.APPROVAL_UNKNOWN)

    costs: list[CostItem] = [quote.gas_cost for quote in quotes]
    costs.extend(
        quote.approval_cost for quote in quotes if quote.approval_cost is not None
    )
    if any(item.amount.token != refreshed.target_size.token for item in costs):
        reasons.append(RejectReason.COST_CURRENCY_MISMATCH)
        return BaselineDecision(
            attempt.candidate_id,
            attempt.initial,
            refreshed,
            None,
            tuple(dict.fromkeys(reasons)),
        )
    if validate_round_trip(refreshed):
        return BaselineDecision(
            attempt.candidate_id,
            attempt.initial,
            refreshed,
            None,
            tuple(dict.fromkeys(reasons)),
        )
    required_kinds = {quote.gas_cost.kind for quote in quotes}
    required_kinds.update(
        quote.approval_cost.kind
        for quote in quotes
        if quote.approval_status is ApprovalStatus.REQUIRED
        and quote.approval_cost is not None
    )
    evaluation = CostLedger(required_cost_kinds=required_kinds).evaluate(
        candidate_id=attempt.candidate_id,
        gross_pnl=TokenDelta(
            token=refreshed.target_size.token,
            raw_delta=(
                refreshed.minimum_final_output.raw_amount
                - refreshed.target_size.raw_amount
            ),
        ),
        costs=costs,
    )
    if not evaluation.is_complete:
        reasons.append(RejectReason.COST_LEDGER_INCOMPLETE)
    if evaluation.local_trade_pnl <= 0:
        reasons.append(RejectReason.NET_NOT_POSITIVE)
    return BaselineDecision(
        attempt.candidate_id,
        attempt.initial,
        refreshed,
        evaluation,
        tuple(dict.fromkeys(reasons)),
    )
