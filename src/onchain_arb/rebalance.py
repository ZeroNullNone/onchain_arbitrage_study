"""Deterministic, paper-only inventory rebalance economics."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Iterable

from onchain_arb.costs import InventoryCycleCostLedger
from onchain_arb.models import TokenAmount, TokenDelta, TokenRef, _require_utc


class RebalancePolicyKind(StrEnum):
    IMMEDIATE = "immediate"
    THRESHOLD = "threshold"
    BATCH = "batch"


@dataclass(frozen=True, slots=True)
class RebalancePolicy:
    kind: RebalancePolicyKind
    threshold: TokenAmount | None = None
    batch_size: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, RebalancePolicyKind):
            raise TypeError("kind must be RebalancePolicyKind")
        if self.kind is RebalancePolicyKind.THRESHOLD:
            if self.threshold is None or self.threshold.raw_amount == 0:
                raise ValueError("threshold policy requires a positive threshold")
            if self.batch_size is not None:
                raise ValueError("threshold policy cannot define batch_size")
        elif self.kind is RebalancePolicyKind.BATCH:
            if (
                isinstance(self.batch_size, bool)
                or not isinstance(self.batch_size, int)
                or self.batch_size <= 0
            ):
                raise ValueError("batch policy requires a positive batch_size")
            if self.threshold is not None:
                raise ValueError("batch policy cannot define threshold")
        elif self.threshold is not None or self.batch_size is not None:
            raise ValueError("immediate policy has no policy parameter")


@dataclass(frozen=True, slots=True)
class PaperTrade:
    """One accepted local trade and the inventory displacement it creates."""

    trade_id: str
    local_trade_pnl: TokenDelta
    inventory_delta: TokenDelta
    observed_at: datetime

    def __post_init__(self) -> None:
        if not self.trade_id:
            raise ValueError("trade_id is required")
        if self.inventory_delta.raw_delta == 0:
            raise ValueError("inventory_delta cannot be zero")
        _require_utc(self.observed_at, "observed_at")


@dataclass(frozen=True, slots=True)
class RebalanceCostObservation:
    """Exact-size cost evidence for a virtual inventory restoration."""

    request_id: str
    raw_ref: str
    source: str
    transfer_amount: TokenAmount
    cost: TokenAmount
    observed_at: datetime
    latency_ms: Decimal

    def __post_init__(self) -> None:
        if not self.request_id or not self.raw_ref or not self.source:
            raise ValueError("request_id, raw_ref, and source are required")
        if self.transfer_amount.raw_amount == 0:
            raise ValueError("transfer_amount must be positive")
        if not isinstance(self.latency_ms, Decimal):
            raise TypeError("latency_ms must be Decimal")
        if not self.latency_ms.is_finite() or self.latency_ms < 0:
            raise ValueError("latency_ms must be finite and non-negative")
        _require_utc(self.observed_at, "observed_at")


class RebalanceStatus(StrEnum):
    COMPLETE = "COMPLETE"
    COST_INCOMPLETE = "COST_INCOMPLETE"


@dataclass(frozen=True, slots=True)
class ImbalanceLevel:
    amount: TokenAmount
    observations: int
    probability: Decimal


@dataclass(frozen=True, slots=True)
class RebalanceEvent:
    after_trade_id: str
    restored_amount: TokenAmount
    cost_observation: RebalanceCostObservation


@dataclass(frozen=True, slots=True)
class RebalanceEvaluation:
    policy: RebalancePolicy
    status: RebalanceStatus
    reject_reasons: tuple[str, ...]
    trade_count: int
    local_trade_pnl: Decimal
    rebalance_cost: Decimal | None
    cycle_pnl: Decimal | None
    rebalance_count: int
    rebalance_frequency: Decimal
    break_even_rebalance_cost: Decimal
    break_even_cost_per_rebalance: Decimal | None
    ending_imbalance: TokenDelta
    imbalance_distribution: tuple[ImbalanceLevel, ...]
    events: tuple[RebalanceEvent, ...]


def evaluate_rebalance(
    trades: Iterable[PaperTrade],
    policy: RebalancePolicy,
    cost_observations: Iterable[RebalanceCostObservation],
) -> RebalanceEvaluation:
    """Run one deterministic cycle and settle every residual imbalance at the end."""

    trade_items = tuple(trades)
    if not trade_items:
        raise ValueError("at least one trade is required")
    _validate_trades(trade_items, policy)
    quotes = list(cost_observations)
    _validate_cost_observations(trade_items, tuple(quotes))

    pnl_raw = sum(trade.local_trade_pnl.raw_delta for trade in trade_items)
    pnl_token = trade_items[0].local_trade_pnl.token
    local_pnl = Decimal(pnl_raw).scaleb(-pnl_token.decimals)
    inventory_token = trade_items[0].inventory_delta.token
    accumulated_raw = 0
    trades_since_rebalance = 0
    events: list[RebalanceEvent] = []
    observed_levels: list[int] = []
    reject_reasons: list[str] = []

    for index, trade in enumerate(trade_items):
        accumulated_raw += trade.inventory_delta.raw_delta
        trades_since_rebalance += 1
        is_last = index == len(trade_items) - 1
        if _should_rebalance(policy, accumulated_raw, trades_since_rebalance) or is_last:
            amount_raw = abs(accumulated_raw)
            quote = _take_exact_quote(quotes, inventory_token, amount_raw)
            if quote is None:
                reject_reasons.append(f"MISSING_REBALANCE_COST:{amount_raw}")
            else:
                events.append(
                    RebalanceEvent(
                        after_trade_id=trade.trade_id,
                        restored_amount=TokenAmount(inventory_token, amount_raw),
                        cost_observation=quote,
                    )
                )
                accumulated_raw = 0
                trades_since_rebalance = 0
        observed_levels.append(abs(accumulated_raw))

    distribution = _distribution(inventory_token, observed_levels)
    count = len(events)
    frequency = Decimal(count) / Decimal(len(trade_items))
    break_even_per_event = local_pnl / Decimal(count) if count else None
    if reject_reasons:
        return RebalanceEvaluation(
            policy=policy,
            status=RebalanceStatus.COST_INCOMPLETE,
            reject_reasons=tuple(dict.fromkeys(reject_reasons)),
            trade_count=len(trade_items),
            local_trade_pnl=local_pnl,
            rebalance_cost=None,
            cycle_pnl=None,
            rebalance_count=count,
            rebalance_frequency=frequency,
            break_even_rebalance_cost=local_pnl,
            break_even_cost_per_rebalance=break_even_per_event,
            ending_imbalance=TokenDelta(inventory_token, accumulated_raw),
            imbalance_distribution=distribution,
            events=tuple(events),
        )

    ledger_result = InventoryCycleCostLedger(accounting_token=pnl_token).evaluate(
        local_trade_pnl=TokenDelta(pnl_token, pnl_raw),
        rebalance_costs=(event.cost_observation.cost for event in events),
    )
    return RebalanceEvaluation(
        policy=policy,
        status=RebalanceStatus.COMPLETE,
        reject_reasons=(),
        trade_count=len(trade_items),
        local_trade_pnl=local_pnl,
        rebalance_cost=ledger_result.rebalance_cost,
        cycle_pnl=ledger_result.inventory_cycle_pnl,
        rebalance_count=count,
        rebalance_frequency=frequency,
        break_even_rebalance_cost=local_pnl,
        break_even_cost_per_rebalance=break_even_per_event,
        ending_imbalance=TokenDelta(inventory_token, accumulated_raw),
        imbalance_distribution=distribution,
        events=tuple(events),
    )


@dataclass(frozen=True, slots=True)
class CapacityScenario:
    trade_size: TokenAmount
    local_trade_pnl: TokenDelta
    rebalance_cost: TokenAmount

    def __post_init__(self) -> None:
        if self.trade_size.raw_amount == 0:
            raise ValueError("trade_size must be positive")
        token = self.trade_size.token
        if self.local_trade_pnl.token != token or self.rebalance_cost.token != token:
            raise ValueError("capacity accounting values must use one token")


@dataclass(frozen=True, slots=True)
class CapacityPoint:
    trade_size: TokenAmount
    local_trade_pnl: Decimal
    rebalance_cost: Decimal
    cycle_pnl: Decimal
    edge_bps: Decimal


@dataclass(frozen=True, slots=True)
class CapacityCurve:
    points: tuple[CapacityPoint, ...]
    profitable_capacity: TokenAmount | None


def build_capacity_curve(scenarios: Iterable[CapacityScenario]) -> CapacityCurve:
    """Report post-rebalance edge by size and the largest profitable tested size."""

    items = tuple(scenarios)
    if not items:
        raise ValueError("at least one capacity scenario is required")
    token = items[0].trade_size.token
    if any(item.trade_size.token != token for item in items):
        raise ValueError("capacity scenarios must use one accounting token")
    ordered = sorted(items, key=lambda item: item.trade_size.raw_amount)
    if len({item.trade_size.raw_amount for item in ordered}) != len(ordered):
        raise ValueError("capacity trade sizes must be unique")

    points = tuple(_capacity_point(item) for item in ordered)
    profitable = [point.trade_size for point in points if point.cycle_pnl > 0]
    return CapacityCurve(
        points=points,
        profitable_capacity=profitable[-1] if profitable else None,
    )


def _capacity_point(item: CapacityScenario) -> CapacityPoint:
    local = item.local_trade_pnl.decimal_delta
    cost = item.rebalance_cost.decimal_amount
    cycle = local - cost
    return CapacityPoint(
        trade_size=item.trade_size,
        local_trade_pnl=local,
        rebalance_cost=cost,
        cycle_pnl=cycle,
        edge_bps=cycle / item.trade_size.decimal_amount * Decimal(10_000),
    )


def _validate_trades(
    trades: tuple[PaperTrade, ...], policy: RebalancePolicy
) -> None:
    pnl_token = trades[0].local_trade_pnl.token
    inventory_token = trades[0].inventory_delta.token
    direction = trades[0].inventory_delta.raw_delta > 0
    if any(trade.local_trade_pnl.token != pnl_token for trade in trades):
        raise ValueError("all local PnL values must use one accounting token")
    if any(trade.inventory_delta.token != inventory_token for trade in trades):
        raise ValueError("all inventory deltas must use one chain-specific token")
    if any((trade.inventory_delta.raw_delta > 0) != direction for trade in trades):
        raise ValueError("opposing inventory flow belongs to the natural-netting backlog")
    if policy.threshold is not None and policy.threshold.token != inventory_token:
        raise ValueError("policy threshold must use the inventory token")


def _validate_cost_observations(
    trades: tuple[PaperTrade, ...], quotes: tuple[RebalanceCostObservation, ...]
) -> None:
    pnl_token = trades[0].local_trade_pnl.token
    inventory_token = trades[0].inventory_delta.token
    if any(quote.transfer_amount.token != inventory_token for quote in quotes):
        raise ValueError("rebalance quote transfer token does not match inventory")
    if any(quote.cost.token != pnl_token for quote in quotes):
        raise ValueError("rebalance quote cost does not match the accounting token")
    request_ids = [quote.request_id for quote in quotes]
    raw_refs = [quote.raw_ref for quote in quotes]
    if len(set(request_ids)) != len(request_ids) or len(set(raw_refs)) != len(raw_refs):
        raise ValueError("rebalance observations require unique request IDs and Raw refs")


def _should_rebalance(
    policy: RebalancePolicy, accumulated_raw: int, trades_since_rebalance: int
) -> bool:
    if policy.kind is RebalancePolicyKind.IMMEDIATE:
        return True
    if policy.kind is RebalancePolicyKind.THRESHOLD:
        assert policy.threshold is not None
        return abs(accumulated_raw) >= policy.threshold.raw_amount
    assert policy.batch_size is not None
    return trades_since_rebalance >= policy.batch_size


def _take_exact_quote(
    quotes: list[RebalanceCostObservation], token: TokenRef, amount_raw: int
) -> RebalanceCostObservation | None:
    for index, quote in enumerate(quotes):
        if (
            quote.transfer_amount.token == token
            and quote.transfer_amount.raw_amount == amount_raw
        ):
            return quotes.pop(index)
    return None


def _distribution(token: TokenRef, levels: list[int]) -> tuple[ImbalanceLevel, ...]:
    counts = Counter(levels)
    total = Decimal(len(levels))
    return tuple(
        ImbalanceLevel(
            amount=TokenAmount(token, raw),
            observations=count,
            probability=Decimal(count) / total,
        )
        for raw, count in sorted(counts.items())
    )
