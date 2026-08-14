"""Two-chain virtual inventory accounting for paper-only arbitrage research."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Iterable

from onchain_arb.costs import CrossChainCostEvaluation, CrossChainCostLedger
from onchain_arb.models import (
    CostItem,
    CostScope,
    TokenAmount,
    TokenDelta,
    TokenRef,
    _require_utc,
)


@dataclass(frozen=True, slots=True)
class InventoryPosition:
    """One chain-specific balance and its fixed Day 10 policy limits."""

    asset_id: str
    balance: TokenAmount
    target_minimum: TokenAmount
    target_maximum: TokenAmount
    max_imbalance: TokenAmount
    accounting_price: Decimal

    def __post_init__(self) -> None:
        if not self.asset_id:
            raise ValueError("asset_id is required")
        amounts = (self.balance, self.target_minimum, self.target_maximum, self.max_imbalance)
        if any(amount.token != self.balance.token for amount in amounts):
            raise ValueError("position amounts must use the same chain-specific token")
        if self.target_minimum.raw_amount > self.target_maximum.raw_amount:
            raise ValueError("target minimum cannot exceed target maximum")
        if not isinstance(self.accounting_price, Decimal):
            raise TypeError("accounting_price must be Decimal")
        if not self.accounting_price.is_finite() or self.accounting_price <= 0:
            raise ValueError("accounting_price must be finite and positive")

    @property
    def key(self) -> tuple[int, str]:
        return (self.balance.token.chain_id, self.asset_id)

    @property
    def capital_value(self) -> Decimal:
        return self.balance.decimal_amount * self.accounting_price

    def within_target_band(self, raw_amount: int | None = None) -> bool:
        value = self.balance.raw_amount if raw_amount is None else raw_amount
        return self.target_minimum.raw_amount <= value <= self.target_maximum.raw_amount

    def within_max_imbalance(self, raw_amount: int) -> bool:
        midpoint = Decimal(
            self.target_minimum.raw_amount + self.target_maximum.raw_amount
        ) / Decimal(2)
        return abs(Decimal(raw_amount) - midpoint) <= self.max_imbalance.raw_amount


@dataclass(frozen=True, slots=True)
class VirtualBalanceSheet:
    positions: tuple[InventoryPosition, ...]
    observed_at: datetime

    def __post_init__(self) -> None:
        if not self.positions:
            raise ValueError("a balance sheet requires positions")
        keys = tuple(position.key for position in self.positions)
        if len(set(keys)) != len(keys):
            raise ValueError("balance sheet positions must be unique by chain and asset")
        _require_utc(self.observed_at, "observed_at")

    @property
    def capital_occupied(self) -> Decimal:
        return sum(
            (position.capital_value for position in self.positions), start=Decimal(0)
        )

    def position(self, chain_id: int, asset_id: str) -> InventoryPosition:
        for position in self.positions:
            if position.key == (chain_id, asset_id):
                return position
        raise KeyError(f"missing inventory position: chain={chain_id}, asset={asset_id}")


@dataclass(frozen=True, slots=True)
class InventoryLeg:
    """A conservative exact-input leg backed by append-only quote evidence."""

    request_id: str
    raw_ref: str
    input_amount: TokenAmount
    minimum_output_amount: TokenAmount
    observed_at: datetime

    def __post_init__(self) -> None:
        if not self.request_id or not self.raw_ref:
            raise ValueError("request_id and raw_ref are required")
        if self.input_amount.raw_amount == 0 or self.minimum_output_amount.raw_amount == 0:
            raise ValueError("leg input and guaranteed output must be positive")
        if self.input_amount.token.chain_id != self.minimum_output_amount.token.chain_id:
            raise ValueError("an inventory leg must execute on one chain")
        if self.input_amount.token == self.minimum_output_amount.token:
            raise ValueError("an inventory leg must exchange distinct tokens")
        _require_utc(self.observed_at, "observed_at")


@dataclass(frozen=True, slots=True)
class CrossChainSignal:
    candidate_id: str
    stable_asset_id: str
    trade_asset_id: str
    cheap_chain_buy: InventoryLeg
    expensive_chain_sell: InventoryLeg
    costs: tuple[CostItem, ...]
    required_cost_kinds: frozenset[str]
    max_leg_skew: timedelta
    capital_lock_hours: Decimal

    def __post_init__(self) -> None:
        if not self.candidate_id or not self.stable_asset_id or not self.trade_asset_id:
            raise ValueError("candidate and economic asset identities are required")
        if self.stable_asset_id == self.trade_asset_id:
            raise ValueError("stable and trade asset identities must differ")
        buy = self.cheap_chain_buy
        sell = self.expensive_chain_sell
        if buy.input_amount.token.chain_id == sell.input_amount.token.chain_id:
            raise ValueError("cross-chain legs must execute on different chains")
        if buy.minimum_output_amount.token.decimals != sell.input_amount.token.decimals:
            raise ValueError("trade asset decimals must match across chains")
        if buy.input_amount.token.decimals != sell.minimum_output_amount.token.decimals:
            raise ValueError("stable asset decimals must match across chains")
        if buy.minimum_output_amount.raw_amount != sell.input_amount.raw_amount:
            raise ValueError(
                "cheap-chain guaranteed buy output must equal expensive-chain sell size"
            )
        if self.max_leg_skew < timedelta(0):
            raise ValueError("max_leg_skew must be non-negative")
        if buy.request_id == sell.request_id or buy.raw_ref == sell.raw_ref:
            raise ValueError("the two local legs require independent refresh evidence")
        if not isinstance(self.capital_lock_hours, Decimal):
            raise TypeError("capital_lock_hours must be Decimal")
        if not self.capital_lock_hours.is_finite() or self.capital_lock_hours <= 0:
            raise ValueError("capital_lock_hours must be finite and positive")
        if not self.required_cost_kinds:
            raise ValueError("required_cost_kinds must explicitly define the complete ledger")
        if any(not kind for kind in self.required_cost_kinds):
            raise ValueError("required cost kinds cannot be empty")
        if any(cost.scope is not CostScope.ATOMIC for cost in self.costs):
            raise ValueError("Day 10 signal costs must be atomic; rebalance belongs to Day 11")

        stable_tokens = {buy.input_amount.token, sell.minimum_output_amount.token}
        if any(cost.amount.token not in stable_tokens for cost in self.costs):
            raise ValueError(
                "Day 10 costs must be sourced in a chain-local stable accounting token"
            )

    @property
    def condition_locked_at(self) -> datetime:
        """The later independent leg observation is the earliest lock instant."""
        return max(self.cheap_chain_buy.observed_at, self.expensive_chain_sell.observed_at)

    @property
    def leg_skew(self) -> timedelta:
        return abs(
            self.cheap_chain_buy.observed_at - self.expensive_chain_sell.observed_at
        )


class InventoryStatus(StrEnum):
    ACCEPTED = "ACCEPTED"
    INVENTORY_BLOCKED = "INVENTORY_BLOCKED"
    COST_INCOMPLETE = "COST_INCOMPLETE"
    SIGNAL_NOT_LOCKED = "SIGNAL_NOT_LOCKED"


@dataclass(frozen=True, slots=True)
class InventoryRequirement:
    asset_id: str
    amount: TokenAmount


@dataclass(frozen=True, slots=True)
class InventoryChange:
    asset_id: str
    before: TokenAmount
    after: TokenAmount
    delta: TokenDelta
    within_target_band: bool


@dataclass(frozen=True, slots=True)
class InventoryEvaluation:
    candidate_id: str
    status: InventoryStatus
    reject_reasons: tuple[str, ...]
    condition_locked_at: datetime
    leg_skew: timedelta
    cost_evaluation: CrossChainCostEvaluation | None
    trade_pnl: Decimal | None
    changes: tuple[InventoryChange, ...]
    capital_occupied: Decimal
    capital_hour_return: Decimal | None
    required_initial_inventory: tuple[InventoryRequirement, ...]

    @property
    def accepted(self) -> bool:
        return self.status is InventoryStatus.ACCEPTED


def evaluate_inventory(
    signal: CrossChainSignal, balance_sheet: VirtualBalanceSheet
) -> InventoryEvaluation:
    """Paper-simulate simultaneous local legs without bridging or wallet access."""

    requirements = _requirements(signal)
    common = dict(
        candidate_id=signal.candidate_id,
        condition_locked_at=signal.condition_locked_at,
        leg_skew=signal.leg_skew,
        capital_occupied=balance_sheet.capital_occupied,
        required_initial_inventory=requirements,
    )
    if signal.leg_skew > signal.max_leg_skew:
        return InventoryEvaluation(
            status=InventoryStatus.SIGNAL_NOT_LOCKED,
            reject_reasons=("LEG_OBSERVATION_SKEW_EXCEEDED",),
            cost_evaluation=None,
            trade_pnl=None,
            changes=(),
            capital_hour_return=None,
            **common,
        )

    buy = signal.cheap_chain_buy
    sell = signal.expensive_chain_sell
    cost_evaluation = CrossChainCostLedger(
        accounting_asset_id=signal.stable_asset_id,
        decimals=buy.input_amount.token.decimals,
        required_cost_kinds=signal.required_cost_kinds,
    ).evaluate(
        candidate_id=signal.candidate_id,
        gross_pnl_raw=(
            sell.minimum_output_amount.raw_amount - buy.input_amount.raw_amount
        ),
        costs=signal.costs,
    )
    if not cost_evaluation.is_complete:
        return InventoryEvaluation(
            status=InventoryStatus.COST_INCOMPLETE,
            reject_reasons=tuple(
                f"MISSING_COST:{kind}"
                for kind in sorted(cost_evaluation.missing_cost_kinds)
            ),
            cost_evaluation=cost_evaluation,
            trade_pnl=None,
            changes=(),
            capital_hour_return=None,
            **common,
        )

    positions = _required_positions(signal, balance_sheet)
    requirement_by_key = {
        (item.amount.token.chain_id, item.asset_id): item.amount.raw_amount
        for item in requirements
    }
    reasons = [
        f"INSUFFICIENT_BALANCE:{chain_id}:{asset_id}"
        for (chain_id, asset_id), required in requirement_by_key.items()
        if positions[(chain_id, asset_id)].balance.raw_amount < required
    ]

    deltas = _raw_deltas(signal)
    for key, delta in deltas.items():
        position = positions[key]
        after = position.balance.raw_amount + delta
        if after < 0:
            reasons.append(f"NEGATIVE_BALANCE:{key[0]}:{key[1]}")
        elif not position.within_max_imbalance(after):
            reasons.append(f"MAX_IMBALANCE_EXCEEDED:{key[0]}:{key[1]}")

    if reasons:
        return InventoryEvaluation(
            status=InventoryStatus.INVENTORY_BLOCKED,
            reject_reasons=tuple(dict.fromkeys(reasons)),
            cost_evaluation=cost_evaluation,
            trade_pnl=None,
            changes=(),
            capital_hour_return=None,
            **common,
        )

    changes = tuple(
        _change(positions[key], asset_id=key[1], raw_delta=delta)
        for key, delta in deltas.items()
    )
    stable_delta_raw = sum(
        change.delta.raw_delta
        for change in changes
        if change.asset_id == signal.stable_asset_id
    )
    stable_delta = Decimal(stable_delta_raw).scaleb(-cost_evaluation.decimals)
    if stable_delta != cost_evaluation.local_trade_pnl:
        raise AssertionError("inventory delta and cost ledger PnL diverged")
    trade_pnl = cost_evaluation.local_trade_pnl
    capital = balance_sheet.capital_occupied
    if capital <= 0:  # Defensive: positive leg inputs normally make this unreachable.
        raise ValueError("capital occupied must be positive")
    capital_hour_return = trade_pnl / capital / signal.capital_lock_hours
    return InventoryEvaluation(
        status=InventoryStatus.ACCEPTED,
        reject_reasons=(),
        cost_evaluation=cost_evaluation,
        trade_pnl=trade_pnl,
        changes=changes,
        capital_hour_return=capital_hour_return,
        **common,
    )


def _required_positions(
    signal: CrossChainSignal, balance_sheet: VirtualBalanceSheet
) -> dict[tuple[int, str], InventoryPosition]:
    keys = (
        (signal.cheap_chain_buy.input_amount.token.chain_id, signal.stable_asset_id),
        (signal.cheap_chain_buy.input_amount.token.chain_id, signal.trade_asset_id),
        (signal.expensive_chain_sell.input_amount.token.chain_id, signal.stable_asset_id),
        (signal.expensive_chain_sell.input_amount.token.chain_id, signal.trade_asset_id),
    )
    positions = {key: balance_sheet.position(*key) for key in keys}
    expected_tokens = {
        keys[0]: signal.cheap_chain_buy.input_amount.token,
        keys[1]: signal.cheap_chain_buy.minimum_output_amount.token,
        keys[2]: signal.expensive_chain_sell.minimum_output_amount.token,
        keys[3]: signal.expensive_chain_sell.input_amount.token,
    }
    if any(positions[key].balance.token != token for key, token in expected_tokens.items()):
        raise ValueError("signal token identity does not match the balance sheet")
    return positions


def _external_costs(costs: Iterable[CostItem]) -> tuple[CostItem, ...]:
    return tuple(cost for cost in costs if not cost.included_in_quote_output)


def _requirements(signal: CrossChainSignal) -> tuple[InventoryRequirement, ...]:
    buy = signal.cheap_chain_buy
    sell = signal.expensive_chain_sell
    required: dict[tuple[int, str], tuple[TokenRef, int]] = {
        (buy.input_amount.token.chain_id, signal.stable_asset_id): (
            buy.input_amount.token,
            buy.input_amount.raw_amount,
        ),
        (sell.input_amount.token.chain_id, signal.trade_asset_id): (
            sell.input_amount.token,
            sell.input_amount.raw_amount,
        ),
    }
    for cost in _external_costs(signal.costs):
        key = (cost.amount.token.chain_id, signal.stable_asset_id)
        token, raw = required.get(key, (cost.amount.token, 0))
        required[key] = (token, raw + cost.amount.raw_amount)
    return tuple(
        InventoryRequirement(asset_id, TokenAmount(token, raw))
        for (chain_id, asset_id), (token, raw) in sorted(required.items())
    )


def _raw_deltas(signal: CrossChainSignal) -> dict[tuple[int, str], int]:
    buy = signal.cheap_chain_buy
    sell = signal.expensive_chain_sell
    deltas = {
        (buy.input_amount.token.chain_id, signal.stable_asset_id): -buy.input_amount.raw_amount,
        (buy.input_amount.token.chain_id, signal.trade_asset_id): buy.minimum_output_amount.raw_amount,
        (sell.input_amount.token.chain_id, signal.stable_asset_id): sell.minimum_output_amount.raw_amount,
        (sell.input_amount.token.chain_id, signal.trade_asset_id): -sell.input_amount.raw_amount,
    }
    for cost in _external_costs(signal.costs):
        key = (cost.amount.token.chain_id, signal.stable_asset_id)
        deltas[key] -= cost.amount.raw_amount
    return deltas


def _change(
    position: InventoryPosition, *, asset_id: str, raw_delta: int
) -> InventoryChange:
    after = TokenAmount(position.balance.token, position.balance.raw_amount + raw_delta)
    return InventoryChange(
        asset_id=asset_id,
        before=position.balance,
        after=after,
        delta=TokenDelta(position.balance.token, raw_delta),
        within_target_band=position.within_target_band(after.raw_amount),
    )
