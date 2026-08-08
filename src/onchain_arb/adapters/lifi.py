"""Offline parsing for raw LI.FI ``GET /v1/quote`` evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from onchain_arb.models import TokenAmount, TokenRef, _require_utc


@dataclass(frozen=True, slots=True)
class LifiQuoteRequest:
    from_chain_id: int
    to_chain_id: int
    from_token: str
    to_token: str
    from_amount_raw: int
    from_address: str
    to_address: str | None
    slippage: Decimal | None

    def __post_init__(self) -> None:
        if self.from_chain_id <= 0 or self.to_chain_id <= 0:
            raise ValueError("request chain IDs must be positive")
        if self.from_amount_raw <= 0:
            raise ValueError("request fromAmount must be positive")
        if not self.from_token or not self.to_token or not self.from_address:
            raise ValueError("request tokens and fromAddress are required")

    def to_query(self) -> dict[str, str]:
        query = {
            "fromChain": str(self.from_chain_id),
            "toChain": str(self.to_chain_id),
            "fromToken": self.from_token,
            "toToken": self.to_token,
            "fromAmount": str(self.from_amount_raw),
            "fromAddress": self.from_address,
        }
        if self.to_address is not None:
            query["toAddress"] = self.to_address
        if self.slippage is not None:
            query["slippage"] = str(self.slippage)
        return query


@dataclass(frozen=True, slots=True)
class LifiRouteStep:
    step_type: str
    tool: str
    from_chain_id: int
    to_chain_id: int
    from_token_address: str
    to_token_address: str


@dataclass(frozen=True, slots=True)
class LifiSourceCost:
    """A source-reported cost without inferred PnL treatment."""

    cost_type: str
    name: str
    amount: TokenAmount
    amount_usd: Decimal | None
    included_in_quote_output: bool | None

    def __post_init__(self) -> None:
        if self.cost_type not in {"fee", "gas"}:
            raise ValueError("cost_type must be fee or gas")
        if not self.name:
            raise ValueError("cost name is required")


@dataclass(frozen=True, slots=True)
class LifiQuote:
    quote_id: str
    request_id: str
    raw_ref: str
    observed_at: datetime
    latency_ms: Decimal
    request: LifiQuoteRequest
    input_amount: TokenAmount
    output_amount: TokenAmount
    minimum_output_amount: TokenAmount
    tool: str
    duration_seconds: Decimal
    approval_address: str | None
    route_steps: tuple[LifiRouteStep, ...]
    route_fingerprint: str
    fee_costs: tuple[LifiSourceCost, ...]
    gas_costs: tuple[LifiSourceCost, ...]
    transaction_request: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not self.quote_id or not self.request_id or not self.raw_ref or not self.tool:
            raise ValueError("quote IDs, raw_ref, and tool are required")
        if self.minimum_output_amount.token != self.output_amount.token:
            raise ValueError("output and minimum output tokens differ")
        if self.minimum_output_amount.raw_amount > self.output_amount.raw_amount:
            raise ValueError("minimum output exceeds quoted output")
        if self.latency_ms < 0 or self.duration_seconds < 0:
            raise ValueError("latency and duration must be non-negative")
        _require_utc(self.observed_at, "observed_at")


def load_raw_quote(path: str | Path) -> LifiQuote:
    """Rebuild one normalized quote from an append-only raw evidence envelope."""

    raw_path = Path(path)
    envelope = json.loads(raw_path.read_text(), parse_float=Decimal)
    if envelope.get("schema_version") != 1 or envelope.get("source") != "lifi":
        raise ValueError("unsupported LI.FI raw envelope")

    response = _mapping(envelope, "response")
    status = response.get("status")
    if status != 200:
        raise ValueError(f"LI.FI quote response status is {status!r}")
    body = response.get("body")
    if not isinstance(body, str):
        raise ValueError("raw response body is missing")
    payload = json.loads(body, parse_float=Decimal)
    if not isinstance(payload, dict):
        raise ValueError("LI.FI quote body must be an object")

    request = _parse_request(_mapping(_mapping(envelope, "request"), "query"))
    action = _mapping(payload, "action")
    estimate = _mapping(payload, "estimate")
    from_token = _parse_token(_mapping(action, "fromToken"))
    to_token = _parse_token(_mapping(action, "toToken"))
    input_amount = TokenAmount(from_token, _raw_integer(action, "fromAmount"))
    output_amount = TokenAmount(to_token, _raw_integer(estimate, "toAmount"))
    minimum_output_amount = TokenAmount(
        to_token, _raw_integer(estimate, "toAmountMin")
    )
    _validate_request_matches_action(request, action, input_amount)

    route_steps = tuple(
        _parse_route_step(step) for step in payload.get("includedSteps", [])
    )
    if not route_steps:
        route_steps = (_parse_route_step(payload),)

    observed_at = datetime.fromisoformat(str(envelope["observed_at"]).replace("Z", "+00:00"))
    transaction_request = payload.get("transactionRequest")
    if not isinstance(transaction_request, dict):
        raise ValueError("transactionRequest is missing")

    return LifiQuote(
        quote_id=_string(payload, "id"),
        request_id=_string(envelope, "request_id"),
        raw_ref=str(raw_path),
        observed_at=observed_at,
        latency_ms=Decimal(str(envelope["latency_ms"])),
        request=request,
        input_amount=input_amount,
        output_amount=output_amount,
        minimum_output_amount=minimum_output_amount,
        tool=_string(payload, "tool"),
        duration_seconds=Decimal(str(estimate.get("executionDuration", 0))),
        approval_address=_optional_string(estimate.get("approvalAddress")),
        route_steps=route_steps,
        route_fingerprint=_route_fingerprint(payload, route_steps),
        fee_costs=tuple(
            _parse_cost(item, "fee") for item in estimate.get("feeCosts", [])
        ),
        gas_costs=tuple(
            _parse_cost(item, "gas") for item in estimate.get("gasCosts", [])
        ),
        transaction_request=transaction_request,
    )


def _parse_request(query: Mapping[str, Any]) -> LifiQuoteRequest:
    slippage = query.get("slippage")
    return LifiQuoteRequest(
        from_chain_id=int(_string(query, "fromChain")),
        to_chain_id=int(_string(query, "toChain")),
        from_token=_string(query, "fromToken"),
        to_token=_string(query, "toToken"),
        from_amount_raw=int(_string(query, "fromAmount")),
        from_address=_string(query, "fromAddress"),
        to_address=_optional_string(query.get("toAddress")),
        slippage=Decimal(str(slippage)) if slippage is not None else None,
    )


def _parse_token(value: Mapping[str, Any]) -> TokenRef:
    return TokenRef(
        chain_id=int(value["chainId"]),
        contract_address=_string(value, "address"),
        symbol=_string(value, "symbol"),
        decimals=int(value["decimals"]),
    )


def _parse_route_step(value: Mapping[str, Any]) -> LifiRouteStep:
    action = _mapping(value, "action")
    return LifiRouteStep(
        step_type=_string(value, "type"),
        tool=_string(value, "tool"),
        from_chain_id=int(action["fromChainId"]),
        to_chain_id=int(action["toChainId"]),
        from_token_address=_string(_mapping(action, "fromToken"), "address").lower(),
        to_token_address=_string(_mapping(action, "toToken"), "address").lower(),
    )


def _parse_cost(value: Mapping[str, Any], cost_type: str) -> LifiSourceCost:
    token = _parse_token(_mapping(value, "token"))
    amount_usd = value.get("amountUSD")
    included = value.get("included")
    if included is not None and not isinstance(included, bool):
        raise TypeError("cost included must be bool when present")
    return LifiSourceCost(
        cost_type=cost_type,
        name=str(value.get("name") or value.get("type") or cost_type),
        amount=TokenAmount(token, _raw_integer(value, "amount")),
        amount_usd=Decimal(str(amount_usd)) if amount_usd is not None else None,
        included_in_quote_output=included,
    )


def _route_fingerprint(
    payload: Mapping[str, Any], steps: tuple[LifiRouteStep, ...]
) -> str:
    semantic_route = {
        "tool": _string(payload, "tool"),
        "steps": [
            {
                "type": step.step_type,
                "tool": step.tool,
                "from_chain_id": step.from_chain_id,
                "to_chain_id": step.to_chain_id,
                "from_token": step.from_token_address,
                "to_token": step.to_token_address,
            }
            for step in steps
        ],
    }
    canonical = json.dumps(semantic_route, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _validate_request_matches_action(
    request: LifiQuoteRequest,
    action: Mapping[str, Any],
    input_amount: TokenAmount,
) -> None:
    if request.from_chain_id != int(action["fromChainId"]):
        raise ValueError("request/action fromChain mismatch")
    if request.to_chain_id != int(action["toChainId"]):
        raise ValueError("request/action toChain mismatch")
    if request.from_amount_raw != input_amount.raw_amount:
        raise ValueError("request/action fromAmount mismatch")
    if request.from_address.lower() != _string(action, "fromAddress").lower():
        raise ValueError("request/action fromAddress mismatch")


def _mapping(value: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    nested = value.get(key)
    if not isinstance(nested, dict):
        raise ValueError(f"{key} must be an object")
    return nested


def _string(value: Mapping[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise ValueError(f"{key} must be a non-empty string")
    return item


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ValueError("optional string is invalid")
    return value


def _raw_integer(value: Mapping[str, Any], key: str) -> int:
    item = _string(value, key)
    if not item.isdecimal():
        raise ValueError(f"{key} must contain raw integer units")
    return int(item)

