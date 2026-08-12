# Day 8 — Same-chain DEX–DEX Baseline

## 状态与结论

- 状态：Day 8 paper-only acceptance scope 已完成。
- Frozen universe：Base (`8453`) USDC/WETH、固定 100 / 500 / 1,000 USDC exact input、
  两个 venue。
- Acceptance fixture 的漏斗结果为 3 个 gross candidates、1 个 re-quote survivor、
  0 个 net-positive survivors；Baseline 能可靠返回「没有机会」。
- 本结论只证明 deterministic scanner 行为，不是 fresh market evidence，也不构成盈利结论。

## 完成项

- 新增 direct quote evidence model，保存 Raw lineage、request ID、UTC timestamp、latency、
  token integer raw units、fee、gas、minimum output，以及显式 approval 状态与成本。
- 新增 re-quote 结构 Gate，检查 venue、target size、token path、时间确实更新，以及两腿之间的
  guaranteed-output linkage。
- 第二腿只允许使用第一腿的 `minimum_output`，不能使用较乐观的 quoted output，避免假设第一腿
  一定能得到未被保证的 WETH 数量。
- 新增 same-chain decision funnel，保留每一个适用的 reject reason，并由共享 `CostLedger`
  统一计算 minimum-output 下的保守 PnL。
- 新增 edge-disappears fixture，并覆盖缺失 re-quote、Gas 令价差转负、stale evidence、
  使用乐观输出连接第二腿，以及 approval cost 缺失等 regression cases。

## Evidence 与验证

- 完整 decision semantics 与 funnel：`docs/day08_baseline.md`。
- Edge-disappears fixture：`tests/fixtures/day08/edge_disappears.json`。
- Acceptance tests：`tests/test_same_chain.py`。
- `uv run pytest`：51 passed。
- 本日没有签名或广播交易，也没有读取钱包、私钥或助记词。

## Gate 边界

- Fixture 使用 Aerodrome 与 Uniswap V3 两个 venue 名称来验证 scanner interface，但不是
  fresh on-chain quote，因此不能据此声称当前市场存在或不存在可交易价差。
- Fresh direct venue collection、更多 venue/pair、quote lifetime calibration、atomic execution
  contract、live simulation 与广播交易均不属于 Day 8 scope。
- 未来若加入 live observation，必须先完整保存外部 Raw request/response/error，并独立刷新
  两条 direct venue legs，才可支持任何市场结论。

## 下一步

- Day 9 只在 frozen universe 与现有 evidence 内分析 LI.FI route dispersion，并使用 independent
  direct source 确认或否证 candidate。
- 不把 route difference 自动解释为 arbitrage；更多 pair、执行基础设施与 live strategy 继续留在
  backlog。
