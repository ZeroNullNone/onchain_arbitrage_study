# Research Charter

## 研究使命

在 21 天内建立一条可持续、可审计、execution-aware 的链上套利研究闭环，用证据判断候选机会在重新报价、完整成本、库存约束与模拟之后是否仍值得进入更长周期的 Paper Research。

研究成功不等于证明盈利。可靠地证明某条路线不可行、数据不足或成本后为负，同样是成功结果。

## 可证伪假设

### H1 — Primary：预置库存跨链套利

在 Arbitrum、Base、Optimism 预先持有 USDC、USDT、WETH，以 USD 100、500、1,000 的目标规模进行研究。如果两条本地交易腿均通过独立、新鲜的 Re-quote，并扣除 Swap Fee、Price Impact、Gas、Rebalance、Hedge/Funding、Inventory Mark-to-market、Capital Occupation Cost 与 Failure Allowance，那么仍可能出现可重复观察、可在 Paper 模式记录为正的 Cycle PnL。

反证：正价差在 Re-quote 后消失，或加入完整周期成本与库存约束后没有正 Cycle PnL。

### H2 — Baseline：同链公开 DEX–DEX 往返

在同一条链、同一 Liquid Pair 和同一 Target Size 下，公开 DEX–DEX 的 Quoted Spread 在 Gas、Approval、Fee、Price Impact、Re-quote 与 Simulation 后大部分会消失。该基线既用于衡量公开市场效率，也作为 Decimals、Token Identity、Stale Quote 和成本重复计算的数据质量对照。

反证：存在可重复、模拟可执行且保守净收益为正的独立机会簇。

## 固定研究 Universe

Day 1–7 不扩张 Universe：

| 维度 | 范围 |
|---|---|
| Chains | Arbitrum、Base、Optimism |
| Assets | USDC、USDT、WETH；身份以 `chain_id + contract_address` 为准 |
| Target sizes | USD 100、500、1,000 |
| Quote sources | LI.FI、一个独立 Direct DEX/Aggregator、EVM RPC |
| Runtime | Python 3.12 |
| Storage | Raw JSON、Parquet、DuckDB |
| Accounting | Integer raw units + token decimals + `Decimal` |
| Execution mode | Read-only、Simulation-only、Paper-only |

Day 7 只可根据数据覆盖、费用、Route Diversity 与 Data QA 缩小或冻结 Universe；扩张进入 Backlog。

## Capital Band 与风险限制

- 假设性研究资金区间：USD 3,000–10,000，总额仅用于计算 Capital Efficiency，不代表部署授权。
- 单个交易腿的目标名义金额上限：USD 1,000。
- 所有 Balance、Allowance 和 Fill 均为 Virtual/Paper 状态。
- 不连接钱包、不接触私钥、不签名、不广播交易。
- Inventory Band、最大 Drift 和 Chain Allocation 在 Day 10 用数据确定；在此之前不得把未定义的库存容量当作可执行性证据。

## 成功标准

### 研究系统成功

- 每条 Normalized Record、Candidate、Decision 均能追溯到不可变 Raw Evidence。
- Raw Reference、UTC Timestamp、Latency Coverage 达到 100%。
- 核心字段 Parse Success 在 Day 7 达到至少 95%；Decimals Tests 全部通过。
- Collector 重启不覆盖历史记录；Candidate 去重与状态迁移可审计。
- 每条正信号经过独立 Re-quote、完整 Cost Ledger 与 Inventory Check。
- Same-chain `PAPER_READY` 还必须有 Simulation Evidence。
- 最终以证据做出且只做出 A（继续 Paper）、B（延长采集）或 C（Kill/Pivot）之一。

### H1 获得支持

至少出现一个独立机会簇，在新鲜双边 Re-quote、保守输出、完整 Cycle Cost 和可行 Virtual Inventory 下仍为正；该结果只能支持继续 Paper Research，不能宣称已锁定实盘利润。

### H2 获得支持

同链 Gross Candidate 的绝大部分在 Re-quote、完整成本或 Simulation Gate 后被解释和拒绝，且 Scanner 可以可靠保存“没有机会”的证据。

## Failure / Kill Criteria

出现以下任一情形，应 Kill、Pivot 或延长数据采集，而不是美化结果：

- 正价差系统性地在独立 Re-quote 后消失。
- 正结果只能由 Decimals、Token Mapping、Stale Quote、Fee Double Count/Under Count 或重复 Snapshot 解释。
- Rebalance、Hedge、Capital 或 Failure Allowance 使 Cycle PnL 持续为负。
- Opportunity Lifetime 低于实际 Decision Latency，无法合理完成双腿决策。
- 所需库存或 Gas 超出假设 Capital Band，或 Inventory Drift 不可恢复。
- Raw Lineage、时间信息或 Cost Completeness 无法达到 Gate。
- Day 14 后有效样本少于 20：标记 `sparse`，禁止盈利结论；优先选择 B。
- Simulation 显示 Revert、Allowance、Min-output 或 State Staleness 问题且无法在本期范围内可靠处理。

## Cross-chain Profit Locking Definition

跨链交易由两笔独立 Transaction 组成，因此不是原子执行，也不存在无条件利润锁定。本项目只使用“`paper-ready / conditionally lockable`”这一受限定义：

1. 两条链均有足够的目标资产、Stablecoin 与 Gas Token；
2. 相反方向的两条本地交易腿在规定 Freshness Window 内分别独立 Re-quote；
3. 使用 Conservative Output 和完整 Cost Ledger 后，Stressed Cycle PnL 仍为正；
4. 两腿的 Transaction Request、Latency、Route Fingerprint 和 Block Context 均被保存；
5. Inventory Change、Failure Allowance 与未来 Rebalance Obligation 已计入；
6. 结论只允许进入 Paper Decision，不代表共同回滚、成交保证、Finality 保证或无风险利润。

Freshness Window、最低经济利润与 Cost Uncertainty Buffer 在 Day 7/16 由观测分布冻结；在冻结前只能报告为 `TBD`，不得静默采用宽松默认值。

## 21 天明确不做

- Mainnet Live Execution、钱包连接、私钥、签名或广播。
- Flash Loan Contract、MEV Bundle/Searcher、Backrun 或 Liquidation Execution。
- Multi-chain Archive Indexer、200ms Latency、Production Deployment。
- Docker/Kubernetes、完整 Dashboard、多策略 Portfolio。
- AI 自动寻找 Alpha、盈利证明或代客资金管理。
- 用网页 Displayed Price、Candle OHLC 或 Reserve Ratio 代替 Executable Quote。

## 决策原则

- 发现 Quote 只用于 Detect；独立 Re-quote 才能进入成本与库存判断。
- Opportunity PnL 与 Cycle PnL 分开报告；H1 的最终经济判断只看 Cycle PnL。
- Slippage Tolerance 是保护阈值，不自动记为已发生成本；保守输出与实际成本必须分项。
- 所有 Unknown 明示，不以 Silent Fallback、自动补零或推测字段通过 Gate。
- Reject 是一等研究结果，必须保存 Reason 与 Evidence。

