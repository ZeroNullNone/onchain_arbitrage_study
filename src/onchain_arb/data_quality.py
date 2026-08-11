"""Repeatable Week 1 quote data-quality gate.

The audit is deliberately read-only.  It validates the append-only attempt log,
its normalized projection, and each raw evidence reference before calculating
the Day 7 gate metrics.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import tomllib
from typing import Any, Mapping

import duckdb

from onchain_arb.normalize import NORMALIZED_COLUMNS


ATTEMPT_COLUMNS = (
    "request_id",
    "raw_ref",
    "route_key",
    "observed_at",
    "latency_ms",
    "outcome",
    "error_type",
    "error_message",
)
CORE_NORMALIZED_COLUMNS = tuple(
    column for column in NORMALIZED_COLUMNS if column != "approval_address"
)
CORE_ATTEMPT_COLUMNS = ATTEMPT_COLUMNS[:6]


@dataclass(frozen=True, slots=True)
class RouteAvailability:
    route_key: str
    attempts: int
    successes: int
    availability: str


@dataclass(frozen=True, slots=True)
class SizeSensitivity:
    route: str
    sizes_raw: tuple[str, ...]
    observations_by_size: Mapping[str, int]
    median_output_per_input: Mapping[str, str]
    largest_vs_smallest_bps: str | None


@dataclass(frozen=True, slots=True)
class DataQualityReport:
    database: str
    config_sha256: str
    schema_complete: bool
    schema_errors: tuple[str, ...]
    attempt_count: int
    valid_observations: int
    minimum_valid_observations: int
    observed_at_start: str | None
    observed_at_end: str | None
    maximum_inter_attempt_gap_seconds: str | None
    outcome_counts: Mapping[str, int]
    parse_success_rate: str
    latency_p50_ms: str | None
    latency_p95_ms: str | None
    raw_reference_coverage: str
    timestamp_coverage: str
    latency_coverage: str
    duplicate_counts: Mapping[str, int]
    missing_core_counts: Mapping[str, int]
    projection_mismatch_count: int
    timestamp_order_violations: int
    decimals_valid: bool
    decimal_errors: tuple[str, ...]
    route_availability: tuple[RouteAvailability, ...]
    size_sensitivity: tuple[SizeSensitivity, ...]
    gate_passed: bool
    failed_gates: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def frozen_config_hash(path: str | Path) -> str:
    """Return the SHA-256 of the exact frozen config bytes."""

    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_expected_decimals(path: str | Path) -> dict[tuple[int, str], int]:
    """Load explicit chain/address decimal identities from a TOML config."""

    with Path(path).open("rb") as source:
        document = tomllib.load(source)
    tokens = document.get("tokens")
    if not isinstance(tokens, list) or not tokens:
        raise ValueError("frozen config must contain [[tokens]] entries")
    result: dict[tuple[int, str], int] = {}
    for token in tokens:
        if not isinstance(token, dict):
            raise TypeError("each token config must be an object")
        chain_id = token.get("chain_id")
        address = token.get("address")
        decimals = token.get("decimals")
        if (
            not isinstance(chain_id, int)
            or isinstance(chain_id, bool)
            or chain_id <= 0
            or not isinstance(address, str)
            or not address
            or not isinstance(decimals, int)
            or isinstance(decimals, bool)
            or not 0 <= decimals <= 255
        ):
            raise ValueError("token chain_id/address/decimals are invalid")
        key = (chain_id, address.lower())
        if key in result:
            raise ValueError(f"duplicate token identity in frozen config: {key}")
        result[key] = decimals
    return result


def audit_quote_database(
    database_path: str | Path,
    config_path: str | Path,
    *,
    minimum_valid_observations: int = 200,
) -> DataQualityReport:
    """Audit one collector database and all raw files referenced by it."""

    if minimum_valid_observations <= 0:
        raise ValueError("minimum valid observations must be positive")
    database = Path(database_path).resolve()
    config = Path(config_path).resolve()
    expected_decimals = load_expected_decimals(config)

    with duckdb.connect(str(database), read_only=True) as connection:
        connection.execute("SET TimeZone = 'UTC'")
        schema_errors = _schema_errors(connection)
        if schema_errors:
            return _schema_failure_report(
                database, config, minimum_valid_observations, schema_errors
            )

        attempts = connection.execute(
            f"SELECT {', '.join(ATTEMPT_COLUMNS)} FROM collection_attempts ORDER BY rowid"
        ).fetchall()
        normalized = connection.execute(
            f"SELECT {', '.join(NORMALIZED_COLUMNS)} FROM normalized_quotes ORDER BY rowid"
        ).fetchall()

    attempt_records = [dict(zip(ATTEMPT_COLUMNS, row, strict=True)) for row in attempts]
    quote_records = [dict(zip(NORMALIZED_COLUMNS, row, strict=True)) for row in normalized]
    outcome_counts = Counter(str(row["outcome"]) for row in attempt_records)
    raw_valid, raw_total, time_valid, latency_valid = _raw_coverage(
        attempt_records, quote_records
    )
    missing = _missing_core_counts(attempt_records, quote_records)
    duplicates = _duplicate_counts(attempt_records, quote_records)
    timestamp_violations = _timestamp_order_violations(attempt_records)
    decimal_errors = _decimal_errors(quote_records, expected_decimals)
    parse_denominator = outcome_counts["success"] + outcome_counts["parse_failure"]
    parse_rate = _ratio(outcome_counts["success"], parse_denominator)
    attempt_count = len(attempt_records)
    valid_observations = len(quote_records)
    projection_mismatch_count = len(
        {row["request_id"] for row in attempt_records if row["outcome"] == "success"}
        ^ {row["request_id"] for row in quote_records}
    )
    timestamps = [row["observed_at"] for row in attempt_records]
    latency_values = [Decimal(str(row["latency_ms"])) for row in attempt_records]
    failed_gates: list[str] = []
    if valid_observations < minimum_valid_observations:
        failed_gates.append("valid_observations")
    if raw_valid != raw_total:
        failed_gates.append("raw_reference_coverage")
    if time_valid != attempt_count:
        failed_gates.append("timestamp_coverage")
    if latency_valid != attempt_count:
        failed_gates.append("latency_coverage")
    if parse_denominator == 0 or Decimal(parse_rate) < Decimal("0.95"):
        failed_gates.append("parse_success_rate")
    if decimal_errors:
        failed_gates.append("decimals")
    if any(missing.values()):
        failed_gates.append("missing_core_fields")
    if any(duplicates.values()):
        failed_gates.append("duplicates")
    if timestamp_violations:
        failed_gates.append("timestamp_order")
    if projection_mismatch_count:
        failed_gates.append("normalized_projection")

    return DataQualityReport(
        database=str(database),
        config_sha256=frozen_config_hash(config),
        schema_complete=True,
        schema_errors=(),
        attempt_count=attempt_count,
        valid_observations=valid_observations,
        minimum_valid_observations=minimum_valid_observations,
        observed_at_start=None if not timestamps else _utc_text(min(timestamps)),
        observed_at_end=None if not timestamps else _utc_text(max(timestamps)),
        maximum_inter_attempt_gap_seconds=_maximum_gap_seconds(timestamps),
        outcome_counts=dict(sorted(outcome_counts.items())),
        parse_success_rate=parse_rate,
        latency_p50_ms=None if not latency_values else _decimal_text(_quantile(latency_values, Decimal("0.5"))),
        latency_p95_ms=None if not latency_values else _decimal_text(_quantile(latency_values, Decimal("0.95"))),
        raw_reference_coverage=_ratio(raw_valid, raw_total),
        timestamp_coverage=_ratio(time_valid, attempt_count),
        latency_coverage=_ratio(latency_valid, attempt_count),
        duplicate_counts=duplicates,
        missing_core_counts=missing,
        projection_mismatch_count=projection_mismatch_count,
        timestamp_order_violations=timestamp_violations,
        decimals_valid=not decimal_errors,
        decimal_errors=tuple(decimal_errors),
        route_availability=_route_availability(attempt_records),
        size_sensitivity=_size_sensitivity(quote_records),
        gate_passed=not failed_gates,
        failed_gates=tuple(failed_gates),
    )


def _schema_errors(connection: duckdb.DuckDBPyConnection) -> tuple[str, ...]:
    tables = {row[0] for row in connection.execute("SHOW TABLES").fetchall()}
    errors: list[str] = []
    for table, expected in (
        ("collection_attempts", ATTEMPT_COLUMNS),
        ("normalized_quotes", NORMALIZED_COLUMNS),
    ):
        if table not in tables:
            errors.append(f"missing table: {table}")
            continue
        actual = {
            row[0]
            for row in connection.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = ?",
                [table],
            ).fetchall()
        }
        errors.extend(f"missing column: {table}.{column}" for column in expected if column not in actual)
    return tuple(errors)


def _schema_failure_report(
    database: Path,
    config: Path,
    minimum: int,
    errors: tuple[str, ...],
) -> DataQualityReport:
    return DataQualityReport(
        database=str(database),
        config_sha256=frozen_config_hash(config),
        schema_complete=False,
        schema_errors=errors,
        attempt_count=0,
        valid_observations=0,
        minimum_valid_observations=minimum,
        observed_at_start=None,
        observed_at_end=None,
        maximum_inter_attempt_gap_seconds=None,
        outcome_counts={},
        parse_success_rate="0",
        latency_p50_ms=None,
        latency_p95_ms=None,
        raw_reference_coverage="0",
        timestamp_coverage="0",
        latency_coverage="0",
        duplicate_counts={},
        missing_core_counts={},
        projection_mismatch_count=0,
        timestamp_order_violations=0,
        decimals_valid=False,
        decimal_errors=("schema incomplete; decimals were not audited",),
        route_availability=(),
        size_sensitivity=(),
        gate_passed=False,
        failed_gates=("schema",),
    )


def _raw_coverage(
    attempts: list[dict[str, Any]], quotes: list[dict[str, Any]]
) -> tuple[int, int, int, int]:
    raw_valid = time_valid = latency_valid = 0
    envelopes: dict[str, Mapping[str, Any]] = {}
    for record in attempts:
        try:
            path = Path(str(record["raw_ref"]))
            envelope = json.loads(path.read_text(), parse_float=Decimal)
            if envelope.get("request_id") != record["request_id"]:
                continue
            raw_valid += 1
            envelopes[str(path)] = envelope
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            continue
        try:
            timestamp = datetime.fromisoformat(
                str(envelope["observed_at"]).replace("Z", "+00:00")
            )
            stored = record["observed_at"]
            if (
                timestamp.utcoffset() is not None
                and timestamp.utcoffset().total_seconds() == 0
                and stored.utcoffset() is not None
                and stored.utcoffset().total_seconds() == 0
                and timestamp == stored
            ):
                time_valid += 1
        except (KeyError, TypeError, ValueError):
            pass
        try:
            raw_latency = Decimal(str(envelope["latency_ms"]))
            stored_latency = Decimal(str(record["latency_ms"]))
            if raw_latency >= 0 and stored_latency >= 0:
                latency_valid += 1
        except (KeyError, InvalidOperation, TypeError, ValueError):
            pass
    for record in quotes:
        envelope = envelopes.get(str(Path(str(record["raw_ref"]))))
        if envelope is None or envelope.get("request_id") != record["request_id"]:
            continue
        try:
            timestamp = datetime.fromisoformat(
                str(envelope["observed_at"]).replace("Z", "+00:00")
            )
            latency = Decimal(str(envelope["latency_ms"]))
            if timestamp == record["observed_at"] and latency == Decimal(str(record["latency_ms"])):
                raw_valid += 1
        except (KeyError, InvalidOperation, TypeError, ValueError):
            pass
    return raw_valid, len(attempts) + len(quotes), time_valid, latency_valid


def _missing_core_counts(
    attempts: list[dict[str, Any]], quotes: list[dict[str, Any]]
) -> dict[str, int]:
    result: dict[str, int] = {}
    for prefix, records, columns in (
        ("attempt", attempts, CORE_ATTEMPT_COLUMNS),
        ("quote", quotes, CORE_NORMALIZED_COLUMNS),
    ):
        for column in columns:
            count = sum(
                value is None or (isinstance(value, str) and not value.strip())
                for value in (record[column] for record in records)
            )
            if count:
                result[f"{prefix}.{column}"] = count
    return result


def _duplicate_counts(
    attempts: list[dict[str, Any]], quotes: list[dict[str, Any]]
) -> dict[str, int]:
    def duplicates(records: list[dict[str, Any]], column: str) -> int:
        values = [record[column] for record in records]
        return len(values) - len(set(values))

    return {
        "attempt_request_id": duplicates(attempts, "request_id"),
        "attempt_raw_ref": duplicates(attempts, "raw_ref"),
        "quote_request_id": duplicates(quotes, "request_id"),
        "quote_id": duplicates(quotes, "quote_id"),
        "quote_raw_ref": duplicates(quotes, "raw_ref"),
    }


def _timestamp_order_violations(records: list[dict[str, Any]]) -> int:
    latest: dict[str, datetime] = {}
    violations = 0
    for record in records:
        route = str(record["route_key"])
        timestamp = record["observed_at"]
        if route in latest and timestamp < latest[route]:
            violations += 1
        latest[route] = timestamp
    return violations


def _decimal_errors(
    records: list[dict[str, Any]], expected: Mapping[tuple[int, str], int]
) -> list[str]:
    errors: set[str] = set()
    observed_identity: dict[tuple[int, str], set[int]] = defaultdict(set)
    for index, record in enumerate(records):
        for side in ("from", "to"):
            chain_id = record[f"{side}_chain_id"]
            address = str(record[f"{side}_token_address"]).lower()
            decimals = record[f"{side}_token_decimals"]
            identity = (chain_id, address)
            observed_identity[identity].add(decimals)
            expected_value = expected.get(identity)
            if expected_value is None:
                errors.add(f"unconfigured token identity: {chain_id}:{address}")
            elif decimals != expected_value:
                errors.add(
                    f"decimal mismatch for {chain_id}:{address}: {decimals} != {expected_value}"
                )
        for column in ("from_amount_raw", "to_amount_raw", "to_amount_min_raw"):
            value = str(record[column])
            if not value.isdecimal():
                errors.add(f"row {index} {column} is not integer raw units")
        if str(record["to_amount_raw"]).isdecimal() and str(record["to_amount_min_raw"]).isdecimal():
            if int(record["to_amount_min_raw"]) > int(record["to_amount_raw"]):
                errors.add(f"row {index} minimum output exceeds output")
        for column in ("fee_costs_json", "gas_costs_json"):
            try:
                costs = json.loads(record[column])
                if not isinstance(costs, list):
                    raise TypeError
                for cost in costs:
                    if not isinstance(cost, dict):
                        raise TypeError
                    decimals = cost.get("token_decimals")
                    amount_raw = cost.get("amount_raw")
                    if (
                        not isinstance(decimals, int)
                        or isinstance(decimals, bool)
                        or not 0 <= decimals <= 255
                        or not isinstance(amount_raw, str)
                        or not amount_raw.isdecimal()
                    ):
                        raise ValueError
            except (TypeError, ValueError, json.JSONDecodeError):
                errors.add(f"row {index} {column} has invalid raw-unit metadata")
    for identity, values in observed_identity.items():
        if len(values) != 1:
            errors.add(f"inconsistent decimals for {identity[0]}:{identity[1]}")
    return sorted(errors)


def _route_availability(
    records: list[dict[str, Any]],
) -> tuple[RouteAvailability, ...]:
    totals: Counter[str] = Counter()
    successes: Counter[str] = Counter()
    for record in records:
        route = str(record["route_key"])
        totals[route] += 1
        if record["outcome"] == "success":
            successes[route] += 1
    return tuple(
        RouteAvailability(route, totals[route], successes[route], _ratio(successes[route], totals[route]))
        for route in sorted(totals)
    )


def _size_sensitivity(records: list[dict[str, Any]]) -> tuple[SizeSensitivity, ...]:
    grouped: dict[str, dict[int, list[Decimal]]] = defaultdict(lambda: defaultdict(list))
    for record in records:
        route = (
            f"{record['from_chain_id']}:{record['from_token_symbol']}->"
            f"{record['to_chain_id']}:{record['to_token_symbol']}"
        )
        input_raw = int(record["from_amount_raw"])
        output_per_input = Decimal(record["to_amount_raw"]) / Decimal(input_raw)
        grouped[route][input_raw].append(output_per_input)

    result: list[SizeSensitivity] = []
    for route in sorted(grouped):
        by_size = grouped[route]
        sizes = sorted(by_size)
        medians = {size: _median(by_size[size]) for size in sizes}
        change: Decimal | None = None
        if len(sizes) >= 2 and medians[sizes[0]] != 0:
            change = (
                (medians[sizes[-1]] / medians[sizes[0]]) - Decimal(1)
            ) * Decimal(10_000)
        result.append(
            SizeSensitivity(
                route=route,
                sizes_raw=tuple(str(size) for size in sizes),
                observations_by_size={str(size): len(by_size[size]) for size in sizes},
                median_output_per_input={
                    str(size): _decimal_text(medians[size]) for size in sizes
                },
                largest_vs_smallest_bps=None if change is None else _decimal_text(change),
            )
        )
    return tuple(result)


def _median(values: list[Decimal]) -> Decimal:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / Decimal(2)


def _quantile(values: list[Decimal], fraction: Decimal) -> Decimal:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = Decimal(len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * weight


def _maximum_gap_seconds(timestamps: list[datetime]) -> str | None:
    ordered = sorted(timestamps)
    if len(ordered) < 2:
        return None
    largest = max(later - earlier for earlier, later in zip(ordered, ordered[1:]))
    seconds = Decimal(largest.days * 86_400 + largest.seconds) + Decimal(largest.microseconds).scaleb(-6)
    return _decimal_text(seconds)


def _utc_text(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _ratio(numerator: int, denominator: int) -> str:
    if denominator == 0:
        return "0"
    return _decimal_text(Decimal(numerator) / Decimal(denominator))


def _decimal_text(value: Decimal) -> str:
    return format(value.normalize(), "f")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the read-only Day 7 data gate")
    parser.add_argument("database", type=Path)
    parser.add_argument("--config", type=Path, default=Path("config/week2.toml"))
    parser.add_argument("--minimum-valid", type=int, default=200)
    args = parser.parse_args()
    report = audit_quote_database(
        args.database,
        args.config,
        minimum_valid_observations=args.minimum_valid,
    )
    print(json.dumps(report.to_dict(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
