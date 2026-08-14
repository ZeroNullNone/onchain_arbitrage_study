# Day 10 Cross-chain Inventory Model

## Result

The paper-only inventory module models one pre-positioned USDC/WETH balance sheet on Base and
Arbitrum. It applies a conservative Base buy and Arbitrum sell at nearly the same time, without a
bridge, wallet lookup, signature, or transaction broadcast. Chain-specific token addresses remain
distinct while `USDC` and `WETH` economic asset IDs permit conservation checks across chains.

Day 9 found no fresh tradable cross-chain edge. The numerical signal below is therefore a
deterministic acceptance example, not captured market evidence and not a profitability claim. A
live signal may enter this model only after both local legs have independent refreshed Raw evidence
and a complete cost ledger.

## Frozen balance sheet and policy

The checked-in [inventory policy](../config/inventory.toml) records every balance and limit in
integer raw token units. `accounting_price` is a fixed `Decimal` capital-occupancy mark, not a live
price or silent fallback.

| Chain | Asset | Balance | Target band | Maximum imbalance | Frozen mark | Capital |
|---|---:|---:|---:|---:|---:|---:|
| Base | USDC | 2,000 | 1,500–2,500 | 1,500 | 1 USDC | 2,000 USDC |
| Base | WETH | 1.00 | 0.50–1.50 | 1.00 | 2,000 USDC | 2,000 USDC |
| Arbitrum | USDC | 2,000 | 1,500–2,500 | 1,500 | 1 USDC | 2,000 USDC |
| Arbitrum | WETH | 1.00 | 0.50–1.50 | 1.00 | 2,000 USDC | 2,000 USDC |

Total capital occupied is 8,000 USDC. The target band is reported as operational state; maximum
imbalance is the hard trade gate measured from the target-band midpoint. Dynamic bands and optimal
allocation remain outside Day 10.

## Conservative paper signal

The example uses guaranteed minimum outputs rather than optimistic quote outputs:

- Base cheap-chain buy: spend 500 USDC and guarantee 0.25 WETH.
- Arbitrum expensive-chain sell: spend pre-positioned 0.25 WETH and guarantee 506 USDC.
- External stressed costs: 0.40 USDC on Base and 0.60 USDC on Arbitrum.
- A 1.50 USDC swap fee marked `included_in_quote_output` is evidence but is not deducted twice.
- The Base leg is observed at `02:00:00.000Z`; the Arbitrum leg at `02:00:00.400Z`. The condition
  is locked no earlier than the later refresh, `02:00:00.400Z`; the 400 ms skew passes the frozen
  1-second bound.

The two legs use pre-positioned inventory and do not assume the spread survives bridge settlement.
The guaranteed Base WETH receipt exactly equals the Arbitrum WETH sale, so total WETH is conserved.

## Accounting output

The inventory delta is:

| Chain | Asset | Before | Delta | After | In target band? |
|---|---:|---:|---:|---:|---:|
| Base | USDC | 2,000 | −500.40 | 1,499.60 | No |
| Base | WETH | 1.00 | +0.25 | 1.25 | Yes |
| Arbitrum | USDC | 2,000 | +505.40 | 2,505.40 | No |
| Arbitrum | WETH | 1.00 | −0.25 | 0.75 | Yes |

The USDC change is `506 − 500 − 0.40 − 0.60 = 5 USDC`; total WETH change is zero. Thus total
assets are conserved after explicit costs, and trade PnL equals the stablecoin balance change.
`CrossChainCostLedger` remains the single owner of PnL semantics: it consolidates only the explicit
`USDC` economic identity when chain-local tokens have matching decimals, preserves every original
`CostItem`, ignores quote-included costs for deduction, and performs no FX conversion. The inventory
delta is checked against its result.
Cross-chain rebalance cost is deliberately not included until Day 11, so this is local trade PnL,
not inventory-cycle PnL.

With the frozen two-hour capital lock assumption:

```text
capital-hour return = trade PnL / capital occupied / lock hours
                    = 5 / 8,000 / 2
                    = 0.0003125 (3.125 bps per capital-hour)
```

Required initial inventory is reported before proceeds may be reused:

- Base: 500.40 USDC for the buy and its external cost.
- Arbitrum: 0.25 WETH for the sell and 0.60 USDC for its external cost.

## Gates and failure semantics

`evaluate_inventory` returns a result without mutating the input snapshot:

- `ACCEPTED`: both refreshed legs fit the lock window, every required cost is present, balances
  cover the required initial inventory, and post-trade positions stay within maximum imbalance.
- `SIGNAL_NOT_LOCKED`: the independent leg observation skew exceeds policy.
- `COST_INCOMPLETE`: a required cost is missing; missing cost is never treated as zero.
- `INVENTORY_BLOCKED`: a required starting balance is unavailable or the trade would exceed the
  hard maximum imbalance. No partial inventory changes are returned.

Every leg retains request ID, Raw reference, UTC observation time, exact-input amount, and
guaranteed minimum output. The acceptance example uses explicit `day10_paper_fixture` references
and makes no claim that external observations exist at those values.

## Scope boundary

Only two chains, one pair, and one static policy are implemented. Real wallet balances, bridges,
live execution, multi-chain netting, portfolio optimization, dynamic bands, and rebalance economics
are excluded. Day 11 will evaluate whether restoring these inventory shifts makes the full cycle
unprofitable.
