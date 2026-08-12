# Day 8 Same-chain DEX–DEX Baseline

## Result

The paper scanner implements the frozen Base USDC/WETH slice for exact inputs of 100, 500,
and 1,000 USDC. It evaluates an Aerodrome buy followed by a Uniswap V3 sell, requires an
independently later quote for the same venues and size, and accepts nothing unless the
conservative minimum-output round trip remains positive after a complete gas/approval ledger.

The checked-in evidence is a deterministic acceptance fixture, not a claim about a live market
opportunity. Its purpose is to prove that the decision loop can reliably return **no opportunity**.

## Decision semantics

- Both legs are exact-input quotes on Base and retain venue, request ID, Raw reference, UTC
  observation time, measured latency, native-unit fee, gas, minimum output, and approval state.
- Leg two spends leg one's **minimum** WETH output, not its optimistic quoted output. This avoids
  assuming inventory that the first leg does not guarantee.
- Initial quote output only creates a gross candidate. A later comparable re-quote must still be
  gross-positive and minimum-output-positive.
- The existing `CostLedger` remains the single owner of PnL. Pool fees are already embedded in
  venue outputs and remain visible on each quote; they are not deducted twice. Gas and any
  required approval are converted upstream into USDC with their source/confidence evidence and
  deducted once.
- Unknown approval, missing re-quote, changed venue/size/path, stale timestamps, broken leg
  linkage, mixed cost currency, incomplete costs, and non-positive economics are explicit
  rejection states. Missing costs are never represented as zero.

## Acceptance evidence

`tests/fixtures/day08/edge_disappears.json` covers the three frozen sizes:

| Size | Initial state | Re-quote / cost result | Decision |
|---:|---|---|---|
| 100 USDC | Gross-positive | Edge disappears on re-quote | Reject |
| 500 USDC | Gross-positive; re-quote survives | Minimum edge is 0.40 USDC; gas is 0.50 USDC | Reject |
| 1,000 USDC | Gross-positive | Re-quote absent | Reject |

Funnel metrics reconstructed by `tests/test_same_chain.py`:

- Attempts: 3
- Gross candidates: 3
- Re-quote survivors: 1
- Net-positive survivors: 0
- Largest false-positive source: `net_not_positive` (two applicable decisions)

All applicable reject reasons remain attached to each decision; for example, the 100 USDC case
records quoted edge disappearance, minimum-output failure, and net failure rather than stopping
at the first reason.

## Evidence boundary

The venue names in the deterministic fixture exercise the two-venue interface but are not fresh
on-chain quotes. Therefore Day 8 establishes scanner behavior and a defensible negative result
for the fixture only. It does not claim current Aerodrome/Uniswap profitability, quote lifetime,
or an executable atomic route. Live signing, broadcasting, smart-contract construction, extra
pairs, and cross-chain signals remain out of scope.
