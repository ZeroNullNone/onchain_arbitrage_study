"""Day 8 acceptance tests for the conservative same-chain baseline."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
import json
from pathlib import Path

import pytest

from onchain_arb.detectors.same_chain import (
    RejectReason,
    RoundTripAttempt,
    scan_same_chain,
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
    RequoteRejectReason,
    RoundTripQuotes,
    validate_requote,
)


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "day08" / "edge_disappears.json"
OBSERVED_AT = datetime(2026, 8, 12, 4, 0, tzinfo=UTC)
USDC = TokenRef(
    8453,
    "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
    "USDC",
    6,
)
WETH = TokenRef(
    8453,
    "0x4200000000000000000000000000000000000006",
    "WETH",
    18,
)


def _cost(kind: str, raw_amount: int, observed_at: datetime) -> CostItem:
    return CostItem(
        kind=kind,
        amount=TokenAmount(USDC, raw_amount),
        scope=CostScope.ATOMIC,
        included_in_quote_output=False,
        confidence=CostConfidence.ESTIMATED,
        source="day08_paper_fixture",
        observed_at=observed_at,
    )


def _quote(
    *,
    quote_id: str,
    venue: str,
    token_in: TokenRef,
    input_raw: int,
    token_out: TokenRef,
    output_raw: int,
    minimum_raw: int,
    gas_raw: int,
    leg: int,
    observed_at: datetime,
) -> DirectQuote:
    return DirectQuote(
        quote_id=quote_id,
        request_id=f"request-{quote_id}",
        raw_ref=f"{FIXTURE_PATH}#{quote_id}",
        venue=venue,
        input_amount=TokenAmount(token_in, input_raw),
        output_amount=TokenAmount(token_out, output_raw),
        minimum_output_amount=TokenAmount(token_out, minimum_raw),
        fee_amount=TokenAmount(token_in, input_raw * 30 // 10_000),
        gas_cost=_cost(f"gas_leg_{leg}", gas_raw, observed_at),
        approval_status=ApprovalStatus.NOT_REQUIRED,
        approval_cost=None,
        observed_at=observed_at,
        latency_ms=Decimal("12.500"),
    )


def _round_trip(
    *,
    prefix: str,
    size_raw: int,
    final_raw: int,
    minimum_final_raw: int,
    gas_raw: int,
    observed_at: datetime,
) -> RoundTripQuotes:
    # Fixed WETH amounts keep the fixture focused on decision semantics. The
    # important invariant is that leg two spends leg one's guaranteed minimum.
    weth_output_raw = size_raw * 500_000_000
    weth_minimum_raw = weth_output_raw * 9_950 // 10_000
    first = _quote(
        quote_id=f"{prefix}-aerodrome-buy",
        venue="aerodrome",
        token_in=USDC,
        input_raw=size_raw,
        token_out=WETH,
        output_raw=weth_output_raw,
        minimum_raw=weth_minimum_raw,
        gas_raw=gas_raw,
        leg=1,
        observed_at=observed_at,
    )
    second = _quote(
        quote_id=f"{prefix}-uniswap-sell",
        venue="uniswap_v3",
        token_in=WETH,
        input_raw=weth_minimum_raw,
        token_out=USDC,
        output_raw=final_raw,
        minimum_raw=minimum_final_raw,
        gas_raw=gas_raw,
        leg=2,
        observed_at=observed_at + timedelta(milliseconds=20),
    )
    return RoundTripQuotes(first, second)


def _fixture_attempts() -> tuple[RoundTripAttempt, ...]:
    payload = json.loads(FIXTURE_PATH.read_text())
    first_venue, second_venue = payload["venues"]
    attempts = []
    for index, item in enumerate(payload["attempts"]):
        initial = _round_trip(
            prefix=f"{item['candidate_id']}-initial",
            size_raw=item["size_usdc_raw"],
            final_raw=item["initial_final_usdc_raw"],
            minimum_final_raw=item["initial_min_usdc_raw"],
            gas_raw=item["gas_usdc_raw_per_leg"],
            observed_at=OBSERVED_AT + timedelta(seconds=index * 10),
        )
        assert initial.first_leg.venue == first_venue
        assert initial.second_leg.venue == second_venue
        refreshed = None
        if item["has_requote"]:
            refreshed = _round_trip(
                prefix=f"{item['candidate_id']}-refreshed",
                size_raw=item["size_usdc_raw"],
                final_raw=item["refreshed_final_usdc_raw"],
                minimum_final_raw=item["refreshed_min_usdc_raw"],
                gas_raw=item["gas_usdc_raw_per_leg"],
                observed_at=OBSERVED_AT + timedelta(seconds=index * 10 + 1),
            )
        attempts.append(RoundTripAttempt(item["candidate_id"], initial, refreshed))
    return tuple(attempts)


def test_fixture_covers_fixed_sizes_and_edge_disappears() -> None:
    attempts = _fixture_attempts()

    assert [item.initial.target_size.decimal_amount for item in attempts] == [
        Decimal("100"),
        Decimal("500"),
        Decimal("1000"),
    ]
    edge = attempts[0]
    assert edge.initial.final_output.raw_amount > edge.initial.target_size.raw_amount
    assert edge.refreshed is not None
    assert edge.refreshed.final_output.raw_amount < edge.refreshed.target_size.raw_amount


def test_baseline_reports_all_funnel_metrics_and_reject_reasons() -> None:
    report = scan_same_chain(_fixture_attempts())

    assert report.metrics.attempts == 3
    assert report.metrics.gross_candidates == 3
    assert report.metrics.requote_survivors == 1
    assert report.metrics.net_positive_survivors == 0
    assert report.metrics.largest_false_positive_source == RejectReason.NET_NOT_POSITIVE

    by_id = {item.candidate_id: item for item in report.decisions}
    edge_reasons = by_id["day08-100-edge-disappears"].reject_reasons
    assert RejectReason.REQUOTE_GROSS_NOT_POSITIVE in edge_reasons
    assert RejectReason.REQUOTE_MINIMUM_NOT_POSITIVE in edge_reasons
    assert RejectReason.NET_NOT_POSITIVE in edge_reasons
    assert by_id["day08-500-gas-reject"].cost_evaluation is not None
    assert by_id[
        "day08-500-gas-reject"
    ].cost_evaluation.local_trade_pnl == Decimal("-0.1")
    assert by_id["day08-1000-missing-requote"].reject_reasons == (
        RejectReason.REQUOTE_MISSING,
    )


def test_requote_gate_returns_every_comparability_failure() -> None:
    initial = _fixture_attempts()[0].initial
    stale = RoundTripQuotes(
        initial.first_leg,
        initial.second_leg,
    )

    reasons = validate_requote(initial, stale)

    assert reasons == (RequoteRejectReason.NOT_REFRESHED,)


def test_leg_two_must_spend_guaranteed_not_optimistic_output() -> None:
    initial = _fixture_attempts()[0].initial
    bad_second = DirectQuote(
        quote_id="bad-link",
        request_id="bad-link-request",
        raw_ref=f"{FIXTURE_PATH}#bad-link",
        venue=initial.second_leg.venue,
        input_amount=initial.first_leg.output_amount,
        output_amount=initial.second_leg.output_amount,
        minimum_output_amount=initial.second_leg.minimum_output_amount,
        fee_amount=TokenAmount(
            WETH, initial.first_leg.output_amount.raw_amount * 30 // 10_000
        ),
        gas_cost=initial.second_leg.gas_cost,
        approval_status=ApprovalStatus.NOT_REQUIRED,
        approval_cost=None,
        observed_at=initial.second_leg.observed_at + timedelta(seconds=1),
        latency_ms=Decimal("10"),
    )
    refreshed = RoundTripQuotes(initial.first_leg, bad_second)

    reasons = validate_requote(initial, refreshed)

    assert RequoteRejectReason.LEG_INPUT_NOT_GUARANTEED in reasons


def test_required_approval_without_cost_is_rejected_at_evidence_boundary() -> None:
    quote = _fixture_attempts()[0].initial.first_leg

    with pytest.raises(ValueError, match="explicit cost"):
        DirectQuote(
            quote_id=quote.quote_id,
            request_id=quote.request_id,
            raw_ref=quote.raw_ref,
            venue=quote.venue,
            input_amount=quote.input_amount,
            output_amount=quote.output_amount,
            minimum_output_amount=quote.minimum_output_amount,
            fee_amount=quote.fee_amount,
            gas_cost=quote.gas_cost,
            approval_status=ApprovalStatus.REQUIRED,
            approval_cost=None,
            observed_at=quote.observed_at,
            latency_ms=quote.latency_ms,
        )
