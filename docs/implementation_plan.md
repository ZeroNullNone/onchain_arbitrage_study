# Day 2–21 Implementation Plan

## 执行规则

- 每天主动工作最多 120 分钟；先完成最小可验证 Slice，再记录 Backlog。
- 依赖顺序固定：Models → API Probe → Collector → Data Gate → Baseline Signal → Inventory Model → Rebalance Model → Simulation → Scanner → Strategy Spec → Replay → Paper Engine → Stress → Final Decision。
- 不牺牲 Raw Evidence、Decimals、Cost Ledger、Re-quote、Reject Reason、Tests 与 Lineage。
- 当天只实现当天 Acceptance Criteria；Backlog 不自动叠加到次日，除非阻塞主线。
- 所有金额使用 Integer Raw Units + `Decimal`；所有时间使用 UTC。

## Day 2 — PnL Truth 与 Cost Ledger

- **Objective**：实现可人工复核且不重复扣费的最小经济模型。
- **Dependencies**：Research Charter、System Design、Python Package Skeleton。
- **Files**：`src/onchain_arb/models.py`、`src/onchain_arb/costs.py`、`tests/test_costs.py`、`docs/daily/day_02.md`。
- **Acceptance criteria**：存在 `TokenAmount`、`CostItem`、`QuoteObservation`、`OpportunityCandidate`、`SimulationResult`；成本含 included/confidence/source/observed_at；输出 Atomic Net 与 Inventory Cycle Breakdown。
- **Test / evidence**：三项测试分别证明 Gross Positive 经 Gas 转负、Quote 内含 Fee 不会重复扣、Local Trade Positive 经 Rebalance 后 Cycle Negative；保存测试输出与手算例。
- **Maximum scope**：纯模型和 Deterministic Calculation，不接外部 Source。
- **Explicit non-goals**：Quote Collector、Database、Strategy Signal、实时汇率。
- **Backlog**：多币种 FX Mark、复杂 Funding Curve、税务/会计报表。

## Day 3 — AMM Executable Price

- **Objective**：区分 Spot/Displayed 与 Exact-input Executable Price，测量 Size Sensitivity。
- **Dependencies**：Day 2 Amount 与 Cost Models。
- **Files**：`src/onchain_arb/amm.py`、`tests/test_amm.py`、`data/derived/day03_*`、`docs/daily/day_03.md`。
- **Acceptance criteria**：一个 Liquid Pair 在 USD 100/500/1,000 下输出 Spot、Executable、Average Price、Price Impact、Min Output、Pool Fee 表。
- **Test / evidence**：常量乘积或选定 Source Fixture 的手算/单测；表格可由输入重建。
- **Maximum scope**：一条 Chain、一个 Pair、一个 Pool/Quote Source。
- **Explicit non-goals**：多 Pool Router、Concentrated Liquidity 完整模拟、Scanner。
- **Backlog**：Tick-level V3 Math、更多 Fee Tier 与 Path Split。

## Day 4 — LI.FI API Probe

- **Objective**：理解并保存 LI.FI Quote 的完整请求、响应和字段语义。
- **Dependencies**：Day 2 Models、Day 3 Executable Price 语义、有效公开 API Access。
- **Files**：`src/onchain_arb/adapters/lifi.py`、`scripts/probe_lifi.py`、`tests/fixtures/lifi/`、`tests/test_lifi_adapter.py`、`docs/schema/lifi_quote.md`、`docs/daily/day_04.md`。
- **Acceptance criteria**：3 Routes × 3 Sizes；保存 Raw JSON；映射 chain/token/from/to/min/gas/fee/duration/tools/approval/transaction；生成稳定 Route Fingerprint。
- **Test / evidence**：脱网 Fixture Test 可从 Raw 重建 Request、Route、Output、Minimum Output 与 Source-reported Cost。
- **Maximum scope**：同步或单次 Probe；只做 Quote Endpoint。
- **Explicit non-goals**：持续采集、执行 Route、自动换 Source。
- **Backlog**：其他 LI.FI Endpoints、更多 Route、SDK 对比。

