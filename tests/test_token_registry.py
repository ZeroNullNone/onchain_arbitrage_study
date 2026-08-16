"""Day 12 acceptance tests for chain-specific token identity and basis risk."""

from dataclasses import replace
from pathlib import Path
import tomllib

import pytest

from onchain_arb.models import TokenRef
from onchain_arb.token_registry import TokenClassification, load_token_registry


ROOT = Path(__file__).parent.parent
CONFIG = ROOT / "config" / "token_registry.toml"
WEEK2_CONFIG = ROOT / "config" / "week2.toml"


def test_current_universe_registry_is_complete_and_valid() -> None:
    registry = load_token_registry(CONFIG)

    assert registry.schema_version == 1
    assert registry.mode == "paper"
    assert len(registry.tokens) == 4
    assert {token.classification for token in registry.tokens} == {
        TokenClassification.CANONICAL,
        TokenClassification.BRIDGED,
        TokenClassification.WRAPPED,
    }
    assert all(token.issuer and token.redemption_path for token in registry.tokens)
    assert all(token.decision_reason and token.source_urls for token in registry.tokens)
    assert all(0 <= token.haircut_bps <= 10_000 for token in registry.tokens)


def test_identity_key_is_chain_id_plus_case_insensitive_contract_address() -> None:
    registry = load_token_registry(CONFIG)

    base_usdc = registry.get(
        8453, "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
    )

    assert base_usdc.identity_key == (
        8453,
        "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
    )
    assert registry.get(8453, base_usdc.contract_address.upper().replace("0X", "0x")) is base_usdc
    with pytest.raises(KeyError, match="unknown token identity"):
        registry.get(42161, base_usdc.contract_address)


def test_same_symbol_is_display_only_and_does_not_imply_equivalence() -> None:
    registry = load_token_registry(CONFIG)

    usdc_matches = registry.by_symbol("USDC")
    weth_matches = registry.by_symbol("WETH")

    assert len(usdc_matches) == len(weth_matches) == 2
    assert usdc_matches[0].identity_key != usdc_matches[1].identity_key
    assert weth_matches[0].identity_key != weth_matches[1].identity_key
    assert {token.classification for token in weth_matches} == {
        TokenClassification.WRAPPED,
        TokenClassification.BRIDGED,
    }


def test_registry_covers_exact_frozen_week2_token_refs() -> None:
    registry = load_token_registry(CONFIG)
    with WEEK2_CONFIG.open("rb") as source:
        week2_tokens = tomllib.load(source)["tokens"]
    refs = tuple(
        TokenRef(
            chain_id=token["chain_id"],
            contract_address=token["address"],
            symbol=token["symbol"],
            decimals=token["decimals"],
        )
        for token in week2_tokens
    )

    registry.require_token_refs(refs)
    assert {token.identity_key for token in registry.tokens} == {
        (ref.chain_id, ref.contract_address.lower()) for ref in refs
    }

    wrong_decimals = replace(refs[0], decimals=18)
    with pytest.raises(ValueError, match="metadata disagrees"):
        registry.require_token_refs((wrong_decimals,))
    unknown = TokenRef(8453, "0x0000000000000000000000000000000000000001", "USDC", 6)
    with pytest.raises(KeyError, match="unknown token identity"):
        registry.require_token_refs((unknown,))


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("haircut_bps = 25", "haircut_bps = -1", "haircut_bps"),
        ('classification = "canonical"', 'classification = "synthetic"', "classification"),
        ("pause_capability = true", 'pause_capability = "unknown"', "pause_capability"),
        ("issuer = \"Circle Internet Financial\"", "", "fields invalid"),
    ],
)
def test_invalid_or_missing_risk_metadata_is_rejected(
    tmp_path: Path, old: str, new: str, message: str
) -> None:
    path = tmp_path / "invalid.toml"
    path.write_text(CONFIG.read_text().replace(old, new, 1))

    with pytest.raises((TypeError, ValueError), match=message):
        load_token_registry(path)


def test_duplicate_identity_is_rejected_even_when_address_case_differs(
    tmp_path: Path,
) -> None:
    document = CONFIG.read_text()
    first_token = document.split("[[tokens]]", maxsplit=2)[1]
    path = tmp_path / "duplicate.toml"
    path.write_text(document + "\n[[tokens]]" + first_token)

    with pytest.raises(ValueError, match="duplicate chain_id"):
        load_token_registry(path)
