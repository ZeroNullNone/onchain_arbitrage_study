# Day 11 — Rebalance Economics

## 状态与结论

- 状态：Day 11 deterministic、paper-only acceptance scope 已完成。
- 已实现 Immediate、Threshold-based、Batch 三种 rebalance policy；所有完整结果都会在周期末恢复
  residual imbalance，不把未平仓库存包装成 Cycle PnL。
- Day 10 单笔 local Trade PnL 为 +5 USDC；Immediate 假设每次 0.25 WETH rebalance 成本为
  7 USDC，四笔交易的 local PnL 为 +20 USDC，但完整 Cycle PnL 为 **−8 USDC**。
- 上述成本和 capacity 数值是 deterministic paper assumptions，不是 live Bridge/CEX evidence 或
  盈利结论。

## 完成项

- 新增 exact-size `RebalanceCostObservation`，强制记录 request ID、Raw reference、source、UTC
  timestamp、latency、integer raw transfer amount 与 cost。
- 缺失准确 size 的成本时显式返回 `COST_INCOMPLETE`；不会插值、猜测、使用 stale cache 或把
  missing cost 当成零。
- `InventoryCycleCostLedger` 成为完整周期 PnL subtraction 的单一 owner，避免重复扣除 Day 10
  已处理的 atomic cost。
- 输出 Cycle PnL、rebalance count/frequency、total 与 per-event break-even cost、ending imbalance、
  imbalance distribution 和逐次 rebalance event evidence。
- 三 Policy 的四笔交易结果分别为：Immediate −8 USDC / frequency 1；Threshold +2 USDC /
  frequency 0.5；Batch +4 USDC / frequency 0.25。
- break-even total rebalance cost 为 20 USDC；Immediate 的 per-event break-even 为 5 USDC。
- capacity curve 展示 100 / 500 / 1,000 USDC 三档：Cycle PnL 为 2 / 1 / −2 USDC，edge 为
  200 / 20 / −20 bps，因此 tested profitable capacity 为 500 USDC。

## Evidence 与验证

- 完整语义、Policy 表、imbalance distribution、break-even 与 capacity worked example：
  `docs/day11_rebalance.md`。
- Append-only deterministic raw paper fixture：`tests/fixtures/day11/rebalance_costs.json`；每个
  normalized test observation 保留准确 JSON Pointer。
- Acceptance tests：`tests/test_rebalance.py`。
- 本日没有外部请求、wallet lookup、Bridge/CEX order、签名或广播交易。

## Gate 边界

- 只实现 deterministic virtual rebalance；Natural Flow、CEX/Perp Hedge、stochastic rebalance、
  funding forecast 和 optimizer 保留在 backlog。
- Capacity 是 largest strictly profitable tested size，不插值未观察 size，也不声称全局最优。
- Threshold/Batch 在持有期间承担更大的 inventory imbalance；较低 frequency 不等于无风险。
- 不再用单笔 local Trade PnL 判断 cross-chain strategy profitability。

## 下一步

- Day 12 建立以 `chain_id + contract_address` 为 identity key 的 token registry，显式记录
  canonical/bridged/wrapped、issuer、redemption 与 basis-risk 决策。
