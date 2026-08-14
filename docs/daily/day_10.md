# Day 10 — Cross-chain Inventory Model

## 状态与结论

- 状态：Day 10 paper-only acceptance scope 已完成。
- 已建立 Base / Arbitrum、USDC / WETH 的 two-chain virtual balance sheet；固定总资本占用为
  8,000 USDC，并记录每个 chain/asset 的 balance、target band 与 maximum imbalance。
- deterministic acceptance signal 在 Base 买入 0.25 WETH、Arbitrum 同时卖出预置的
  0.25 WETH；扣除两链显式成本后 Trade PnL 为 5 USDC，WETH 总量守恒。
- Day 9 没有 fresh tradable cross-chain edge，因此上述数值只验证 inventory accounting，
  不是 live market evidence 或盈利结论。

## 完成项

- 新增 `InventoryPosition`、`VirtualBalanceSheet`、`InventoryLeg`、`CrossChainSignal` 与
  `InventoryEvaluation`，所有 token 数量继续使用 integer raw units + decimals。
- 新增 cheap-chain buy + expensive-chain sell 的保守 minimum-output paper simulation；两腿必须
  位于不同链，且买入 guaranteed asset amount 必须等于另一链预置卖出量。
- 输出 condition lock time、leg skew、Trade PnL、逐位置 Inventory Change、Capital Occupied、
  Capital-hour Return 与 Required Initial Inventory。
- `included_in_quote_output` 成本不会二次扣减；required cost 缺失返回 `COST_INCOMPLETE`。
- 新增窄化的 `CrossChainCostLedger`：只允许同一显式 economic asset、相同 decimals 的 chain-local
  成本，不做 FX 转换；Inventory delta 必须与 Ledger PnL 一致。
- 初始余额不足或超过 hard maximum imbalance 时明确返回 `INVENTORY_BLOCKED`，且不返回 partial
  balance mutation。
- 两腿刷新超过固定窗口时返回 `SIGNAL_NOT_LOCKED`；不会用 stale leg 静默替代。

## Evidence 与验证

- 完整语义与 deterministic worked example：`docs/day10_inventory_model.md`。
- Frozen policy：`config/inventory.toml`。
- Acceptance tests：`tests/test_inventory.py`。
- 本日没有外部请求、wallet balance lookup、Bridge、签名或广播交易。

## Gate 边界

- 当前 capital mark 与 signal 都是明确冻结的 paper assumptions；不得解释为 live quote 或
  price fallback。
- Trade PnL 还不包含 inventory restoration / rebalance，因此不是完整 Cycle PnL。
- 仅支持两 Chain、一个 Pair、一组静态 Policy；multi-chain netting、portfolio optimization、
  dynamic bands 保留在 backlog。

## 下一步

- Day 11 为同一 inventory delta 实现 Immediate、Threshold-based、Batch 三种 rebalance policy，
  输出 Cycle PnL、frequency、break-even cost、capacity curve 与 imbalance distribution。
- 必须展示 local Trade PnL 为正但 Cycle PnL 为负的情形，不能用单笔 5 USDC 判断策略盈利。
