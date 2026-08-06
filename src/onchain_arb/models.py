"""Stable internal models for quote, candidate, cost, and simulation evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum


def _require_utc(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    if value.utcoffset().total_seconds() != 0:
        raise ValueError(f"{field_name} must use UTC")


@dataclass(frozen=True, slots=True)
class TokenRef:
    """A chain-specific token identity; symbol is display-only."""

    chain_id: int
    contract_address: str
    symbol: str
    decimals: int

    def __post_init__(self) -> None:
        if self.chain_id <= 0:
            raise ValueError("chain_id must be positive")
        if not self.contract_address:
            raise ValueError("contract_address is required")
        if not self.symbol:
            raise ValueError("symbol is required")
        if not 0 <= self.decimals <= 255:
            raise ValueError("decimals must be between 0 and 255")


@dataclass(frozen=True, slots=True)
class TokenAmount:
    """A non-negative token quantity stored in indivisible raw units."""

    token: TokenRef
    raw_amount: int

    def __post_init__(self) -> None:
        if isinstance(self.raw_amount, bool) or not isinstance(self.raw_amount, int):
            raise TypeError("raw_amount must be an integer")
        if self.raw_amount < 0:
            raise ValueError("raw_amount must be non-negative")

    @property
    def decimal_amount(self) -> Decimal:
        return Decimal(self.raw_amount).scaleb(-self.token.decimals)

    @classmethod
    def from_decimal(cls, token: TokenRef, value: Decimal) -> TokenAmount:
        """Build an amount only when ``value`` is exactly representable."""
        if not isinstance(value, Decimal):
            raise TypeError("value must be Decimal")
        if not value.is_finite():
            raise ValueError("value must be finite")
        if value < 0:
            raise ValueError("value must be non-negative")

        raw_value = value.scaleb(token.decimals)
        integral_value = raw_value.to_integral_value()
        if raw_value != integral_value:
            raise ValueError(
                f"value has more precision than {token.symbol} supports"
            )
        return cls(token=token, raw_amount=int(integral_value))


@dataclass(frozen=True, slots=True)
class TokenDelta:
    """A signed token balance or PnL change stored in raw units."""

    token: TokenRef
    raw_delta: int

    def __post_init__(self) -> None:
        if isinstance(self.raw_delta, bool) or not isinstance(self.raw_delta, int):
            raise TypeError("raw_delta must be an integer")

    @property
    def decimal_delta(self) -> Decimal:
        return Decimal(self.raw_delta).scaleb(-self.token.decimals)

    @classmethod
    def from_decimal(cls, token: TokenRef, value: Decimal) -> TokenDelta:
        """Build a signed delta only when ``value`` is exactly representable."""
        if not isinstance(value, Decimal):
            raise TypeError("value must be Decimal")
        if not value.is_finite():
            raise ValueError("value must be finite")

        raw_value = value.scaleb(token.decimals)
        integral_value = raw_value.to_integral_value()
        if raw_value != integral_value:
            raise ValueError(
                f"value has more precision than {token.symbol} supports"
            )
        return cls(token=token, raw_delta=int(integral_value))


class CostConfidence(StrEnum):
    EXACT = "exact"
    ESTIMATED = "estimated"
    STRESSED = "stressed"


class CostScope(StrEnum):
    """The first PnL boundary at which an external cost is deducted."""

    ATOMIC = "atomic"
    CYCLE = "cycle"


@dataclass(frozen=True, slots=True)
class CostItem:
    kind: str
    amount: TokenAmount
    scope: CostScope
    included_in_quote_output: bool
    confidence: CostConfidence
    source: str
    observed_at: datetime

    def __post_init__(self) -> None:
        if not self.kind:
            raise ValueError("cost kind is required")
        if not self.source:
            raise ValueError("cost source is required")
        if not isinstance(self.scope, CostScope):
            raise TypeError("scope must be CostScope")
        if not isinstance(self.included_in_quote_output, bool):
            raise TypeError("included_in_quote_output must be bool")
        if not isinstance(self.confidence, CostConfidence):
            raise TypeError("confidence must be CostConfidence")
        _require_utc(self.observed_at, "observed_at")


@dataclass(frozen=True, slots=True)
class QuoteObservation:
    observation_id: str
    raw_ref: str
    source: str
    input_amount: TokenAmount
    output_amount: TokenAmount
    minimum_output_amount: TokenAmount
    observed_at: datetime

    def __post_init__(self) -> None:
        if not self.observation_id or not self.raw_ref or not self.source:
            raise ValueError("observation_id, raw_ref, and source are required")
        if self.output_amount.token != self.minimum_output_amount.token:
            raise ValueError("output and minimum output must use the same token")
        if self.minimum_output_amount.raw_amount > self.output_amount.raw_amount:
            raise ValueError("minimum output cannot exceed quoted output")
        _require_utc(self.observed_at, "observed_at")


@dataclass(frozen=True, slots=True)
class OpportunityCandidate:
    candidate_id: str
    observations: tuple[QuoteObservation, ...]
    direction: str
    target_size: TokenAmount
    detected_at: datetime

    def __post_init__(self) -> None:
        if not self.candidate_id or not self.direction:
            raise ValueError("candidate_id and direction are required")
        if not self.observations:
            raise ValueError("a candidate requires at least one observation")
        _require_utc(self.detected_at, "detected_at")


@dataclass(frozen=True, slots=True)
class SimulationResult:
    candidate_id: str
    method: str
    block_number: int
    success: bool
    gas_used: int | None
    balance_changes: tuple[TokenDelta, ...]
    revert_reason: str | None
    evidence_ref: str
    observed_at: datetime

    def __post_init__(self) -> None:
        if not self.candidate_id or not self.method or not self.evidence_ref:
            raise ValueError("candidate_id, method, and evidence_ref are required")
        if self.block_number < 0:
            raise ValueError("block_number must be non-negative")
        if self.gas_used is not None and self.gas_used < 0:
            raise ValueError("gas_used must be non-negative")
        if self.success and self.revert_reason is not None:
            raise ValueError("a successful simulation cannot have a revert reason")
        _require_utc(self.observed_at, "observed_at")
