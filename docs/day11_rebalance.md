# Day 11 Rebalance Economics

## Result

The deterministic paper simulator converts Day 10 local trade PnL into complete inventory-cycle
PnL. It implements Immediate, Threshold, and Batch policies over the same repeated inventory delta.
Every policy settles its final residual imbalance, so a reported Cycle PnL always describes a
closed inventory cycle rather than an open position.

This is an acceptance example, not live route evidence or a profitability claim. No bridge, CEX,
wallet, signature, or transaction broadcast is used. Natural-flow netting and hedging remain out of
scope.

## Accounting boundary

Each accepted paper trade contributes:

- 5 USDC of local Trade PnL after atomic costs;
- +0.25 WETH of Base inventory displacement, representing the Day 10 cheap-chain buy side; and
- a UTC observation timestamp.

Four repetitions therefore produce 20 USDC local Trade PnL and 1 WETH of cumulative displacement
before policy actions. `InventoryCycleCostLedger` is the sole owner of the final subtraction:

```text
Cycle PnL = sum(local Trade PnL) - sum(explicit rebalance costs)
```

Quote-included and atomic costs were already handled by the Day 10 ledger and are not deducted
again. A rebalance cost observation is usable only for its exact transfer amount and must retain a
request ID, Raw reference, source, UTC timestamp, and measured latency. There is no interpolation,
stale cache, guessed cost, or missing cost represented as zero. If exact-size evidence is absent,
the result is `COST_INCOMPLETE` and Cycle PnL is unavailable.

## Policy comparison

The frozen paper cost schedule is deliberately chosen to expose the economics. The complete paper
requests and responses are preserved in `tests/fixtures/day11/rebalance_costs.json`, and every
normalized test observation points back to its exact JSON entry. These values are named assumptions;
they are not external market captures.

Each rebalance event consumes a distinct observation. Even when amount and cost are identical, one
request or Raw reference cannot be reused for another event; an exhausted observation set makes the
cycle incomplete.

| Policy | Trigger | Rebalance assumption | Count / 4 trades | Frequency | Total cost | Cycle PnL |
|---|---:|---:|---:|---:|---:|---:|
| Immediate | After every trade | 0.25 WETH costs 7 USDC | 4 | 1.00 | 28 USDC | **−8 USDC** |
| Threshold | At 0.50 WETH | 0.50 WETH costs 9 USDC | 2 | 0.50 | 18 USDC | 2 USDC |
| Batch | Every 4 trades | 1.00 WETH costs 16 USDC | 1 | 0.25 | 16 USDC | 4 USDC |

The Immediate case is the required counterexample: every local trade earns +5 USDC, while its
corresponding rebalance costs 7 USDC. Four positive local trades therefore form a **−8 USDC**
inventory cycle. Local Trade PnL alone would give the wrong strategy decision.

The break-even total rebalance cost is exactly the 20 USDC local Trade PnL. For Immediate, with four
rebalance events, this is 5 USDC per rebalance. Costs below that level produce positive Cycle PnL;
costs above it produce negative Cycle PnL.

## Inventory imbalance distribution

Imbalance is sampled after each policy decision, including a restoration when triggered. All final
residuals are restored.

| Policy | Observed post-decision imbalance distribution | Ending imbalance |
|---|---|---:|
| Immediate | 0 WETH: 100% | 0 WETH |
| Threshold | 0 WETH: 50%; 0.25 WETH: 50% | 0 WETH |
| Batch | 0, 0.25, 0.50, 0.75 WETH: 25% each | 0 WETH |

Batching lowers cost frequency in this frozen example but carries larger inventory displacement
between restorations. The simulator reports this exposure rather than hiding it behind the better
Cycle PnL.

## Capacity curve

Capacity is the largest tested size with strictly positive post-rebalance Cycle PnL. The curve uses
integer raw USDC units and `Decimal` calculations throughout.

| Trade size | Local Trade PnL | Rebalance cost | Cycle PnL | Post-rebalance edge |
|---:|---:|---:|---:|---:|
| 100 USDC | 4 USDC | 2 USDC | 2 USDC | 200 bps |
| 500 USDC | 8 USDC | 7 USDC | 1 USDC | 20 bps |
| 1,000 USDC | 10 USDC | 12 USDC | −2 USDC | −20 bps |

The tested profitable capacity is therefore 500 USDC. Increasing size from 100 to 1,000 USDC
reduces edge from 200 bps to −20 bps; the 1,000 USDC point exceeds capacity. This discrete curve
does not interpolate unobserved sizes or claim a global optimum.

## Failure semantics and scope

- The final residual is always scheduled for restoration, even when a threshold or batch boundary
  was not reached. This prevents open inventory from being presented as complete Cycle PnL.
- Missing exact-size cost evidence returns `COST_INCOMPLETE`, preserves the open imbalance, and
  suppresses both rebalance cost and Cycle PnL.
- All trades in one deterministic run must share an accounting token, inventory token, and
  displacement direction. Opposing flow belongs to the natural-netting backlog.
- The implementation is read-only and paper-only. Live bridging, CEX/perp orders, funding forecasts,
  stochastic costs, and optimization are not implemented.

The exit criterion is met: cross-chain profitability is evaluated at the complete inventory-cycle
boundary, never from one local trade alone.
