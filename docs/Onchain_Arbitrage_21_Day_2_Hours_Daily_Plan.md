# 链上套利残酷共学：21 天 × 每日 2 小时执行计划

> **适用对象**：Louis（Python / Quant Research / Arbitrage / Execution System 背景）  
> **执行周期**：2026-08-05 至 2026-08-25  
> **Buffer / 补交日**：2026-08-26  
> **每日时间预算**：最多 120 分钟，连续执行 21 天，不设休息日或补偿性加时。
> **执行原则**：每一天均有 Core deliverable；任务未完成时缩小 scope，不把工作累计到下一天。
>
> **核心目标**：在 21 天内建立一个可持续自主研究的 `execution-aware on-chain arbitrage research loop`，而不是仓促完成自动实盘 Bot。

---

## 1. 21 天结束时的目标状态

### 必须完成

1. 一个明确的 Research Charter。
2. 一个不会 double count 的 Cost Ledger。
3. 一个可持续运行的 LI.FI Quote Collector。
4. Raw 与 normalized dataset。
5. 一个最小 Scanner：

```text
Collect
→ Normalize
→ Detect
→ Re-quote
→ Cost
→ Reject / Paper-ready
→ Persist Evidence
```

6. 两个 Hypothesis：

- **H1 Primary**：Cross-chain pre-positioned inventory arbitrage。
- **H2 Baseline**：Same-chain public DEX–DEX executable round trip。

7. 至少一个 transaction simulation workflow。
8. 一个简化 Event-time Replay。
9. 一个 Paper Execution / Shadow Decision Log。
10. Final Decision：Continue / Extend Data / Kill-Pivot。
11. 一份 30 天后续计划。

### 不要求完成

- Mainnet live execution
- Flash Loan smart contract
- MEV bundle/searcher infrastructure
- Multi-chain archive indexer
- 完整 Web Dashboard
- AI model 自动寻找 alpha
- 200ms latency
- Docker / Kubernetes / production deployment
- 多策略 portfolio
- 盈利证明

---

## 2. 时间管理规则

### 每日固定 Timebox：最多 120 分钟

| 模块 | 时间 |
|---|---:|
| 今日问题与设计检查 | 10–15 min |
| Reading / Documentation | 15–20 min |
| Implementation / Experiment | 65–75 min |
| Evidence Review + Daily Note | 15–20 min |
| 总计 | 105–120 min |

### Daily Completion Rule

每天都必须完成一个可验证的最小交付物，不设休息日，也不因周末增加任务量。

若任务在 120 分钟内无法完成：

1. 停止增加功能。
2. 保留最小可运行或可验证 slice。
3. 将未完成部分写入 Backlog。
4. 不把未完成工作直接叠加到次日 Core task。
5. 次日只在它阻塞主线时，使用前 30 分钟修复。
6. 不牺牲 raw evidence、accounting correctness、tests 和 reject logging。

### Scope Reduction 顺序

超时时按以下顺序删减：

1. UI / Dashboard
2. Additional chain / token / size
3. Secondary adapter
4. Performance optimization
5. Optional metrics
6. Documentation polish

不得删减：

- Raw response preservation
- Token decimals correctness
- Cost ledger
- Re-quote
- Reject reason
- Evidence traceability

---

## 3. 最小研究 Universe

第一周结束前保持固定：

- **Chains**：Arbitrum、Base、Optimism
- **Assets**：USDC、USDT、WETH
- **Notional Sizes**：USD 100、500、1,000
- **Sources**：
  - LI.FI API
  - 1 个 direct DEX / aggregator confirmation source
  - EVM RPC
- **Storage**：Parquet + DuckDB
- **Runtime**：Python 3.12
- **Accounting**：integer raw amount + token decimals + `Decimal`
- **Simulation**：Tenderly、local fork 或 `eth_call`，选择其中一个即可

正式 universe 应在 Day 7 根据 quote availability、费用、route diversity 和数据质量调整。

---

# 4. 21 天总览（每日 ≤ 2 小时，无休息日）

