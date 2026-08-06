# Day 2 — PnL Truth 与 Cost Ledger

- 日期：2026-08-06
- 状态：完成

## 结论

Cost Ledger 是 PnL 的唯一 Owner。Day 2 只使用明确标注来源的测试数据，
不连接 LI.FI；Day 4 的 Adapter 只提供数据，不定义 PnL。

## 完成

- 实现 `TokenAmount`、signed `TokenDelta`、`CostItem`、Quote、Candidate 和 Simulation Models。
- 使用 integer raw units + `Decimal`，并强制 UTC、source 和 confidence。
- 输出 Gross、Atomic/Local 和 Inventory Cycle PnL。
- 已包含在 Quote Output 的费用不重复扣除。
- 缺失成本标记为 incomplete；不同 Token 无 FX Evidence 时拒绝相加。

## 手算验证

```text
Gross PnL                1.50 USDC
Gas                     -0.40
Local trade PnL          1.10
Rebalance               -2.00
Cycle PnL               -0.90 USDC
```

Ledger 输出与手算一致。

## 测试

```text
UV_CACHE_DIR=.uv-cache uv run pytest
6 passed in 0.01s
```

覆盖三个必测场景，以及 missing cost 和 mixed-currency guards。

## 下一步

Day 3 只实现一个 Liquid Pair 的 executable-price 与 size-impact 对比。
LI.FI 费用字段语义留到 Day 4 用 Raw Fixture 验证。
