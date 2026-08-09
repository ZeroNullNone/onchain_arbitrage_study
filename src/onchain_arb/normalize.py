"""Lossless-enough tabular projection of parsed LI.FI quote evidence."""

from __future__ import annotations

import json
from typing import Any

from onchain_arb.adapters.lifi import LifiQuote, LifiSourceCost


NORMALIZED_COLUMNS = (
    "request_id",
    "quote_id",
    "raw_ref",
    "observed_at",
    "latency_ms",
    "from_chain_id",
    "to_chain_id",
    "from_token_address",
    "from_token_symbol",
    "from_token_decimals",
    "from_amount_raw",
    "to_token_address",
    "to_token_symbol",
    "to_token_decimals",
    "to_amount_raw",
    "to_amount_min_raw",
    "tool",
    "duration_seconds",
    "approval_address",
    "route_fingerprint",
    "route_steps_json",
    "fee_costs_json",
    "gas_costs_json",
    "transaction_request_json",
)


def normalize_lifi_quote(quote: LifiQuote) -> dict[str, Any]:
    """Flatten a quote without using binary floats or dropping raw lineage."""

    return {
        "request_id": quote.request_id,
        "quote_id": quote.quote_id,
        "raw_ref": quote.raw_ref,
        "observed_at": quote.observed_at,
        "latency_ms": str(quote.latency_ms),
        "from_chain_id": quote.request.from_chain_id,
        "to_chain_id": quote.request.to_chain_id,
        "from_token_address": quote.input_amount.token.contract_address,
        "from_token_symbol": quote.input_amount.token.symbol,
        "from_token_decimals": quote.input_amount.token.decimals,
        "from_amount_raw": str(quote.input_amount.raw_amount),
        "to_token_address": quote.output_amount.token.contract_address,
        "to_token_symbol": quote.output_amount.token.symbol,
        "to_token_decimals": quote.output_amount.token.decimals,
        "to_amount_raw": str(quote.output_amount.raw_amount),
        "to_amount_min_raw": str(quote.minimum_output_amount.raw_amount),
        "tool": quote.tool,
        "duration_seconds": str(quote.duration_seconds),
        "approval_address": quote.approval_address,
        "route_fingerprint": quote.route_fingerprint,
        "route_steps_json": _json(
            [
                {
                    "step_type": step.step_type,
                    "tool": step.tool,
                    "from_chain_id": step.from_chain_id,
                    "to_chain_id": step.to_chain_id,
                    "from_token_address": step.from_token_address,
                    "to_token_address": step.to_token_address,
                }
                for step in quote.route_steps
            ]
        ),
        "fee_costs_json": _json([_cost(cost) for cost in quote.fee_costs]),
        "gas_costs_json": _json([_cost(cost) for cost in quote.gas_costs]),
        "transaction_request_json": _json(quote.transaction_request),
    }


def _cost(cost: LifiSourceCost) -> dict[str, Any]:
    return {
        "cost_type": cost.cost_type,
        "name": cost.name,
        "chain_id": cost.amount.token.chain_id,
        "token_address": cost.amount.token.contract_address,
        "token_symbol": cost.amount.token.symbol,
        "token_decimals": cost.amount.token.decimals,
        "amount_raw": str(cost.amount.raw_amount),
        "amount_usd": None if cost.amount_usd is None else str(cost.amount_usd),
        "included_in_quote_output": cost.included_in_quote_output,
    }


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))