| Day | Type | 主题 | 当日最低产出 |
|---:|---|---|---|
| 1 | Core | Research Charter | Scope、成功标准、非目标 |
| 2 | Core | PnL 与 Cost Ledger | 成本模型 + 3 个测试 |
| 3 | Core | AMM Executable Price | Size / impact 对比 |
| 4 | Core | LI.FI API Probe | Raw quote 与 schema map |
| 5 | Core | Quote Collector v0 | 可持续采集与落盘 |
| 6 | Core | RPC / Block Context | Quote 与 block 对齐 |
| 7 | Core | Week 1 Data Gate | Data QA 与 universe freeze |
| 8 | Core | Same-chain Baseline | Round-trip scanner |
| 9 | Core | Route Dispersion | 多路径稳定性分析 |
| 10 | Core | Inventory Arbitrage Model | 双链 balance sheet |
| 11 | Core | Rebalance Economics | Cycle PnL 与 capacity |
| 12 | Core | Token Identity / Risk | Token registry |
| 13 | Core | Transaction Simulation | Quote vs simulation |
| 14 | Core | Scanner v1 | 完整 reject pipeline |
| 15 | Core | Hypothesis Ranking | Primary / baseline verdict |
| 16 | Core | Strategy Specification | 无歧义规则与 guards |
| 17 | Core | Event-time Replay | Latency-aware evidence |
| 18 | Core | Paper Decision Engine | State log / virtual fill |
| 19 | Core | Stress Test | Break-even 与 failure modes |
| 20 | Core | Final Run | 12–24h paper observation |
| 21 | Core | Final Synthesis | A/B/C decision + 30-day plan |

---

# 5. 每日详细计划

## Day 1 — Research Charter、系统设计与执行计划

**学习难度**：中  
**预计时间**：120 分钟

### 核心问题

这 21 天要验证什么、系统最小闭环是什么，以及每天应按什么依赖顺序推进？

### Timebox

| 工作 | 时间 |
|---|---:|
| Research Charter | 20 min |
| System Design | 40 min |
| 21-day Implementation Plan | 35 min |
| Repo / AGENTS / Smoke Test | 25 min |

### Core Tasks

#### 1. Research Charter

创建 `docs/research_charter.md`，明确：

- Primary hypothesis
- Baseline hypothesis
- Target chains / assets / sizes
- Capital band
- Success criteria
- Failure / Kill criteria
- 21 天内不做的事项
- 不进行 live execution
- Cross-chain opportunity 的 profit locking definition

#### 2. Opportunity Taxonomy

创建 `docs/opportunity_taxonomy.md`，至少包含：

- Same-chain DEX–DEX
- Triangular arbitrage
- Cross-chain route dispersion
- Pre-positioned inventory arbitrage
- Stablecoin / wrapped asset basis
- MEV / backrun / liquidation（study-only）

每类标注：

- Atomic / non-atomic
- Required inventory
- Latency sensitivity
- Counterparty
- Capacity constraint
- Main failure mode
- 本期 Priority

#### 3. System Design

创建 `docs/system_design.md`。

最小系统架构：

```text
LI.FI / Direct Quote / RPC
          │
          ▼
      Collectors
          │
          ▼
   Raw Evidence Store
          │
          ▼
      Normalizer
          │
          ▼
 Candidate Detector
          │
          ▼
       Re-quote
          │
          ▼
 Cost + Inventory Check
          │
          ▼
 Simulation / Paper Decision
          │
          ▼
 Evidence Log + Daily Report
```

设计必须定义：

- Component responsibilities
- Input / output schema
- Raw vs normalized data boundary
- Candidate lifecycle
- Cost ledger ownership
- Re-quote gate
- Simulation boundary
- Storage layout
- Failure handling
- Idempotency / deduplication
- Config boundary
- 哪些部分由 Codex 实现
- 哪些经济判断必须由你完成

#### 4. Generate 21-day Implementation Plan

创建 `docs/implementation_plan.md`，将 Day 2–21 转换为可执行任务。

每一天必须包含：

- Objective
- Dependencies
- Files to create / modify
- Acceptance criteria
- Test / evidence
- Maximum scope
- Explicit non-goals
- Backlog items

计划依赖顺序：

```text
Models
→ API Probe
→ Collector
→ Data Gate
→ Baseline Signal
→ Inventory Model
→ Rebalance Model
→ Simulation
→ Scanner
→ Strategy Spec
→ Replay
→ Paper Engine
→ Stress
→ Final Decision
```

