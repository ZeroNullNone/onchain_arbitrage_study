"""Strict token identity and basis-risk registry.

Symbols are deliberately display-only.  Every lookup and uniqueness check uses
the EVM chain ID and the case-insensitive contract address.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
import re
import tomllib
from typing import Any, Iterable, Mapping

from onchain_arb.models import TokenRef


_EVM_ADDRESS = re.compile(r"0x[0-9a-fA-F]{40}\Z")
_TOKEN_FIELDS = frozenset(
    {
        "chain_id",
        "contract_address",
        "symbol",
        "decimals",
        "issuer",
        "classification",
        "redemption_path",
        "pause_capability",
        "blacklist_capability",
        "upgradeability",
        "haircut_bps",
        "excluded",
        "decision_reason",
        "source_urls",
    }
)
_DOCUMENT_FIELDS = frozenset({"schema_version", "mode", "reviewed_at", "tokens"})


class TokenClassification(StrEnum):
    """The token's primary basis-risk form on its registered chain."""

    CANONICAL = "canonical"
    BRIDGED = "bridged"
    WRAPPED = "wrapped"


@dataclass(frozen=True, slots=True)
class TokenRecord:
    chain_id: int
    contract_address: str
    symbol: str
    decimals: int
    issuer: str
    classification: TokenClassification
    redemption_path: str
    pause_capability: bool
    blacklist_capability: bool
    upgradeability: bool
    haircut_bps: int
    excluded: bool
    decision_reason: str
    source_urls: tuple[str, ...]

    def __post_init__(self) -> None:
        if isinstance(self.chain_id, bool) or not isinstance(self.chain_id, int):
            raise TypeError("chain_id must be an integer")
        if self.chain_id <= 0:
            raise ValueError("chain_id must be positive")
        if not isinstance(self.contract_address, str) or not _EVM_ADDRESS.fullmatch(
            self.contract_address
        ):
            raise ValueError("contract_address must be a 20-byte EVM address")
        object.__setattr__(self, "contract_address", self.contract_address.lower())
        for name in (
            "symbol",
            "issuer",
            "redemption_path",
            "decision_reason",
        ):
            if not isinstance(getattr(self, name), str) or not getattr(self, name).strip():
                raise ValueError(f"{name} is required")
        if isinstance(self.decimals, bool) or not isinstance(self.decimals, int):
            raise TypeError("decimals must be an integer")
        if not 0 <= self.decimals <= 255:
            raise ValueError("decimals must be between 0 and 255")
        if not isinstance(self.classification, TokenClassification):
            raise TypeError("classification must be TokenClassification")
        for name in (
            "pause_capability",
            "blacklist_capability",
            "upgradeability",
            "excluded",
        ):
            if not isinstance(getattr(self, name), bool):
                raise TypeError(f"{name} must be bool")
        if isinstance(self.haircut_bps, bool) or not isinstance(self.haircut_bps, int):
            raise TypeError("haircut_bps must be an integer")
        if not 0 <= self.haircut_bps <= 10_000:
            raise ValueError("haircut_bps must be between 0 and 10000")
        if not self.source_urls or any(
            not isinstance(url, str) or not url.startswith("https://")
            for url in self.source_urls
        ):
            raise ValueError("source_urls must contain at least one HTTPS URL")

    @property
    def identity_key(self) -> tuple[int, str]:
        return (self.chain_id, self.contract_address)

    @property
    def token_ref(self) -> TokenRef:
        return TokenRef(
            chain_id=self.chain_id,
            contract_address=self.contract_address,
            symbol=self.symbol,
            decimals=self.decimals,
        )