## Day 5 — Quote Collector v0

- **Objective**：构建低并发、可重启、Append-only 的 Quote Collector。
- **Dependencies**：LI.FI Adapter Fixture、Raw/Normalized Schema。
- **Files**：`src/onchain_arb/collector.py`、`src/onchain_arb/storage.py`、`src/onchain_arb/normalize.py`、`scripts/collect_quotes.py`、`tests/test_collector.py`、`docs/daily/day_05.md`。
- **Acceptance criteria**：Timeout、Bounded Retry/Backoff、Rate-limit、Request ID、UTC、Latency、Raw-first 写入、Parquet + DuckDB；轮询 30–60 秒且重启不覆盖。
- **Test / evidence**：至少运行 2 小时；报告 Request Count、Success/Parse Failure/Timeout、p50/p95 Latency、Unavailable Routes；每条 Normalized Record 有 Raw Ref。
- **Maximum scope**：固定 Universe、单进程、低并发。
- **Explicit non-goals**：Distributed Queue、Overnight 强制运行、性能优化、Dashboard。
- **Backlog**：Structured Concurrency、Compression/Partition Tuning、长期调度。

## Day 6 — RPC / Block Context

- **Objective**：把 Quote 时间与可验证的 Chain Head/Block Context 对齐。
- **Dependencies**：Collector、EVM RPC、Chain Config。
- **Files**：`src/onchain_arb/adapters/rpc.py`、`src/onchain_arb/block_context.py`、`tests/fixtures/rpc/`、`tests/test_block_context.py`、`docs/daily/day_06.md`。
- **Acceptance criteria**：记录附近 Block Number/Timestamp/Base Fee/Chain Head；明确 Direct Quote + RPC 用于 Decision-time，Indexed Data 只用于 Research/Backfill。
- **Test / evidence**：Fixture 验证 Hex/Integer、UTC 与 Chain ID；可选测一个 Indexer 相对 Chain Head 的 Lag。
- **Maximum scope**：三条 Chain 的 Head Context；一个可选 DEX Event Query。
- **Explicit non-goals**：Archive Node、完整 Event Indexer、Reorg Engine。
- **Backlog**：Confirmation Depth、Multi-provider Health、历史 State Replay。

## Day 7 — Week 1 Data Gate

- **Objective**：审计数据质量并冻结 Week 2 Universe/Config。
- **Dependencies**：至少一轮 Collector 数据、Raw Lineage、Decimals Tests、Block Context。
- **Files**：`src/onchain_arb/data_quality.py`、`tests/test_data_quality.py`、`docs/week_1_report.md`、`config/week2.toml`、`docs/daily/day_07.md`。
- **Acceptance criteria**：检查 Schema、Decimals、Duplicate、Missingness、Timestamp Order、Raw/Latency Coverage、Failure/Availability、Size Sensitivity；目标 ≥200 Valid Observations（不足说明原因）、Raw/Time/Latency 100%、Parse ≥95%、Decimals 全通过。
- **Test / evidence**：可重复 QA Report，列正式 Universe、排除项、最大错误假设与 Frozen Config Hash。
- **Maximum scope**：只修阻塞 Gate 的 Collector/Data Bug；可缩小 Universe。
- **Explicit non-goals**：在不合格数据上实现复杂 Strategy；增加 Chain/Token。
- **Backlog**：非阻塞字段、可视化、更多历史样本。

## Day 8 — Same-chain DEX–DEX Baseline

- **Objective**：证明公开价差在 Same-size、Gas 和 Re-quote 后是否仍存在，并能可靠证明“没有机会”。
- **Dependencies**：Frozen Config、Cost Ledger、两个可比 Venue/Source、Re-quote Gate。
- **Files**：`src/onchain_arb/detectors/same_chain.py`、`src/onchain_arb/requote.py`、`tests/test_same_chain.py`、`docs/day08_baseline.md`、`docs/daily/day_08.md`。
- **Acceptance criteria**：一 Chain、一 Liquid Pair、两 Venue；Exact-input A 买→B 卖 Round Trip；保存 Quote Timing/Fee/Gas/Min Output/Approval/Re-quote/全部 Reject Reason。
- **Test / evidence**：Gross Candidates、Re-quote Survivors、Net-positive Survivors、最大 False-positive 来源；Fixture 覆盖 Edge Disappears。
- **Maximum scope**：一个 Pair 与固定 Sizes。
- **Explicit non-goals**：Live Tx、Atomic Smart Contract、Cross-chain Signal。
- **Backlog**：更多 Venue/Pair、Atomic Bundle Construction。

