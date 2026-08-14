"""Day 10 acceptance tests for the two-chain virtual balance sheet."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from onchain_arb.inventory import (
    CrossChainSignal,
    InventoryLeg,
    InventoryPosition,
    InventoryStatus,
    VirtualBalanceSheet,
    evaluate_inventory,
)
from onchain_arb.models import (
    CostConfidence,
    CostItem,
    CostScope,
    TokenAmount,
    TokenRef,
)


OBSERVED_AT = datetime(2026, 8, 14, 2, 0, tzinfo=UTC)
BASE_USDC = TokenRef(8453, "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913", "USDC", 6)
BASE_WETH = TokenRef(8453, "0x4200000000000000000000000000000000000006", "WETH", 18)
ARB_USDC = TokenRef(42161, "0xaf88d065e77c8cc2239327c5edb3a432268e5831", "USDC", 6)
ARB_WETH = TokenRef(42161, "0x82af49447d8a07e3bd95bd0d56f35241523fbab1", "WETH", 18)


def amount(token: TokenRef, value: str) -> TokenAmount:
    return TokenAmount.from_decimal(token, Decimal(value))


def position(
    asset_id: str,
    token: TokenRef,
    balance: str,
    target_minimum: str,
    target_maximum: str,
    max_imbalance: str,
    price: str,
) -> InventoryPosition:
    return InventoryPosition(
        asset_id=asset_id,
        balance=amount(token, balance),
        target_minimum=amount(token, target_minimum),
        target_maximum=amount(token, target_maximum),
        max_imbalance=amount(token, max_imbalance),
        accounting_price=Decimal(price),
    )


def balance_sheet(*, arb_weth_balance: str = "1") -> VirtualBalanceSheet:
    return VirtualBalanceSheet(
        positions=(
            position("USDC", BASE_USDC, "2000", "1500", "2500", "1500", "1"),
            position("WETH", BASE_WETH, "1", "0.5", "1.5", "1", "2000"),
            position("USDC", ARB_USDC, "2000", "1500", "2500", "1500", "1"),
            position("WETH", ARB_WETH, arb_weth_balance, "0.5", "1.5", "1", "2000"),
        ),
        observed_at=OBSERVED_AT,
    )


def cost(kind: str, token: TokenRef, value: str, *, included: bool = False) -> CostItem:
    return CostItem(
        kind=kind,
        amount=amount(token, value),
        scope=CostScope.ATOMIC,
        included_in_quote_output=included,
        confidence=CostConfidence.STRESSED,
        source="day10_paper_fixture",
        observed_at=OBSERVED_AT,
    )


def signal() -> CrossChainSignal:
    return CrossChainSignal(
        candidate_id="day10-base-buy-arbitrum-sell",
        stable_asset_id="USDC",
        trade_asset_id="WETH",
        cheap_chain_buy=InventoryLeg(
            request_id="base-buy-refresh",
            raw_ref="day10_paper_fixture#base-buy",
            input_amount=amount(BASE_USDC, "500"),
            minimum_output_amount=amount(BASE_WETH, "0.25"),
            observed_at=OBSERVED_AT,
        ),
        expensive_chain_sell=InventoryLeg(
            request_id="arbitrum-sell-refresh",
            raw_ref="day10_paper_fixture#arbitrum-sell",
            input_amount=amount(ARB_WETH, "0.25"),
            minimum_output_amount=amount(ARB_USDC, "506"),
            observed_at=OBSERVED_AT + timedelta(milliseconds=400),
        ),
        costs=(
            cost("gas_buy", BASE_USDC, "0.40"),
            cost("gas_sell", ARB_USDC, "0.60"),
            cost("swap_fee_included", BASE_USDC, "1.50", included=True),
        ),
        required_cost_kinds=frozenset(
            {"gas_buy", "gas_sell", "swap_fee_included"}
        ),
        max_leg_skew=timedelta(seconds=1),
        capital_lock_hours=Decimal("2"),
    )


def test_two_leg_trade_reports_pnl_inventory_capital_and_requirements() -> None:
    sheet = balance_sheet()

    result = evaluate_inventory(signal(), sheet)

    assert result.status is InventoryStatus.ACCEPTED
    assert result.condition_locked_at == OBSERVED_AT + timedelta(milliseconds=400)
    assert result.leg_skew == timedelta(milliseconds=400)
    assert result.trade_pnl == Decimal("5")
    assert result.cost_evaluation is not None
    assert result.cost_evaluation.is_complete
    assert result.cost_evaluation.gross_pnl == Decimal("6")
    assert result.cost_evaluation.external_cost_total == Decimal("1")
    assert result.cost_evaluation.included_cost_total == Decimal("1.5")
    assert result.capital_occupied == Decimal("8000")
    assert result.capital_hour_return == Decimal("0.0003125")
    requirements = {
        (item.amount.token.chain_id, item.asset_id): item.amount.decimal_amount
        for item in result.required_initial_inventory
    }
    assert requirements == {
        (8453, "USDC"): Decimal("500.4"),
        (42161, "USDC"): Decimal("0.6"),
        (42161, "WETH"): Decimal("0.25"),
    }


def test_total_assets_are_conserved_after_explicit_costs() -> None:
    result = evaluate_inventory(signal(), balance_sheet())
    stable_delta = sum(
        (change.delta.decimal_delta for change in result.changes if change.asset_id == "USDC"),
        Decimal(0),
    )
    trade_asset_delta = sum(
        (change.delta.decimal_delta for change in result.changes if change.asset_id == "WETH"),
        Decimal(0),
    )

    assert stable_delta == result.trade_pnl == Decimal("5")
    assert trade_asset_delta == Decimal("0")
    assert {
        (change.before.token.chain_id, change.asset_id): change.delta.decimal_delta
        for change in result.changes
    } == {
        (8453, "USDC"): Decimal("-500.4"),
        (8453, "WETH"): Decimal("0.25"),
        (42161, "USDC"): Decimal("505.4"),
        (42161, "WETH"): Decimal("-0.25"),
    }


def test_insufficient_expensive_chain_asset_is_inventory_blocked() -> None:
    result = evaluate_inventory(signal(), balance_sheet(arb_weth_balance="0.20"))

    assert result.status is InventoryStatus.INVENTORY_BLOCKED
    assert "INSUFFICIENT_BALANCE:42161:WETH" in result.reject_reasons
    assert result.trade_pnl is None
    assert result.changes == ()


def test_maximum_imbalance_is_a_hard_policy_limit() -> None:
    constrained_sheet = balance_sheet()
    constrained_base_usdc = replace(
        constrained_sheet.position(8453, "USDC"),
        max_imbalance=amount(BASE_USDC, "100"),
    )
    constrained_sheet = replace(
        constrained_sheet,
        positions=tuple(
            constrained_base_usdc if item.key == (8453, "USDC") else item
            for item in constrained_sheet.positions
        ),
    )

    result = evaluate_inventory(signal(), constrained_sheet)

    assert result.status is InventoryStatus.INVENTORY_BLOCKED
    assert "MAX_IMBALANCE_EXCEEDED:8453:USDC" in result.reject_reasons


def test_missing_cost_is_not_silently_treated_as_zero() -> None:
    incomplete = replace(signal(), costs=signal().costs[:1])

    result = evaluate_inventory(incomplete, balance_sheet())

    assert result.status is InventoryStatus.COST_INCOMPLETE
    assert result.reject_reasons == (
        "MISSING_COST:gas_sell",
        "MISSING_COST:swap_fee_included",
    )
    assert result.trade_pnl is None


def test_signal_requires_independently_refreshed_legs_inside_lock_window() -> None:
    stale_sell = replace(
        signal().expensive_chain_sell,
        observed_at=OBSERVED_AT + timedelta(seconds=3),
    )
    unlocked = replace(signal(), expensive_chain_sell=stale_sell)

    result = evaluate_inventory(unlocked, balance_sheet())

    assert result.status is InventoryStatus.SIGNAL_NOT_LOCKED
    assert result.condition_locked_at == stale_sell.observed_at
    assert result.reject_reasons == ("LEG_OBSERVATION_SKEW_EXCEEDED",)
