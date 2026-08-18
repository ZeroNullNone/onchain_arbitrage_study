# Day 14 Scanner v1

## Scope & Objective

Day 14 integrates the modular research components into an end-to-end research loop that evaluates arbitrage opportunities through a conservative, multi-stage rejection pipeline.

The pipeline connects:
1. Ingestion / Detection of candidate opportunities
2. Deduplication across time and route signatures
3. Independent Re-quote validation
4. Cost Ledger evaluation (single-owner PnL semantics)
5. Virtual Inventory checks (for cross-chain pre-positioned inventory)
6. Transaction Simulation verification (for same-chain execution)
7. Final State Assignment & Explicit Reject Reason Logging
8. Append-only Report and Evidence Persistence

---

## The 10-Step Pipeline Architecture

```text
1. Collect     -> Ingest direct quotes and candidate opportunities
2. Normalize   -> Enforce integer raw units, TokenRef, and UTC timestamps
3. Detect      -> Validate initial path and positive gross spread
4. Deduplicate -> Filter repeat candidate signals within sliding window
5. Re-quote    -> Verify fresh, independent quote with guaranteed leg output
6. Cost Ledger -> 100% complete cost ledger attribution (no double-counting)
7. Inventory   -> Verify virtual balance sheet target bands and max imbalance
8. Simulation  -> Verify eth_call simulation output, gas, allowance, revert state
9. Accept/Reject -> Assign one of 6 formal candidate states with reject reasons
10. Persist    -> Atomically write immutable report JSON and derived metrics
```

---

## Candidate State Machine

Every candidate processed by Scanner v1 transitions deterministically into one of 6 states:

| Candidate State | Description | Gate Trigger / Rejection Cause |
|:---|:---|:---|
| `DETECTED` | Initial candidate detected | Raw spread identified before secondary validation |
| `REQUOTE_FAILED` | Re-quote validation failed | Missing requote, stale timestamp, venue/size change, leg output not guaranteed, or non-positive refreshed gross/min |
| `NET_NEGATIVE` | Economics turned negative | Complete cost ledger deductions (gas, approval fees) reduce net trade PnL $\le 0$, or cost ledger incomplete |
| `INVENTORY_BLOCKED` | Capital/Inventory limit reached | Insufficient local balance, position exceeds target band, or max imbalance exceeded |
| `SIMULATION_FAILED` | Simulation unexecutable | Transaction reverted, output below quote/min, insufficient allowance, or stale block state |
| `PAPER_READY` | Fully validated paper candidate | Passed all re-quote, cost, inventory, and simulation gates |

---

## Gate & Funnel Performance

### 1. Gate Invariants
- **Cost Completeness Ratio**: **100%** (All evaluated candidates have complete cost ledgers).
- **Raw Evidence Coverage**: **100%** (All candidate observations retain their source `raw_ref`).
- **Idempotency & Deduplication**: Sliding-window deduplicator filters repeated signals on identical venues, paths, and sizes.

### 2. Funnel Survivor Ratios
- **Candidate $\to$ Re-quote Survivor Ratio**: $N_{\text{requote\_survivors}} / N_{\text{detected}}$
- **Re-quote $\to$ Simulation Survivor Ratio**: $N_{\text{sim\_passed}} / N_{\text{sim\_attempted}}$
- **Opportunity Lifetime vs Decision Latency**: Tracks duration from detection to execution decision vs measured latency (p50/p95).

### 3. Sparse Sample Rule
When total evaluated opportunities $N < 20$, the scanner automatically sets `is_sparse = True`. No statistical profitability claims are permitted under sparse sample conditions.

---

## Code Deliverables

1. **`src/onchain_arb/decision.py`**:
   - `CandidateState` enum: `DETECTED`, `REQUOTE_FAILED`, `NET_NEGATIVE`, `INVENTORY_BLOCKED`, `SIMULATION_FAILED`, `PAPER_READY`.
   - `CandidateRejectReason` enum: complete taxonomy of reject reasons.
   - `ScanDecision` dataclass: comprehensive audit record containing candidate metadata, state, net PnL, evaluations, latency, and lifetime.

2. **`src/onchain_arb/scanner.py`**:
   - `ScannerPipeline`: unified scan engine for same-chain and cross-chain candidates.
   - `CandidateDeduplicator`: time-windowed deduplication.
   - `ScannerMetrics` & `ScannerReport`: metrics computation and atomic report serialization.
   - `persist_scanner_report()`: atomic file persistence to `data/derived/scanner/`.

3. **`scripts/run_scanner.py`**:
   - CLI tool for running the scanner over scenarios or recorded quote batches.

4. **`tests/test_scanner.py`**:
   - 10 acceptance tests covering all 6 candidate states, gate rejections, deduplication, survivor metrics, and report persistence.

---

## Non-Goals & Boundaries

- No live transaction signing or private keys.
- Single-process sequential pipeline; no distributed workers or queues.
- No live web dashboards or external notification webhooks.