## Day 9 — LI.FI Route Dispersion

- **Objective**：区分 Route Quality Analytics 与真正可交易 Edge。
- **Dependencies**：LI.FI Observations、Route Fingerprint、一个 Independent Direct Source。
- **Files**：`src/onchain_arb/analysis/route_dispersion.py`、`tests/test_route_dispersion.py`、`docs/day09_route_dispersion.md`、`docs/daily/day_09.md`。
- **Acceptance criteria**：计算 Best/Second-best、Switch Rate、Lifetime、Provider Concentration、Duration/Fee Dispersion、Size Sensitivity；每类差异标记 routing/subsidy/stale/mapping/unavailable/tradable。
- **Test / evidence**：至少一个 Candidate 由 Direct Source 确认或否证；不把单纯 Route Difference 标为 Arbitrage。
- **Maximum scope**：Frozen Universe 内现有数据。
- **Explicit non-goals**：执行 LI.FI Route、Bridge Profit Assumption、增加 Aggregator。
- **Backlog**：Provider Reliability Time Series、Subsidy Detection。

## Day 10 — Cross-chain Inventory Model

- **Objective**：建立双链 Virtual Balance Sheet，验证预置库存的可行性与资本占用。
- **Dependencies**：H1、Token Identity、Cost Model、Cross-chain Candidate Evidence。
- **Files**：`src/onchain_arb/inventory.py`、`tests/test_inventory.py`、`config/inventory.toml`、`docs/day10_inventory_model.md`、`docs/daily/day_10.md`。
- **Acceptance criteria**：按 Chain/Asset 记录 Balance、Target Band、Max Imbalance、Trade Size、Capital Occupied；模拟 Cheap-chain Buy + Expensive-chain Sell；输出 Trade PnL、Inventory Change、Capital-hour Return、Required Initial Inventory。
- **Test / evidence**：双腿后总资产守恒（扣成本）；库存不足明确 `INVENTORY_BLOCKED`；每个 Signal 说明条件锁定时点。
- **Maximum scope**：两 Chain、一个 Pair、一组 Policy。
- **Explicit non-goals**：真实 Bridge、Wallet Balance、自动资金配置。
- **Backlog**：多链 Netting、Portfolio Optimization、动态 Bands。

## Day 11 — Rebalance Economics

- **Objective**：把 Local Trade PnL 转换为完整 Inventory Cycle PnL。
- **Dependencies**：Inventory Model、Cost Ledger、Route/Bridge Cost Evidence。
- **Files**：`src/onchain_arb/rebalance.py`、`tests/test_rebalance.py`、`docs/day11_rebalance.md`、`docs/daily/day_11.md`。
- **Acceptance criteria**：实现 Immediate、Threshold-based、Batch 三 Policy；输出 Cycle PnL、Frequency、Break-even Cost、Capacity Curve、Imbalance Distribution。
- **Test / evidence**：必须展示 Trade PnL 正但 Cycle PnL 负、Break-even Rebalance Cost、Size 增大时 Edge/Capacity 变化。
- **Maximum scope**：Deterministic Virtual Rebalance；最多一个可选 Natural Flow 或 Hedge 情景。
- **Explicit non-goals**：真实 Bridge/CEX Order、复杂优化器、Funding Forecast。
- **Backlog**：Natural Netting、CEX/Perp Hedge、Stochastic Rebalance。

## Day 12 — Token Identity 与 Basis Risk

