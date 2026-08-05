# System Design

## 设计目标

用最小、可审计的 Research Loop 回答“候选机会为何被接受或拒绝”。系统优先保证 Evidence Lineage、Accounting Correctness 和 Explicit Failure，不追求实盘吞吐或低延迟。

本文使用以下工程词汇：**Module** 是具有明确职责的实现单元；**Interface** 是调用方和测试可见的契约；**Implementation** 是藏在 Interface 后的细节；**Depth** 表示简单 Interface 能隐藏多少复杂性；**Seam** 是确实存在替换需求的位置；**Adapter** 把外部 Source 翻译成内部模型；**Leverage** 是一个小 Interface 服务多少下游用途；**Locality** 表示相关知识是否集中在同一处。

## 最小 Research Loop

```text
LI.FI / Direct Quote / EVM RPC
              │
              ▼
      Source Adapters + Collector
              │
              ▼
       Immutable Raw Evidence
              │
              ▼
           Normalizer
              │
              ▼
       Candidate Detector
              │
              ▼
       Independent Re-quote
              │
              ▼
     Cost Ledger + Inventory Check
              │
              ▼
       Simulation / Paper Decision
              │
              ▼
       Evidence Log + Daily Report
```

## 核心数据契约

所有金额首先保存 Integer Raw Units；展示和计算通过 Token Decimals 转为 `Decimal`，禁止用二进制 Float 做经济判断。

| Model | 最小字段 | 约束 |
|---|---|---|
| `TokenRef` | `chain_id`, `contract_address`, `symbol`, `decimals` | Identity 是 chain + address；symbol 仅展示 |
| `TokenAmount` | `token`, `raw_amount`, `decimal_amount` | `decimal_amount` 必须能由 raw + decimals 重建 |
| `QuoteRequest` | `request_id`, source, tokens, amount, chain(s), UTC requested_at | Request ID 幂等；不含 Secret |
| `RawEvidence` | `raw_id`, request, received_at, latency_ms, status, payload/blob_ref, checksum | Append-only；失败响应也保存 |
| `QuoteObservation` | `observation_id`, `raw_id`, input/output/min output, fee/gas, duration, route fingerprint, block context | 所有派生字段可回到 `raw_id` |
| `OpportunityCandidate` | `candidate_id`, observations, direction, target_size, gross_edge, state, reject_reason | ID 稳定；连续 Snapshot 后续聚类 |
| `CostItem` | type, amount, currency, `included_in_quote_output`, confidence, source, observed_at | Confidence 仅 `exact/estimated/stressed` |
| `CostLedger` | candidate ID, items, gross/local/cycle PnL, completeness | 唯一成本语义所有者 |
| `InventorySnapshot` | chain/token balances, gas balance, target band, observed_at | Day 10 前仅 Virtual/TBD |
| `SimulationResult` | candidate, method, block, success, gas used, balance changes, revert reason, evidence ref | 证明指定状态下结果，不保证未来 |
| `DecisionRecord` | candidate, prior/new state, gate, decision time, evidence refs | Append-only 状态审计 |

具体 Python 类型从 Day 2 开始实现；Day 1 只冻结契约方向，不提前编码业务逻辑。

## Modules、Interfaces 与职责

### 1. Source Adapter Module

**Interface**：`QuoteRequest -> RawSourceResponse`。

- 为 LI.FI、独立 Direct Source、RPC 隔离 HTTP/RPC 字段、认证、限流和错误格式。
- External Source 是真实变化点，因此这里建立 Adapter Seam。
- Adapter 不计算 PnL、不填补缺失字段、不吞掉错误。
- 每次 Adapter 字段或解析变化必须同时提交 Raw Fixture 与 Test。

该 Module 有较高 Depth：下游只看稳定请求/响应契约，外部供应商差异留在 Implementation 内。

### 2. Collector Module

**Interface**：`CollectionJob + Source Adapter -> RawEvidenceRef`。

- 负责 Timeout、Retry/Backoff、Rate Limit、Request ID、UTC 时间、Latency。
- 先持久化完整 Raw Response，再允许 Normalization。
- Retry 每次 Attempt 单独记录；禁止用成功结果覆盖失败证据。
- 重启后通过 Request/Attempt ID 防止覆盖，Append-only 写入。

### 3. Raw Evidence Store Module

**Interface**：`append(RawEvidence) -> RawEvidenceRef`；`get(ref) -> RawEvidence`。

