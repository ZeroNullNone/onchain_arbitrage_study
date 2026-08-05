# Day 1 — Research Charter、系统设计与执行计划

- 日期：2026-08-05
- 状态：完成
- 今日主题：先定义研究，再设计系统
- 今日核心问题：这 21 天要验证什么，什么证据才足以把“观察到价差”升级为“值得继续研究的机会”？
- 公开版本：[GitHub Day 1 Note](https://github.com/ZeroNullNone/onchain_arbitrage_study/blob/main/docs/daily/day_01.md)

## ICL Agent Check-in

- 发布状态：成功
- Check-in ID：`cmsg0p4rr01gwpl29uatlafor`
- 发布时间：2026-08-05 11:42:26 UTC（19:42:26 UTC+8）
- 课程页面：[链上套利残酷共学](https://intensivecolearn.ing/programs/b43d2e97-ed88-4ca3-b12f-7ef672b01205)

## 今日一句话总结

本项目不是收集“看起来有利润”的价差，而是建立一条可追溯、可重放、execution-aware 的证据链，判断预置库存跨链套利在完整周期成本后是否值得继续研究。

## 今天已完成

### 1. 审阅 Day 1 计划并缩小范围

确认 Day 1 的目标不是实现 Scanner 或交易逻辑，而是完成以下基础工作：

- 明确可证伪的研究假设、成功标准和 Kill Criteria；
- 建立 Opportunity Taxonomy；
- 定义最小 Research Loop 和组件边界；
- 固定 Day 2–21 的依赖顺序；
- 建立安全、证据和工程规则。

### 2. 完成 Day 1 必修概念学习

已完成研究笔记：[`docs/research/day1_essential_concepts.md`](../research/day1_essential_concepts.md)。

掌握的核心主线：

```text
观察到价差
≠ 获得可执行报价
≠ 两条腿都能成交
≠ 完整周期赚钱
```

重点理解：

- Research Hypothesis 必须包含机制、Universe、可执行条件、成本边界和判定标准；
- 研究成功不等于证明盈利，`Kill/Pivot` 也可以是高质量结果；
- Displayed Price、Quoted Price、Executable Price 和 Realized Price 不能混用；
- Price Impact 是自己的订单对 Pool 造成的影响，Slippage 是 Quote 到执行之间的偏差；
- Slippage Tolerance 是保护阈值，不是必然成本；
- 两笔独立 Transaction 不具备共同回滚能力；只有封装在同一 Transaction 中的调用才可能原子执行；
- Atomicity 描述“全部成功或全部回滚”，Finality 描述已发生结果被 Reorg 的难度；
- Pre-positioned Inventory 减少桥接等待，但跨链两腿仍然是 Non-atomic，并存在 Leg Risk；
- Opportunity PnL 不等于 Cycle PnL，后者必须包含恢复目标库存的成本；
- Raw Evidence 必须不可变，Normalized 和 Derived 数据必须能够回溯到 Raw；
- 第一次 Quote 用于发现，独立 Re-quote 用于确认机会是否仍存在；
- Cost Ledger 必须有单一 Owner，防止 Double Count、Under Count 和语义不一致；
- Simulation 只能证明指定 Block State 下的结果，不能保证未来实盘执行、排序、跨链第二腿或最终利润。

参考的一手资料包括：

- [Ethereum Transactions](https://ethereum.org/developers/docs/transactions)
- [Solidity Error Handling and Revert](https://docs.soliditylang.org/en/latest/control-structures.html)
- [Uniswap Price Impact](https://support.uniswap.org/hc/en-us/articles/8671539602317-What-is-price-impact)
- [Uniswap Price Impact vs Slippage](https://support.uniswap.org/hc/en-us/articles/8643794102669-Price-Impact-vs-Price-Slippage)
- [LI.FI Quote vs Route](https://docs.li.fi/introduction/user-flows-and-examples/difference-between-quote-and-route)
- [LI.FI Route Execution](https://docs.li.fi/sdk/execute-routes)
- [LI.FI Status Tracking](https://docs.li.fi/introduction/user-flows-and-examples/status-tracking)
- [W3C PROV](https://www.w3.org/TR/prov-o/)
- [ERC-20](https://eips.ethereum.org/EIPS/eip-20)
- [Geth `eth_call`](https://geth.ethereum.org/docs/interacting-with-geth/rpc/ns-eth)

### 3. 完成概念自测和纠错

自测初始掌握度约为 7/10。已经纠正以下理解：

1. 两个 Quote 的差只能叫 Quoted Spread；它还没有证明两腿可执行，也没有包含完整周期成本。
2. 两笔同链交易若是两个独立 Transaction，第一笔成功后不能因为第二笔失败而共同回滚。
3. Pre-positioned Inventory 的主要 Leg Risk 是一条链成功、另一条链失败；库存或 Gas 不足属于 Feasibility Risk。
4. Cost Ledger 的单一所有权不只是负责计算成本，更重要的是防止重复扣费、漏算和不同 Adapter 使用不同成本语义。

### 4. 确认残酷共学 Agent API 打卡方式

已确认 `ACCESS_KEY` 用于 ICL 2.0 Agent API，并通过只读接口验证认证有效。已创建安全发布说明：[`docs/agent_checkin.md`](../agent_checkin.md)。

没有发布任何打卡，也没有输出或写入 Access Key。

### 5. 完成 Research Charter 与 Opportunity Taxonomy

- [`docs/research_charter.md`](../research_charter.md)：正式冻结 H1/H2、Universe、USD 3,000–10,000 假设性 Capital Band、成功/Kill Criteria、Non-goals 和 Cross-chain Conditional Profit-locking Definition。
- [`docs/opportunity_taxonomy.md`](../opportunity_taxonomy.md)：完成 Same-chain、Triangular、Route Dispersion、Pre-positioned Inventory、Token Basis、MEV 六类机会的 Atomicity、Inventory、Latency、Counterparty、Capacity、Failure Mode 和 Priority 对比。

### 6. 完成最小系统设计

已创建 [`docs/system_design.md`](../system_design.md)，定义：

- Source Adapter、Collector、Raw Evidence Store、Normalizer、Detector、Re-quote、Cost Ledger、Inventory、Simulation、Decision、Report 的职责和输入输出；
- Raw / Normalized / Derived 数据边界与 Lineage；
- Candidate Lifecycle、Reject Reasons、Re-quote/Simulation Gate；
- Cost Ledger 单一 Owner、Idempotency/Deduplication、Config Boundary 和 Explicit Failure Handling；
- Codex 可以实现的确定性工程工作，以及必须由研究者确认的经济判断。

系统保持 Deep Module 原则：外部 Source 差异留在 Adapter，实现复杂度收进 Module，调用方只依赖小而稳定的 Interface；不为 Dashboard、Live Wallet、MEV 等非目标预建 Seam。

### 7. 完成 Day 2–21 可执行计划

已创建 [`docs/implementation_plan.md`](../implementation_plan.md)。Day 2–21 每天均包含：

- Objective、Dependencies；
- Files to create/modify；
- Acceptance Criteria、Test/Evidence；
- Maximum Scope、Explicit Non-goals、Backlog。

依赖主线已固定为：

```text
Models → API Probe → Collector → Data Gate → Baseline
→ Inventory → Rebalance → Simulation → Scanner
→ Strategy Spec → Replay → Paper Engine → Stress → Final Decision
```

### 8. 完成 Repo Skeleton、规则与测试

- 创建 `README.md`、`pyproject.toml`、`config/research.example.toml`；
- 创建 `src/onchain_arb/` 与 `tests/`；
- 创建 `data/raw/`、`data/normalized/`、`data/derived/` 并默认忽略运行数据；
- 补全 `AGENTS.md` 的 Simulation-only、Never Handle Private Keys、Raw Preservation、Integer + Decimal、UTC + Latency、No Silent Fallback、Full Cost Ledger、Adapter Fixture/Test 和 Scope Control 规则；
- 完善 `.gitignore`，排除 `.env`、Virtual Environment、Cache、Local Database 和 Research Runtime Data；
- 创建 `.env.example`，只含空白 `ACCESS_KEY` 占位，不含真实 Credential；
- 使用 Python 3.12 和 pytest 运行 Smoke Test：`1 passed`。

## 当前暂定的研究方向

以下方向已经正式写入并确认在 `research_charter.md` 中：

### Primary Hypothesis

在 Arbitrum、Base、Optimism 上预先持有 USDC、USDT、WETH，以 USD 100、500、1,000 的规模交易。当两个本地交易腿都通过新鲜 Re-quote，且扣除 Swap Fee、Price Impact、Gas、Rebalance、Hedge、Capital Cost 和 Failure Allowance 后，是否仍存在可重复观察的正 Cycle PnL？

### Baseline Hypothesis

同链公开 DEX–DEX 往返交易是否偶尔会在扣除 Gas 和全部显性成本后仍保持正净收益？该 Baseline 同时用于发现 Decimals、Token Identity、陈旧 Quote 和成本核算错误。

### 暂定 Profit-locking Definition

跨链 Pre-positioned Inventory Candidate 只有在以下条件全部满足时，才能标记为 `paper-ready`：

- 两条链均有足够目标资产和 Gas Token；
- 两个相反方向的本地交易腿均在规定窗口内独立 Re-quote；
- 使用保守输出和完整 Cycle Cost 后 PnL 仍为正；
- 记录了失败准备金、库存变化和未来 Rebalance 义务；
- 只代表 Paper Decision，不宣称跨链原子保证或无风险利润。

## 综合例子

观察到：

```text
Arbitrum 买入 0.25 WETH：500.00 USDC
Base 卖出 0.25 WETH：   503.00 USDC
Gross Spread：             3.00 USDC
```

重新 Quote 后，Base 输出下降为 502.40 USDC。加入完整成本：

```text
Base 最新输出              502.40
Arbitrum 买入成本          -500.00
Arbitrum Gas                -0.18
Base Gas                    -0.12
Rebalance 分摊              -1.40
Capital/Hedge/Failure       -0.90
---------------------------------
Cycle PnL                   -0.20 USDC
```

最终 Decision：

```text
REJECTED_COST
```

这个结果说明观察到了价差，但它不足以形成正 Cycle PnL。Reject 本身也是研究证据。

## Day 1 Exit Criteria 检查

- [x] 能用两分钟解释目标、非目标和 H1/H2。
- [x] 能画出完整 Research Loop。
- [x] 每个 Module 的 Interface、输入输出和责任已有定义。
- [x] Day 2–21 依赖与每日 Acceptance Criteria 已固定。
- [x] 21 天内明确不实现 Live Signing、Flash Loan、MEV、Dashboard 和 Production Deployment。
- [x] Repo Skeleton、Agent Rules 与 pytest Smoke Test 完成。
- [x] Git Repository、`origin` 与 Day 1 Commit 在本日最终步骤完成。
- [x] ICL Agent Check-in 已通过 Agent API 发布，并记录 Check-in ID 与时间。

## 带入后续日期的 Backlog / Data Gates

- Day 4 前选择一个 Direct DEX/Aggregator Confirmation Source。
- Freshness Window 在 Day 7/16 依据真实 Latency 和 Opportunity Lifetime 冻结。
- Minimum Economic Profit、Cost Uncertainty Buffer 在 Day 16 冻结。
- Inventory Target Band 和 Maximum Drift 在 Day 10 用 Virtual Balance Sheet 确认。
- Simulation Workflow 在 Day 13 从 Tenderly、Local Fork、`eth_call` 中选择一个。

这些项目不是 Day 1 缺失项；它们需要后续数据或对应模型，过早给出数值会制造虚假精确度。

## 下一步：Day 2

只实现 `TokenAmount`、`CostItem`、`QuoteObservation`、`OpportunityCandidate`、`SimulationResult` 和 Cost Ledger，并完成三个强制测试。不要提前接 LI.FI、数据库或 Scanner。
