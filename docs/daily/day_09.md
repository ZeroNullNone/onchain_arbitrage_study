# Day 9 — LI.FI Route Dispersion

## 状态与结论

- 状态：Day 9 frozen-universe acceptance scope 已完成。
- LI.FI Base USDC→WETH 的 size sequence 为 Fly → Fly → KyberSwap，Switch Rate 为 0.5；
  Fly Provider Concentration 为 2/3。
- Independent Aerodrome direct source 按 Day 3 frozen 50 bps minimum-output policy 计算后，在三个
  size 的 minimum output 排名均高于 LI.FI，但证据相隔约一天，100 USDC 的精确间隔为
  98,225.491580 秒。
- 因此 Candidate 被 direct-source gate 否证为 `stale_quote`，不是可交易套利；本日没有盈利结论。

## 完成项

- 新增 route observation boundary，保留 request ID、Raw reference、UTC time、latency、integer
  token units、decimals、provider、fingerprint、duration 与 fee evidence。
- 新增以 minimum output 排名的 Best/Second-best，以及 Route Switch Rate、Observed Lifetime、
  Provider Concentration、Duration/Fee Dispersion 与 Size Sensitivity。
- 新增 routing improvement、temporary subsidy、stale quote、token mapping difference、
  unavailable route、tradable edge 六类显式分类。
- `tradable_edge` 必须同时有 fresh independent refresh、complete cost ledger 与 complete
  executable cycle；Route Difference 单独永远不会设置 `is_arbitrage=true`。
- Fee evidence 缺失时返回 unknown，不把缺失成本写成零。

## Evidence 与验证

- 完整语义与 frozen evidence：`docs/day09_route_dispersion.md`。
- LI.FI Raw fixtures：`tests/fixtures/lifi/`。
- Independent direct Raw fixture：
  `tests/fixtures/amm/base_aerodrome_weth_usdc_block_49641814.json`。
- Acceptance tests：`tests/test_route_dispersion.py`。
- `uv run pytest`：57 passed。

## Gate 边界

- 当前 Switch Rate/Lifetime 来自连续的不同 size probe，只描述 size sequence，不代表固定 size
  的时间序列 reliability。
- LI.FI 与 Direct Source 不同时，因此 Best/Second-best 只用于 route analytics，不能声称同步可执行。
- 本日没有新增外部请求、Aggregator、Bridge PnL assumption、签名或广播交易。

## 下一步

- Day 10 只基于已证据化的 cross-chain candidate 建立 two-chain virtual balance sheet；任何
  cross-chain signal 都必须说明利润锁定时点与 initial inventory requirement。
- Provider Reliability Time Series 与 Subsidy Detection 保留在 backlog。