- Raw Payload 不可变，保存 Checksum、Source、Request 与接收时间。
- 不暴露供应商 Secret，不将 `.env` 或 Header 写入 Evidence。
- 这是最高 Leverage 的审计 Interface：Normalizer、Debug、Fixture、Replay 都依赖它。

### 4. Normalizer Module

**Interface**：`RawEvidenceRef + TokenRegistry -> QuoteObservation | ParseFailure`。

- 验证 Schema、Decimals、Token Identity、Amount Direction 与必填字段。
- 生成稳定 Route Fingerprint 与 Normalized Schema。
- Unknown/Unavailable 与数值 0 不等价；缺失字段产生显式 Parse Failure。
- 通过集中映射提升 Locality，业务层不接触供应商字段。

### 5. Candidate Detector Module

**Interface**：`QuoteObservation set + FrozenConfig -> Candidate/Reject records`。

- 按相同 Token Identity、Direction、Target Size 和可比时间窗寻找 Gross Candidate。
- 检测阶段只允许使用可执行 Exact-input Quote，不用网页价格或 OHLC。
- 去重并保存所有 Reject Reason；不判断最终盈利。

### 6. Re-quote Gate Module

**Interface**：`Candidate + RequotePolicy -> RequoteResult`。

- 对候选路线发起新的独立请求，不复用 Detection Quote。
- 检查 Freshness、Route Change、Latency、Minimum Output 和 Source Independence。
- 超时、Unavailable、Route 变化或 Edge 消失均显式拒绝。
- Freshness Window 未冻结前为配置中的 `TBD`，不得 Silent Fallback。

### 7. Cost Ledger Module

**Interface**：`RequotedCandidate + CostInputs -> CostEvaluation`。

- 是 Gross、Atomic Net、Local Trade、Inventory Cycle PnL 的唯一 Owner。
- 逐项记录 Quote 是否已包含该费用，避免 Double Count。
- 对 Exact、Estimated、Stressed 分层，暴露缺失项；成本不完整不得为正信号。
- Adapter 只能报告 Source 字段，不能自行定义最终 PnL。

这是一个 Deep Module：调用方只提交有来源的成本输入并读取 Breakdown；货币换算、包含关系和 PnL 语义集中在 Implementation，保持 Accounting Locality。

### 8. Inventory Module

**Interface**：`CostedCandidate + InventorySnapshot + Policy -> InventoryEvaluation`。

- 检查两链 Asset/Stablecoin/Gas、Target Band、最大 Drift 和 Capital Occupied。
- 记录成交后的 Virtual Balance 与 Rebalance Obligation。
- 不执行 Bridge、Hedge 或真实 Rebalance。

### 9. Simulation Module

**Interface**：`UnsignedTransaction + BlockContext -> SimulationResult`。

- Simulation Provider 是变化点，可选 `eth_call`、Tenderly 或 Local Fork，故保留单一 Adapter Seam。
- 保存 Gas、Balance Changes、Revert Reason、Allowance、Block Context。
- Same-chain Candidate 无 Simulation Evidence 不得 `PAPER_READY`。
- Cross-chain 两腿分别模拟也不能证明共同 Atomicity 或最终成交。

### 10. Decision Module

**Interface**：`GateEvidence -> DecisionRecord`。

- 按固定顺序推进状态；任一 Gate 可产生带原因的拒绝。
- 只允许完整证据进入 `PAPER_READY`；不签名、不发送交易。
- 状态迁移为 Append-only，重复输入应返回相同 Decision，不重复 Paper Fill。

### 11. Evidence/Report Module

**Interface**：`Evidence Query -> Metrics/Report`。

- 生成观察数、独立机会簇、Re-quote/Simulation Survival、Latency、PnL Distribution 和 Reject Breakdown。
- Report 只读取证据，不修改 Candidate 或经济结果。

## Raw / Normalized / Derived 边界

```text
data/raw/         原始 request/response/error；不可变；事实来源
data/normalized/  稳定 schema；可由 raw + registry + parser version 重建
data/derived/     candidates、ledgers、decisions、metrics、reports；可重算
```

- Raw 必须先于 Normalized 落盘。
- Normalized 保存 `raw_id`、Parser Version、Registry Version。
- Derived 保存所有上游 ID 和 Config Hash。
- 修复 Parser 时生成新版本输出，不修改旧 Raw。

## Candidate Lifecycle

