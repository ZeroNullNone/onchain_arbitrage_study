"""Day 3 executable-price tests against a pinned Base pool fixture."""

from datetime import UTC, datetime
from decimal import Decimal
import csv
import json
from pathlib import Path

import pytest

from onchain_arb.amm import ConstantProductPool, quote_exact_input
from onchain_arb.models import TokenAmount, TokenRef


FIXTURE_PATH = (
    Path(__file__).parent
    / "fixtures"
    / "amm"
    / "base_aerodrome_weth_usdc_block_49641814.json"
)
DERIVED_PATH = (
    Path(__file__).parents[1]
    / "data"
    / "derived"
    / "day03_base_aerodrome_weth_usdc.csv"
)
WETH = TokenRef(
    chain_id=8453,
    contract_address="0x4200000000000000000000000000000000000006",
    symbol="WETH",
    decimals=18,
)
USDC = TokenRef(
    chain_id=8453,
    contract_address="0x833589fCD6eDb6E08f4C7C32D4f71b54bdA02913",
    symbol="USDC",
    decimals=6,
)


def _responses_by_id(fixture: dict[str, object]) -> dict[str, dict[str, object]]:
    responses: dict[str, dict[str, object]] = {}
    for observation in fixture["observations"]:  # type: ignore[index]
        response = observation["response"]
        items = response if isinstance(response, list) else [response]
        responses.update({item["id"]: item for item in items})
    return responses


def _decode_words(value: str) -> tuple[int, ...]:
    payload = value.removeprefix("0x")
    return tuple(int(payload[index : index + 64], 16) for index in range(0, len(payload), 64))


def test_selected_pool_matches_reported_weth_usdc_liquidity() -> None:
    """Guard the pool selection against a similarly named but different venue."""
    fixture = json.loads(FIXTURE_PATH.read_text())
    responses = _responses_by_id(fixture)
    reserve0, reserve1, _reserve_updated_at = _decode_words(
        responses["pool-reserves"]["result"]  # type: ignore[arg-type]
    )

    assert Decimal("2000") <= Decimal(reserve0).scaleb(-WETH.decimals) <= Decimal("2100")
    assert Decimal("3900000") <= Decimal(reserve1).scaleb(-USDC.decimals) <= Decimal("4100000")


def test_derived_table_reconstructs_from_raw_fixture(
    base_pool: ConstantProductPool,
) -> None:
    with DERIVED_PATH.open(newline="") as table_file:
        rows = list(csv.DictReader(table_file))

    assert [row["size_usdc"] for row in rows] == ["100", "500", "1000"]
    for row in rows:
        quote = quote_exact_input(
            base_pool,
            TokenAmount.from_decimal(USDC, Decimal(row["size_usdc"])),
            slippage_tolerance_bps=50,
        )
        assert Decimal(row["spot_price_usdc_per_weth"]) == quote.displayed_spot_price
        assert Decimal(row["executable_output_weth"]) == quote.output_amount.decimal_amount
        assert (
            Decimal(row["average_execution_price_usdc_per_weth"])
            == quote.average_execution_price
        )


@pytest.fixture
def base_pool() -> ConstantProductPool:
    fixture = json.loads(FIXTURE_PATH.read_text())
    responses = _responses_by_id(fixture)
    reserve0, reserve1, _reserve_updated_at = _decode_words(
        responses["pool-reserves"]["result"]  # type: ignore[arg-type]
    )

    assert int(responses["chain-id"]["result"], 16) == 8453  # type: ignore[arg-type]
    assert responses["pool-token0"]["result"][-40:].lower() == WETH.contract_address[-40:].lower()  # type: ignore[index]
    assert responses["pool-token1"]["result"][-40:].lower() == USDC.contract_address[-40:].lower()  # type: ignore[index]

    return ConstantProductPool(
        pool_address=fixture["pool_address"],
        token0=WETH,
        token1=USDC,
        reserve0_raw=reserve0,
        reserve1_raw=reserve1,
        fee_bps=int(responses["pool-fee"]["result"], 16),  # type: ignore[arg-type]
        block_number=fixture["block_number"],
        request_id="pool-reserves",
        source=fixture["source"],
        raw_ref=str(FIXTURE_PATH),
        observed_at=datetime.fromisoformat(
            fixture["observations"][0]["observed_at"]
        ),
    )


@pytest.mark.parametrize(
    ("size_usdc", "response_id", "expected_output_raw"),
    [
        ("100", "quote-100-usdc", 52_389_478_392_237_505),
        ("500", "quote-500-usdc-retry-1", 261_920_729_277_126_889),
        ("1000", "quote-1000-usdc-retry-1", 523_774_817_107_841_071),
    ],
)
def test_local_integer_math_matches_onchain_get_amount_out(
    base_pool: ConstantProductPool,
    size_usdc: str,
    response_id: str,
    expected_output_raw: int,
) -> None:
    fixture = json.loads(FIXTURE_PATH.read_text())
    response = _responses_by_id(fixture)[response_id]
    onchain_output_raw = int(response["result"], 16)  # type: ignore[arg-type]

    quote = quote_exact_input(
        base_pool,
        TokenAmount.from_decimal(USDC, Decimal(size_usdc)),
        slippage_tolerance_bps=50,
    )

    assert quote.output_amount.raw_amount == expected_output_raw
    assert quote.output_amount.raw_amount == onchain_output_raw
    assert quote.pool_fee_amount.decimal_amount == Decimal(size_usdc) * Decimal("0.003")
    assert quote.minimum_output_amount.raw_amount == expected_output_raw * 9_950 // 10_000
    assert quote.average_execution_price > quote.displayed_spot_price
    assert quote.price_impact_bps > Decimal("30")


def test_constant_product_hand_calculation_uses_fee_before_curve() -> None:
    token_in = TokenRef(1, "0x01", "IN", 0)
    token_out = TokenRef(1, "0x02", "OUT", 0)
    pool = ConstantProductPool(
        pool_address="0xpool",
        token0=token_in,
        token1=token_out,
        reserve0_raw=1_000,
        reserve1_raw=2_000,
        fee_bps=100,
        block_number=1,
        request_id="hand-calculation",
        source="hand_calculation",
        raw_ref="tests/test_amm.py",
        observed_at=datetime(2026, 8, 7, tzinfo=UTC),
    )

    quote = quote_exact_input(
        pool,
        TokenAmount(token_in, 100),
        slippage_tolerance_bps=100,
    )

    # Fee = floor(100 * 1%), then output = floor(99 * 2,000 / (1,000 + 99)).
    assert quote.pool_fee_amount.raw_amount == 1
    assert quote.output_amount.raw_amount == 180
    assert quote.minimum_output_amount.raw_amount == 178


def test_quote_rejects_token_outside_pool(base_pool: ConstantProductPool) -> None:
    other = TokenRef(8453, "0xother", "OTHER", 18)

    with pytest.raises(ValueError, match="not in this pool"):
        quote_exact_input(
            base_pool,
            TokenAmount(other, 1),
            slippage_tolerance_bps=50,
        )
