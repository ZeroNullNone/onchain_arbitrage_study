# Opportunity Taxonomy

## 分类目的

“价格不同”不是单一策略。分类用于明确每类机会的执行原子性、库存要求、时延暴露、对手方和失败模式，避免把 Routing Analytics、Basis 或 MEV 误标为同一种套利。

## Taxonomy

| 类型 | Atomicity | Required inventory | Latency sensitivity | Counterparty / venue | Capacity constraint | Main failure mode | 本期 Priority |
|---|---|---|---|---|---|---|---|
| Same-chain DEX–DEX | 只有封装在同一 Transaction 才可能 Atomic；两笔独立 Tx 非 Atomic | 需要起始资产与 Gas；原子合约可临时借贷但本期不做 | 高；公开 Quote 易衰减并受排序影响 | 两个 DEX/Aggregator、LP、Searcher | Pool Depth、Price Impact、Gas、Approval、竞争 | 第二腿失败、Quote Stale、Min-output Revert、Gas 后转负 | **P1 Baseline**：Day 8 建立可拒绝假机会的对照 |
| Triangular arbitrage | 同一 Chain、同一 Transaction 内三 Swap 才可能 Atomic | 起始资产、Gas；不要求跨链库存 | 很高；三段 Route 放大状态变化 | 同一或多个 DEX/Pool | 最浅 Pool、累计 Fee、Gas、路径长度 | 三段中任一段输出恶化或 Revert，Gross Edge 被累计 Fee 吃掉 | **P3 Backlog**：只保留概念，不在 21 天实现 |
| Cross-chain route dispersion | Non-atomic；Bridge/跨链消息有独立 Finality | 通常需要源链输入资产；若等待 Bridge 则占用在途资本 | 中至高；Route、Subsidy、Bridge Fee 与 ETA 会变化 | Aggregator、DEX、Bridge、Relayer | Bridge Liquidity、Route Availability、Transfer Limit、Duration | 把临时补贴/Token Mapping/旧 Quote 误当套利，目的链输出不确定 | **P2 Analytics**：Day 9 分析，不自动视为套利 |
| Pre-positioned inventory arbitrage | Non-atomic；两链两笔 Tx 无共同回滚 | 两链预置 Asset、Stablecoin、Gas，外加 Rebalance Capacity | 很高；Leg Risk 取决于两腿 Re-quote 与 Decision Latency | 两链本地 DEX/Aggregator、LP；Rebalance/Hedge Venue | 双边库存、最大 Drift、Rebalance Cost、Capital Band | 一腿成交一腿失败；Local PnL 正但 Cycle PnL 负 | **P1 Primary**：H1，Day 10–21 主线 |
| Stablecoin / wrapped asset basis | 通常 Non-atomic；同链原子 Route 只是特例 | 两种法律/技术身份不同的 Token 库存与赎回能力 | 中；Depeg、Pause 或 Redemption Stress 时可骤升 | Issuer、Bridge、Wrapper、DEX、Custodian | Redemption Limit、Bridge Liquidity、Issuer Risk、Haircut | Symbol 相同但资产不同；Depeg/Blacklist/Pause/Bridge Failure | **P2 Risk Lens**：Day 12 建 Registry 与 Haircut，不独立扩张策略 |
| MEV / backrun / liquidation | Bundle 内可条件原子，但 inclusion 与 ordering 不保证 Finality | Gas、Searcher Infra；Liquidation 可能需 Capital/Flash Liquidity | 极高，Block/Builder 级 | Builder、Relay、Validator、Protocol、竞争 Searcher | Inclusion、Bid、Competition、State Contention | Bundle 不包含、被抢先、Reorg、竞价耗尽 Edge、智能合约风险 | **Study-only / Non-goal**：不实现、不发交易 |

## 统一判定标签

- `OBSERVATION`：仅观察到两个 Displayed/Quoted 数值有差异。
- `CANDIDATE`：Token Identity、Size、Direction 与 Raw Lineage 完整，初步 Gross Edge 通过 Detect Threshold。
- `REQUOTED`：独立 Re-quote 在 Freshness Window 内完成。
- `COSTED`：完整 Cost Ledger 和不确定性标签齐全。
- `PAPER_READY`：通过库存检查；Same-chain 还通过 Simulation；Cross-chain 满足 Research Charter 的条件锁定定义。
- `REJECTED`：任一 Gate 失败，必须附机器可读 Reject Reason。

`PAPER_READY` 不是 `EXECUTABLE`、`GUARANTEED` 或 `PROFIT_LOCKED` 的同义词。

## 本期排序理由

1. Same-chain DEX–DEX 是最小 Baseline，可最早暴露报价、Decimals、Gas 与 Simulation 错误。
2. Pre-positioned Inventory 是 Primary Hypothesis，但必须先有 Collector、Cost Ledger、Data Gate 与 Baseline。
3. Route Dispersion 和 Token Basis 用于解释信号来源与风险，不直接升级为套利。
4. Triangular 与 MEV 需要额外执行基础设施，会破坏 21 天的最小闭环，因此留在 Backlog/Study-only。
