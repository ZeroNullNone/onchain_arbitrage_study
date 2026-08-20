"""Golden test scenarios and configuration validation for Day 16 Primary Strategy Specification."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
import tempfile
import pytest

from onchain_arb.inventory import (
    CrossChainSignal,
    InventoryLeg,
    InventoryPosition,
    VirtualBalanceSheet,
)
from onchain_arb.models import (
    CostConfidence,
    CostItem,
    CostScope,
    TokenAmount,
    TokenRef,
)
from onchain_arb.scanner import CandidateDeduplicator
from onchain_arb.strategy import (
    KillMetricsConfig,
    PrimaryStrategySpec,
    StrategyConfig,
    StrategyId,
    StrategyRejectReason,
    ThresholdConfig,
    TimingConfig,
    _check_no_tbd,
    evaluate_primary_strategy,
    load_strategy_spec,
)
from onchain_arb.token_registry import TokenClassification, TokenRecord, TokenRegistry

CONFIG_PATH = Path(__file__).parent.parent / "config" / "strategy.toml"
NOW_UTC = datetime(2026, 8, 17, 10, 0, 0, tzinfo=UTC)

BASE_USDC = TokenRef(8453, "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913", "USDC", 6)
BASE_WETH = TokenRef(8453, "0x4200000000000000000000000000000000000006", "WETH", 18)
ARB_USDC = TokenRef(42161, "0xaf88d065e77c8cC2239327C5EDb3A432268e5831", "USDC", 6)
ARB_WETH = TokenRef(42161, "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1", "WETH", 18)


def _make_cost(token: TokenRef, kind: str, raw_amount: int, observed_at: datetime) -> CostItem:
    return CostItem(
        kind=kind,
        amount=TokenAmount(token, raw_amount),
        scope=CostScope.ATOMIC,
        included_in_quote_output=False,
        confidence=CostConfidence.ESTIMATED,
        source="strategy_spec_test",
        observed_at=observed_at,
    )


def _make_signal(
    *,
    candidate_id: str,
    buy_input_usd: int = 500,
    gross_edge_usd: Decimal = Decimal("3.00"),
    gas_cost_usd_each_leg: Decimal = Decimal("0.40"),
    observed_at: datetime = NOW_UTC,
    skew_ms: int = 100,
) -> CrossChainSignal:
    buy_raw = buy_input_usd * 1_000_000
    sell_raw = buy_raw + int(gross_edge_usd * 1_000_000)
    weth_raw = 250_000_000_000_000_000  # 0.25 WETH

    buy_leg = InventoryLeg(
        request_id=f"req-buy-{candidate_id}",
        raw_ref=f"raw://{candidate_id}/buy",
        input_amount=TokenAmount(BASE_USDC, buy_raw),
        minimum_output_amount=TokenAmount(BASE_WETH, weth_raw),
        observed_at=observed_at,
    )
    sell_leg = InventoryLeg(
        request_id=f"req-sell-{candidate_id}",
        raw_ref=f"raw://{candidate_id}/sell",
        input_amount=TokenAmount(ARB_WETH, weth_raw),
        minimum_output_amount=TokenAmount(ARB_USDC, sell_raw),
        observed_at=observed_at + timedelta(milliseconds=skew_ms),
    )

    cheap_gas_raw = int(gas_cost_usd_each_leg * 1_000_000)
    expensive_gas_raw = int(gas_cost_usd_each_leg * 1_000_000)
    costs = (
        _make_cost(BASE_USDC, "cheap_gas", cheap_gas_raw, observed_at),
        _make_cost(ARB_USDC, "expensive_gas", expensive_gas_raw, observed_at),
    )

    return CrossChainSignal(
        candidate_id=candidate_id,
        stable_asset_id="USDC",
        trade_asset_id="WETH",
        cheap_chain_buy=buy_leg,
        expensive_chain_sell=sell_leg,
        costs=costs,
        required_cost_kinds=frozenset({"cheap_gas", "expensive_gas"}),
        max_leg_skew=timedelta(milliseconds=1000),
        capital_lock_hours=Decimal("2.0"),
    )


def _make_balance_sheet(
    *,
    base_usdc_raw: int = 2_000_000_000,
    base_weth_raw: int = 1_000_000_000_000_000_000,
    arb_usdc_raw: int = 2_000_000_000,
    arb_weth_raw: int = 1_000_000_000_000_000_000,
) -> VirtualBalanceSheet:
    positions = (
        InventoryPosition(
            asset_id="USDC",
            balance=TokenAmount(BASE_USDC, base_usdc_raw),
            target_minimum=TokenAmount(BASE_USDC, 1_500_000_000),
            target_maximum=TokenAmount(BASE_USDC, 2_500_000_000),
            max_imbalance=TokenAmount(BASE_USDC, 1_500_000_000),
            accounting_price=Decimal("1.0"),
        ),
        InventoryPosition(
            asset_id="WETH",
            balance=TokenAmount(BASE_WETH, base_weth_raw),
            target_minimum=TokenAmount(BASE_WETH, 500_000_000_000_000_000),
            target_maximum=TokenAmount(BASE_WETH, 1_500_000_000_000_000_000),
            max_imbalance=TokenAmount(BASE_WETH, 1_000_000_000_000_000_000),
            accounting_price=Decimal("2000.0"),
        ),
        InventoryPosition(
            asset_id="USDC",
            balance=TokenAmount(ARB_USDC, arb_usdc_raw),
            target_minimum=TokenAmount(ARB_USDC, 1_500_000_000),
            target_maximum=TokenAmount(ARB_USDC, 2_500_000_000),
            max_imbalance=TokenAmount(ARB_USDC, 1_500_000_000),
            accounting_price=Decimal("1.0"),
        ),
        InventoryPosition(
            asset_id="WETH",
            balance=TokenAmount(ARB_WETH, arb_weth_raw),
            target_minimum=TokenAmount(ARB_WETH, 500_000_000_000_000_000),
            target_maximum=TokenAmount(ARB_WETH, 1_500_000_000_000_000_000),
            max_imbalance=TokenAmount(ARB_WETH, 1_000_000_000_000_000_000),
            accounting_price=Decimal("2000.0"),
        ),
    )
    return VirtualBalanceSheet(positions=positions, observed_at=NOW_UTC)


# ============================================================================
# 1. Config Loading & Anti-TBD Validation Tests
# ============================================================================

def test_load_frozen_strategy_config() -> None:
    config = load_strategy_spec(CONFIG_PATH)
    assert isinstance(config, StrategyConfig)
    assert config.schema_version == 1
    assert config.reviewed_at.tzinfo is not None

    # Primary Strategy Specs
    primary = config.primary
    assert primary.strategy_id == StrategyId.H1_CROSS_CHAIN_INVENTORY
    assert primary.mode == "paper"
    assert primary.chains == (8453, 42161)
    assert primary.stable_asset_id == "USDC"
    assert primary.trade_asset_id == "WETH"
    assert primary.target_sizes_usd == (Decimal("100"), Decimal("500"), Decimal("1000"))
    assert primary.rebalance_threshold_usd == Decimal("500")
    assert primary.max_inventory_imbalance_usd == Decimal("1500")
    assert len(primary.tokens) == 4

    # Timing parameters
    assert primary.timing.max_quote_age_ms == 10000
    assert primary.timing.max_leg_skew_ms == 1000
    assert primary.timing.requote_window_ms == 3000
    assert primary.timing.dedup_window_seconds == 60.0

    # Threshold parameters
    assert primary.threshold.cost_uncertainty_pct == Decimal("0.20")
    assert primary.threshold.cost_uncertainty_floor_usd == Decimal("0.10")
    assert primary.threshold.latency_buffer_bps == Decimal("10.0")
    assert primary.threshold.rebalance_buffer_usd == Decimal("0.40")
    assert primary.threshold.min_economic_profit_usd == Decimal("0.50")

    # Kill metrics
    assert primary.kill_metrics.max_consecutive_losses == 3
    assert primary.kill_metrics.min_requote_survival_rate == Decimal("0.10")
    assert primary.kill_metrics.max_balance_drift_pct == Decimal("0.50")
    assert primary.kill_metrics.max_gas_multiplier == Decimal("5.0")

    # Backup Strategy Specs
    backup = config.backup
    assert backup.strategy_id == StrategyId.H2_SAME_CHAIN_BASELINE
    assert backup.mode == "paper_negative_control"
    assert backup.chain_id == 8453
    assert backup.venues == ("aerodrome", "uniswap_v3")
    assert bool(backup.read_only_description)


def test_config_rejects_tbd_placeholders() -> None:
    # Test helper _check_no_tbd directly
    with pytest.raises(ValueError, match="contains unpopulated placeholder"):
        _check_no_tbd({"threshold": {"buffer": "TBD_DAY_16"}})

    with pytest.raises(ValueError, match="contains unpopulated placeholder"):
        _check_no_tbd(["valid", "TODO_FIXME"])

    with pytest.raises(ValueError, match="contains unpopulated placeholder"):
        _check_no_tbd({"status": "UNCONFIGURED"})

    # Test file loader rejecting a modified config with TBD
    raw_content = CONFIG_PATH.read_text().replace(
        'min_economic_profit_usd = "0.50"',
        'min_economic_profit_usd = "TBD_NEED_RESEARCH"'
    )
    with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as tf:
        tf.write(raw_content)
        tf_path = Path(tf.name)

    try:
        with pytest.raises(ValueError, match="contains unpopulated placeholder"):
            load_strategy_spec(tf_path)
    finally:
        tf_path.unlink()


def test_config_validates_numeric_types_and_bounds() -> None:
    # Negative threshold should fail
    with pytest.raises(ValueError, match="must be non-negative"):
        ThresholdConfig(
            cost_uncertainty_pct=Decimal("-0.1"),
            cost_uncertainty_floor_usd=Decimal("0.10"),
            latency_buffer_bps=Decimal("10.0"),
            rebalance_buffer_usd=Decimal("0.40"),
            min_economic_profit_usd=Decimal("0.50"),
        )

    # Invalid survival rate (> 1.0) should fail
    with pytest.raises(ValueError, match="between 0 and 1"):
        KillMetricsConfig(
            max_consecutive_losses=3,
            min_requote_survival_rate=Decimal("1.5"),
            max_balance_drift_pct=Decimal("0.50"),
            max_gas_multiplier=Decimal("5.0"),
        )


# ============================================================================
# 2. Required Edge Formula Hand-Calculations
# ============================================================================

def test_required_edge_formula_size_500() -> None:
    config = load_strategy_spec(CONFIG_PATH)
    threshold = config.primary.threshold

    trade_size_usd = Decimal("500")
    known_execution_cost = Decimal("0.80")  # 0.40 Base + 0.40 Arb

    # Hand calculation:
    # 1. cost_uncertainty = max(0.80 * 0.20, 0.10) = 0.16 USD
    # 2. latency_buffer = 500 * (10 / 10000) = 0.50 USD
    # 3. rebalance_buffer = 0.40 USD
    # 4. min_economic_profit = 0.50 USD
    # Total Required Edge = 0.80 + 0.16 + 0.50 + 0.40 + 0.50 = 2.36 USD

    # Case A: gross_edge = 3.00 USD -> Surplus = +0.64 USD -> Met
    breakdown_a = threshold.compute_required_edge(
        trade_size_usd=trade_size_usd,
        known_execution_cost=known_execution_cost,
        gross_edge_usd=Decimal("3.00"),
    )
    assert breakdown_a.known_execution_cost == Decimal("0.80")
    assert breakdown_a.cost_uncertainty_buffer == Decimal("0.16")
    assert breakdown_a.latency_deterioration_buffer == Decimal("0.50")
    assert breakdown_a.inventory_rebalance_buffer == Decimal("0.40")
    assert breakdown_a.minimum_economic_profit == Decimal("0.50")
    assert breakdown_a.required_edge == Decimal("2.36")
    assert breakdown_a.gross_edge == Decimal("3.00")
    assert breakdown_a.net_surplus == Decimal("0.64")
    assert breakdown_a.is_met is True

    # Case B: gross_edge = 2.00 USD -> Surplus = -0.36 USD -> Not Met
    breakdown_b = threshold.compute_required_edge(
        trade_size_usd=trade_size_usd,
        known_execution_cost=known_execution_cost,
        gross_edge_usd=Decimal("2.00"),
    )
    assert breakdown_b.required_edge == Decimal("2.36")
    assert breakdown_b.gross_edge == Decimal("2.00")
    assert breakdown_b.net_surplus == Decimal("-0.36")
    assert breakdown_b.is_met is False


def test_required_edge_formula_size_100_uncertainty_floor() -> None:
    config = load_strategy_spec(CONFIG_PATH)
    threshold = config.primary.threshold

    trade_size_usd = Decimal("100")
    known_execution_cost = Decimal("0.30")

    # Hand calculation:
    # 1. cost_uncertainty = max(0.30 * 0.20 = 0.06, floor = 0.10) = 0.10 USD (floor active)
    # 2. latency_buffer = 100 * (10 / 10000) = 0.10 USD
    # 3. rebalance_buffer = 0.40 USD
    # 4. min_economic_profit = 0.50 USD
    # Total Required Edge = 0.30 + 0.10 + 0.10 + 0.40 + 0.50 = 1.40 USD

    breakdown = threshold.compute_required_edge(
        trade_size_usd=trade_size_usd,
        known_execution_cost=known_execution_cost,
        gross_edge_usd=Decimal("1.50"),
    )
    assert breakdown.cost_uncertainty_buffer == Decimal("0.10")  # floor verified
    assert breakdown.latency_deterioration_buffer == Decimal("0.10")
    assert breakdown.required_edge == Decimal("1.40")
    assert breakdown.net_surplus == Decimal("0.10")
    assert breakdown.is_met is True


# ============================================================================
# 3. Golden Acceptance / Rejection Evaluator Scenarios
# ============================================================================

def test_golden_scenario_clean_accepted_paper_ready() -> None:
    config = load_strategy_spec(CONFIG_PATH)
    signal = _make_signal(
        candidate_id="golden-accept-01",
        buy_input_usd=500,
        gross_edge_usd=Decimal("3.00"),  # > required 2.36 USD
        gas_cost_usd_each_leg=Decimal("0.40"),
        observed_at=NOW_UTC,
        skew_ms=100,
    )
    balance_sheet = _make_balance_sheet()

    decision = evaluate_primary_strategy(
        spec=config.primary,
        signal=signal,
        balance_sheet=balance_sheet,
        evaluated_at=NOW_UTC + timedelta(milliseconds=500),
    )

    assert decision.accepted is True
    assert decision.state == "PAPER_READY"
    assert decision.reject_reasons == ()
    assert decision.threshold_breakdown is not None
    assert decision.threshold_breakdown.is_met is True
    assert decision.threshold_breakdown.net_surplus == Decimal("0.64")
    assert len(decision.raw_refs) == 2


def test_golden_scenario_reject_required_edge_not_met() -> None:
    config = load_strategy_spec(CONFIG_PATH)
    # Gross edge 1.80 USD is positive, but less than required edge 2.36 USD
    signal = _make_signal(
        candidate_id="golden-reject-edge-01",
        buy_input_usd=500,
        gross_edge_usd=Decimal("1.80"),
        gas_cost_usd_each_leg=Decimal("0.40"),
        observed_at=NOW_UTC,
    )
    balance_sheet = _make_balance_sheet()

    decision = evaluate_primary_strategy(
        spec=config.primary,
        signal=signal,
        balance_sheet=balance_sheet,
        evaluated_at=NOW_UTC + timedelta(milliseconds=500),
    )

    assert decision.accepted is False
    assert decision.state == "REJECTED"
    assert StrategyRejectReason.REQUIRED_EDGE_NOT_MET.value in decision.reject_reasons
    assert decision.threshold_breakdown is not None
    assert decision.threshold_breakdown.net_surplus == Decimal("-0.56")


def test_golden_scenario_reject_stale_quote() -> None:
    config = load_strategy_spec(CONFIG_PATH)
    signal = _make_signal(
        candidate_id="golden-reject-stale-01",
        observed_at=NOW_UTC - timedelta(seconds=15),  # 15s old > max 10s
    )
    balance_sheet = _make_balance_sheet()

    decision = evaluate_primary_strategy(
        spec=config.primary,
        signal=signal,
        balance_sheet=balance_sheet,
        evaluated_at=NOW_UTC,
    )

    assert decision.accepted is False
    assert StrategyRejectReason.QUOTE_STALE.value in decision.reject_reasons


def test_golden_scenario_reject_skew_exceeded() -> None:
    config = load_strategy_spec(CONFIG_PATH)
    signal = _make_signal(
        candidate_id="golden-reject-skew-01",
        skew_ms=1500,  # 1.5s skew > max 1.0s
    )
    balance_sheet = _make_balance_sheet()

    decision = evaluate_primary_strategy(
        spec=config.primary,
        signal=signal,
        balance_sheet=balance_sheet,
        evaluated_at=NOW_UTC + timedelta(milliseconds=200),
    )

    assert decision.accepted is False
    assert StrategyRejectReason.LEG_OBSERVATION_SKEW_EXCEEDED.value in decision.reject_reasons


def test_golden_scenario_reject_inventory_insufficient() -> None:
    config = load_strategy_spec(CONFIG_PATH)
    signal = _make_signal(candidate_id="golden-reject-inv-01")
    # Balance sheet with zero Arbitrum WETH
    balance_sheet = _make_balance_sheet(arb_weth_raw=0)

    decision = evaluate_primary_strategy(
        spec=config.primary,
        signal=signal,
        balance_sheet=balance_sheet,
        evaluated_at=NOW_UTC + timedelta(milliseconds=200),
    )

    assert decision.accepted is False
    assert StrategyRejectReason.INVENTORY_BLOCKED.value in decision.reject_reasons
    assert any("INSUFFICIENT_BALANCE:42161:WETH" in r for r in decision.reject_reasons)


def test_golden_scenario_reject_duplicate_opportunity() -> None:
    config = load_strategy_spec(CONFIG_PATH)
    dedup = CandidateDeduplicator(window_seconds=60.0)
    signal1 = _make_signal(candidate_id="golden-dup-01")
    signal2 = _make_signal(candidate_id="golden-dup-02")
    balance_sheet = _make_balance_sheet()

    dec1 = evaluate_primary_strategy(
        spec=config.primary,
        signal=signal1,
        balance_sheet=balance_sheet,
        deduplicator=dedup,
        evaluated_at=NOW_UTC + timedelta(milliseconds=100),
    )
    dec2 = evaluate_primary_strategy(
        spec=config.primary,
        signal=signal2,
        balance_sheet=balance_sheet,
        deduplicator=dedup,
        evaluated_at=NOW_UTC + timedelta(milliseconds=500),
    )

    assert dec1.accepted is True
    assert dec2.accepted is False
    assert StrategyRejectReason.DUPLICATE_OPPORTUNITY.value in dec2.reject_reasons


def test_golden_scenario_reject_unsupported_size() -> None:
    config = load_strategy_spec(CONFIG_PATH)
    # Trade size 250 USD is not in [100, 500, 1000]
    signal = _make_signal(
        candidate_id="golden-reject-size-01",
        buy_input_usd=250,
    )
    balance_sheet = _make_balance_sheet()

    decision = evaluate_primary_strategy(
        spec=config.primary,
        signal=signal,
        balance_sheet=balance_sheet,
        evaluated_at=NOW_UTC + timedelta(milliseconds=200),
    )

    assert decision.accepted is False
    assert StrategyRejectReason.UNSUPPORTED_TARGET_SIZE.value in decision.reject_reasons


def test_golden_scenario_token_registry_exclusion() -> None:
    config = load_strategy_spec(CONFIG_PATH)
    signal = _make_signal(candidate_id="golden-registry-excluded")
    balance_sheet = _make_balance_sheet()

    # Create dummy token registry where Base USDC is excluded
    excluded_usdc = TokenRecord(
        chain_id=8453,
        contract_address="0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
        symbol="USDC",
        decimals=6,
        issuer="Circle",
        classification=TokenClassification.CANONICAL,
        redemption_path="Circle Mint",
        pause_capability=True,
        blacklist_capability=True,
        upgradeability=True,
        haircut_bps=25,
        excluded=True,  # EXCLUDED
        decision_reason="Testing exclusion reject gate",
        source_urls=("https://example.com",),
    )
    normal_weth_base = TokenRecord(
        chain_id=8453,
        contract_address="0x4200000000000000000000000000000000000006",
        symbol="WETH",
        decimals=18,
        issuer="Base",
        classification=TokenClassification.WRAPPED,
        redemption_path="Unwrap",
        pause_capability=False,
        blacklist_capability=False,
        upgradeability=False,
        haircut_bps=5,
        excluded=False,
        decision_reason="Keep",
        source_urls=("https://example.com",),
    )
    normal_usdc_arb = TokenRecord(
        chain_id=42161,
        contract_address="0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
        symbol="USDC",
        decimals=6,
        issuer="Circle",
        classification=TokenClassification.CANONICAL,
        redemption_path="Circle Mint",
        pause_capability=True,
        blacklist_capability=True,
        upgradeability=True,
        haircut_bps=25,
        excluded=False,
        decision_reason="Keep",
        source_urls=("https://example.com",),
    )
    normal_weth_arb = TokenRecord(
        chain_id=42161,
        contract_address="0x82aF49447D8a07e3bd95BD0d56f35241523fBab1",
        symbol="WETH",
        decimals=18,
        issuer="Arbitrum",
        classification=TokenClassification.BRIDGED,
        redemption_path="Withdraw",
        pause_capability=False,
        blacklist_capability=False,
        upgradeability=True,
        haircut_bps=50,
        excluded=False,
        decision_reason="Keep",
        source_urls=("https://example.com",),
    )

    registry = TokenRegistry(
        schema_version=1,
        mode="paper",
        reviewed_at=NOW_UTC,
        tokens=(excluded_usdc, normal_weth_base, normal_usdc_arb, normal_weth_arb),
    )

    decision = evaluate_primary_strategy(
        spec=config.primary,
        signal=signal,
        balance_sheet=balance_sheet,
        token_registry=registry,
        evaluated_at=NOW_UTC + timedelta(milliseconds=200),
    )

    assert decision.accepted is False
    assert StrategyRejectReason.TOKEN_EXCLUDED.value in decision.reject_reasons


# ============================================================================
# 4. Strict Determinism Check
# ============================================================================

def test_evaluation_strict_determinism() -> None:
    config = load_strategy_spec(CONFIG_PATH)
    signal = _make_signal(candidate_id="deterministic-01")
    balance_sheet = _make_balance_sheet()

    results = [
        evaluate_primary_strategy(
            spec=config.primary,
            signal=signal,
            balance_sheet=balance_sheet,
            evaluated_at=NOW_UTC + timedelta(milliseconds=300),
        )
        for _ in range(10)
    ]

    first = results[0]
    for other in results[1:]:
        assert other.accepted == first.accepted
        assert other.state == first.state
        assert other.reject_reasons == first.reject_reasons
        assert other.threshold_breakdown == first.threshold_breakdown
        assert other.raw_refs == first.raw_refs
