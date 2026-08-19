# Day 15 — Hypothesis Ranking & Strategic Verdict

## 1. Executive Summary

Day 15 applies a unified, evidence-driven multi-criteria scorecard to evaluate the project's three core research hypotheses ($H1$, $H2$, $H3$). Based on empirical evidence and deterministic models established across Days 1–14:

1. **H1 (Cross-chain Pre-positioned Inventory Arbitrage)** achieves the highest score (**75 / 100**) and is selected as the **PRIMARY** strategy. It advances to Day 16 for full Strategy Specification.
2. **H2 (Same-chain DEX–DEX Public Round-Trip Baseline)** achieves **51 / 100** and is designated as the **BACKUP / CONTROL BASELINE**. It serves as an ongoing negative-control benchmark and simulation testbed.
3. **H3 (Aggregator Route Dispersion as Standalone Arbitrage)** achieves the lowest score (**26 / 100**) and is **FORMALLY KILLED**. It is eliminated as an arbitrage strategy and retained solely as a read-only routing analytics tool.

All scoring inputs are linked directly to raw evidence fixtures, deterministic acceptance tests, and cost ledgers. No hypothetical profitability is assumed, and no forward-looking alpha claims are made.

---

## 2. Formal Scorecard Dimensions & Weights

The scorecard uses 7 weighted dimensions totaling 100 points:

| Dimension | Weight | Definition & Evaluation Basis |
|:---|---:|:---|
| **Conservative Net-Edge Evidence** | 25 | Empirical proof of positive net PnL after conservative minimum output, gas, swap fees, approval, and amortized rebalance costs. |
| **Lifetime vs Decision Latency** | 20 | Observed opportunity duration relative to measured asynchronous Python scanner decision latency (400ms–1000ms). |
| **Capital Efficiency** | 15 | Capital turnover, balance sheet idle requirements ($8,000 band for $500 trade sizes), and capital-hour returns. |
| **Infrastructure Fit** | 15 | Feasibility within the project's Python read-only/simulation stack without requiring C++ MEV searcher / private builder infrastructure. |
| **Ability to Lock Profit** | 10 | Degree of atomicity or conditional lockability without unhedgeable cross-chain price drift. |
| **Data Quality** | 10 | Precision of integer raw units, Decimal accounting, 100% cost completeness, and contract-address token registry. |
| **Operational Tail Risk** | 5 | Vulnerability to bridge exploits, token basis risk, contract upgrades, issuer freezes, and inventory drift. |
| **Total** | **100** | |

---

## 3. Scorecard Evaluation Matrix

| Evaluation Dimension | Weight | H1: Cross-Chain Inventory | H2: Same-Chain Baseline | H3: Route Dispersion |
|:---|---:|:---:|:---:|:---:|
| 1. Conservative Net-Edge Evidence | 25 | **18** | **5** | **3** |
| 2. Lifetime vs Decision Latency | 20 | **16** | **3** | **4** |
| 3. Capital Efficiency | 15 | **9** | **13** | **4** |
| 4. Infrastructure Fit | 15 | **14** | **8** | **6** |
| 5. Ability to Lock Profit | 10 | **7** | **9** | **1** |
| 6. Data Quality | 10 | **8** | **9** | **7** |
| 7. Operational Tail Risk | 5 | **3** | **4** | **1** |
| **Total Score** | **100** | **75 / 100** | **51 / 100** | **26 / 100** |
| **Strategic Verdict** | — | **PRIMARY (Keep & Specify)** | **BACKUP (Control Baseline)** | **KILL (Formally Discarded)** |

---

## 4. Deep-Dive Evaluation by Hypothesis

### 4.1 H1 — Cross-chain Pre-positioned Inventory Arbitrage (Score: 75 / 100 — PRIMARY)

- **Hypothesis Statement**: Quoted price dislocations between liquid L2 pairs (Base, Arbitrum, Optimism USDC/WETH) can be captured via pre-positioned dual-chain inventory without bridge settlement latency, yielding strictly positive Cycle PnL after conservative minimum output and amortized rebalance costs.
- **Null Hypothesis ($H_0$)**: Cross-chain price dislocations disappear upon independent dual-leg re-quotes, or total cycle rebalancing and capital costs exceed gross spreads, yielding non-positive Cycle PnL.
- **Sample Size & Sparsity**: $N = 24$ evaluated scenarios across Week 1 & 2 fixtures; flagged `is_sparse = True` for live synchronized cross-chain captures ($N < 20$).

