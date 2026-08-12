"""Independent re-quote evidence and structural freshness gate."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from onchain_arb.models import CostItem, TokenAmount, _require_utc


class ApprovalStatus(StrEnum):
    NOT_REQUIRED = "not_required"
    REQUIRED = "required"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class DirectQuote:
    """One exact-input, direct-venue quote with its raw evidence lineage."""

    quote_id: str
    request_id: str
    raw_ref: str
    venue: str
    input_amount: TokenAmount
    output_amount: TokenAmount
    minimum_output_amount: TokenAmount
    fee_amount: TokenAmount
    gas_cost: CostItem
    approval_status: ApprovalStatus
    approval_cost: CostItem | None
    observed_at: datetime
    latency_ms: Decimal

    def __post_init__(self) -> None:
        if not all((self.quote_id, self.request_id, self.raw_ref, self.venue)):
            raise ValueError("quote ID, request ID, raw ref, and venue are required")
        if self.input_amount.token.chain_id != self.output_amount.token.chain_id:
            raise ValueError("a direct quote must remain on one chain")
        if self.output_amount.token != self.minimum_output_amount.token:
            raise ValueError("output and minimum output must use the same token")
        if self.minimum_output_amount.raw_amount > self.output_amount.raw_amount:
            raise ValueError("minimum output cannot exceed quoted output")
        if self.fee_amount.token != self.input_amount.token:
            raise ValueError("fee amount must use the input token")
        if not isinstance(self.approval_status, ApprovalStatus):
            raise TypeError("approval_status must be ApprovalStatus")
        if self.approval_status is ApprovalStatus.REQUIRED and self.approval_cost is None:
            raise ValueError("a required approval must have an explicit cost")
        if self.approval_status is not ApprovalStatus.REQUIRED and self.approval_cost:
            raise ValueError("approval cost is only valid when approval is required")
        if not isinstance(self.latency_ms, Decimal) or not self.latency_ms.is_finite():
            raise TypeError("latency_ms must be a finite Decimal")
        if self.latency_ms < 0:
            raise ValueError("latency_ms must be non-negative")
        _require_utc(self.observed_at, "observed_at")


@dataclass(frozen=True, slots=True)
class RoundTripQuotes:
    """A buy then sell path; leg two spends leg one's guaranteed output."""

    first_leg: DirectQuote
    second_leg: DirectQuote

    @property
    def target_size(self) -> TokenAmount:
        return self.first_leg.input_amount

    @property
    def final_output(self) -> TokenAmount:
        return self.second_leg.output_amount

    @property
    def minimum_final_output(self) -> TokenAmount:
        return self.second_leg.minimum_output_amount


class RequoteRejectReason(StrEnum):
    VENUE_CHANGED = "requote_venue_changed"
    TARGET_SIZE_CHANGED = "requote_target_size_changed"
    TOKEN_PATH_CHANGED = "requote_token_path_changed"
    NOT_REFRESHED = "requote_not_refreshed"
    LEG_INPUT_NOT_GUARANTEED = "leg_two_input_not_leg_one_minimum"


def validate_round_trip(quotes: RoundTripQuotes) -> tuple[RequoteRejectReason, ...]:
    reasons: list[RequoteRejectReason] = []
    first = quotes.first_leg
    second = quotes.second_leg
    if (
        second.input_amount.token != first.output_amount.token
        or second.output_amount.token != first.input_amount.token
    ):
        reasons.append(RequoteRejectReason.TOKEN_PATH_CHANGED)
    if second.input_amount != first.minimum_output_amount:
        reasons.append(RequoteRejectReason.LEG_INPUT_NOT_GUARANTEED)
    return tuple(reasons)


def validate_requote(
    initial: RoundTripQuotes,
    refreshed: RoundTripQuotes,
) -> tuple[RequoteRejectReason, ...]:
    """Return every structural reason the refreshed evidence is incomparable."""

    reasons = list(validate_round_trip(refreshed))
    if (
        initial.first_leg.venue != refreshed.first_leg.venue
        or initial.second_leg.venue != refreshed.second_leg.venue
    ):
        reasons.append(RequoteRejectReason.VENUE_CHANGED)
    if initial.target_size != refreshed.target_size:
        reasons.append(RequoteRejectReason.TARGET_SIZE_CHANGED)
    if (
        initial.first_leg.input_amount.token != refreshed.first_leg.input_amount.token
        or initial.first_leg.output_amount.token != refreshed.first_leg.output_amount.token
        or initial.second_leg.output_amount.token != refreshed.second_leg.output_amount.token
    ):
        reasons.append(RequoteRejectReason.TOKEN_PATH_CHANGED)
    if (
        refreshed.first_leg.observed_at <= initial.first_leg.observed_at
        or refreshed.second_leg.observed_at <= initial.second_leg.observed_at
    ):
        reasons.append(RequoteRejectReason.NOT_REFRESHED)
    return tuple(dict.fromkeys(reasons))
