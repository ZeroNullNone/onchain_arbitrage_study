# Day 17 — Event-time Replay

## 结论

Day 17 以 **captured snapshot event stream** 重放 Day 16 冻结的 H1 策略，不使用 OHLC、candle 或插值成交价。重放只在证据的 `arrived_at` 之后使用该证据；连续快照先聚合成 Opportunity Cluster，再报告候选数量与独立机会数量，避免 Snapshot Inflation。

本模块严格保持 read-only / simulation-only / paper-only，不签名、不广播，也不声称 Raw fixture 的小样本结果具有统计代表性。

## 时间模型与无未来数据泄漏

每个 Detection、Re-quote、Simulation 与 Rebalance observation 都必须保存：

- UTC `observed_at`：外部状态被观察到的时间；
- UTC `arrived_at`：证据进入本地决策域的时间；
- 实测整数 `latency_ms`，且必须等于 `arrived_at - observed_at`；
- 独立 `request_id`、`raw_ref` 与 `source`。

`run_event_time_replay(..., as_of=T)` 只加载 `arrived_at <= T` 的证据。若 Re-quote 已到但 Simulation 尚未到，状态为 `WAITING_SIMULATION`，不会 Paper Fill 或改变 Virtual Inventory。测试 `test_future_evidence_is_not_visible_or_applied` 固定验证此性质。

Decision 排序使用 arrival time；Cluster 连续性使用 observation/event time。这避免网络快慢改变市场事件的聚类，同时杜绝未到达证据影响当时决策。

## Entry 与 Cost Ledger

每个候选按以下顺序评估：

1. Detection 已到达；
2. Re-quote 在冻结的 `requote_window_ms` 内到达；
3. Re-quote 的 minimum-output gross edge 进入完整 Cost Ledger；
4. Cost Ledger 覆盖所有 `required_cost_kinds`，并唯一拥有 Required Edge/PnL 语义；
5. `gross_edge >= known costs + uncertainty + latency + rebalance + minimum profit`；
6. 独立 Simulation 到达、成功且满足 minimum output；
7. Virtual Inventory 应用后不出现负余额。

任何缺失成本、超时、门限失败、仿真失败或库存不足都产生明确 Reject Reason。不存在成本缺失记为零、猜测值或 silent fallback。

## Opportunity Cluster

Cluster identity 是 `(opportunity_key, direction, target_size_raw)`。同一 identity 的相邻 snapshot 若 event-time gap 不超过 Day 16 `dedup_window_seconds`，归入同一 Cluster。报告同时保留：

- `detected_candidates`：观察到的正向 snapshot 数；
- `unique_clusters`：时间连续的独立机会数；
- 每个 Cluster 的 candidate IDs、起止时间和 lifetime。

因此收益、Lifetime 与样本陈述不会把每个轮询快照伪装成独立机会。

## Virtual Inventory 与 Rebalance Lifecycle

Accepted paper entry 只应用显式 raw-unit `InventoryDelta`。余额不足则拒绝，绝不产生负 Virtual Balance。若 snapshot 带有独立 Rebalance evidence，生命周期记录 `PENDING → COMPLETE`；恢复 delta 只在该证据的 `arrived_at` 到达后应用。结束报告保留完整 ending inventory 与 lifecycle events。

所有代币/会计数量均使用整数 raw units + explicit decimals。报告展示值才转换为 `Decimal`。

## Metrics 定义

- Re-quote survival：完整且 `net_edge_raw >= 0` 的及时 Re-quote / detected snapshots。
- Simulation survival：通过 minimum-output simulation / Re-quote survivors。
- Net edge p05/p50/p95：只对 Paper Filled 的 Cost Ledger net edge 计算线性分位数。
- Worst case：所有已完成 Re-quote（含拒绝）的最小 net edge。
- Edge decay by latency：`initial gross edge - re-quote minimum gross edge`，按实测 Re-quote latency 分组。
- Lifetime：Cluster 首末 event time 之差。
- Capacity：本次窗口中通过的最大已测试 target size；不外推未测试规模。
- Capital-hour return：`Σ filled net edge / Σ(capital occupied × lock hours)`。
- Latency p05/p50/p95：实际 Detection/Re-quote/Simulation evidence latency distribution。

## Saved Fixture 结果

`tests/fixtures/replay/day17_event_stream.json` 是可审查的小型 Raw envelope，只用于 schema、时序与计算验收：

| Metric | Result |
|---|---:|
| Detected snapshots | 2 |
| Unique clusters | 1 |
| Re-quote survival | 1 / 2 (50%) |
| Simulation survival | 1 / 1 (100%) |
| Paper fills | 1 |
| Net edge p05 / p50 / p95 | $0.70 / $0.70 / $0.70 |
| Worst case net edge | -$0.30 |
| Cluster lifetime p50 | 20,000 ms |
| Profitable tested capacity | $100 |
| Capital-hour return | 0.000175 |

这两条 fixture 不是实证盈利结论；它只证明 end-to-end replay、拒绝路径、lineage 与指标公式可重复。

## 运行

```bash
uv run python scripts/run_replay.py \
  tests/fixtures/replay/day17_event_stream.json

uv run python scripts/run_replay.py \
  tests/fixtures/replay/day17_event_stream.json \
  --as-of 2026-08-17T08:00:01.500Z \
  --output data/derived/day17_replay.json
```

默认只把 JSON 打印到 stdout；传入 `--output` 才写 derived report。输入 fixture 不会被修改。

## Scope 与 Backlog

本日只覆盖现有采集窗口和一份冻结 Strategy Config。未实现 candle backtest、参数搜索、Monte Carlo、counterfactual ordering、精确成交伪造或生产执行。更长历史与随机压力分布保留到后续 backlog。