#### Supporting Evidence
1. **Bridge-Free Dual-Leg Execution**: [Day 10 Inventory Model](day10_inventory_model.md#L58-L73) proves that pre-positioned inventory allows simultaneous execution on Base and Arbitrum, avoiding bridge transit latency and locking local trade profit (+5 USDC on a 500 USDC trade size).
2. **Positive Amortized Cycle PnL**: [Day 11 Rebalance Economics](day11_rebalance.md#L47-L58) demonstrates that Threshold (+2 USDC) and Batch (+4 USDC) policies achieve positive Cycle PnL after settling all residual imbalances.
3. **Bounded Capacity**: [Day 11 Capacity Curve](day11_rebalance.md#L80-L88) establishes profitable capacity up to 500 USDC (+20 bps net edge), providing an explicit operational bound.
4. **End-to-End Pipeline Validation**: [Day 14 Scanner v1](day14_scanner.md#L19-L33) successfully processes cross-chain candidates through deduplication, re-quotes, cost ledgers, and virtual balance sheets.

#### Contradictory Evidence & Key Challenges
1. **Immediate Rebalance Counterexample**: [Day 11 Rebalance Economics](day11_rebalance.md#L48-L54) shows that rebalancing after every trade incurs 28 USDC in costs against 20 USDC local profit, turning Cycle PnL negative (-8 USDC).
2. **Capacity Collapse at Scale**: At 1,000 USDC size, post-rebalance edge collapses to -20 bps (-2 USDC), proving scalability is strictly bounded.
3. **Substantial Capital Lock**: Maintaining dual-chain target bands requires $8,000 in capital for $500 trade sizes, yielding a moderate 3.125 bps/capital-hour return.
4. **Token Basis & Issuer Risk**: [Day 12 Token Risk](day12_token_risk.md#L8-L24) shows Arbitrum WETH relies on Canonical Bridge and upgradeable proxies, while USDC contains Circle freeze/upgrade capabilities.

#### Unknowns & Open Questions
- Optimal rebalance threshold under non-stationary L2 gas spikes and fee volatility.
- Exact leg execution asymmetry during high network congestion.
- Probability of natural flow netting over continuous multi-day observation windows.

#### Verdict & Next Steps
- **Verdict**: **MODIFY & ADVANCE AS PRIMARY**.
- **Action**: Advances to Day 16 for comprehensive Strategy Specification (`docs/strategy_spec.md`), defining explicit Required Edge buffers, threshold rebalance policies, inventory drift caps, and kill criteria.

---

### 4.2 H2 — Same-chain DEX–DEX Public Round-Trip Baseline (Score: 51 / 100 — BACKUP)

- **Hypothesis Statement**: Public quoted spreads between DEXs on the same chain (e.g. Aerodrome vs Uniswap V3 on Base) disappear after conservative minimum output, gas, swap fees, approval, and transaction simulation.
- **Null Hypothesis ($H_0$)**: Public same-chain DEX–DEX spreads on liquid pairs do not offer positive net edge after execution costs when accessed by non-MEV public RPC clients.
- **Sample Size & Sparsity**: $N = 33$ attempts/fixtures across Day 8, Day 13, and Day 14; `is_sparse = False`.

#### Supporting Evidence (Confirming the Baseline Null Hypothesis)
1. **100% Elimination of Public Spreads**: [Day 8 Baseline](day08_baseline.md#L39-L46) demonstrated 3 gross candidates resulting in 0 net-positive survivors.
2. **Simulation Rejection**: [Day 13 Simulation](day13_simulation.md#L15-L29) verified that `eth_call` simulations reliably catch allowance deficits, min-output reverts, and gas overhead.
3. **Scanner Funnel Rejection**: [Day 14 Scanner v1](day14_scanner.md#L40-L48) confirmed that 100% of public same-chain candidates are rejected at the re-quote or cost ledger gates.

#### Contradictory Evidence
- Temporary gross dislocations may exist during violent market swings or on illiquid token pairs, but are inaccessible without sub-block MEV infrastructure.

#### Unknowns & Open Questions
- Pricing and availability of private builder endpoints (e.g. Flashbots Protect/Builder bundles on Base).

#### Verdict & Next Steps
- **Verdict**: **RETAIN AS BACKUP (CONTROL BASELINE)**.
- **Action**: Retained as a negative-control benchmark to audit data quality, simulation integrity, and cost accounting. Not pursued as an active alpha strategy.

---

### 4.3 H3 — Cross-chain Aggregator Route Dispersion (Score: 26 / 100 — KILLED)

- **Hypothesis Statement**: Price and route dispersion reported across cross-chain aggregators (e.g. LI.FI) represent executable arbitrage opportunities that can be captured via direct sequential bridging.
- **Null Hypothesis ($H_0$)**: Aggregator route dispersion reflects provider heuristics, temporary subsidies, and bridge delays, and cannot produce executable arbitrage profit after bridge fees, delays, and destination slippage.
- **Sample Size & Sparsity**: $N = 18$ analyzed route pairs; `is_sparse = False`.

#### Contradictory Evidence (Refuting the Hypothesis)
1. **Dispersion is Routing Quality, Not Arbitrage**: [Day 9 Route Dispersion](day09_route_dispersion.md#L25-L45) proved that observed price differences reflect timestamp observation gaps (e.g. 98,225s), provider heuristics, or temporary subsidies.
2. **100% Non-Arbitrage Classification**: 100% of candidate comparisons in Day 9 were classified as `stale_quote`, `routing_improvement`, or `unavailable_route`, with zero `tradable_edge`.
3. **Bridge Latency Destroys Edge**: Bridge settlement delays (10–30+ minutes) completely expose capital to destination price drift.
4. **Prohibitive Fees**: Aggregator fees (25 bps) and bridge protocol fees (25–100 bps) systematically exceed quoted gross spreads.
5. **Zero Profit Locking**: Bridged execution cannot be atomically or conditionally locked at detection time.

#### Verdict & Strategic Action
- **Verdict**: **FORMALLY KILLED**.
- **Action**: Completely eliminated as an arbitrage candidate. The LI.FI adapter remains strictly a read-only liquidity discovery and routing analytics feed.

---

## 5. Formal Kill Decision

In accordance with [Research Charter](research_charter.md#L69-L80) failure criteria and the Day 15 acceptance criteria:

> **Formal Kill Verdict**:  
> **Hypothesis H3 (Cross-chain Aggregator Route Dispersion as Standalone Arbitrage) is hereby TERMINATED.**  
> **Rationale**: Aggregator price dispersion does not constitute executable arbitrage. Bridge transit delays eliminate profit locking, fees exceed observed gross spreads, and 100% of empirical observations failed the Day 9 classification gate. No further engineering or simulation resources will be allocated to sequential bridging strategies.

---

## 6. Strategic Advancement Plan (Days 16–21)

```text
Day 15 Hypothesis Ranking (COMPLETED)
  │
  ├── H3: Route Dispersion ──► [KILLED & DISCARDED]
  │
  ├── H2: Same-chain DEX-DEX ──► [RETAINED AS BACKUP / NEGATIVE CONTROL]
  │
  └── H1: Cross-chain Inventory ──► [ADVANCED AS PRIMARY STRATEGY]
        │
        ▼
Day 16: Primary Strategy Specification (docs/strategy_spec.md + config/strategy.toml)
        │
        ▼
Day 17: Event-time Replay (Latency-aware evidence without OHLC)
        │
        ▼
Day 18: Paper Decision Engine (Virtual fill state machine)
        │
        ▼
Day 19: Stress Test (Gas, Latency, Haircut, Imbalance scenarios)
        │
        ▼
Day 20: Final Paper Run (Frozen run & observation)
        │
        ▼
Day 21: Final Synthesis & A/B/C Decision
```

---

## 7. Traceability and Evidence References

- **Day 3 AMM Pricing**: [docs/daily/day_03.md](daily/day_03.md), `tests/fixtures/amm/base_aerodrome_weth_usdc_block_49641814.json`
- **Day 4/5 LI.FI Probe & Collector**: [docs/daily/day_04.md](daily/day_04.md), [docs/daily/day_05.md](daily/day_05.md)
- **Day 8 DEX–DEX Baseline**: [docs/day08_baseline.md](day08_baseline.md), `tests/fixtures/day08/edge_disappears.json`
- **Day 9 Route Dispersion**: [docs/day09_route_dispersion.md](day09_route_dispersion.md)
- **Day 10 Inventory Model**: [docs/day10_inventory_model.md](day10_inventory_model.md), `config/inventory.toml`
- **Day 11 Rebalance Economics**: [docs/day11_rebalance.md](day11_rebalance.md), `tests/fixtures/day11/rebalance_costs.json`
- **Day 12 Token Risk Registry**: [docs/day12_token_risk.md](day12_token_risk.md), `config/token_registry.toml`
- **Day 13 Simulation**: [docs/day13_simulation.md](day13_simulation.md), `tests/fixtures/simulation/`
- **Day 14 Scanner v1**: [docs/day14_scanner.md](day14_scanner.md), `tests/fixtures/scanner/day14_scenarios.json`
- **Day 15 Ranking Models & Tests**: `src/onchain_arb/ranking.py`, `tests/test_ranking.py`
