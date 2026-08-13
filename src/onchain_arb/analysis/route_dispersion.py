"""Day 9 route-quality analytics without arbitrage inference."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Iterable

from onchain_arb.adapters.lifi import LifiQuote
from onchain_arb.models import TokenAmount, TokenRef, _require_utc


BASIS_POINTS = Decimal(10_000)


class DifferenceKind(StrEnum):
    ROUTING_IMPROVEMENT = "routing_improvement"
    TEMPORARY_SUBSIDY = "temporary_subsidy"
    STALE_QUOTE = "stale_quote"
    TOKEN_MAPPING_DIFFERENCE = "token_mapping_difference"
    UNAVAILABLE_ROUTE = "unavailable_route"
    TRADABLE_EDGE = "tradable_edge"


class DirectCheckStatus(StrEnum):
    CONFIRMED = "confirmed"
    REFUTED = "refuted"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class RouteObservation:
    observation_id: str
    request_id: str
    raw_ref: str
    source: str
    provider: str
    route_fingerprint: str
    input_amount: TokenAmount
    output_amount: TokenAmount
    minimum_output_amount: TokenAmount
    observed_at: datetime
    latency_ms: Decimal
    duration_seconds: Decimal
    fee_amount: TokenAmount | None
    available: bool = True

    def __post_init__(self) -> None:
        if not all(
            (
                self.observation_id,
                self.request_id,
                self.raw_ref,
                self.source,
                self.provider,
                self.route_fingerprint,
            )
        ):
            raise ValueError("observation lineage, source, provider, and route are required")
        if not _same_token(
            self.output_amount.token, self.minimum_output_amount.token
        ):
            raise ValueError("output and minimum output tokens differ")
        if self.minimum_output_amount.raw_amount > self.output_amount.raw_amount:
            raise ValueError("minimum output exceeds quoted output")
        if self.fee_amount is not None and not _same_token(
            self.fee_amount.token, self.input_amount.token
        ):
            raise ValueError("fee amount must use the input token")
        if self.latency_ms < 0 or self.duration_seconds < 0:
            raise ValueError("latency and duration must be non-negative")
        _require_utc(self.observed_at, "observed_at")


@dataclass(frozen=True, slots=True)
class RouteRanking:
    input_amount: TokenAmount
    best: RouteObservation
    second_best: RouteObservation | None
    best_over_second_raw: int | None
    best_over_second_bps: Decimal | None


@dataclass(frozen=True, slots=True)
class ProviderShare:
    provider: str
    observations: int
    share: Decimal


@dataclass(frozen=True, slots=True)
class RouteLifetime:
    route_fingerprint: str
    observations: int
    lifetime_seconds: Decimal


@dataclass(frozen=True, slots=True)
class SizeSensitivityPoint:
    input_amount: TokenAmount
    provider: str
    output_per_input: Decimal
    change_bps_from_smallest: Decimal


@dataclass(frozen=True, slots=True)
class RouteDispersionReport:
    rankings: tuple[RouteRanking, ...]
    route_switch_rate: Decimal
    route_lifetimes: tuple[RouteLifetime, ...]
    provider_concentration: tuple[ProviderShare, ...]
    duration_spread_seconds: Decimal
    fee_rate_spread_bps: Decimal | None
    size_sensitivity: tuple[SizeSensitivityPoint, ...]


@dataclass(frozen=True, slots=True)
class CandidateAssessment:
    candidate_id: str
    difference_kind: DifferenceKind
    direct_check_status: DirectCheckStatus
    is_arbitrage: bool
    reasons: tuple[str, ...]


def from_lifi_quote(quote: LifiQuote) -> RouteObservation:
    """Project a normalized LI.FI quote into the route-analysis boundary."""

    fee_amount: TokenAmount | None
    if not quote.fee_costs:
        fee_amount = None
    elif any(
        not _same_token(cost.amount.token, quote.input_amount.token)
        for cost in quote.fee_costs
    ):
        fee_amount = None
    else:
        fee_amount = TokenAmount(
            quote.input_amount.token,
            sum(cost.amount.raw_amount for cost in quote.fee_costs),
        )
    return RouteObservation(
        observation_id=quote.quote_id,
        request_id=quote.request_id,
        raw_ref=quote.raw_ref,
        source="lifi",
        provider=quote.tool,
        route_fingerprint=quote.route_fingerprint,
        input_amount=quote.input_amount,
        output_amount=quote.output_amount,
        minimum_output_amount=quote.minimum_output_amount,
        observed_at=quote.observed_at,
        latency_ms=quote.latency_ms,
        duration_seconds=quote.duration_seconds,
        fee_amount=fee_amount,
    )


def analyze_route_dispersion(
    observations: Iterable[RouteObservation],
    *,
    primary_source: str = "lifi",
) -> RouteDispersionReport:
    """Calculate conservative route metrics for one token path.

    Rankings use guaranteed minimum output. Sequential metrics use only the
    primary source so an independent checker cannot alter LI.FI route behavior.
    """

    items = tuple(observations)
    if not items:
        raise ValueError("at least one route observation is required")
    _validate_path(items)
    available = tuple(item for item in items if item.available)
    primary = tuple(
        sorted(
            (item for item in available if item.source == primary_source),
            key=lambda item: item.observed_at,
        )
    )
    if not primary:
        raise ValueError("the primary source has no available observations")

    rankings = _rank_by_size(available)
    transitions = len(primary) - 1
    switches = sum(
        left.route_fingerprint != right.route_fingerprint
        for left, right in zip(primary, primary[1:], strict=False)
    )
    switch_rate = Decimal(switches) / Decimal(transitions) if transitions else Decimal(0)

    route_groups: dict[str, list[RouteObservation]] = {}
    for item in primary:
        route_groups.setdefault(item.route_fingerprint, []).append(item)
    lifetimes = tuple(
        RouteLifetime(
            route_fingerprint=fingerprint,
            observations=len(group),
            lifetime_seconds=Decimal(
                str((group[-1].observed_at - group[0].observed_at).total_seconds())
            ),
        )
        for fingerprint, group in sorted(route_groups.items())
    )

    provider_counts = Counter(item.provider for item in primary)
    concentration = tuple(
        ProviderShare(provider, count, Decimal(count) / Decimal(len(primary)))
        for provider, count in sorted(
            provider_counts.items(), key=lambda pair: (-pair[1], pair[0])
        )
    )
    durations = [item.duration_seconds for item in primary]
    fee_rates = [
        item.fee_amount.decimal_amount / item.input_amount.decimal_amount * BASIS_POINTS
        for item in primary
        if item.fee_amount is not None
    ]
    fee_spread = (
        max(fee_rates) - min(fee_rates)
        if len(fee_rates) == len(primary)
        else None
    )
    return RouteDispersionReport(
        rankings=rankings,
        route_switch_rate=switch_rate,
        route_lifetimes=lifetimes,
        provider_concentration=concentration,
        duration_spread_seconds=max(durations) - min(durations),
        fee_rate_spread_bps=fee_spread,
        size_sensitivity=_size_sensitivity(primary),
    )


def assess_candidate(
    candidate_id: str,
    route: RouteObservation,
    independent: RouteObservation | None,
    *,
    max_observation_gap: timedelta,
    subsidy_evidence: bool = False,
    independently_refreshed: bool = False,
    complete_cost_ledger: bool = False,
    executable_cycle: bool = False,
) -> CandidateAssessment:
    """Classify a route difference; only a complete executable cycle is tradable."""

    if not candidate_id:
        raise ValueError("candidate_id is required")
    if max_observation_gap < timedelta(0):
        raise ValueError("max_observation_gap must be non-negative")
    if independent is None or not independent.available:
        return _assessment(
            candidate_id,
            DifferenceKind.UNAVAILABLE_ROUTE,
            DirectCheckStatus.UNAVAILABLE,
            "independent direct route is unavailable",
        )
    if (
        not _same_token(route.input_amount.token, independent.input_amount.token)
        or not _same_token(route.output_amount.token, independent.output_amount.token)
        or route.input_amount.raw_amount != independent.input_amount.raw_amount
    ):
        return _assessment(
            candidate_id,
            DifferenceKind.TOKEN_MAPPING_DIFFERENCE,
            DirectCheckStatus.REFUTED,
            "direct evidence does not use the same chain-specific token mapping and size",
        )
    observation_gap = abs(route.observed_at - independent.observed_at)
    if observation_gap > max_observation_gap:
        return _assessment(
            candidate_id,
            DifferenceKind.STALE_QUOTE,
            DirectCheckStatus.REFUTED,
            f"direct observation gap {observation_gap.total_seconds():.6f}s exceeds freshness bound",
        )
    if subsidy_evidence:
        return _assessment(
            candidate_id,
            DifferenceKind.TEMPORARY_SUBSIDY,
            DirectCheckStatus.REFUTED,
            "output difference is attributed to explicit subsidy evidence",
        )
    if independently_refreshed and independent.observed_at <= route.observed_at:
        raise ValueError("independently refreshed evidence must be observed later")
    if independently_refreshed and complete_cost_ledger and executable_cycle:
        return CandidateAssessment(
            candidate_id,
            DifferenceKind.TRADABLE_EDGE,
            DirectCheckStatus.CONFIRMED,
            True,
            ("fresh independent evidence confirms a complete costed executable cycle",),
        )
    return _assessment(
        candidate_id,
        DifferenceKind.ROUTING_IMPROVEMENT,
        DirectCheckStatus.CONFIRMED,
        "comparable direct evidence confirms a route-quality difference, not an executable cycle",
    )


def _assessment(
    candidate_id: str,
    kind: DifferenceKind,
    status: DirectCheckStatus,
    reason: str,
) -> CandidateAssessment:
    return CandidateAssessment(candidate_id, kind, status, False, (reason,))


def _validate_path(items: tuple[RouteObservation, ...]) -> None:
    first = items[0]
    for item in items[1:]:
        if (
            not _same_token(item.input_amount.token, first.input_amount.token)
            or not _same_token(item.output_amount.token, first.output_amount.token)
        ):
            raise ValueError("all observations must use one chain-specific token path")


def _rank_by_size(items: tuple[RouteObservation, ...]) -> tuple[RouteRanking, ...]:
    by_size: dict[int, list[RouteObservation]] = {}
    for item in items:
        by_size.setdefault(item.input_amount.raw_amount, []).append(item)
    rankings = []
    for input_raw, group in sorted(by_size.items()):
        ranked = sorted(
            group,
            key=lambda item: (
                -item.minimum_output_amount.raw_amount,
                item.provider,
                item.observation_id,
            ),
        )
        best = ranked[0]
        second = ranked[1] if len(ranked) > 1 else None
        difference = (
            best.minimum_output_amount.raw_amount
            - second.minimum_output_amount.raw_amount
            if second is not None
            else None
        )
        difference_bps = (
            Decimal(difference)
            / Decimal(second.minimum_output_amount.raw_amount)
            * BASIS_POINTS
            if second is not None and second.minimum_output_amount.raw_amount > 0
            else None
        )
        rankings.append(
            RouteRanking(
                TokenAmount(best.input_amount.token, input_raw),
                best,
                second,
                difference,
                difference_bps,
            )
        )
    return tuple(rankings)


def _size_sensitivity(
    primary: tuple[RouteObservation, ...],
) -> tuple[SizeSensitivityPoint, ...]:
    # One best primary observation per size prevents repeated samples from
    # weighting the size curve. Minimum output keeps the comparison conservative.
    by_size: dict[int, RouteObservation] = {}
    for item in primary:
        current = by_size.get(item.input_amount.raw_amount)
        if current is None or (
            item.minimum_output_amount.raw_amount
            > current.minimum_output_amount.raw_amount
        ):
            by_size[item.input_amount.raw_amount] = item
    selected = [by_size[size] for size in sorted(by_size)]
    rates = [
        item.minimum_output_amount.decimal_amount / item.input_amount.decimal_amount
        for item in selected
    ]
    baseline = rates[0]
    return tuple(
        SizeSensitivityPoint(
            item.input_amount,
            item.provider,
            rate,
            (rate / baseline - Decimal(1)) * BASIS_POINTS,
        )
        for item, rate in zip(selected, rates, strict=True)
    )


def _same_token(left: TokenRef, right: TokenRef) -> bool:
    """Compare economic token identity without relying on address casing."""

    return (
        left.chain_id == right.chain_id
        and left.contract_address.lower() == right.contract_address.lower()
        and left.decimals == right.decimals
    )