#### 5. Repo 与 Agent Rules

建立：

```text
onchain-arb-lab/
├─ AGENTS.md
├─ README.md
├─ pyproject.toml
├─ config/
├─ docs/
│  ├─ research_charter.md
│  ├─ opportunity_taxonomy.md
│  ├─ system_design.md
│  ├─ implementation_plan.md
│  └─ daily/
├─ src/onchain_arb/
├─ tests/
└─ data/
   ├─ raw/
   ├─ normalized/
   └─ derived/
```

`AGENTS.md` 至少包括：

- Read-only / simulation-only by default
- Never handle private keys
- Preserve raw responses
- Integer raw units + `Decimal`
- Record UTC timestamp and latency
- No silent fallback
- Every positive signal requires full cost ledger
- Every adapter change requires fixture + test
- Implement only current day acceptance criteria
- No premature Dashboard / live signing / Flash Loan / MEV infrastructure

### 最低交付物

- `research_charter.md`
- `opportunity_taxonomy.md`
- `system_design.md`
- `implementation_plan.md`
- `AGENTS.md`
- Repo skeleton
- `pytest` smoke test
- Day 1 commit

### Exit Criteria

Day 1 结束时，你必须能够：

1. 用 2 分钟解释课程目标和非目标。
2. 画出完整 research loop。
3. 解释每个 component 的 input / output。
4. 说明 Day 2–21 的依赖顺序。
5. 指出哪些模块在 21 天内明确不实现。
6. 直接把 `implementation_plan.md` 交给 Codex，逐日执行而不需要重新设计项目。

---

## Day 2 — PnL Truth 与 Cost Ledger

**学习难度**：中  
**预计时间**：120 分钟

### Core Tasks

建立最小 models：

- `TokenAmount`
- `CostItem`
- `QuoteObservation`
- `OpportunityCandidate`
- `SimulationResult`

建立两类 PnL：

```text
Atomic / same-chain net PnL
= final balance change
- gas
- external fees
- failure allowance
```

```text
Inventory cycle PnL
= local trade PnL
- rebalance cost
- hedge fee / funding
- inventory mark-to-market
- capital occupation cost
```

增加：

- `included_in_quote_output`
- `confidence = exact / estimated / stressed`
- `source`
- `observed_at`

### 必须测试

1. Gross positive，Gas 后 negative。
2. Fee 已包含在 output，却被重复扣除。
3. Local trade positive，rebalance 后 cycle negative。

### Exit Criteria

任意 candidate 都能输出人工可复核的 cost breakdown。

---

## Day 3 — AMM Executable Price

**学习难度**：中  
**预计时间**：90 分钟

### Tasks

选择一个 liquid pair，对 USD 100 / 500 / 1,000 比较：

- Displayed / spot price
- Exact-input executable price
- Average execution price
- Price impact
- Minimum output
- Pool fee

### 最低交付物

一张 size → output / price impact / net edge 表。

### Exit Criteria

后续 scanner 不允许直接使用网页 price 或 reserve ratio 作为成交价。

---

## Day 4 — LI.FI API Probe

**学习难度**：中  
**预计时间**：120 分钟

### Core Tasks

- 对 3 个 route × 3 个 size 获取 quote。
- 保存完整 raw JSON。
- 映射：
  - chain / token address
  - `fromAmount`
  - `toAmount`
  - `toAmountMin`
  - gas / fee
  - duration
  - tools / route steps
  - approval address
  - transaction request
- 建立 `route_fingerprint`。
- 为 API response 建立 fixture。

### Exit Criteria

可以从保存的数据重建完整 request、route、output、minimum output 和成本。

---

## Day 5 — Quote Collector v0

**学习难度**：中高  
**预计时间**：120 分钟

### Core Tasks

实现低并发 async collector：

- timeout
- retry + backoff
- rate-limit handling
- request ID
- UTC timestamps
- latency
- raw / normalized separation
- append-only storage
- Parquet + DuckDB

Polling interval 使用 30–60 秒。

### 运行要求

至少持续 2 小时；不强制 overnight。

