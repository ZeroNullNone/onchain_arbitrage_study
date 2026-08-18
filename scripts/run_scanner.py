"""Run Scanner v1 pipeline over scenarios or recorded quote evidence and persist report."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import json
from pathlib import Path
import sys

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
from onchain_arb.requote import (
    ApprovalStatus,
    DirectQuote,
    RoundTripQuotes,
)
from onchain_arb.scanner import (
    CrossChainScanAttempt,
    SameChainScanAttempt,
    ScannerPipeline,
    persist_scanner_report,
)
from onchain_arb.simulation import load_raw_simulation

BASE_USDC = TokenRef(8453, "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913", "USDC", 6)
BASE_WETH = TokenRef(8453, "0x4200000000000000000000000000000000000006", "WETH", 18)
ARB_USDC = TokenRef(42161, "0xaf88d065e77c8cC2239327C5EDb3A432268e5831", "USDC", 6)
ARB_WETH = TokenRef(42161, "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1", "WETH", 18)


def _cost(token: TokenRef, kind: str, raw_amount: int, observed_at: datetime) -> CostItem:
    return CostItem(
        kind=kind,
        amount=TokenAmount(token, raw_amount),
        scope=CostScope.ATOMIC,
        included_in_quote_output=False,
        confidence=CostConfidence.ESTIMATED,
        source="scanner_cli",
        observed_at=observed_at,
    )


def _load_scenario_attempts(fixture_path: Path, sim_dir: Path) -> list[SameChainScanAttempt | CrossChainScanAttempt]:
    data = json.loads(fixture_path.read_text())
    base_time = datetime.fromisoformat(data["generated_at"].replace("Z", "+00:00"))
    attempts: list[SameChainScanAttempt | CrossChainScanAttempt] = []

    for index, item in enumerate(data.get("scenarios", [])):
        observed_at = base_time + timedelta(seconds=index * 15)
        cid = item["candidate_id"]
        ctype = item["type"]

        if ctype == "same_chain":
            size_usdc = Decimal(str(item["size_usdc"]))
            size_raw = int(size_usdc * 1_000_000)
            initial_final_usdc = Decimal(str(item["initial_output_usdc"]))
            initial_final_raw = int(initial_final_usdc * 1_000_000)
            initial_min_raw = int(initial_final_raw * 0.998)
            gas_raw = int(Decimal(str(item.get("gas_per_leg_usdc", 0.25))) * 1_000_000)

            # Leg 1: USDC -> WETH
            weth_out_raw = 52_000_000_000_000_000_000  # 0.052 WETH
            weth_min_raw = 51_000_000_000_000_000_000  # 0.051 WETH

            leg1_init = DirectQuote(
                quote_id=f"{cid}-init-l1",
                request_id=f"req-{cid}-init-l1",
                raw_ref=f"{fixture_path}#{cid}-init-l1",
                venue=item["venue_buy"],
                input_amount=TokenAmount(BASE_USDC, size_raw),
                output_amount=TokenAmount(BASE_WETH, weth_out_raw),
                minimum_output_amount=TokenAmount(BASE_WETH, weth_min_raw),
                fee_amount=TokenAmount(BASE_USDC, size_raw * 30 // 10_000),
                gas_cost=_cost(BASE_USDC, f"gas_{item['venue_buy']}", gas_raw, observed_at),
                approval_status=ApprovalStatus.NOT_REQUIRED,
                approval_cost=None,
                observed_at=observed_at,
                latency_ms=Decimal("12.0"),
            )
            leg2_init = DirectQuote(
                quote_id=f"{cid}-init-l2",
                request_id=f"req-{cid}-init-l2",
                raw_ref=f"{fixture_path}#{cid}-init-l2",
                venue=item["venue_sell"],
                input_amount=TokenAmount(BASE_WETH, weth_min_raw),
                output_amount=TokenAmount(BASE_USDC, initial_final_raw),
                minimum_output_amount=TokenAmount(BASE_USDC, initial_min_raw),
                fee_amount=TokenAmount(BASE_WETH, weth_min_raw * 30 // 10_000),
                gas_cost=_cost(BASE_USDC, f"gas_{item['venue_sell']}", gas_raw, observed_at + timedelta(milliseconds=20)),
                approval_status=ApprovalStatus.NOT_REQUIRED,
                approval_cost=None,
                observed_at=observed_at + timedelta(milliseconds=20),
                latency_ms=Decimal("12.0"),
            )
            initial = RoundTripQuotes(leg1_init, leg2_init)

            refreshed = None
            if item.get("has_requote", True):
                ref_final_usdc = Decimal(str(item.get("refreshed_output_usdc", item["initial_output_usdc"])))
                ref_final_raw = int(ref_final_usdc * 1_000_000)
                ref_min_usdc = Decimal(str(item.get("refreshed_min_output_usdc", ref_final_usdc * Decimal("0.998"))))
                ref_min_raw = int(ref_min_usdc * 1_000_000)
                leg1_ref = DirectQuote(
                    quote_id=f"{cid}-ref-l1",
                    request_id=f"req-{cid}-ref-l1",
                    raw_ref=f"{fixture_path}#{cid}-ref-l1",
                    venue=item["venue_buy"],
                    input_amount=TokenAmount(BASE_USDC, size_raw),
                    output_amount=TokenAmount(BASE_WETH, weth_out_raw),
                    minimum_output_amount=TokenAmount(BASE_WETH, weth_min_raw),
                    fee_amount=TokenAmount(BASE_USDC, size_raw * 30 // 10_000),
                    gas_cost=_cost(BASE_USDC, f"gas_{item['venue_buy']}", gas_raw, observed_at + timedelta(seconds=1)),
                    approval_status=ApprovalStatus.NOT_REQUIRED,
                    approval_cost=None,
                    observed_at=observed_at + timedelta(seconds=1),
                    latency_ms=Decimal("12.0"),
                )
                leg2_ref = DirectQuote(
                    quote_id=f"{cid}-ref-l2",
                    request_id=f"req-{cid}-ref-l2",
                    raw_ref=f"{fixture_path}#{cid}-ref-l2",
                    venue=item["venue_sell"],
                    input_amount=TokenAmount(BASE_WETH, weth_min_raw),
                    output_amount=TokenAmount(BASE_USDC, ref_final_raw),
                    minimum_output_amount=TokenAmount(BASE_USDC, ref_min_raw),
                    fee_amount=TokenAmount(BASE_WETH, weth_min_raw * 30 // 10_000),
                    gas_cost=_cost(BASE_USDC, f"gas_{item['venue_sell']}", gas_raw, observed_at + timedelta(seconds=1, milliseconds=20)),
                    approval_status=ApprovalStatus.NOT_REQUIRED,
                    approval_cost=None,
                    observed_at=observed_at + timedelta(seconds=1, milliseconds=20),
                    latency_ms=Decimal("12.0"),
                )
                refreshed = RoundTripQuotes(leg1_ref, leg2_ref)

            sim = None
            sim_status = item.get("sim_status")
            if sim_status == "success":
                sim = load_raw_simulation(sim_dir / "day13_success.json")
            elif sim_status == "revert":
                sim = load_raw_simulation(sim_dir / "day13_min_output_revert.json")
            elif sim_status == "allowance_reject":
                sim = load_raw_simulation(sim_dir / "day13_allowance_reject.json")

            attempts.append(
                SameChainScanAttempt(
                    candidate_id=cid,
                    initial=initial,
                    refreshed=refreshed,
                    simulation=sim,
                    detected_at=observed_at,
                    expiry_at=observed_at + timedelta(seconds=15),
                )
            )

        elif ctype == "cross_chain":
            buy_input_raw = int(Decimal(str(item["buy_input_usdc"])) * 1_000_000)
            sell_min_raw = int(Decimal(str(item["sell_min_output_usdc"])) * 1_000_000)
            weth_amount_raw = 500_000_000_000_000_000  # 0.5 WETH

            buy_leg = InventoryLeg(
                request_id=f"req-buy-{cid}",
                raw_ref=f"{fixture_path}#{cid}-buy",
                input_amount=TokenAmount(BASE_USDC, buy_input_raw),
                minimum_output_amount=TokenAmount(BASE_WETH, weth_amount_raw),
                observed_at=observed_at,
            )
            sell_leg = InventoryLeg(
                request_id=f"req-sell-{cid}",
                raw_ref=f"{fixture_path}#{cid}-sell",
                input_amount=TokenAmount(ARB_WETH, weth_amount_raw),
                minimum_output_amount=TokenAmount(ARB_USDC, sell_min_raw),
                observed_at=observed_at + timedelta(milliseconds=500),
            )
            cost_raw = int(Decimal(str(item.get("atomic_costs_usdc", 1.5))) * 500_000)
            costs = (
                _cost(BASE_USDC, "cheap_gas", cost_raw, observed_at),
                _cost(ARB_USDC, "expensive_gas", cost_raw, observed_at),
            )
            signal = CrossChainSignal(
                candidate_id=cid,
                stable_asset_id="USDC",
                trade_asset_id="WETH",
                cheap_chain_buy=buy_leg,
                expensive_chain_sell=sell_leg,
                costs=costs,
                required_cost_kinds=frozenset({"cheap_gas", "expensive_gas"}),
                max_leg_skew=timedelta(seconds=2),
                capital_lock_hours=Decimal("1.0"),
            )

            # Inventory setup
            inv_status = item.get("inventory_status", "sufficient")
            arb_weth_bal = 0 if inv_status == "insufficient_balance" else 20_000_000_000_000_000_000
            balance_sheet = VirtualBalanceSheet(
                positions=(
                    InventoryPosition(
                        asset_id="USDC",
                        balance=TokenAmount(BASE_USDC, 50_000_000_000),
                        target_minimum=TokenAmount(BASE_USDC, 10_000_000_000),
                        target_maximum=TokenAmount(BASE_USDC, 100_000_000_000),
                        max_imbalance=TokenAmount(BASE_USDC, 45_000_000_000),
                        accounting_price=Decimal("1.0"),
                    ),
                    InventoryPosition(
                        asset_id="WETH",
                        balance=TokenAmount(BASE_WETH, 20_000_000_000_000_000_000),
                        target_minimum=TokenAmount(BASE_WETH, 5_000_000_000_000_000_000),
                        target_maximum=TokenAmount(BASE_WETH, 50_000_000_000_000_000_000),
                        max_imbalance=TokenAmount(BASE_WETH, 20_000_000_000_000_000_000),
                        accounting_price=Decimal("2000.0"),
                    ),
                    InventoryPosition(
                        asset_id="USDC",
                        balance=TokenAmount(ARB_USDC, 50_000_000_000),
                        target_minimum=TokenAmount(ARB_USDC, 10_000_000_000),
                        target_maximum=TokenAmount(ARB_USDC, 100_000_000_000),
                        max_imbalance=TokenAmount(ARB_USDC, 45_000_000_000),
                        accounting_price=Decimal("1.0"),
                    ),
                    InventoryPosition(
                        asset_id="WETH",
                        balance=TokenAmount(ARB_WETH, arb_weth_bal),
                        target_minimum=TokenAmount(ARB_WETH, 5_000_000_000_000_000_000),
                        target_maximum=TokenAmount(ARB_WETH, 50_000_000_000_000_000_000),
                        max_imbalance=TokenAmount(ARB_WETH, 20_000_000_000_000_000_000),
                        accounting_price=Decimal("2000.0"),
                    ),
                ),
                observed_at=observed_at,
            )

            attempts.append(
                CrossChainScanAttempt(
                    candidate_id=cid,
                    signal=signal,
                    refreshed_signal=signal,
                    balance_sheet=balance_sheet,
                    detected_at=observed_at,
                    expiry_at=observed_at + timedelta(seconds=30),
                )
            )

    return attempts


def main() -> None:
    parser = argparse.ArgumentParser(description="Scanner v1 Pipeline CLI")
    parser.add_argument(
        "--fixture",
        type=Path,
        default=Path("tests/fixtures/scanner/day14_scenarios.json"),
        help="Path to scenarios fixture",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/derived/scanner"),
        help="Directory to save scanner reports",
    )
    args = parser.parse_args()

    fixture_path = args.fixture.resolve()
    if not fixture_path.exists():
        print(f"Error: fixture path {fixture_path} not found.", file=sys.stderr)
        sys.exit(1)

    sim_dir = Path("tests/fixtures/simulation").resolve()
    attempts = _load_scenario_attempts(fixture_path, sim_dir)

    pipeline = ScannerPipeline(dedup_window_seconds=0.0)
    report = pipeline.scan(attempts)
    saved_path = persist_scanner_report(report, args.output_dir.resolve())

    # Print summary
    m = report.metrics
    print("\n=================== SCANNER v1 REPORT ===================")
    print(f"Generated at: {report.generated_at.isoformat()}")
    print(f"Report path : {saved_path}")
    print(f"Total Scanned: {m.total_detected} (Evaluated: {m.evaluated_count}, Duplicates: {m.duplicates_filtered})")
    print(f"Sample Status: {'SPARSE (<20 samples)' if m.is_sparse else 'SUFFICIENT'}")
    print("---------------------------------------------------------")
    print("FUNNEL METRICS:")
    print(f"  - Re-quote Survivors      : {m.requote_survivors}/{m.total_detected} ({m.requote_survivor_ratio:.1%})")
    print(f"  - Net-Positive Survivors  : {m.net_positive_survivors}/{m.total_detected}")
    print(f"  - Simulation Survivors    : {m.simulation_survivors}/{m.simulation_attempted} ({m.simulation_survivor_ratio:.1%})")
    print(f"  - Inventory Survivors     : {m.inventory_survivors}/{m.inventory_attempted}")
    print(f"  - Paper Ready Count       : {m.paper_ready_count}/{m.total_detected}")
    print("---------------------------------------------------------")
    print("GATE CHECKS:")
    print(f"  - Cost Completeness Ratio : {m.cost_completeness_ratio:.1%} (Target: 100%)")
    print(f"  - Raw Reference Coverage  : {m.raw_ref_coverage_ratio:.1%} (Target: 100%)")
    print("---------------------------------------------------------")
    print("LATENCY & LIFETIME:")
    print(f"  - Mean Decision Latency   : {m.mean_decision_latency_ms:.2f} ms")
    print(f"  - P50 Decision Latency    : {m.p50_decision_latency_ms:.2f} ms")
    print(f"  - P95 Decision Latency    : {m.p95_decision_latency_ms:.2f} ms")
    print(f"  - Mean Opp Lifetime       : {m.mean_opportunity_lifetime_ms} ms")
    print("---------------------------------------------------------")
    print("DECISION BREAKDOWN:")
    for d in report.decisions:
        net_str = f"{d.net_pnl} USDC" if d.net_pnl is not None else "N/A"
        reasons_str = ", ".join(d.reject_reasons) if d.reject_reasons else "NONE (Accepted)"
        print(f"  [{d.state.value:18}] {d.candidate_id:28} | Net: {net_str:10} | Rejects: {reasons_str}")
    print("=========================================================\n")


if __name__ == "__main__":
    main()
