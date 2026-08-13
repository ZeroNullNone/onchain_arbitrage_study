"""Day 9 route-dispersion acceptance tests over the frozen universe."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
import json
from pathlib import Path

import pytest

from onchain_arb.adapters.lifi import load_raw_quote
from onchain_arb.analysis.route_dispersion import (
    DifferenceKind,
    DirectCheckStatus,
    RouteObservation,
    analyze_route_dispersion,
    assess_candidate,
    from_lifi_quote,
)
from onchain_arb.models import TokenAmount, TokenRef


FIXTURES = Path(__file__).parent / "fixtures"
LIFI_FIXTURES = FIXTURES / "lifi"
AMM_FIXTURE = FIXTURES / "amm" / "base_aerodrome_weth_usdc_block_49641814.json"
WETH = TokenRef(
    8453,
    "0x4200000000000000000000000000000000000006",
    "WETH",
    18,
)
USDC = TokenRef(
    8453,
    "0x833589fCD6eDb6E08f4C7C32D4f71b54bdA02913",
    "USDC",
    6,
)


def _base_lifi() -> tuple[RouteObservation, ...]:
    observations = tuple(
        from_lifi_quote(load_raw_quote(path))
        for path in sorted(LIFI_FIXTURES.glob("base_usdc_weth_*_usdc.json"))
    )
    return tuple(sorted(observations, key=lambda item: item.input_amount.raw_amount))


def _direct_aerodrome() -> tuple[RouteObservation, ...]:
    fixture = json.loads(AMM_FIXTURE.read_text())
    responses: dict[str, tuple[dict[str, object], dict[str, object]]] = {}
    for observation in fixture["observations"]:
        response = observation["response"]
        for item in response if isinstance(response, list) else [response]:
            if "result" in item:
                responses[item["id"]] = (item, observation)
    request_ids = {
        100_000_000: "quote-100-usdc",
        500_000_000: "quote-500-usdc-retry-1",
        1_000_000_000: "quote-1000-usdc-retry-1",
    }
    observations = []
    for input_raw, request_id in request_ids.items():
        response, envelope = responses[request_id]
        output_raw = int(response["result"], 16)  # type: ignore[arg-type]
        observations.append(
            RouteObservation(
                observation_id=f"aerodrome-{input_raw}",
                request_id=request_id,
                raw_ref=f"{AMM_FIXTURE}#{request_id}",
                source="direct_rpc",
                provider="aerodrome",
                route_fingerprint="aerodrome-base-weth-usdc",
                input_amount=TokenAmount(USDC, input_raw),
                output_amount=TokenAmount(WETH, output_raw),
                minimum_output_amount=TokenAmount(WETH, output_raw * 9_950 // 10_000),
                observed_at=datetime.fromisoformat(envelope["observed_at"]),  # type: ignore[arg-type]
                latency_ms=Decimal(envelope["latency_ms"]),  # type: ignore[arg-type]
                duration_seconds=Decimal(0),
                fee_amount=TokenAmount(USDC, input_raw * 30 // 10_000),
            )
        )
    return tuple(observations)


def test_frozen_evidence_calculates_all_dispersion_metrics() -> None:
    lifi = _base_lifi()
    direct = _direct_aerodrome()

    report = analyze_route_dispersion((*lifi, *direct))

    assert [ranking.input_amount.decimal_amount for ranking in report.rankings] == [
        Decimal(100),
        Decimal(500),
        Decimal(1000),
    ]
    assert all(ranking.best.provider == "aerodrome" for ranking in report.rankings)
    assert [ranking.second_best.provider for ranking in report.rankings] == [  # type: ignore[union-attr]
        "fly",
        "fly",
        "kyberswap",
    ]
    assert all(ranking.best_over_second_raw > 0 for ranking in report.rankings)  # type: ignore[operator]
    assert report.route_switch_rate == Decimal("0.5")
    assert sorted(item.observations for item in report.route_lifetimes) == [1, 2]
    assert sorted(item.lifetime_seconds for item in report.route_lifetimes) == [
        Decimal(0),
        Decimal("1.808387"),
    ]
    assert report.provider_concentration[0].provider == "fly"
    assert report.provider_concentration[0].share == Decimal(2) / Decimal(3)
    assert report.duration_spread_seconds == 0
    assert report.fee_rate_spread_bps == 0
    assert [point.provider for point in report.size_sensitivity] == [
        "fly",
        "fly",
        "kyberswap",
    ]
    assert report.size_sensitivity[0].change_bps_from_smallest == 0
    assert report.size_sensitivity[-1].change_bps_from_smallest > 0


def test_independent_direct_source_refutes_stale_candidate() -> None:
    lifi_100 = next(
        item for item in _base_lifi() if item.input_amount.decimal_amount == Decimal(100)
    )
    direct_100 = next(
        item
        for item in _direct_aerodrome()
        if item.input_amount.decimal_amount == Decimal(100)
    )

    assessment = assess_candidate(
        "day09-base-100",
        lifi_100,
        direct_100,
        max_observation_gap=timedelta(seconds=60),
    )

    assert assessment.difference_kind is DifferenceKind.STALE_QUOTE
    assert assessment.direct_check_status is DirectCheckStatus.REFUTED
    assert not assessment.is_arbitrage
    assert "exceeds freshness bound" in assessment.reasons[0]


def test_every_difference_kind_has_an_explicit_classification_path() -> None:
    route = _base_lifi()[0]
    fresh_direct = replace(
        _direct_aerodrome()[0],
        observed_at=route.observed_at + timedelta(seconds=1),
    )
    unavailable = replace(fresh_direct, available=False)
    other_weth = TokenRef(8453, "0xdifferent", "WETH", 18)
    mapping_difference = replace(
        fresh_direct,
        output_amount=TokenAmount(other_weth, fresh_direct.output_amount.raw_amount),
        minimum_output_amount=TokenAmount(
            other_weth, fresh_direct.minimum_output_amount.raw_amount
        ),
    )

    cases = [
        (
            assess_candidate(
                "unavailable", route, unavailable, max_observation_gap=timedelta(seconds=5)
            ),
            DifferenceKind.UNAVAILABLE_ROUTE,
            False,
        ),
        (
            assess_candidate(
                "mapping",
                route,
                mapping_difference,
                max_observation_gap=timedelta(seconds=5),
            ),
            DifferenceKind.TOKEN_MAPPING_DIFFERENCE,
            False,
        ),
        (
            assess_candidate(
                "subsidy",
                route,
                fresh_direct,
                max_observation_gap=timedelta(seconds=5),
                subsidy_evidence=True,
            ),
            DifferenceKind.TEMPORARY_SUBSIDY,
            False,
        ),
        (
            assess_candidate(
                "routing", route, fresh_direct, max_observation_gap=timedelta(seconds=5)
            ),
            DifferenceKind.ROUTING_IMPROVEMENT,
            False,
        ),
        (
            assess_candidate(
                "tradable",
                route,
                fresh_direct,
                max_observation_gap=timedelta(seconds=5),
                independently_refreshed=True,
                complete_cost_ledger=True,
                executable_cycle=True,
            ),
            DifferenceKind.TRADABLE_EDGE,
            True,
        ),
    ]

    assert [(item.difference_kind, item.is_arbitrage) for item, _, _ in cases] == [
        (kind, is_arbitrage) for _, kind, is_arbitrage in cases
    ]


def test_missing_fee_evidence_is_not_silently_treated_as_zero() -> None:
    lifi = _base_lifi()

    report = analyze_route_dispersion((replace(lifi[0], fee_amount=None), *lifi[1:]))

    assert report.fee_rate_spread_bps is None


def test_independent_refresh_must_actually_be_later() -> None:
    route = _base_lifi()[0]
    older_direct = replace(
        _direct_aerodrome()[0],
        observed_at=route.observed_at - timedelta(seconds=1),
    )

    with pytest.raises(ValueError, match="must be observed later"):
        assess_candidate(
            "false-refresh",
            route,
            older_direct,
            max_observation_gap=timedelta(seconds=5),
            independently_refreshed=True,
        )


def test_mixed_token_paths_are_rejected_before_ranking() -> None:
    lifi = _base_lifi()
    other_token = TokenRef(8453, "0xother", "USDC", 6)
    other = replace(
        lifi[0],
        input_amount=TokenAmount(other_token, 100_000_000),
        fee_amount=TokenAmount(other_token, lifi[0].fee_amount.raw_amount),  # type: ignore[union-attr]
    )

    with pytest.raises(ValueError, match="one chain-specific token path"):
        analyze_route_dispersion((other, *lifi[1:]))