- **Objective**：消除 Symbol-based Mapping，并显式记录资产/发行方/Bridge 风险。
- **Dependencies**：Frozen Tokens、官方 Token/Issuer/Bridge 资料。
- **Files**：`config/token_registry.toml`、`src/onchain_arb/token_registry.py`、`tests/test_token_registry.py`、`docs/day12_token_risk.md`、`docs/daily/day_12.md`。
- **Acceptance criteria**：每个 Token 有 Chain ID、Address、Symbol、Decimals、Issuer、Canonical/Bridged/Wrapped、Redemption、Pause/Blacklist/Upgradeability、Haircut/Exclude。
- **Test / evidence**：Identity Key 强制为 `chain_id + contract_address`；同 Symbol 不自动等价；Registry Validation 全通过。
- **Maximum scope**：当前 Universe Token。
- **Explicit non-goals**：全市场 Token Database、实时信用评分、法律意见。
- **Backlog**：On-chain Metadata Monitor、Issuer Event Alerts。

## Day 13 — Transaction Simulation

- **Objective**：验证至少一个 Same-chain Candidate 在指定 Block State 的 Unsigned Transaction 行为。
- **Dependencies**：Same-chain Candidate、RPC/Simulation Method、Transaction Request、Token Registry。
- **Files**：`src/onchain_arb/simulation.py`、`tests/fixtures/simulation/`、`tests/test_simulation.py`、`docs/day13_simulation.md`、`docs/daily/day_13.md`。
- **Acceptance criteria**：选 `eth_call`、Tenderly 或 Local Fork 之一；保存 Gas Used、Balance Changes、Revert Reason、Approval、Block Context；比较 Quote/Simulation Output 与 Gas。
- **Test / evidence**：至少两个 Failure Fixtures，覆盖 Allowance、Expired/Stale 或 Min-output Revert 中至少两类；无 Simulation Evidence 不可标 Executable/Paper-ready。
- **Maximum scope**：一 Chain、一个 Candidate、一个 Simulation Adapter。
- **Explicit non-goals**：签名、广播、跨链原子模拟、多个 Provider。
- **Backlog**：State Override、Trace Analysis、Fork-based Integration。

## Day 14 — Scanner v1

- **Objective**：把分散能力连接成端到端、可拒绝错误机会的 Research Loop。
- **Dependencies**：Collector、Normalizer、Detector、Re-quote、Ledger、Inventory、Simulation、Evidence Store。
- **Files**：`src/onchain_arb/scanner.py`、`src/onchain_arb/decision.py`、`tests/test_scanner.py`、`scripts/run_scanner.py`、`docs/day14_scanner.md`、`docs/daily/day_14.md`。
- **Acceptance criteria**：实现 Collect→Normalize→Detect→Deduplicate→Re-quote→Cost→Inventory→Simulation→Accept/Reject→Persist；Cost/Raw Ref 100%；状态和 Reject Reason 完整。
- **Test / evidence**：统计 Candidate→Re-quote、Re-quote→Simulation Survival、Lifetime vs Decision Latency；有效样本 <20 标 `sparse`；主动配置 ≤2h，可被动运行 4–8h。
- **Maximum scope**：Primary + Baseline 的单进程 Pipeline。
- **Explicit non-goals**：Dashboard、Live Execution、Alert Fan-out、Distributed Workers。
- **Backlog**：Resume/Checkpoint 优化、更多 Adapter、Operational UI。

## Day 15 — Hypothesis Ranking

- **Objective**：用一致 Scorecard 决定 Primary、Backup，并明确放弃至少一个方向。
- **Dependencies**：Week 1 QA、Baseline、Route Dispersion、Inventory/Rebalance、Scanner Evidence。
- **Files**：`docs/day15_hypothesis_ranking.md`、`docs/daily/day_15.md`；必要时只读分析脚本。
- **Acceptance criteria**：H1/H2/H3 均列 Supporting/Contradictory Evidence、Null、Sample、Unknown、Keep/Modify/Kill；按 25/20/15/15/10/10/5 权重评分；选 Primary + Backup。
- **Test / evidence**：评分输入链接 Raw/Derived Evidence；明确 Kill 至少一个方向且记录理由。
- **Maximum scope**：只比较已有三假设。
- **Explicit non-goals**：新增 Strategy、调整历史结果以提高评分、盈利宣称。
- **Backlog**：更长样本后的 Bayesian Update、替代假设。

