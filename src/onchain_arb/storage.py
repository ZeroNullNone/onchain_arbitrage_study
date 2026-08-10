"""Append-only raw and normalized storage for quote collection."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
import os
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

import duckdb

from onchain_arb.normalize import NORMALIZED_COLUMNS


_NORMALIZED_SCHEMA = """
    request_id VARCHAR PRIMARY KEY,
    quote_id VARCHAR NOT NULL,
    raw_ref VARCHAR NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL,
    latency_ms VARCHAR NOT NULL,
    from_chain_id INTEGER NOT NULL,
    to_chain_id INTEGER NOT NULL,
    from_token_address VARCHAR NOT NULL,
    from_token_symbol VARCHAR NOT NULL,
    from_token_decimals INTEGER NOT NULL,
    from_amount_raw VARCHAR NOT NULL,
    to_token_address VARCHAR NOT NULL,
    to_token_symbol VARCHAR NOT NULL,
    to_token_decimals INTEGER NOT NULL,
    to_amount_raw VARCHAR NOT NULL,
    to_amount_min_raw VARCHAR NOT NULL,
    tool VARCHAR NOT NULL,
    duration_seconds VARCHAR NOT NULL,
    approval_address VARCHAR,
    route_fingerprint VARCHAR NOT NULL,
    route_steps_json JSON NOT NULL,
    fee_costs_json JSON NOT NULL,
    gas_costs_json JSON NOT NULL,
    transaction_request_json JSON NOT NULL
"""


@dataclass(frozen=True, slots=True)
class CollectionMetrics:
    request_count: int
    success_count: int
    parse_failure_count: int
    timeout_count: int
    rate_limited_count: int
    unavailable_route_count: int
    p50_latency_ms: float | None
    p95_latency_ms: float | None

    @property
    def success_rate(self) -> float:
        return 0.0 if self.request_count == 0 else self.success_count / self.request_count


class QuoteStorage:
    """Persist raw evidence first, then append its outcome and normalized row."""

    def __init__(self, raw_dir: Path, normalized_dir: Path, database_path: Path) -> None:
        self.raw_dir = raw_dir
        self.normalized_dir = normalized_dir
        self.database_path = database_path
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.normalized_dir.mkdir(parents=True, exist_ok=True)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                f"CREATE TABLE IF NOT EXISTS normalized_quotes ({_NORMALIZED_SCHEMA})"
            )
            connection.execute(
                """CREATE TABLE IF NOT EXISTS collection_attempts (
                    request_id VARCHAR PRIMARY KEY,
                    raw_ref VARCHAR NOT NULL,
                    route_key VARCHAR NOT NULL,
                    observed_at TIMESTAMPTZ NOT NULL,
                    latency_ms DOUBLE NOT NULL,
                    outcome VARCHAR NOT NULL,
                    error_type VARCHAR,
                    error_message VARCHAR
                )"""
            )

    def write_raw(self, envelope: Mapping[str, Any]) -> Path:
        """Atomically create one immutable raw envelope and return its absolute path."""

        return append_raw_envelope(self.raw_dir, envelope)

    def record_attempt(
        self,
        *,
        request_id: str,
        raw_ref: Path,
        route_key: str,
        observed_at: datetime,
        latency_ms: float,
        outcome: str,
        error: BaseException | None = None,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO collection_attempts VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    request_id,
                    str(raw_ref),
                    route_key,
                    observed_at,
                    latency_ms,
                    outcome,
                    None if error is None else type(error).__name__,
                    None if error is None else str(error),
                ],
            )

    def write_normalized(self, record: Mapping[str, Any]) -> Path:
        """Append one normalized row to DuckDB and one immutable Parquet part."""

        values = [record[column] for column in NORMALIZED_COLUMNS]
        placeholders = ", ".join("?" for _ in NORMALIZED_COLUMNS)
        columns = ", ".join(NORMALIZED_COLUMNS)
        part_dir = self.normalized_dir / "quotes"
        part_dir.mkdir(parents=True, exist_ok=True)
        part_path = (part_dir / f"part-{record['request_id']}.parquet").resolve()
        if part_path.exists():
            raise FileExistsError(f"normalized Parquet part already exists: {part_path}")

        with self._connect() as connection:
            connection.execute("BEGIN TRANSACTION")
            try:
                connection.execute(
                    f"INSERT INTO normalized_quotes ({columns}) VALUES ({placeholders})",
                    values,
                )
                escaped_path = str(part_path).replace("'", "''")
                connection.execute(
                    f"COPY (SELECT {columns} FROM normalized_quotes WHERE request_id = ?) "
                    f"TO '{escaped_path}' (FORMAT PARQUET)",
                    [record["request_id"]],
                )
                connection.execute("COMMIT")
            except BaseException:
                connection.execute("ROLLBACK")
                if part_path.exists():
                    part_path.unlink()
                raise
        return part_path

    def metrics(self) -> CollectionMetrics:
        with self._connect() as connection:
            row = connection.execute(
                """SELECT
                    count(*),
                    count(*) FILTER (WHERE outcome = 'success'),
                    count(*) FILTER (WHERE outcome = 'parse_failure'),
                    count(*) FILTER (WHERE outcome = 'timeout'),
                    count(*) FILTER (WHERE outcome = 'rate_limited'),
                    count(DISTINCT route_key) FILTER (WHERE outcome = 'unavailable'),
                    quantile_cont(latency_ms, 0.50),
                    quantile_cont(latency_ms, 0.95)
                FROM collection_attempts"""
            ).fetchone()
        assert row is not None
        return CollectionMetrics(
            request_count=row[0],
            success_count=row[1],
            parse_failure_count=row[2],
            timeout_count=row[3],
            rate_limited_count=row[4],
            unavailable_route_count=row[5],
            p50_latency_ms=row[6],
            p95_latency_ms=row[7],
        )

    def _connect(self) -> duckdb.DuckDBPyConnection:
        connection = duckdb.connect(str(self.database_path))
        connection.execute("SET TimeZone = 'UTC'")
        return connection


def append_raw_envelope(raw_dir: Path, envelope: Mapping[str, Any]) -> Path:
    """Atomically append a source envelope without exposing storage internals."""

    observed_at = datetime.fromisoformat(
        str(envelope["observed_at"]).replace("Z", "+00:00")
    )
    partition = raw_dir / observed_at.strftime("%Y-%m-%d")
    partition.mkdir(parents=True, exist_ok=True)
    request_id = str(envelope["request_id"])
    final_path = (
        partition / f"{observed_at.strftime('%Y%m%dT%H%M%S%fZ')}_{request_id}.json"
    )
    temporary_path = partition / f".{request_id}.{uuid4().hex}.tmp"
    serialized = json.dumps(envelope, indent=2, sort_keys=True) + "\n"
    with temporary_path.open("x", encoding="utf-8") as output:
        output.write(serialized)
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary_path, final_path)
    return final_path.resolve()