```text
COLLECTED
  → NORMALIZED
  → DETECTED
  → REQUOTING
  → REQUOTED
  → COSTED
  → INVENTORY_CHECKED
  → SIMULATED / SIMULATION_NA
  → PAPER_READY
```

任一适用阶段可进入：

```text
REJECTED | EXPIRED | ERROR
```

常见机器可读原因：`PARSE_FAILED`、`STALE_QUOTE`、`ROUTE_CHANGED`、`NET_NEGATIVE`、`COST_INCOMPLETE`、`INVENTORY_BLOCKED`、`SIMULATION_FAILED`、`DUPLICATE`。终态不静默复活；新证据生成新的 Decision Attempt。

## Re-quote 与 Simulation Gate

Gate 顺序不可绕过：

1. Detection Quote 只产生 `DETECTED`。
2. 独立 Re-quote 必须满足配置 Freshness，保存新的 Raw Evidence。
3. Cost Ledger 必须 100% 完整，Unknown 成本按策略 Stress 或拒绝，不自动补零。
4. Cross-chain 经过 Inventory Check；Same-chain 经过必要 Balance/Allowance Check。
5. Same-chain 构造 Unsigned Transaction 并 Simulation；Cross-chain 标记 `SIMULATION_NA` 只表示没有跨链原子模拟，不能提升确定性。
6. 所有证据齐全才可 `PAPER_READY`。

## Idempotency 与 Deduplication

- `request_id`：Source + Canonical Request + Scheduled Time Bucket 的稳定 Hash。
- `raw_id`：Request ID + Attempt + Payload Checksum。
- `observation_id`：Raw ID + Parser Version。
- `route_fingerprint`：标准化后的 Tool/Pool/Bridge/Token/Direction Sequence。
- `candidate_id`：Strategy Type + Token Identities + Directions + Size + Detection Window + Observation IDs。
- `decision_id`：Candidate ID + Attempt + Config Hash。
- 重复调用返回已有结果或追加明确的新 Attempt；绝不覆盖。
- Day 17 另以时间连续性形成 `cluster_id`，避免 Snapshot Inflation。

## Failure Handling

- Network、Rate Limit、Timeout、HTTP/RPC Error、Parse Failure 分开计数。
- Retry 只处理显式可重试错误，采用有上限的 Backoff；用旧 Quote 代替失败 Re-quote 属于禁止的 Silent Fallback。
- Partial Data 不升级状态；保留 Raw Error 和 Reject Record。
- Storage 写入先落 Raw，再处理下游；下游失败可从 Raw 重放。
- Source 不可用时标记 `UNAVAILABLE`，不得换 Source 后伪装成同一观察。
- 所有异常日志使用 UTC、Request/Candidate ID，且清除 Secret。

## Config Boundary

配置只保存会随研究冻结而变化的政策：

- Universe：Chains、Token Registry、Sizes、Sources。
- Collection：Interval、Timeout、Retry、Concurrency。
- Decision：Freshness、Detection Threshold、Minimum Profit、Cost Buffers。
- Inventory：Capital Band、Target Bands、Maximum Drift。
- Simulation：Method、RPC Alias、Block Policy。
- Version：Schema、Parser、Registry、Config Hash。

Secret 只从环境变量读取且不进入 Config、Log、Evidence 或 Git。Config 缺少经济关键字段时启动失败，不设 Silent Default。

## 实现顺序与职责边界

### Codex 可实现

- 数据模型、Schema Validation、Source Adapter、Collector 和存储。
- Deterministic PnL/Cost Calculation、Deduplication、State Machine。
- Fixtures、Unit/Integration Tests、Simulation Wrapper、Replay 与 Report。
- 将所有假设、未知项、Reject 与 Evidence 明确呈现。

### 必须由研究者确认的经济判断

- Research Capital Band 是否符合真实风险承受能力。
- Token/Issuer/Bridge Counterparty 是否可接受及 Haircut。
- Minimum Economic Profit、Cost/Latency Buffer 和 Failure Allowance。
- Inventory Band、Rebalance/Hedge Policy 与 Mark-to-market 方法。
- H1/H2 的 Keep/Modify/Kill 和最终 A/B/C 决策。
- 任何从 Paper 走向 Live 的授权；该授权不属于本项目。

## 明确不预建的 Seams

Day 1 不为 Dashboard、Live Wallet、Signer、Flash Loan、MEV、Deployment 或任意未来 Database 建 Interface。这些不是当前真实变化点，预建只会降低 Depth 和 Locality。新增 Seam 必须由已出现的第二种实现或测试需求证明。