### 最低 Metrics

- request count
- success rate
- parse failure
- timeout
- p50 / p95 latency
- unavailable route count

### Exit Criteria

Collector restart 不覆盖旧数据，每条 normalized record 可追溯到 raw response。

---

## Day 6 — RPC / Block Context

**学习难度**：中  
**预计时间**：90 分钟

### Tasks

- 记录 quote 时附近的：
  - block number
  - block timestamp
  - base fee
  - chain head
- 可选：用 The Graph 查询一个 DEX 的 swap event。
- 测量 indexed data 与 chain head lag。

### Exit Criteria

明确：

- Indexed data 用于 research / backfill。
- Direct quote + RPC 用于 execution-time decision。

---

## Day 7 — Week 1 Data Gate

**学习难度**：中  
**预计时间**：120 分钟

### Data QA

- schema completeness
- decimals correctness
- duplicate rate
- missingness
- timestamp ordering
- raw reference coverage
- latency coverage
- quote failure rate
- route availability
- size sensitivity

### Gate

建议目标：

- ≥ 200 valid observations；若低于此数，需要写明原因。
- Raw reference coverage = 100%。
- Timestamp / latency coverage = 100%。
- Decimal tests 全部通过。
- 核心字段 parse success ≥ 95%。

### Output

- `week_1_report.md`
- 正式 universe
- 排除项
- 最大错误假设
- Week 2 frozen config

### Exit Criteria

数据不合格时，不进入复杂 strategy，先修 collector。

---

## Day 8 — Same-chain DEX–DEX Baseline

**学习难度**：中高  
**预计时间**：120 分钟

### 核心问题

公开 DEX 价差在同一 target size、Gas、re-quote 后是否仍然存在？

### Tasks

- 一条 chain。
- 一个 liquid pair。
- 两个 venue。
- Exact-input quotes。
- 计算 A 买入 → B 卖出的 round trip。
- 保存：
  - quote timing
  - fee
  - gas
  - minimum output
  - approval cost
  - re-quote result
- 保存所有 reject reason。

### Metrics

- gross candidates
- re-quote survivors
- net-positive survivors
- 最大 false-positive 来源

### Exit Criteria

Scanner 能可靠证明「没有机会」。

---

## Day 9 — LI.FI Route Dispersion

**学习难度**：中  
**预计时间**：120 分钟

### Tasks

分析相同输入下：

- best vs second-best output
- route switch rate
- route lifetime
- provider concentration
- duration dispersion
- fee dispersion
- size sensitivity

至少用一个 independent direct source 做确认。

### 重点判断

Route difference 属于：

- routing improvement
- temporary subsidy
- stale quote
- token mapping difference
- unavailable route
- 真正可交易 edge

### Exit Criteria

不给 routing analytics 错误贴上 arbitrage 标签。

---

## Day 10 — Cross-chain Inventory Model

**学习难度**：中高  
**预计时间**：120 分钟

### Core Tasks

建立 two-chain virtual balance sheet：

- asset balance per chain
- stablecoin balance per chain
- target inventory band
- maximum imbalance
- trade size
- capital occupied

模拟：

- cheap chain buy
- expensive chain sell
- 双边近同时执行
- 不依赖 bridge 后价差仍然存在

### Output

- Trade PnL
- Inventory change
- Capital-hour return
- Required initial inventory

### Exit Criteria

每个 cross-chain signal 都能说明利润锁定时点和 inventory requirement。

---

## Day 11 — Rebalance Economics

**学习难度**：高  
**预计时间**：120 分钟

### Tasks

实现三种 rebalance policy：

1. Immediate
2. Threshold-based
3. Batch

可选：

4. Natural flow netting
5. CEX / perp hedge

### 输出

- Cycle PnL
- Rebalance frequency
- Break-even rebalance cost
- Capacity curve
- Inventory imbalance distribution

### 必须展示

- 一笔 Trade PnL 为正但 Cycle PnL 为负的例子。
- 一个 break-even rebalance cost。
- Size 增大时 edge 与 capacity 的变化。

### Exit Criteria

不以单笔 local trade PnL 判断 cross-chain strategy profitability。

---

## Day 12 — Token Identity 与 Basis Risk