## Day 16 — Primary Strategy Specification

- **Objective**：写出另一位开发者可实现相同 Accept/Reject 行为的无歧义规则。
- **Dependencies**：Day 15 Primary、Frozen Registry/Config、Latency/Cost/Inventory Evidence。
- **Files**：`docs/strategy_spec.md`、`config/strategy.toml`、`tests/test_strategy_spec_examples.py`、`docs/daily/day_16.md`。
- **Acceptance criteria**：定义 Universe、Identity、Signal、Freshness、Independent Confirmation、Re-quote、Conservative Output、Buffers、Entry、Size/Capacity、Inventory、Rebalance、Cooldown/Dedupe、Reject、Paper Fill、Kill Metrics；Required Edge 公式完整。
- **Test / evidence**：至少一组 Golden Examples 对相同输入产生固定 Accept/Reject；Config Validation 阻止 TBD 进入 Paper Engine。
- **Maximum scope**：一个 Primary + 一个只读 Backup 描述。
- **Explicit non-goals**：参数优化、机器学习、Live Risk Limits。
- **Backlog**：参数敏感度与多策略组合。

## Day 17 — Event-time Replay

- **Objective**：只用当时已到达的数据重放 Decision，并消除 Snapshot Inflation。
- **Dependencies**：Frozen Strategy、Timestamp/Latency、Historical Evidence、Candidate IDs。
- **Files**：`src/onchain_arb/replay.py`、`tests/test_replay.py`、`scripts/run_replay.py`、`docs/day17_replay.md`、`docs/daily/day_17.md`。
- **Acceptance criteria**：不用 OHLC；采用实际 Latency Distribution；Entry 使用 Re-quote/Min Output/Simulation；连续 Snapshot 聚为 Opportunity Cluster；追踪 Virtual Inventory/Rebalance。
- **Test / evidence**：报告 Detected、Unique Clusters、Survival、Net Edge p05/p50/p95、Decay、Lifetime、Capacity、Capital-hour Return、Worst Case；未来数据泄漏测试。
- **Maximum scope**：现有采集窗口、一个 Strategy Config。
- **Explicit non-goals**：Candle Backtest、参数搜索、伪造 Fill Precision。
- **Backlog**：更长历史、Monte Carlo、Counterfactual Ordering。

## Day 18 — Paper Decision Engine

- **Objective**：建立幂等、可审计的 Virtual Decision/Fill State Machine。
- **Dependencies**：Strategy Spec、Replay、Scanner、Virtual Inventory、Evidence Store。
- **Files**：`src/onchain_arb/paper_engine.py`、`tests/test_paper_engine.py`、`scripts/run_paper_engine.py`、`docs/day18_paper_engine.md`、`docs/daily/day_18.md`。
- **Acceptance criteria**：实现 DETECTED→REQUOTING→COSTED→INVENTORY_CHECKED→SIMULATED/NA→PAPER_READY→PAPER_FILLED→REBALANCE_PENDING→CLOSED，以及 REJECTED/EXPIRED/ERROR；处理 Expiry、Route Change、Virtual Allowance、Audit Log。
- **Test / evidence**：重复 Candidate 不重复 Fill；每个 Paper Fill 回溯 Raw、Re-quote、Ledger、Simulation；Alert 只针对 PAPER_READY 或系统异常。
- **Maximum scope**：Paper-only、单进程、Virtual Balances。
- **Explicit non-goals**：Wallet、Signing、Broadcast、真实通知集成。
- **Backlog**：Crash Recovery、外部 Alert Connector、Multi-process Lock。

## Day 19 — Stress Test