@dataclass(frozen=True, slots=True)
class TokenRegistry:
    schema_version: int
    mode: str
    reviewed_at: datetime
    tokens: tuple[TokenRecord, ...]

    def __post_init__(self) -> None:
        if isinstance(self.schema_version, bool) or not isinstance(
            self.schema_version, int
        ):
            raise TypeError("schema_version must be an integer")
        if self.schema_version != 1:
            raise ValueError("unsupported token registry schema_version")
        if not isinstance(self.mode, str):
            raise TypeError("token registry mode must be a string")
        if self.mode != "paper":
            raise ValueError("token registry mode must be paper")
        if not isinstance(self.reviewed_at, datetime):
            raise TypeError("reviewed_at must be a datetime")
        if self.reviewed_at.tzinfo is None or self.reviewed_at.utcoffset() != UTC.utcoffset(
            self.reviewed_at
        ):
            raise ValueError("reviewed_at must use UTC")
        if not self.tokens:
            raise ValueError("token registry requires at least one token")
        keys = tuple(token.identity_key for token in self.tokens)
        if len(set(keys)) != len(keys):
            raise ValueError("duplicate chain_id + contract_address token identity")

    def get(self, chain_id: int, contract_address: str) -> TokenRecord:
        """Resolve one token only by its chain-specific address identity."""

        if isinstance(chain_id, bool) or not isinstance(chain_id, int):
            raise TypeError("chain_id must be an integer")
        if not isinstance(contract_address, str):
            raise TypeError("contract_address must be a string")
        key = (chain_id, contract_address.lower())
        for token in self.tokens:
            if token.identity_key == key:
                return token
        raise KeyError(f"unknown token identity: {chain_id}:{contract_address.lower()}")

    def by_symbol(self, symbol: str) -> tuple[TokenRecord, ...]:
        """Return display matches without asserting identity or equivalence."""

        return tuple(token for token in self.tokens if token.symbol == symbol)

    def require_token_refs(self, token_refs: Iterable[TokenRef]) -> None:
        """Require exact registry coverage and metadata agreement for a universe."""

        for token_ref in token_refs:
            record = self.get(token_ref.chain_id, token_ref.contract_address)
            if record.symbol != token_ref.symbol or record.decimals != token_ref.decimals:
                raise ValueError(
                    "token metadata disagrees with registry for "
                    f"{token_ref.chain_id}:{token_ref.contract_address.lower()}"
                )


def load_token_registry(path: str | Path) -> TokenRegistry:
    """Load a registry without defaults, fallbacks, or ignored fields."""

    with Path(path).open("rb") as source:
        document = tomllib.load(source)
    if not isinstance(document, dict):
        raise TypeError("token registry document must be an object")
    _require_exact_fields(document, _DOCUMENT_FIELDS, "registry")
    raw_tokens = document["tokens"]
    if not isinstance(raw_tokens, list):
        raise TypeError("tokens must be an array")
    reviewed_at = _parse_reviewed_at(document["reviewed_at"])
    tokens = tuple(_parse_token(item, index) for index, item in enumerate(raw_tokens))
    return TokenRegistry(
        schema_version=document["schema_version"],
        mode=document["mode"],
        reviewed_at=reviewed_at,
        tokens=tokens,
    )


def _parse_token(value: Any, index: int) -> TokenRecord:
    if not isinstance(value, dict):
        raise TypeError(f"tokens[{index}] must be an object")
    _require_exact_fields(value, _TOKEN_FIELDS, f"tokens[{index}]")
    source_urls = value["source_urls"]
    if not isinstance(source_urls, list):
        raise TypeError(f"tokens[{index}].source_urls must be an array")
    try:
        classification = TokenClassification(value["classification"])
    except (TypeError, ValueError) as error:
        raise ValueError(
            f"tokens[{index}].classification must be canonical, bridged, or wrapped"
        ) from error
    return TokenRecord(
        chain_id=value["chain_id"],
        contract_address=value["contract_address"],
        symbol=value["symbol"],
        decimals=value["decimals"],
        issuer=value["issuer"],
        classification=classification,
        redemption_path=value["redemption_path"],
        pause_capability=value["pause_capability"],
        blacklist_capability=value["blacklist_capability"],
        upgradeability=value["upgradeability"],
        haircut_bps=value["haircut_bps"],
        excluded=value["excluded"],
        decision_reason=value["decision_reason"],
        source_urls=tuple(source_urls),
    )


def _require_exact_fields(
    value: Mapping[str, Any], expected: frozenset[str], location: str
) -> None:
    actual = frozenset(value)
    missing = sorted(expected - actual)
    unknown = sorted(actual - expected)
    if missing or unknown:
        raise ValueError(f"{location} fields invalid; missing={missing}, unknown={unknown}")


def _parse_reviewed_at(value: Any) -> datetime:
    if not isinstance(value, str):
        raise TypeError("reviewed_at must be an ISO-8601 string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("reviewed_at must be a valid ISO-8601 timestamp") from error
    return parsed
