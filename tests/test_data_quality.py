"""Day 7 repeatable data-quality gate tests."""

from datetime import datetime
from decimal import Decimal
import json
from pathlib import Path

import duckdb

from onchain_arb.adapters.lifi import load_raw_quote
from onchain_arb.data_quality import audit_quote_database, frozen_config_hash
from onchain_arb.normalize import normalize_lifi_quote
from onchain_arb.storage import QuoteStorage


ROOT = Path(__file__).parent.parent
CONFIG = ROOT / "config" / "week2.toml"
FIXTURES = sorted((Path(__file__).parent / "fixtures" / "lifi").glob("*.json"))


def _fixture_database(tmp_path: Path) -> Path:
    database = tmp_path / "quotes.duckdb"
    storage = QuoteStorage(tmp_path / "raw", tmp_path / "normalized", database)
    for path in FIXTURES:
        quote = load_raw_quote(path)
        route_key = (
            f"{quote.request.from_chain_id}_{quote.request.to_chain_id}_"
            f"{quote.input_amount.token.symbol}_{quote.output_amount.token.symbol}_"
            f"{quote.input_amount.raw_amount}"
        )
        storage.record_attempt(
            request_id=quote.request_id,
            raw_ref=path.resolve(),
            route_key=route_key,
            observed_at=quote.observed_at,
            latency_ms=float(quote.latency_ms),
            outcome="success",
        )
        storage.write_normalized(normalize_lifi_quote(quote))
    return database


def test_complete_fixture_dataset_passes_all_gates(tmp_path: Path) -> None:
    database = _fixture_database(tmp_path)

    report = audit_quote_database(
        database, CONFIG, minimum_valid_observations=len(FIXTURES)
    )

    assert report.gate_passed
    assert report.schema_complete
    assert report.valid_observations == report.attempt_count == 9
    assert report.raw_reference_coverage == "1"
    assert report.timestamp_coverage == "1"
    assert report.latency_coverage == "1"
    assert report.parse_success_rate == "1"
    assert report.decimals_valid
    assert not report.missing_core_counts
    assert not any(report.duplicate_counts.values())
    assert report.timestamp_order_violations == 0
    assert len(report.route_availability) == 9
    assert all(item.availability == "1" for item in report.route_availability)
    assert {item.route for item in report.size_sensitivity} == {
        "8453:USDC->8453:WETH",
        "8453:USDC->42161:USDC",
        "42161:USDC->42161:WETH",
    }
    assert all(len(item.sizes_raw) == 3 for item in report.size_sensitivity)
    assert report.config_sha256 == frozen_config_hash(CONFIG)


def test_missing_raw_and_insufficient_sample_fail_explicitly(tmp_path: Path) -> None:
    database = tmp_path / "quotes.duckdb"
    storage = QuoteStorage(tmp_path / "raw", tmp_path / "normalized", database)
    missing = tmp_path / "raw" / "does-not-exist.json"
    storage.record_attempt(
        request_id="missing-raw",
        raw_ref=missing,
        route_key="route",
        observed_at=datetime.fromisoformat("2026-08-11T00:00:00+00:00"),
        latency_ms=Decimal("1.25"),
        outcome="parse_failure",
        error=ValueError("saved failure"),
    )

    report = audit_quote_database(database, CONFIG)

    assert not report.gate_passed
    assert report.raw_reference_coverage == "0"
    assert report.parse_success_rate == "0"
    assert set(report.failed_gates) >= {
        "valid_observations",
        "raw_reference_coverage",
        "timestamp_coverage",
        "latency_coverage",
        "parse_success_rate",
    }


def test_schema_failure_is_reported_without_querying_missing_tables(
    tmp_path: Path,
) -> None:
    database = tmp_path / "empty.duckdb"
    with duckdb.connect(str(database)):
        pass

    report = audit_quote_database(database, CONFIG)

    assert not report.schema_complete
    assert report.failed_gates == ("schema",)
    assert set(report.schema_errors) == {
        "missing table: collection_attempts",
        "missing table: normalized_quotes",
    }


def test_frozen_token_metadata_controls_decimal_correctness(tmp_path: Path) -> None:
    database = _fixture_database(tmp_path)
    config = tmp_path / "wrong-decimals.toml"
    document = CONFIG.read_text().replace(
        'address = "0x4200000000000000000000000000000000000006"\n'
        "decimals = 18",
        'address = "0x4200000000000000000000000000000000000006"\n'
        "decimals = 6",
    )
    config.write_text(document)

    report = audit_quote_database(
        database, config, minimum_valid_observations=len(FIXTURES)
    )

    assert not report.gate_passed
    assert not report.decimals_valid
    assert report.failed_gates == ("decimals",)
    assert any("decimal mismatch" in error for error in report.decimal_errors)


def test_cli_report_shape_is_json_serializable(tmp_path: Path) -> None:
    report = audit_quote_database(
        _fixture_database(tmp_path),
        CONFIG,
        minimum_valid_observations=len(FIXTURES),
    )

    encoded = json.dumps(report.to_dict(), sort_keys=True)

    assert '"gate_passed": true' in encoded