- **Objective**：寻找平均收益掩盖的最危险 Failure Mode 和经济 Break-even。
- **Dependencies**：Paper Engine、Strategy Config、Replay Evidence、Cost/Latency Distributions。
- **Files**：`src/onchain_arb/stress.py`、`tests/test_stress.py`、`docs/day19_stress.md`、`docs/daily/day_19.md`。
- **Acceptance criteria**：矩阵覆盖 Gas ×2/×5、Latency 1/3/10s、Output Haircut 5/10/25bps、Route Changed、RPC Down、Rebalance ×2、Stablecoin Deviation、Inventory Imbalance、Competitor-first。
- **Test / evidence**：输出 Break-even Gas/Latency/Rebalance、Non-linear Failure、更新 Kill Criteria；至少指出一个被均值掩盖的 Tail Risk。
- **Maximum scope**：Deterministic Scenario Matrix，不做无限组合。
- **Explicit non-goals**：完整风险模型、VaR 认证、真实故障注入到资金系统。
- **Backlog**：联合分布、Monte Carlo、Extreme Depeg Scenarios。

## Day 20 — Final Paper Run

- **Objective**：在冻结代码和配置下验证系统稳定拒绝错误机会并生成审计记录。
- **Dependencies**：测试通过的 Paper Engine、Stress 后 Frozen Config、运行环境。
- **Files**：`config/final_run.toml`、`data/derived/final_run/`、`docs/day20_final_run.md`、`docs/daily/day_20.md`。
- **Acceptance criteria**：冻结 Code/Config，不新增 Chain/Token/Strategy；主动操作 ≤120min；可被动运行 12–24h；检查 Process、Quote Failure、Duplicate、Stale、Transition、Inventory Drift、Alert Quality。
- **Test / evidence**：报告 Detected、Expired、Net-negative、Inventory-blocked、Simulation-failed、Paper-ready/filled、Unique Clusters、System Errors；记录 Commit + Config Hash。
- **Maximum scope**：运维、观察、Bug-only Fix；修复后重新冻结并明确版本。
- **Explicit non-goals**：调参追逐正结果、新功能、Live Execution。
- **Backlog**：更长 Paper Window、可靠调度与监控。

## Day 21 — Final Synthesis

- **Objective**：综合数据、成本、Replay、Paper 和 Stress Evidence 做唯一 A/B/C 决策及 30 天计划。
- **Dependencies**：所有日报、Final Run、Frozen Evidence、Open Unknowns。
- **Files**：`docs/final_report.md`、`docs/30_day_plan.md`、`docs/daily/day_21.md`、最终 Release/Commit Tag 说明。
- **Acceptance criteria**：Final Report 包含 Executive Conclusion、Scope、Data Quality、Cost、Hypotheses、Primary Strategy、Replay/Paper、Counterparty/Edge Source、Capacity/Capital、Failures、Negative Results、Unknowns、Decision、30-day Plan；只选 A/B/C 一个。
- **Test / evidence**：填写结营指标：Primary、Decision、Valid Observations、Clusters、Re-quote/Simulation Survival、Median/P05 Edge、Lifetime、P95 Latency、Capacity、Break-even Rebalance、Largest Risk、Next Date；全部链接证据。
- **Maximum scope**：综合与决策，不重跑未计划研究。
- **Explicit non-goals**：为了给出 A 而改变 Gate、实盘部署、无证据盈利预测。
- **Backlog**：只进入 30 天计划，并按 A/B/C 结果排序；C 时写清 Pivot 或停止条件。

## 依赖 Gate 摘要

```text
Day 2 Models
  → Day 3 Executable Price
  → Day 4 API Probe
  → Day 5 Collector
  → Day 6 Block Context
  → Day 7 Data Gate
  → Day 8 Baseline + Day 9 Dispersion
  → Day 10 Inventory
  → Day 11 Rebalance + Day 12 Identity
  → Day 13 Simulation
  → Day 14 Scanner
  → Day 15 Ranking
  → Day 16 Strategy Spec
  → Day 17 Replay
  → Day 18 Paper Engine
  → Day 19 Stress
  → Day 20 Frozen Run
  → Day 21 A/B/C Decision
```

若任一 Gate 不合格，先修最早失效依赖或选择 Extend/Kill；禁止靠下游复杂度掩盖上游证据缺口。