**学习难度**：中  
**预计时间**：90 分钟

### Tasks

建立 token registry：

- chain ID
- contract address
- symbol
- decimals
- issuer
- canonical / bridged / wrapped
- redemption path
- pause / blacklist / upgradeability
- haircut / exclude decision

### Exit Criteria

Token identity 使用 `chain_id + contract_address`，symbol 只作显示。

---

## Day 13 — Transaction Simulation

**学习难度**：高  
**预计时间**：120 分钟

### Tasks

对至少一个 same-chain candidate：

- 构建 unsigned transaction。
- 使用 Tenderly、local fork 或 `eth_call` 进行 simulation。
- 保存：
  - gas used
  - balance changes
  - revert reason
  - approval requirement
  - block context
- 比较 quote 与 simulation：
  - output difference
  - gas difference
  - stale state
  - allowance issue

### Failure Fixtures

至少两个：

- insufficient allowance
- expired / stale quote
- min-output revert

### Exit Criteria

没有 simulation evidence 的 candidate 不标记为 executable。

---

## Day 14 — Scanner v1

**学习难度**：高  
**预计时间**：120 分钟

### Pipeline

```text
Collect
→ Normalize
→ Detect
→ Deduplicate
→ Re-quote
→ Complete Cost Ledger
→ Inventory Check
→ Simulation（same-chain）
→ Accept / Reject
→ Persist Evidence
```

### Candidate States

- `DETECTED`
- `REQUOTE_FAILED`
- `NET_NEGATIVE`
- `INVENTORY_BLOCKED`
- `SIMULATION_FAILED`
- `PAPER_READY`

### 运行要求

主动配置、检查与分析限制在 2 小时内；scanner 可在完成后被动持续运行 4–8 小时。

### Gate

- Cost completeness = 100%。
- Raw evidence reference = 100%。
- 统计 candidate → re-quote survivor ratio。
- 统计 re-quote → simulation survivor ratio。
- 对比 opportunity lifetime 与 decision latency。
- 若有效样本 < 20，标记为 sparse，不做盈利结论。

### Exit Criteria

形成一个完整 research loop，而不是多个独立 notebook。

---

## Day 15 — Hypothesis Ranking

**学习难度**：中  
**预计时间**：120 分钟

### Hypotheses

#### H1 Primary

选定 L2 之间的 stablecoin / liquid asset dislocation，在预先布置 inventory 后，机会寿命足够完成双边交易，并在 amortized rebalance 后仍有正 edge。

#### H2 Baseline

公开 same-chain DEX–DEX spread 在 same-size、Gas、re-quote 和 simulation 后大部分消失。

#### H3 Optional

LI.FI route dispersion 可以提供 liquidity migration / route quality signal，但未必构成独立 arbitrage。

### Scorecard

| Dimension | Weight |
|---|---:|
| Conservative net-edge evidence | 25 |
| Lifetime vs decision latency | 20 |
| Capital efficiency | 15 |
| Infrastructure fit | 15 |
| Ability to lock profit | 10 |
| Data quality | 10 |
| Operational tail risk | 5 |

### Output

- supporting evidence
- contradictory evidence
- null hypothesis
- sample size
- unknowns
- Keep / Modify / Kill
- primary + backup

### Exit Criteria

明确放弃至少一个不值得继续投入的方向。

---

## Day 16 — Primary Strategy Specification

**学习难度**：高  
**预计时间**：120 分钟

### Strategy Spec 必须定义

- Universe
- Token identity
- Signal formula
- Quote freshness
- Independent confirmation
- Re-quote sequence
- Conservative output
- Cost uncertainty buffer
- Entry threshold
- Size / capacity
- Inventory bands
- Rebalance rule
- Cooldown / dedupe
- Reject conditions
- Paper fill assumptions
- Kill metrics

### Threshold

```text
Required Edge
= Known Execution Cost
+ Cost Uncertainty Buffer
+ Latency Deterioration Buffer
+ Inventory / Rebalance Buffer
+ Minimum Economic Profit
```

### Exit Criteria

另一位开发者只读 spec，就能实现相同的 accept / reject behavior。

---

## Day 17 — Event-time Replay

**学习难度**：高  
**预计时间**：120 分钟

