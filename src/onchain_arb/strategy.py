"""Primary strategy specification, threshold models, configuration validation, and decision engine."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
import re
import tomllib
from typing import Any, Mapping

from onchain_arb.decision import CandidateRejectReason
from onchain_arb.inventory import (
    CrossChainSignal,
    InventoryEvaluation,
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
    TokenDelta,
    TokenRef,
    _require_utc,
)
from onchain_arb.scanner import CandidateDeduplicator
from onchain_arb.token_registry import TokenRegistry, load_token_registry


class StrategyId(StrEnum):
    """The canonical identifier for strategy specifications in the research repo."""

    H1_CROSS_CHAIN_INVENTORY = "H1_CROSS_CHAIN_INVENTORY"
    H2_SAME_CHAIN_BASELINE = "H2_SAME_CHAIN_BASELINE"


class StrategyRejectReason(StrEnum):
    """Strategy-specific reject reasons supplementing scanner candidate reasons."""

    # Timing & Freshness
    QUOTE_STALE = "quote_stale"
    LEG_OBSERVATION_SKEW_EXCEEDED = "leg_observation_skew_exceeded"
    REQUOTE_TIMEOUT = "requote_timeout"
    DUPLICATE_OPPORTUNITY = "duplicate_opportunity"

    # Token Identity & Universe
    UNSUPPORTED_CHAIN = "unsupported_chain"
    UNSUPPORTED_ASSET = "unsupported_asset"
    TOKEN_IDENTITY_MISMATCH = "token_identity_mismatch"
    TOKEN_EXCLUDED = "token_excluded"
    UNSUPPORTED_TARGET_SIZE = "unsupported_target_size"

    # Threshold & Economic Edge
    INITIAL_GROSS_NOT_POSITIVE = "initial_gross_not_positive"
    REQUOTE_GROSS_NOT_POSITIVE = "requote_gross_not_positive"
    REQUOTE_MINIMUM_NOT_POSITIVE = "requote_minimum_not_positive"
    COST_LEDGER_INCOMPLETE = "cost_ledger_incomplete"
    REQUIRED_EDGE_NOT_MET = "required_edge_not_met"

    # Inventory & Rebalance
    INVENTORY_BLOCKED = "inventory_blocked"
    INSUFFICIENT_BALANCE = "insufficient_balance"
    MAX_IMBALANCE_EXCEEDED = "max_imbalance_exceeded"

    # Independent Confirmation
    SAME_REQUEST_ID_COLLISION = "same_request_id_collision"
    SAME_RAW_REF_COLLISION = "same_raw_ref_collision"


@dataclass(frozen=True, slots=True)
class ThresholdBreakdown:
    """Complete, reviewable decomposition of the Required Edge entry threshold."""

    known_execution_cost: Decimal
    cost_uncertainty_buffer: Decimal
    latency_deterioration_buffer: Decimal
    inventory_rebalance_buffer: Decimal
    minimum_economic_profit: Decimal
    required_edge: Decimal
    gross_edge: Decimal
    net_surplus: Decimal
    is_met: bool

    def __post_init__(self) -> None:
        for field_name in (
            "known_execution_cost",
            "cost_uncertainty_buffer",
            "latency_deterioration_buffer",
            "inventory_rebalance_buffer",
            "minimum_economic_profit",
            "required_edge",
            "gross_edge",
            "net_surplus",
        ):
            val = getattr(self, field_name)
            if not isinstance(val, Decimal) or not val.is_finite():
                raise TypeError(f"{field_name} must be a finite Decimal")


@dataclass(frozen=True, slots=True)
class ThresholdConfig:
    """Mathematical parameterization for the Day 16 Required Edge hurdle."""

    cost_uncertainty_pct: Decimal
    cost_uncertainty_floor_usd: Decimal
    latency_buffer_bps: Decimal
    rebalance_buffer_usd: Decimal
    min_economic_profit_usd: Decimal

    def __post_init__(self) -> None:
        for name in (
            "cost_uncertainty_pct",
            "cost_uncertainty_floor_usd",
            "latency_buffer_bps",
            "rebalance_buffer_usd",
            "min_economic_profit_usd",
        ):
            val = getattr(self, name)
            if not isinstance(val, Decimal) or not val.is_finite():
                raise TypeError(f"{name} must be a finite Decimal")
            if val < 0:
                raise ValueError(f"{name} must be non-negative")

    def compute_required_edge(
        self,
        *,
        trade_size_usd: Decimal,
        known_execution_cost: Decimal,
        gross_edge_usd: Decimal,
    ) -> ThresholdBreakdown:
        """Compute each buffer and the final Required Edge according to the spec."""
        if not isinstance(trade_size_usd, Decimal) or trade_size_usd <= 0:
            raise ValueError("trade_size_usd must be a positive Decimal")
        if not isinstance(known_execution_cost, Decimal) or known_execution_cost < 0:
            raise ValueError("known_execution_cost must be a non-negative Decimal")
        if not isinstance(gross_edge_usd, Decimal) or not gross_edge_usd.is_finite():
            raise ValueError("gross_edge_usd must be a finite Decimal")

        # 1. Cost Uncertainty Buffer = max(known_cost * uncertainty_pct, uncertainty_floor)
        cost_uncertainty = max(
            known_execution_cost * self.cost_uncertainty_pct,
            self.cost_uncertainty_floor_usd,
        )

        # 2. Latency Deterioration Buffer = trade_size_usd * (latency_buffer_bps / 10000)
        latency_buffer = trade_size_usd * (self.latency_buffer_bps / Decimal("10000"))

        # 3. Inventory / Rebalance Buffer = fixed amortized allowance
        rebalance_buffer = self.rebalance_buffer_usd

        # 4. Minimum Economic Profit = fixed hurdle
        min_profit = self.min_economic_profit_usd

        # Total Required Edge
        required_edge = (
            known_execution_cost
            + cost_uncertainty
            + latency_buffer
            + rebalance_buffer
            + min_profit
        )

        net_surplus = gross_edge_usd - required_edge
        is_met = gross_edge_usd >= required_edge

        return ThresholdBreakdown(
            known_execution_cost=known_execution_cost,
            cost_uncertainty_buffer=cost_uncertainty,
            latency_deterioration_buffer=latency_buffer,
            inventory_rebalance_buffer=rebalance_buffer,
            minimum_economic_profit=min_profit,
            required_edge=required_edge,
            gross_edge=gross_edge_usd,
            net_surplus=net_surplus,
            is_met=is_met,
        )


@dataclass(frozen=True, slots=True)
class TimingConfig:
    """Timing, skew, freshness, and cooldown constraints."""

    max_quote_age_ms: int
    max_leg_skew_ms: int
    requote_window_ms: int
    dedup_window_seconds: float

    def __post_init__(self) -> None:
        if self.max_quote_age_ms <= 0:
            raise ValueError("max_quote_age_ms must be positive")
        if self.max_leg_skew_ms <= 0:
            raise ValueError("max_leg_skew_ms must be positive")
        if self.requote_window_ms <= 0:
            raise ValueError("requote_window_ms must be positive")
        if self.dedup_window_seconds < 0:
            raise ValueError("dedup_window_seconds must be non-negative")


@dataclass(frozen=True, slots=True)
class KillMetricsConfig:
    """Circuit-breaker thresholds for paper engine and stress testing."""

    max_consecutive_losses: int
    min_requote_survival_rate: Decimal
    max_balance_drift_pct: Decimal
    max_gas_multiplier: Decimal

    def __post_init__(self) -> None:
        if self.max_consecutive_losses <= 0:
            raise ValueError("max_consecutive_losses must be positive")
        if not isinstance(self.min_requote_survival_rate, Decimal) or not (
            Decimal(0) <= self.min_requote_survival_rate <= Decimal(1)
        ):
            raise ValueError("min_requote_survival_rate must be a Decimal between 0 and 1")
        if not isinstance(self.max_balance_drift_pct, Decimal) or not (
            Decimal(0) <= self.max_balance_drift_pct <= Decimal(1)
        ):
            raise ValueError("max_balance_drift_pct must be a Decimal between 0 and 1")
        if not isinstance(self.max_gas_multiplier, Decimal) or self.max_gas_multiplier <= 0:
            raise ValueError("max_gas_multiplier must be a positive Decimal")


@dataclass(frozen=True, slots=True)
class PrimaryStrategySpec:
    """Unambiguous specification of H1: Cross-chain pre-positioned inventory arbitrage."""

    strategy_id: StrategyId
    name: str
    mode: str
    chains: tuple[int, ...]
    stable_asset_id: str
    trade_asset_id: str
    target_sizes_usd: tuple[Decimal, ...]
    tokens: tuple[TokenRef, ...]
    timing: TimingConfig
    threshold: ThresholdConfig
    kill_metrics: KillMetricsConfig
    rebalance_threshold_usd: Decimal
    max_inventory_imbalance_usd: Decimal

    def __post_init__(self) -> None:
        if self.strategy_id is not StrategyId.H1_CROSS_CHAIN_INVENTORY:
            raise ValueError("primary strategy must be H1_CROSS_CHAIN_INVENTORY")
        if self.mode != "paper":
            raise ValueError("mode must be paper")
        if len(self.chains) != 2:
            raise ValueError("primary cross-chain strategy requires exactly two chains")
        if not self.target_sizes_usd:
            raise ValueError("target_sizes_usd cannot be empty")
        for size in self.target_sizes_usd:
            if not isinstance(size, Decimal) or size <= 0:
                raise ValueError("all target_sizes_usd must be positive Decimals")
        if not self.tokens:
            raise ValueError("tokens cannot be empty")
        if not isinstance(self.rebalance_threshold_usd, Decimal) or self.rebalance_threshold_usd <= 0:
            raise ValueError("rebalance_threshold_usd must be a positive Decimal")
        if not isinstance(self.max_inventory_imbalance_usd, Decimal) or self.max_inventory_imbalance_usd <= 0:
            raise ValueError("max_inventory_imbalance_usd must be a positive Decimal")


@dataclass(frozen=True, slots=True)
class BackupStrategySpec:
    """Read-only negative control specification of H2: Same-chain DEX-DEX baseline."""

    strategy_id: StrategyId
    name: str
    mode: str
    chain_id: int
    pair: str
    venues: tuple[str, ...]
    read_only_description: str

    def __post_init__(self) -> None:
        if self.strategy_id is not StrategyId.H2_SAME_CHAIN_BASELINE:
            raise ValueError("backup strategy must be H2_SAME_CHAIN_BASELINE")
        if not self.read_only_description:
            raise ValueError("read_only_description is required")


@dataclass(frozen=True, slots=True)
class StrategyConfig:
    """Complete frozen configuration containing primary and backup strategy specifications."""

    schema_version: int
    reviewed_at: datetime
    primary: PrimaryStrategySpec
    backup: BackupStrategySpec

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("unsupported strategy schema_version")
        _require_utc(self.reviewed_at, "reviewed_at")


@dataclass(frozen=True, slots=True)
class StrategyDecisionRecord:
    """Auditable result of evaluating a cross-chain candidate under the primary strategy."""

    candidate_id: str
    strategy_id: StrategyId
    accepted: bool
    state: str
    reject_reasons: tuple[str, ...]
    threshold_breakdown: ThresholdBreakdown | None
    target_size: TokenAmount
    evaluated_at: datetime
    raw_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.candidate_id:
            raise ValueError("candidate_id is required")
        if self.accepted and self.reject_reasons:
            raise ValueError("accepted decision cannot have reject reasons")
        if not self.accepted and not self.reject_reasons:
            raise ValueError("rejected decision must provide reject reasons")
        _require_utc(self.evaluated_at, "evaluated_at")


def _check_no_tbd(val: Any, path: str = "root") -> None:
    """Recursively enforce that no placeholder/TBD string exists in the configuration."""
    if isinstance(val, str):
        cleaned = val.strip().upper()
        if (
            cleaned.startswith("TBD")
            or cleaned.startswith("TODO")
            or cleaned.startswith("FIXME")
            or "TBD_" in cleaned
            or cleaned == "UNCONFIGURED"
        ):
            raise ValueError(
                f"Strategy config contains unpopulated placeholder at {path}: {val!r}"
            )
    elif isinstance(val, dict):
        for k, v in val.items():
            _check_no_tbd(v, f"{path}.{k}")
    elif isinstance(val, list):
        for idx, item in enumerate(val):
            _check_no_tbd(item, f"{path}[{idx}]")


def load_strategy_spec(path: str | Path) -> StrategyConfig:
    """Load and validate `config/strategy.toml` with strict schema and anti-TBD checks."""
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"Strategy config file not found: {file_path}")

    with file_path.open("rb") as f:
        data = tomllib.load(f)

    if not isinstance(data, dict):
        raise TypeError("Strategy config must be a TOML table")

    # Anti-TBD check across the entire TOML document
    _check_no_tbd(data, "strategy")

    # Validate document-level fields
    schema_version = data.get("schema_version")
    if schema_version != 1:
        raise ValueError(f"Unsupported schema_version: {schema_version}")

    raw_reviewed_at = data.get("reviewed_at")
    if not isinstance(raw_reviewed_at, str):
        raise TypeError("reviewed_at must be an ISO-8601 timestamp string")
    try:
        reviewed_at = datetime.fromisoformat(raw_reviewed_at.replace("Z", "+00:00"))
    except ValueError as err:
        raise ValueError(f"Invalid reviewed_at format: {raw_reviewed_at}") from err

    # Parse primary strategy
    primary_data = data.get("primary")
    if not isinstance(primary_data, dict):
        raise TypeError("primary section is required and must be a table")

    timing_data = primary_data.get("timing")
    if not isinstance(timing_data, dict):
        raise TypeError("primary.timing table is required")
    timing = TimingConfig(
        max_quote_age_ms=int(timing_data["max_quote_age_ms"]),
        max_leg_skew_ms=int(timing_data["max_leg_skew_ms"]),
        requote_window_ms=int(timing_data["requote_window_ms"]),
        dedup_window_seconds=float(timing_data["dedup_window_seconds"]),
    )

    threshold_data = primary_data.get("threshold")
    if not isinstance(threshold_data, dict):
        raise TypeError("primary.threshold table is required")
    threshold = ThresholdConfig(
        cost_uncertainty_pct=Decimal(str(threshold_data["cost_uncertainty_pct"])),
        cost_uncertainty_floor_usd=Decimal(str(threshold_data["cost_uncertainty_floor_usd"])),
        latency_buffer_bps=Decimal(str(threshold_data["latency_buffer_bps"])),
        rebalance_buffer_usd=Decimal(str(threshold_data["rebalance_buffer_usd"])),
        min_economic_profit_usd=Decimal(str(threshold_data["min_economic_profit_usd"])),
    )

    kill_data = primary_data.get("kill_metrics")
    if not isinstance(kill_data, dict):
        raise TypeError("primary.kill_metrics table is required")
    kill_metrics = KillMetricsConfig(
        max_consecutive_losses=int(kill_data["max_consecutive_losses"]),
        min_requote_survival_rate=Decimal(str(kill_data["min_requote_survival_rate"])),
        max_balance_drift_pct=Decimal(str(kill_data["max_balance_drift_pct"])),
        max_gas_multiplier=Decimal(str(kill_data["max_gas_multiplier"])),
    )

    raw_tokens = primary_data.get("tokens", [])
    if not isinstance(raw_tokens, list) or not raw_tokens:
        raise TypeError("primary.tokens must be a non-empty list")
    tokens = tuple(
        TokenRef(
            chain_id=int(t["chain_id"]),
            contract_address=str(t["contract_address"]),
            symbol=str(t["symbol"]),
            decimals=int(t["decimals"]),
        )
        for t in raw_tokens
    )

    raw_sizes = primary_data.get("target_sizes_usd", [])
    target_sizes_usd = tuple(Decimal(str(s)) for s in raw_sizes)

    raw_chains = primary_data.get("chains", [])
    chains = tuple(int(c) for c in raw_chains)

    primary = PrimaryStrategySpec(
        strategy_id=StrategyId(primary_data["strategy_id"]),
        name=str(primary_data["name"]),
        mode=str(primary_data["mode"]),
        chains=chains,
        stable_asset_id=str(primary_data["stable_asset_id"]),
        trade_asset_id=str(primary_data["trade_asset_id"]),
        target_sizes_usd=target_sizes_usd,
        tokens=tokens,
        timing=timing,
        threshold=threshold,
        kill_metrics=kill_metrics,
        rebalance_threshold_usd=Decimal(str(primary_data["rebalance_threshold_usd"])),
        max_inventory_imbalance_usd=Decimal(str(primary_data["max_inventory_imbalance_usd"])),
    )

    # Parse backup strategy
    backup_data = data.get("backup")
    if not isinstance(backup_data, dict):
        raise TypeError("backup section is required and must be a table")

    backup = BackupStrategySpec(
        strategy_id=StrategyId(backup_data["strategy_id"]),
        name=str(backup_data["name"]),
        mode=str(backup_data["mode"]),
        chain_id=int(backup_data["chain_id"]),
        pair=str(backup_data["pair"]),
        venues=tuple(str(v) for v in backup_data.get("venues", [])),
        read_only_description=str(backup_data["read_only_description"]),
    )

    return StrategyConfig(
        schema_version=schema_version,
        reviewed_at=reviewed_at,
        primary=primary,
        backup=backup,
    )


def evaluate_primary_strategy(
    spec: PrimaryStrategySpec,
    signal: CrossChainSignal,
    balance_sheet: VirtualBalanceSheet,
    *,
    refreshed_signal: CrossChainSignal | None = None,
    deduplicator: CandidateDeduplicator | None = None,
    evaluated_at: datetime | None = None,
    token_registry: TokenRegistry | None = None,
) -> StrategyDecisionRecord:
    """Evaluate a cross-chain arbitrage signal against the complete Day 16 strategy specification."""

    active_signal = refreshed_signal or signal
    now_utc = evaluated_at or datetime.now(UTC)
    _require_utc(now_utc, "evaluated_at")

    buy = active_signal.cheap_chain_buy
    sell = active_signal.expensive_chain_sell
    target_size = buy.input_amount
    trade_size_usd = target_size.decimal_amount

    raw_refs = [
        signal.cheap_chain_buy.raw_ref,
        signal.expensive_chain_sell.raw_ref,
    ]
    if refreshed_signal is not None:
        raw_refs.extend([
            refreshed_signal.cheap_chain_buy.raw_ref,
            refreshed_signal.expensive_chain_sell.raw_ref,
        ])
    deduped_raw_refs = tuple(dict.fromkeys(filter(bool, raw_refs)))

    reasons: list[str] = []

    # 1. Independent Confirmation Check (No collisions)
    if buy.request_id == sell.request_id:
        reasons.append(StrategyRejectReason.SAME_REQUEST_ID_COLLISION.value)
    if buy.raw_ref == sell.raw_ref:
        reasons.append(StrategyRejectReason.SAME_RAW_REF_COLLISION.value)

    # 2. Token Identity & Universe Check
    configured_token_keys = {(t.chain_id, t.contract_address.lower()) for t in spec.tokens}
    buy_token_key = (buy.input_amount.token.chain_id, buy.input_amount.token.contract_address.lower())
    sell_token_key = (sell.minimum_output_amount.token.chain_id, sell.minimum_output_amount.token.contract_address.lower())

    if buy_token_key not in configured_token_keys or sell_token_key not in configured_token_keys:
        reasons.append(StrategyRejectReason.TOKEN_IDENTITY_MISMATCH.value)

    if buy.input_amount.token.chain_id not in spec.chains or sell.input_amount.token.chain_id not in spec.chains:
        reasons.append(StrategyRejectReason.UNSUPPORTED_CHAIN.value)

    if token_registry is not None:
        try:
            rec_buy = token_registry.get(buy.input_amount.token.chain_id, buy.input_amount.token.contract_address)
            rec_sell = token_registry.get(sell.minimum_output_amount.token.chain_id, sell.minimum_output_amount.token.contract_address)
            if rec_buy.excluded or rec_sell.excluded:
                reasons.append(StrategyRejectReason.TOKEN_EXCLUDED.value)
        except KeyError:
            reasons.append(StrategyRejectReason.TOKEN_IDENTITY_MISMATCH.value)

    # 3. Target Size Check
    if trade_size_usd not in spec.target_sizes_usd:
        reasons.append(StrategyRejectReason.UNSUPPORTED_TARGET_SIZE.value)

    # 4. Freshness Gate (Quote Age)
    max_quote_age = timedelta(milliseconds=spec.timing.max_quote_age_ms)
    if (now_utc - buy.observed_at > max_quote_age) or (now_utc - sell.observed_at > max_quote_age):
        reasons.append(StrategyRejectReason.QUOTE_STALE.value)

    # 5. Leg Observation Skew Gate
    max_skew = timedelta(milliseconds=spec.timing.max_leg_skew_ms)
    if active_signal.leg_skew > max_skew:
        reasons.append(StrategyRejectReason.LEG_OBSERVATION_SKEW_EXCEEDED.value)

    # 6. Deduplication Gate
    if deduplicator is not None:
        fp = (
            f"cross_chain:{buy.input_amount.token.chain_id}:{sell.input_amount.token.chain_id}:"
            f"{active_signal.stable_asset_id}:{active_signal.trade_asset_id}:{target_size.raw_amount}"
        )
        if deduplicator.is_duplicate(fp, active_signal.condition_locked_at):
            reasons.append(StrategyRejectReason.DUPLICATE_OPPORTUNITY.value)
        else:
            deduplicator.record(fp, active_signal.condition_locked_at)

    # 7. Gross Edge Gate (Must be positive based on guaranteed minimum output)
    gross_raw = sell.minimum_output_amount.raw_amount - buy.input_amount.raw_amount
    gross_edge_usd = Decimal(gross_raw).scaleb(-buy.input_amount.token.decimals)
    if gross_raw <= 0:
        reasons.append(StrategyRejectReason.INITIAL_GROSS_NOT_POSITIVE.value)

    # 8. Known Execution Costs
    known_cost_raw = sum(
        c.amount.raw_amount
        for c in active_signal.costs
        if not c.included_in_quote_output and c.scope is CostScope.ATOMIC
    )
    known_execution_cost = Decimal(known_cost_raw).scaleb(-buy.input_amount.token.decimals)

    # 9. Required Edge Threshold Gate
    threshold_breakdown = spec.threshold.compute_required_edge(
        trade_size_usd=trade_size_usd,
        known_execution_cost=known_execution_cost,
        gross_edge_usd=gross_edge_usd,
    )
    if not threshold_breakdown.is_met:
        reasons.append(StrategyRejectReason.REQUIRED_EDGE_NOT_MET.value)

    # 10. Inventory & Balance Sheet Gate
    inv_eval = evaluate_inventory(active_signal, balance_sheet)
    if not inv_eval.accepted:
        reasons.append(StrategyRejectReason.INVENTORY_BLOCKED.value)
        reasons.extend(inv_eval.reject_reasons)

    ordered_reasons = tuple(dict.fromkeys(reasons))
    accepted = len(ordered_reasons) == 0

    return StrategyDecisionRecord(
        candidate_id=active_signal.candidate_id,
        strategy_id=spec.strategy_id,
        accepted=accepted,
        state="PAPER_READY" if accepted else "REJECTED",
        reject_reasons=ordered_reasons,
        threshold_breakdown=threshold_breakdown,
        target_size=target_size,
        evaluated_at=now_utc,
        raw_refs=deduped_raw_refs,
    )
