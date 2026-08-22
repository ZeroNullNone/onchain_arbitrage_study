#!/usr/bin/env python3
"""Run the Day 18 paper-only engine over a saved evidence envelope."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path

from onchain_arb.paper_engine import PaperDecisionEngine, decision_to_dict, load_paper_fixture


def _utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset().total_seconds() != 0:
        raise argparse.ArgumentTypeError("--as-of must be a UTC timestamp")
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", type=Path, help="saved paper evidence JSON")
    parser.add_argument("--as-of", required=True, type=_utc,
                        help="UTC decision time; explicit to prevent wall-clock ambiguity")
    parser.add_argument("--output", type=Path, help="optional derived JSON report path")
    args = parser.parse_args()

    candidates, balances, allowances = load_paper_fixture(args.fixture)
    engine = PaperDecisionEngine(balances, allowances)
    decisions = [engine.process(candidate, now=args.as_of) for candidate in candidates]
    payload = {
        "schema_version": 1,
        "as_of": args.as_of.isoformat().replace("+00:00", "Z"),
        "decisions": [decision_to_dict(item) for item in decisions],
        "ending_balances": [
            {"chain_id": item.chain_id, "asset_id": item.asset_id,
             "raw_amount": item.raw_amount}
            for item in engine.balances
        ],
        "alert_count": len(engine.alerts),
    }
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