### Tasks

- 不使用 candle OHLC。
- 决策时只能使用当时已到达的数据。
- 使用实际 latency distribution。
- Entry 使用 re-quote / minimum output / simulation result。
- 对连续 snapshots 做 opportunity clustering。
- Inventory strategy 追踪 virtual balance 和 rebalance lifecycle。

### 输出 Metrics

- detected candidates
- unique clusters
- re-quote survival
- simulation survival
- net edge distribution
- p05 / p50 / p95
- edge decay by latency
- opportunity lifetime
- capacity
- capital-hour return
- worst-case scenario

### Exit Criteria

不使用 snapshot inflation 夸大样本数。

---

## Day 18 — Paper Decision Engine

**学习难度**：高  
**预计时间**：120 分钟

### State Machine

```text
DETECTED
→ REQUOTING
→ COSTED
→ INVENTORY_CHECKED
→ SIMULATED / SIMULATION_NA
→ PAPER_READY
→ PAPER_FILLED
→ REBALANCE_PENDING
→ CLOSED
```

任何阶段可进入：

```text
REJECTED / EXPIRED / ERROR
```

### Tasks

- idempotent candidate ID
- deduplication
- quote expiry
- route change handling
- virtual balances
- virtual allowance
- state transition audit
- latency and error log
- alert 只发送 `PAPER_READY` 或系统异常

### Exit Criteria

Paper fill 能追溯到 raw quote、re-quote、cost ledger 和 simulation evidence。

---

## Day 19 — Stress Test

**学习难度**：中高  
**预计时间**：120 分钟

### 最小 Stress Matrix

- Gas ×2 / ×5
- Latency 1 / 3 / 10 秒
- Output haircut 5 / 10 / 25 bps
- Route changed
- RPC unavailable
- Rebalance cost ×2
- Stablecoin deviation
- Inventory imbalance
- Competitor captures first

### 输出

- Break-even Gas
- Break-even latency
- Break-even rebalance cost
- Non-linear failure mode
- Updated kill criteria

### Exit Criteria

找出一个最危险但容易被平均收益掩盖的 failure mode。

---

## Day 20 — Final Paper Run

**学习难度**：中  
**预计时间**：主动操作 ≤ 120 分钟；Paper Engine 可被动持续运行 12–24 小时

### Tasks

- 冻结 code 和 config。
- 不新增 chain / token / strategy。
- 运行 Paper Engine。
- 检查：
  - process health
  - quote failure
  - duplicate candidate
  - stale quote
  - state transition
  - inventory drift
  - alert quality
- 生成 daily summary。

### 最低输出

- detected
- expired
- net-negative
- inventory-blocked
- simulation-failed
- paper-ready
- paper-filled
- unique clusters
- system errors

### Exit Criteria

系统能稳定拒绝错误机会，并输出可审计记录。

---

## Day 21 — Final Synthesis

**学习难度**：中  
**预计时间**：120 分钟

### Final Report

1. Executive conclusion
2. Research scope
3. Data quality
4. Cost model
5. Hypotheses
6. Primary strategy
7. Replay evidence
8. Paper evidence
9. Counterparty / edge source
10. Capacity / capital requirement
11. Failure modes
12. Negative results
13. Unknowns
14. Final decision
15. 30-day plan

### Final Decision

只能选择一种：

- **A — Continue to 30-day Paper**
- **B — Extend Data Collection**
- **C — Kill / Pivot**

### 结营指标

```text
Primary hypothesis:
Decision: A / B / C
Valid observations:
Independent opportunity clusters:
Re-quote survival rate:
Simulation survival rate:
Median conservative net edge:
P05 conservative net edge:
Opportunity lifetime:
P95 decision latency:
Capacity at target threshold:
Break-even rebalance cost:
Largest unresolved risk:
Next decision date:
```

---

# 6. 每日打卡模板

