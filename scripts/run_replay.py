#!/usr/bin/env python3
"""Run the Day 17 paper-only replay over a saved evidence envelope."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path

from onchain_arb.replay import load_replay_fixture, report_to_dict, run_event_time_replay
from onchain_arb.strategy import load_strategy_spec


def _utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset().total_seconds() != 0:
        raise argparse.ArgumentTypeError("--as-of must be a UTC timestamp")
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", type=Path, help="saved replay evidence JSON")
    parser.add_argument("--strategy", type=Path, default=Path("config/strategy.toml"))
    parser.add_argument("--as-of", type=_utc, help="optional event-time cutoff")
    parser.add_argument("--output", type=Path, help="optional derived JSON report path")
    args = parser.parse_args()

    strategy = load_strategy_spec(args.strategy).primary
    snapshots, inventory = load_replay_fixture(args.fixture)
    report = run_event_time_replay(
        snapshots,
        inventory,
        requote_window_ms=strategy.timing.requote_window_ms,
        cluster_gap_ms=int(strategy.timing.dedup_window_seconds * 1000),
        as_of=args.as_of,
    )
    payload = report_to_dict(report)
    rendered = json.dumps(payload, indent=2, sort_keys=True)
    if args.output is None:
        print(rendered)
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n")
        print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
