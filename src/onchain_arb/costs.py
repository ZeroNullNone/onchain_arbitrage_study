"""Single-owner PnL semantics for atomic trades and inventory cycles."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable

from onchain_arb.models import CostItem, CostScope, TokenDelta, TokenRef


@dataclass(frozen=True, slots=True)
class CostEvaluation:
    """An auditable breakdown in one accounting token."""

    candidate_id: str
    accounting_token: TokenRef
    gross_pnl: TokenDelta
    costs: tuple[CostItem, ...]
    atomic_deduction_total: Decimal
    cycle_deduction_total: Decimal
    included_cost_total: Decimal
    atomic_net_pnl: Decimal
    local_trade_pnl: Decimal
    inventory_cycle_pnl: Decimal
    missing_cost_kinds: frozenset[str]

    @property
    def is_complete(self) -> bool:
        return not self.missing_cost_kinds


@dataclass(frozen=True, slots=True)
class CrossChainCostEvaluation:
    """A ledger over one explicit economic asset on multiple chains."""

    candidate_id: str
    accounting_asset_id: str
    decimals: int
    gross_pnl: Decimal
    costs: tuple[CostItem, ...]
    external_cost_total: Decimal
    included_cost_total: Decimal
    local_trade_pnl: Decimal
    missing_cost_kinds: frozenset[str]

    @property
    def is_complete(self) -> bool:
        return not self.missing_cost_kinds


class CostLedger:
    """Calculate PnL once, without re-deducting quote-included costs."""

    def __init__(self, *, required_cost_kinds: Iterable[str]) -> None:
        required = frozenset(required_cost_kinds)
        if any(not kind for kind in required):
            raise ValueError("required cost kinds cannot be empty")
        self._required_cost_kinds = required

    def evaluate(
        self,
        *,
        candidate_id: str,
        gross_pnl: TokenDelta,
        costs: Iterable[CostItem],
    ) -> CostEvaluation:
        if not candidate_id:
            raise ValueError("candidate_id is required")

        cost_items = tuple(costs)
        self._validate_accounting_token(gross_pnl.token, cost_items)

        present_kinds = frozenset(item.kind for item in cost_items)
        missing_kinds = self._required_cost_kinds - present_kinds
        included_total = self._sum(
            item for item in cost_items if item.included_in_quote_output
        )
        atomic_deductions = self._sum(
            item
            for item in cost_items
            if not item.included_in_quote_output and item.scope is CostScope.ATOMIC
        )
        cycle_deductions = self._sum(
            item
            for item in cost_items
            if not item.included_in_quote_output and item.scope is CostScope.CYCLE
        )

        gross = gross_pnl.decimal_delta
        atomic_net = gross - atomic_deductions
        return CostEvaluation(
            candidate_id=candidate_id,
            accounting_token=gross_pnl.token,
            gross_pnl=gross_pnl,
            costs=cost_items,
            atomic_deduction_total=atomic_deductions,
            cycle_deduction_total=cycle_deductions,
            included_cost_total=included_total,
            atomic_net_pnl=atomic_net,
            local_trade_pnl=atomic_net,
            inventory_cycle_pnl=atomic_net - cycle_deductions,
            missing_cost_kinds=missing_kinds,
        )

    @staticmethod
    def _sum(costs: Iterable[CostItem]) -> Decimal:
        return sum((item.amount.decimal_amount for item in costs), start=Decimal(0))

    @staticmethod
    def _validate_accounting_token(
        accounting_token: TokenRef,
        costs: tuple[CostItem, ...],
    ) -> None:
        if any(item.amount.token != accounting_token for item in costs):
            raise ValueError(
                "all costs must use the same accounting token as gross PnL; "
                "currency conversion belongs upstream and requires sourced FX evidence"
            )


class CrossChainCostLedger:
    """Consolidate chain-local units only after explicit economic-asset mapping.

    This does not perform FX conversion. Every cost must have the same decimals as
    the mapped accounting asset; chain-specific token identity remains preserved on
    each ``CostItem`` for the inventory delta.
    """

    def __init__(
        self,
        *,
        accounting_asset_id: str,
        decimals: int,
        required_cost_kinds: Iterable[str],
    ) -> None:
        if not accounting_asset_id:
            raise ValueError("accounting_asset_id is required")
        if not 0 <= decimals <= 255:
            raise ValueError("decimals must be between 0 and 255")
        required = frozenset(required_cost_kinds)
        if not required or any(not kind for kind in required):
            raise ValueError("required cost kinds must be explicit and non-empty")
        self._accounting_asset_id = accounting_asset_id
        self._decimals = decimals
        self._required_cost_kinds = required

    def evaluate(
        self,
        *,
        candidate_id: str,
        gross_pnl_raw: int,
        costs: Iterable[CostItem],
    ) -> CrossChainCostEvaluation:
        if not candidate_id:
            raise ValueError("candidate_id is required")
        if isinstance(gross_pnl_raw, bool) or not isinstance(gross_pnl_raw, int):
            raise TypeError("gross_pnl_raw must be an integer")
        cost_items = tuple(costs)
        if any(item.amount.token.decimals != self._decimals for item in cost_items):
            raise ValueError(
                "cross-chain costs require matching decimals; FX conversion belongs upstream"
            )

        missing = self._required_cost_kinds - {item.kind for item in cost_items}
        included_raw = sum(
            item.amount.raw_amount
            for item in cost_items
            if item.included_in_quote_output
        )
        external_raw = sum(
            item.amount.raw_amount
            for item in cost_items
            if not item.included_in_quote_output and item.scope is CostScope.ATOMIC
        )
        gross = Decimal(gross_pnl_raw).scaleb(-self._decimals)
        external = Decimal(external_raw).scaleb(-self._decimals)
        return CrossChainCostEvaluation(
            candidate_id=candidate_id,
            accounting_asset_id=self._accounting_asset_id,
            decimals=self._decimals,
            gross_pnl=gross,
            costs=cost_items,
            external_cost_total=external,
            included_cost_total=Decimal(included_raw).scaleb(-self._decimals),
            local_trade_pnl=gross - external,
            missing_cost_kinds=missing,
        )