```markdown
# Day XX — YYYY-MM-DD

## 今日核心问题

一句话描述今天需要回答的问题。

## Hypothesis

如果 X 成立，则在 Y 条件、Z size 下，保守结果应表现为……

## Timebox

- Planned:
- Actual:

## 今日完成

- Reading:
- Code:
- Data:
- Experiment:

## Evidence

- Valid observations:
- Unique clusters:
- Gross edge:
- Known costs:
- Conservative net edge:
- Re-quote latency:
- Simulation:
- Commit / report:

## Reject / Failure

- Rejected candidates:
- Main rejection reason:
- Unexpected error:

## 发现

1. 支持原假设的证据：
2. 与原假设冲突的证据：
3. 仍未知：

## Verdict

Keep / Modify / Kill

## 明日最小动作

只写一个可在 timebox 内完成的动作。
```

---

# 7. Codex 每日执行规则

```text
Read AGENTS.md and the current day task first.
Inspect the existing repository before modifying files.

Implement only the current day's Core acceptance criteria.
Do not add live signing, private-key handling, dashboard,
flash loans, MEV searcher infrastructure, or unrelated abstractions.

Preserve raw API/RPC responses.
Use integer raw token amounts plus Decimal.
Record UTC timestamps, request latency, source, and block context.
Never silently fallback to another route, token, chain, decimal, or price source.

Add fixtures and pytest tests for adapter/model changes.
Run ruff and pytest.
Update the daily note with:
- files changed
- commands run
- evidence generated
- rejected assumptions
- unresolved risks

Review the diff specifically for:
- decimal errors
- fee double counting
- look-ahead
- stale quote usage
- missing failure handling
- incorrect cross-chain atomicity assumptions
```

---

# 8. 自主学习能力验收

21 天后，你应能够不依赖现成课程答案，独立完成以下循环：

## 8.1 Define

- 把一个模糊套利 idea 写成可证伪 hypothesis。
- 说明 counterparty、edge source、profit locking point 和 capacity。

## 8.2 Instrument

- 找到并验证适合的数据源。
- 保留 raw evidence。
- 处理 decimals、token identity、block context 和 latency。

## 8.3 Model

- 将 gross spread 转换为 conservative cycle PnL。
- 区分 trade PnL、portfolio PnL 和 rebalance PnL。
- 避免 fee double count。

## 8.4 Test

- 使用 re-quote、simulation、event-time replay 和 paper execution。
- 保存 negative result 与 reject reason。
- 不把连续 snapshot 当作独立样本。

## 8.5 Decide

- 使用预先定义的 kill criteria。
- 对方向作 Keep / Modify / Kill。
- 知道下一阶段需要减少哪一种 uncertainty。

只要能够稳定执行以上五步，即使 21 天没有发现可盈利策略，也已达到「自主学习与研究」目标。

---

# 9. 课程完成标准

## 完成

- 连续完成 21 个 Daily Core milestones。
- 每日主动学习与开发时间不超过 2 小时。
- 有 raw + normalized data。
- 有完整 Cost Ledger。
- Scanner 能输出明确 reject reason。
- 至少两个 hypothesis 有 evidence-based verdict。
- Primary hypothesis 完成 Event-time Replay。
- 完成 Paper Decision Engine。
- Final report 给出 A / B / C。
- 有 30-day next experiment plan。

## 不算完成

- 只有概念笔记。
- 只展示 gross spread。
- 没有 minimum output 或 conservative cost。
- 使用 symbol 识别 token。
- 把 cross-chain bridge lifecycle 当成 atomic transaction。
- 只记录成功，不记录 reject。
- 使用 stale indexed data 作为实时 execution evidence。
- 未进行 re-quote 就宣布机会可执行。
- 为了打卡而扩大 scope 或伪造结果。

---

# 10. 最合理的预期结果

21 天结束时，成功结果不一定是一个赚钱 Bot。更合理的高价值结果包括：

1. 发现一个值得继续 30 天 Paper 的 inventory-based edge。
2. 证明 route dispersion 是 routing intelligence，而不是独立 arbitrage。
3. 证明公开 same-chain spread 在 re-quote、Gas 和 simulation 后基本消失。
4. 发现某些 stablecoin / wrapped asset basis 实际是信用、赎回或 bridge risk。
5. 建成一个可复用的 on-chain arbitrage research framework，后续可接更多 DEX、chain、bridge、CEX hedge 和 notification，而无需重写 evidence 与 cost layer。

Negative Result 同样是成果，因为它直接减少未来错误资本配置。
