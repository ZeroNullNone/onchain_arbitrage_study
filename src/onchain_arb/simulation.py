"""Day 13 transaction simulation evidence reconstruction for `eth_call`.

The module is intentionally narrow:
- single simulation adapter: `eth_call`
- raw evidence first (`raw_ref`) and deterministic parsing
- explicit quote-vs-simulation comparison reasons for execution gates
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
import json
import re
from pathlib import Path
from typing import Any, Mapping

from onchain_arb.models import QuoteObservation, SimulationResult, TokenAmount, TokenDelta, TokenRef


class SimulationRejectReason(StrEnum):
    OUTPUT_BELOW_QUOTED = "output_below_quoted"
    OUTPUT_BELOW_MINIMUM = "output_below_minimum"
    OUTPUT_MISSING = "output_missing"
    INSUFFICIENT_ALLOWANCE = "insufficient_allowance"
    STALE_BLOCK = "stale_block"
    TOKEN_MISMATCH = "token_mismatch"
    REVERTED = "simulation_reverted"


@dataclass(frozen=True, slots=True)
class SimulatedBalanceChange:
    account: str
    delta: TokenDelta


@dataclass(frozen=True, slots=True)
class SimulationEvidence:
    candidate_id: str
    raw_ref: str
    request_id: str
    chain_id: int
    block_number: int
    tx_from: str
    tx_to: str
    tx_data: str
    tx_value: int
    tx_gas: int | None
    tx_gas_price: int | None
    observed_at: datetime
    result: SimulationResult
    simulated_output: TokenAmount | None
    output_account: str | None
    allowance_required: TokenAmount | None
    allowance_available: TokenAmount | None
    balance_changes: tuple[SimulatedBalanceChange, ...]


@dataclass(frozen=True, slots=True)
class SimulationComparison:
    candidate_id: str
    simulated_output: TokenAmount | None
    output_delta_from_quote: int | None
    output_meets_quote: bool
    output_meets_minimum: bool
    allowance_sufficient: bool | None
    stale_state: bool
    gas_delta_raw: int | None
    reject_reasons: tuple[SimulationRejectReason, ...]

    @property
    def executable(self) -> bool:
        return not self.reject_reasons


_HEX_QTY_RE = re.compile(r"^0x(?:0|[1-9a-fA-F][0-9a-fA-F]*)$")
_INT_RE = re.compile(r"^-?(0|[1-9]\d*)$")
_DEC_RE = re.compile(r"^(0|[1-9]\d*)$")
_ADDR_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")


def compare_quote_and_simulation(
    quote: QuoteObservation,
    simulation: SimulationEvidence,
    *,
    block_number: int | None = None,
    quote_gas_used: int | None = None,
) -> SimulationComparison:
    """Compare quoted output expectations against one simulation evidence record."""

    if quote.output_amount.token != quote.minimum_output_amount.token:
        raise ValueError("quote output and minimum output token mismatch")

    reasons: list[SimulationRejectReason] = []
    stale_state = (
        block_number is not None and simulation.result.block_number != block_number
    )
    if stale_state:
        reasons.append(SimulationRejectReason.STALE_BLOCK)

    output_delta: int | None = None
    output_meets_quote = False
    output_meets_minimum = False
    if simulation.result.revert_reason is not None:
        reasons.append(SimulationRejectReason.REVERTED)

    output = simulation.simulated_output
    if output is None:
        reasons.append(SimulationRejectReason.OUTPUT_MISSING)
    else:
        if output.token != quote.output_amount.token:
            reasons.append(SimulationRejectReason.TOKEN_MISMATCH)
        else:
            output_delta = output.raw_amount - quote.output_amount.raw_amount
            output_meets_quote = output.raw_amount >= quote.output_amount.raw_amount
            output_meets_minimum = (
                output.raw_amount >= quote.minimum_output_amount.raw_amount
            )
            if not output_meets_quote:
                reasons.append(SimulationRejectReason.OUTPUT_BELOW_QUOTED)
            if not output_meets_minimum:
                reasons.append(SimulationRejectReason.OUTPUT_BELOW_MINIMUM)

    allowance_sufficient = None
    if simulation.allowance_required is not None and simulation.allowance_available is not None:
        allowance_sufficient = (
            simulation.allowance_available.raw_amount
            >= simulation.allowance_required.raw_amount
        )
        if not allowance_sufficient:
            reasons.append(SimulationRejectReason.INSUFFICIENT_ALLOWANCE)

    gas_delta_raw = None
    if quote_gas_used is not None and simulation.result.gas_used is not None:
        gas_delta_raw = simulation.result.gas_used - quote_gas_used

    return SimulationComparison(
        candidate_id=simulation.candidate_id,
        simulated_output=output,
        output_delta_from_quote=output_delta,
        output_meets_quote=output_meets_quote,
        output_meets_minimum=output_meets_minimum,
        allowance_sufficient=allowance_sufficient,
        stale_state=stale_state,
        gas_delta_raw=gas_delta_raw,
        reject_reasons=tuple(dict.fromkeys(reasons)),
    )


def load_raw_simulation(path: str | Path) -> SimulationEvidence:
    """Normalize one saved eth_call simulation envelope."""

    raw_path = Path(path)
    envelope = json.loads(raw_path.read_text())

    if envelope.get("schema_version") != 1:
        raise ValueError("unsupported simulation envelope schema")
    if envelope.get("source") != "eth_call":
        raise ValueError("unsupported simulation source")
    if envelope.get("method") != "eth_call":
        raise ValueError("unsupported simulation method")

    candidate_id = _string(envelope, "candidate_id")
    request_id = _string(envelope, "request_id")
    chain_id = _positive_int(envelope, "chain_id")
    block_number = _hex_or_decimal(envelope, "block_number", "block number")
    observed_at = _utc_datetime(_string(envelope, "observed_at"), "observed_at")

    request = _mapping(envelope, "request")
    tx_from = _address(request, "from")
    tx_to = _address(request, "to")
    tx_data = _string(request, "data")
    tx_value = _hex_or_decimal(request, "value", "tx value")
    tx_gas = _optional_hex_or_decimal(request, "gas")
    tx_gas_price = _optional_hex_or_decimal(request, "gasPrice")

    response = _mapping(envelope, "response")
    status = _positive_int(response, "status")
    if status != 200:
        raise ValueError("simulation HTTP status is not 200")

    raw_body = response.get("body")
    if not isinstance(raw_body, (str, dict)):
        raise TypeError("simulation body must be string or object")

    body = json.loads(raw_body) if isinstance(raw_body, str) else raw_body
    if not isinstance(body, dict):
        raise TypeError("simulation body must decode to an object")
    if body.get("jsonrpc") != "2.0":
        raise ValueError("simulation body must be JSON-RPC 2.0")

    response_id = body.get("id")
    if response_id is not None and str(response_id) != str(response.get("request_id", request_id)):
        raise ValueError("simulation response id mismatch")

    result = body.get("result")
    if not isinstance(result, dict):
        raise TypeError("simulation body.result must be an object")

    success = _bool(result, "success")
    gas_used = _optional_hex_or_decimal(result, "gasUsed")
    revert_reason = _optional_string(result, "revertReason")
    if success and revert_reason is not None:
        raise ValueError("successful simulation cannot have a revert reason")
    if not success and revert_reason is None:
        revert_reason = "unspecified"

    balance_changes = _parse_balance_changes(result)
    output = _optional_output(result)
    allowance_required, allowance_available = _parse_allowance(
        result,
        chain_id=chain_id,
        default_account=tx_from,
    )

    output_account = _optional_string(result, "outputAccount")
    if output_account is not None:
        output_account = output_account.lower()
        if not _ADDR_RE.fullmatch(output_account):
            raise ValueError("outputAccount must be a valid address")

    simulation_result = SimulationResult(
        candidate_id=candidate_id,
        method="eth_call",
        block_number=block_number,
        success=success,
        gas_used=gas_used,
        balance_changes=tuple(change.delta for change in balance_changes),
        revert_reason=revert_reason,
        evidence_ref=str(raw_path),
        observed_at=observed_at,
    )

    return SimulationEvidence(
        candidate_id=candidate_id,
        raw_ref=str(raw_path),
        request_id=request_id,
        chain_id=chain_id,
        block_number=block_number,
        tx_from=tx_from,
        tx_to=tx_to,
        tx_data=tx_data,
        tx_value=tx_value,
        tx_gas=tx_gas,
        tx_gas_price=tx_gas_price,
        observed_at=observed_at,
        result=simulation_result,
        simulated_output=output,
        output_account=output_account,
        allowance_required=allowance_required,
        allowance_available=allowance_available,
        balance_changes=balance_changes,
    )


def _parse_balance_changes(payload: Mapping[str, Any]) -> tuple[SimulatedBalanceChange, ...]:
    raw_changes = _list(payload, "balanceChanges")
    return tuple(
        SimulatedBalanceChange(
            account=_address(change, "account"),
            delta=_parse_delta(change),
        )
        for change in raw_changes
    )


def _parse_delta(value: Mapping[str, Any]) -> TokenDelta:
    token = _parse_token(_mapping(value, "token"))
    delta = _hex_or_decimal(value, "delta", "balance delta")
    return TokenDelta(token=token, raw_delta=delta)


def _parse_allowance(
    payload: Mapping[str, Any],
    *,
    chain_id: int,
    default_account: str,
) -> tuple[TokenAmount | None, TokenAmount | None]:
    raw = payload.get("allowance")
    if raw is None:
        return None, None
    if not isinstance(raw, dict):
        raise TypeError("allowance must be an object")

    token_value = raw.get("token")
    if token_value is None:
        token = TokenRef(
            chain_id=chain_id,
            contract_address=default_account,
            symbol="ETH",
            decimals=18,
        )
    else:
        token = _parse_token(_mapping(raw, "token"))

    required = raw.get("required")
    available = raw.get("available")

    required_amount: TokenAmount | None = None
    available_amount: TokenAmount | None = None
    if required is not None:
        required_amount = TokenAmount(token, _hex_or_decimal({"x": required}, "x", "required allowance"))
    if available is not None:
        available_amount = TokenAmount(token, _hex_or_decimal({"x": available}, "x", "available allowance"))
    return required_amount, available_amount


def _optional_output(payload: Mapping[str, Any]) -> TokenAmount | None:
    raw_output = payload.get("output")
    if raw_output is None:
        return None
    if not isinstance(raw_output, dict):
        raise TypeError("output must be an object")

    token = _parse_token(_mapping(raw_output, "token"))
    amount = _hex_or_decimal(raw_output, "raw", "simulated output")
    return TokenAmount(token, amount)


def _parse_token(value: Mapping[str, Any]) -> TokenRef:
    if "chain_id" in value:
        chain_id = _positive_int(value, "chain_id")
    elif "chainId" in value:
        chain_id = _parse_int_like(value["chainId"], "chainId")
    else:
        raise TypeError("token chain id is required")
    if chain_id <= 0:
        raise ValueError("chain_id must be positive")
    address = _string(value, "address").lower()
    if not _ADDR_RE.fullmatch(address):
        raise ValueError("invalid token address")
    decimals = _non_negative_int(value, "decimals")
    if decimals > 255:
        raise ValueError("decimals must be <= 255")
    return TokenRef(
        chain_id=chain_id,
        contract_address=address,
        symbol=_string(value, "symbol"),
        decimals=decimals,
    )


def _hex_or_decimal(value: Mapping[str, Any], key: str, label: str) -> int:
    raw = value.get(key)
    if isinstance(raw, bool) or not isinstance(raw, int | str):
        raise TypeError(f"{label} must be integer-like")

    if isinstance(raw, int):
        return raw
    if _HEX_QTY_RE.fullmatch(raw):
        return int(raw, 16)
    if _INT_RE.fullmatch(raw):
        return int(raw)
    raise ValueError(f"{label} must be hex quantity or decimal integer")


def _optional_hex_or_decimal(value: Mapping[str, Any], key: str) -> int | None:
    if key not in value:
        return None
    return _hex_or_decimal(value, key, key)


def _parse_int_like(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int | str):
        raise TypeError(f"{label} must be integer-like")
    if isinstance(value, int):
        return value
    if _HEX_QTY_RE.fullmatch(value):
        return int(value, 16)
    if _INT_RE.fullmatch(value):
        return int(value)
    raise ValueError(f"{label} must be hex quantity or decimal integer")


def _positive_int(value: Mapping[str, Any], key: str) -> int:
    parsed = _hex_or_decimal(value, key, key)
    if parsed <= 0:
        raise ValueError(f"{key} must be positive")
    return parsed


def _non_negative_int(value: Mapping[str, Any], key: str) -> int:
    parsed = _hex_or_decimal(value, key, key)
    if parsed < 0:
        raise ValueError(f"{key} must be non-negative")
    return parsed


def _bool(value: Mapping[str, Any], key: str) -> bool:
    item = value.get(key)
    if not isinstance(item, bool):
        raise TypeError(f"{key} must be bool")
    return item


def _string(value: Mapping[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise ValueError(f"{key} must be a non-empty string")
    return item


def _optional_string(value: Mapping[str, Any], key: str) -> str | None:
    item = value.get(key)
    if item is None:
        return None
    if not isinstance(item, str) or not item:
        raise ValueError(f"{key} must be a string when present")
    return item


def _address(value: Mapping[str, Any], key: str) -> str:
    address = _string(value, key).lower()
    if not _ADDR_RE.fullmatch(address):
        raise ValueError(f"{key} must be a valid address")
    return address


def _mapping(value: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    nested = value.get(key)
    if not isinstance(nested, Mapping):
        raise TypeError(f"{key} must be an object")
    return nested


def _list(value: Mapping[str, Any], key: str) -> tuple[Mapping[str, Any], ...]:
    entries = value.get(key)
    if entries is None:
        return tuple()
    if not isinstance(entries, list):
        raise TypeError(f"{key} must be a list")
    return tuple(entries)


def _utc_datetime(value: str, label: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.utcoffset() is None or parsed.utcoffset().total_seconds() != 0:
        raise ValueError(f"{label} must use UTC")
    return parsed
