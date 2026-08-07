"""Deterministic exact-input quotes for volatile constant-product AMMs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from onchain_arb.models import TokenAmount, TokenRef, _require_utc


BASIS_POINTS = 10_000


@dataclass(frozen=True, slots=True)
class ConstantProductPool:
    """A pinned observation of a two-token ``x * y = k`` pool."""

    pool_address: str
    token0: TokenRef
    token1: TokenRef
    reserve0_raw: int
    reserve1_raw: int
    fee_bps: int
    block_number: int
    request_id: str
    source: str
    raw_ref: str
    observed_at: datetime

    def __post_init__(self) -> None:
        if not self.pool_address or not self.request_id or not self.source or not self.raw_ref:
            raise ValueError(
                "pool_address, request_id, source, and raw_ref are required"
            )
        if self.token0.chain_id != self.token1.chain_id:
            raise ValueError("pool tokens must be on the same chain")
        if self.token0 == self.token1:
            raise ValueError("pool tokens must be different")
        if self.reserve0_raw <= 0 or self.reserve1_raw <= 0:
            raise ValueError("pool reserves must be positive")
        if isinstance(self.fee_bps, bool) or not 0 <= self.fee_bps < BASIS_POINTS:
            raise ValueError("fee_bps must be between 0 and 9,999")
        if self.block_number < 0:
            raise ValueError("block_number must be non-negative")
        _require_utc(self.observed_at, "observed_at")

    def reserves_for(self, token_in: TokenRef) -> tuple[int, int, TokenRef]:
        if token_in == self.token0:
            return self.reserve0_raw, self.reserve1_raw, self.token1
        if token_in == self.token1:
            return self.reserve1_raw, self.reserve0_raw, self.token0
        raise ValueError("input token is not in this pool")


@dataclass(frozen=True, slots=True)
class ExactInputQuote:
    """Execution-aware quote with explicit price and fee semantics."""

    input_amount: TokenAmount
    output_amount: TokenAmount
    minimum_output_amount: TokenAmount
    pool_fee_amount: TokenAmount
    displayed_spot_price: Decimal
    average_execution_price: Decimal
    price_impact_bps: Decimal
    slippage_tolerance_bps: int


def quote_exact_input(
    pool: ConstantProductPool,
    input_amount: TokenAmount,
    *,
    slippage_tolerance_bps: int,
) -> ExactInputQuote:
    """Quote one exact-input swap using the pool contract's integer math.

    Prices are denominated as input-token units per output-token unit. Price
    impact compares the average execution price with the displayed reserve
    ratio and therefore includes both the pool fee and curve impact.
    """

    if input_amount.raw_amount <= 0:
        raise ValueError("input amount must be positive")
    if (
        isinstance(slippage_tolerance_bps, bool)
        or not 0 <= slippage_tolerance_bps < BASIS_POINTS
    ):
        raise ValueError("slippage_tolerance_bps must be between 0 and 9,999")

    reserve_in, reserve_out, token_out = pool.reserves_for(input_amount.token)
    fee_raw = input_amount.raw_amount * pool.fee_bps // BASIS_POINTS
    amount_after_fee_raw = input_amount.raw_amount - fee_raw
    output_raw = amount_after_fee_raw * reserve_out // (
        reserve_in + amount_after_fee_raw
    )
    if output_raw <= 0:
        raise ValueError("input amount is too small to produce output")

    minimum_output_raw = (
        output_raw * (BASIS_POINTS - slippage_tolerance_bps) // BASIS_POINTS
    )
    output_amount = TokenAmount(token=token_out, raw_amount=output_raw)

    reserve_in_decimal = Decimal(reserve_in).scaleb(-input_amount.token.decimals)
    reserve_out_decimal = Decimal(reserve_out).scaleb(-token_out.decimals)
    displayed_spot_price = reserve_in_decimal / reserve_out_decimal
    average_execution_price = (
        input_amount.decimal_amount / output_amount.decimal_amount
    )
    price_impact_bps = (
        (average_execution_price / displayed_spot_price) - Decimal(1)
    ) * BASIS_POINTS

    return ExactInputQuote(
        input_amount=input_amount,
        output_amount=output_amount,
        minimum_output_amount=TokenAmount(
            token=token_out,
            raw_amount=minimum_output_raw,
        ),
        pool_fee_amount=TokenAmount(
            token=input_amount.token,
            raw_amount=fee_raw,
        ),
        displayed_spot_price=displayed_spot_price,
        average_execution_price=average_execution_price,
        price_impact_bps=price_impact_bps,
        slippage_tolerance_bps=slippage_tolerance_bps,
    )
