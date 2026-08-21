# Day 17 — Event-time Replay

## 状态与结论

- 状态：Day 17 acceptance scope 全部完成。
- 新增 event-time replay engine、Raw fixture loader、CLI、指标报告与验收测试。
- Replay 不使用 OHLC；只使用在当时已经 `arrived_at` 的 captured evidence。
- 连续 2 个 fixture snapshots 被正确聚为 1 个 Opportunity Cluster，未以 polling 次数夸大独立样本。
- 全过程保持 Paper-only，使用 raw integer units 与 `Decimal` 报告，不签名、不广播。

## 完成项

- `src/onchain_arb/replay.py`
  - 实测 latency 与 observed/arrival time 强一致校验；
  - 任意 `as_of` cutoff 的无未来泄漏重放；
  - Re-quote/complete Cost Ledger/minimum output/Simulation entry gate；
  - Opportunity clustering、Virtual Inventory 与 Rebalance lifecycle；
  - Detected、Clusters、Survival、Net Edge percentiles、Decay、Lifetime、Capacity、Capital-hour Return、Worst Case 指标。
- `tests/fixtures/replay/day17_event_stream.json`
  - 保存完整 request ID、Raw ref、source、UTC timestamps、latency、raw-unit economics 与 inventory deltas。
- `tests/test_replay.py`
  - 覆盖聚类、指标、未来泄漏、超时、库存变化、rebalance lifecycle、fixture parsing 与 latency schema failure。
- `scripts/run_replay.py`
  - 从 Day 16 frozen config 读取 Re-quote 与 cluster window；支持 cutoff 和 derived JSON output。
- `docs/day17_replay.md`
  - 固定时序、Entry、PnL、Cluster 与全部指标语义。

## Evidence 与验证

- 实现：[`src/onchain_arb/replay.py`](../../src/onchain_arb/replay.py)
- Raw fixture：[`tests/fixtures/replay/day17_event_stream.json`](../../tests/fixtures/replay/day17_event_stream.json)
- 验收测试：[`tests/test_replay.py`](../../tests/test_replay.py)
- 规范：[`docs/day17_replay.md`](../day17_replay.md)

Saved fixture 的 2 个 detections 形成 1 个 cluster；1 个通过 Re-quote 与 Simulation 并 Paper Fill，另 1 个因 Required Edge 不足明确拒绝。该 fixture 仅用于确定性验收，不用于盈利推断。

## 学习总结

- **回测首先是时间问题**：决策只能使用当时已经到达系统的数据；正确的公式若读取未来证据，结果仍然无效。
- **市场时间不等于系统时间**：`observed_at` 描述市场状态被观察的时刻，`arrived_at` 才决定策略何时能够使用它；两者差值就是执行研究必须面对的真实 latency。
- **Snapshot 不等于独立样本**：连续轮询看到的同一机会必须聚为 Opportunity Cluster，否则会夸大样本量、胜率与收益。
- **初始报价只负责发现候选**：可执行判断必须依赖独立 Re-quote、minimum output、完整 Cost Ledger、Simulation 与可用库存。
- **分析策略要看完整漏斗**：Detected → Re-quote survived → Simulation survived → Inventory feasible → Paper filled，比单独观察胜率更能定位机会消失的位置。
- **跨链预置库存仍有资本成本**：避免即时跨链不代表资金免费；应使用 Capital-hour Return 比较收益、占用资本与锁定时间。
- **测试 fixture 不是盈利证据**：它证明时序、会计、Reject、聚类和 lineage 可重复，但不能代替更长的真实市场观察窗口。

## Gate 边界

- 未使用 candle/OHLC、插值成交、stale fallback 或 guessed metadata。
- 未进行参数搜索、Monte Carlo、counterfactual ordering 或超出已测试规模的 capacity 外推。
- 未接入钱包、签名、广播、flash loan、MEV infrastructure 或 live execution。

## 下一步

Day 18 可直接消费 ReplayDecision、Raw refs 与 ending Virtual Inventory，建立幂等 Paper Decision/Fill State Machine。
