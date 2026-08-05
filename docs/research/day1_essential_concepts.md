# Day 1 必修概念：先定义研究，再设计系统

> 目标：学完后，你应能独立完成 `research_charter.md`、`opportunity_taxonomy.md` 和 `system_design.md`。本笔记只讨论 Day 1 所需概念，不提前实现 PnL、采集器或交易执行。

## 先记住这一条主线

```text
观察到价差
≠ 拿到可执行报价
≠ 两条腿都能成交
≠ 完整周期赚钱
```

Day 1 的任务，是把这四层分开，并定义什么证据才允许系统从一层进入下一层。

---

## 1. Research Charter：把想法改写成可被证伪的问题

### 1.1 Hypothesis 不是愿望

“我要找到赚钱机会”无法被严谨验证，因为它没有明确对象、条件、成本和失败标准。一个可研究的假设至少包含：

- **机制**：利润为什么可能存在；
- **Universe**：在哪些链、资产和金额上观察；
- **可执行性条件**：报价新鲜度、库存、模拟、余额等；
- **核算边界**：哪些成本计入；
- **判定规则**：什么证据支持、反驳或要求延长数据采集。

本项目可以先写成：

> 在 Arbitrum、Base、Optimism 上预先持有 USDC、USDT、WETH，在 USD 100/500/1,000 的交易规模下，当两个本地交易腿都经新鲜 re-quote 验证，且扣除 swap fee、price impact、gas、rebalance、capital、hedge 与 failure allowance 后，仍会出现可重复观察的正 cycle PnL。

这句话不是结论，而是待证伪命题。`可重复`、`新鲜`、`正`等词在 Day 1 可以先保留为待标定参数；后续必须用数据给出数值。

### 1.2 Success 不等于盈利，Kill 也不等于失败

21 天研究的成功，是得到足够可信的证据做出以下一种决定：

- `Continue`：信号在完整成本和压力条件后仍值得继续；
- `Extend Data`：方法可行，但样本量、覆盖率或数据质量不足；
- `Kill/Pivot`：经济性或可执行性不支持当前假设。

因此 Charter 应将“研究过程成功”和“策略盈利”分开。一个严谨的 `Kill/Pivot` 结论同样是成功交付物。

可用的 Kill Criteria 示例：

- 在预先规定的最小样本和时段内，没有任何 re-quote 后仍为正的 cycle；
- 正信号只来自缺失费用、错误 decimals 或过期报价；
- 两条链的库存约束使名义机会不可执行；
- rebalance 成本长期高于已捕获价差；
- API/RPC 证据无法稳定关联到时间和链状态，因而不可复查。

### 1.3 Scope 与 Non-goals 是研究控制变量

固定三条链、三种资产和三个 size，不是因为它们一定最好，而是为了避免“看到哪里有结果就把 Universe 移到哪里”的选择偏差。Non-goals（不实盘、不做私钥、不做 flash loan、不做 MEV infra、不做 dashboard）则防止基础证据尚未成立时扩大工程范围。

**常见误区**：

- “先多接几条链比较全面。”——变量同时增加后，很难判断失败来自策略还是数据质量。
- “正样本少就改阈值。”——阈值应先定义或明确记录变更，否则属于事后挑选。
- “21 天没有盈利就是失败。”——本项目的产物是可靠决策，不是收益承诺。

---

## 2. Quote、Price、Executable Price：三者不是同一件事

### 2.1 AMM 的价格取决于交易规模

以 Uniswap v2 的常数乘积池为最小模型。池中两种资产储备为 `x`、`y`，近似保持：

```text
x × y = k
```

Uniswap v2 官方白皮书说明其核心采用 constant-product 机制，并对交易收费；因此交易会沿曲线改变储备，不能用屏幕上的 spot price 直接乘数量得到成交额（[Uniswap v2 Whitepaper](https://app.uniswap.org/whitepaper.pdf)）。

忽略费用的直观例子：

```text
池：100 ETH + 200,000 USDC
边际价格：约 2,000 USDC/ETH

若卖入 10 ETH：
新 ETH 储备 = 110
新 USDC 储备 = 20,000,000 / 110 ≈ 181,818.18
可取出 USDC ≈ 18,181.82
平均成交价 ≈ 1,818.18 USDC/ETH
```

即使外部“市场价”没变，大订单本身也会推坏成交价格。Uniswap 官方将 **price impact** 定义为你的交易自身导致的价格变化；池越浅、size 越大，impact 通常越大（[What is price impact?](https://support.uniswap.org/hc/en-us/articles/8671539602317-What-is-Price-Impact)）。

### 2.2 Price impact 与 slippage 要分开

- **Price impact**：你的订单对池状态造成的机械性影响；报价时通常已经体现在预期输出中。
- **Slippage**：从报价到真正执行之间，预期输出与实际输出的差异，可能来自其他交易、区块排序、延迟等。
- **Slippage tolerance**：你允许的最差偏差；它是保护阈值，不是必然发生的成本。

Uniswap 官方明确区分：impact 由自己的交易造成，而 slippage 是预期结果与实际结果的差（[Price Impact vs Price Slippage](https://support.uniswap.org/hc/en-us/articles/8643794102669-Price-Impact-vs-Price-Slippage)）。Tolerance 太低会 revert，太高则可能接受很差的成交（[Slippage settings](https://support.uniswap.org/hc/en-us/articles/8643879653261-How-to-change-slippage-on-the-Uniswap-Web-app)）。

所以不要在 Cost Ledger 中同时把“报价已包含的 price impact”和一个同名 impact 百分比再扣一次，也不要把最大 slippage 全部当成必然成本。Day 1 只需确定：**谁拥有这些字段、哪些是 estimate、哪些是 realized、后续由 Cost Ledger 统一核算。**

### 2.3 LI.FI Quote 是执行计划，不是成交承诺

LI.FI 将 Quote 定义为带有可立即使用 transaction data 的单步 transfer plan；Route 则由 steps、transactions 和 costs 组成（[LI.FI Concepts and Objects](https://docs.li.fi/agents/concepts)、[Quote vs Route](https://docs.li.fi/introduction/user-flows-and-examples/difference-between-quote-and-route)）。其 schema 中至少包含输入最小单位、slippage、estimate 和 transaction request（[LI.FI Data Schemas](https://docs.li.fi/agents/reference/schemas)）。

因此：

- Quote 是“在某个请求时刻，根据某组参数计算出的执行方案”；
- 它不是资产已被预留，也不是目标输出已被保证；
- `toAmount` 是估计输出，`toAmountMin` 才是按 slippage tolerance 计算的最低可接受输出；放宽 tolerance 只是放宽执行边界，不会阻止市场价格变化（[LI.FI Slippage and Price Impact](https://docs.li.fi/faqs/slippage-price-impact)）；
- 排名第一也不代表最快；LI.FI 的 `FASTEST` 与按费用/输出优化是不同选择（[LI.FI Decision Tables](https://docs.li.fi/agents/quick-start/decision-tables)）；
- 必须保存请求参数、完整响应、请求时间、响应时间和延迟，才能知道自己比较的究竟是什么。

**例子**：10:00:00.000 获取 Chain A 卖 WETH 的报价，10:00:00.800 才获取 Chain B 买 WETH 的报价。这不是同一个市场快照。若直接相减，800ms 内的市场变化会伪装成跨链价差。

---

## 3. Atomicity 与 Finality：套利分类的两根轴

### 3.1 Atomicity 回答“能否全部成功或全部回滚”

在同一 EVM 交易内，合约之间的调用仍属于整体交易；未被捕获的 revert 会回滚相应状态变化，以维持交易原子性（[Solidity Control Structures](https://docs.soliditylang.org/en/latest/control-structures.html)）。但 `REVERT` 不会返还已经消耗的 gas（[EIP-140](https://eips.ethereum.org/EIPS/eip-140)）。因此：

- 若 `DEX A 买入 → DEX B 卖出 → 检查最终利润` 全部封装在**同一条链的一笔交易**里，最后一步不满足可 revert，便可以是原子的；
- 仅仅由脚本连续发送两笔交易，即使在同一条链，也不是原子执行；第一笔可能成功、第二笔可能失败；
- 两条不同链各自有独立状态与排序，普通的跨链双腿交易不能靠一笔 EVM transaction 同时回滚，所以是 non-atomic。

### 3.2 Finality 回答“已经发生的结果有多难被重组”

Ethereum 交易先广播、进 mempool、被纳入区块，之后区块再成为 justified 和 finalized（[Ethereum Transactions](https://ethereum.org/developers/docs/transactions)）。`latest`、`safe`、`finalized` 也不是同义词：Ethereum Execution API 明确指出 `latest` 在正常情况下仍可能被 reorg，而 `finalized` 有更强保证（[Ethereum `eth_call` block tags](https://ethereum.github.io/execution-apis/api/methods/eth_call/)）。

本项目研究的是 L2，更不能只写“confirmed”。OP Stack 官方区分 sequencer-confirmed/unsafe、published-to-L1/safe、finalized；安全保证逐级增加（[OP Mainnet transaction statuses](https://docs.optimism.io/app-developers/guides/transactions/statuses)）。Base 也区分 preconfirmation、L2 block、L1 batch 与 L1 finality（[Base transaction troubleshooting](https://docs.base.org/base-chain/network-information/troubleshooting-transactions)）。

**结论**：Atomicity 是执行边界；Finality 是时间上的确定性等级。原子交易也需要等待 finality；finalized 的两笔跨链交易仍不是原子组合。

### 3.3 “Profit locking”的正确写法

对 pre-positioned inventory 策略，建议定义为：

> 两条链均有足够的目标资产和 gas token；两个相反方向的本地腿在规定的新鲜度窗口内分别 re-quote；按保守输出、完整周期成本和失败准备金计算仍为正；系统只将其标为 `paper-ready`，不宣称原子保证。

不要写“发现价差即锁定利润”，也不要写“先桥接再卖出就能无风险套利”。跨链过程可能等待 source confirmations、destination transaction，或出现 bridge/RPC 不可用、refund 等状态；LI.FI 的状态模型明确列出了这些情况（[LI.FI Status Tracking](https://docs.li.fi/introduction/user-flows-and-examples/status-tracking)）。甚至可能出现 bridge 已成功而 destination swap 失败，最终收到的 token 与请求不同的 `PARTIAL` 结果（[LI.FI Partial Completion](https://docs.li.fi/agents/workflows/partial-completion)）。

---

## 4. Opportunity Taxonomy：按执行机制分类，而不是按“看起来像价差”分类

| 类型 | 最小机制 | 原子性 | 主要库存 | 主要失败模式 | Day 1 判断 |
|---|---|---|---|---|---|
| Same-chain DEX–DEX | 同链 A 买、B 卖 | 封装成单 tx 时可原子 | 输入资产 + gas | impact、gas、MEV、revert | Baseline |
| Triangular | A→B→C→A | 封装成单 tx 时可原子 | 起始资产 + gas | 任一池深度不足、费用累积、MEV | Study-only |
| Cross-chain route dispersion | 比较跨链 route 的输出/费用/时间 | 报价观察本身无原子性 | 若执行则依 route | 异步、partial、bridge/RPC 故障 | Supporting evidence |
| Pre-positioned inventory | 两链用预置库存做反向本地交易 | Non-atomic | 两链双资产 + 两链 gas | leg risk、库存耗尽、rebalance | Primary |
| Stablecoin / wrapped basis | 同类经济敞口价格偏离 | 通常 non-atomic | 两侧相关 token | depeg、赎回/包装假设失效、流动性 | Secondary |
| MEV/backrun/liquidation | 围绕交易排序或状态事件执行 | 依机制而定 | 专门资本和基础设施 | 竞争、排序、失败 gas、基础设施 | Study-only |

### 4.1 Route dispersion 不等于 arbitrage

两个 route 输出不同，只能证明“路由估值不同”。若它们方向相同，就没有闭环；若 route 包含不同 token、不同到账时间或不同风险，也不能直接比较。先要求共同的经济单位、相同 notional、相近 event time、明确的反向退出路径，再谈 candidate。

### 4.2 Pre-positioned inventory 如何工作

假设 WETH 在 Arbitrum 的可执行买价较低、在 Base 的可执行卖价较高：

```text
Arbitrum：用预置 USDC 买 WETH
Base：    卖出预置 WETH 换 USDC
```

两腿完成后，组合总资产可能增加，但库存变为：Arbitrum 的 WETH 增、USDC 减；Base 相反。继续交易前迟早要 rebalance。相关实证研究将 inventory arbitrage 描述为套利者在两链持有资本、进行独立的相反方向交易，并将其与需要桥接的策略区分；跨链套利本身因跨域执行而具有 non-atomic 特征（[Öz et al., *Pandora’s Box: Cross-Chain Arbitrages*](https://arxiv.org/abs/2501.17335)）。

所以必须分三层利润：

```text
Signal spread        = 两地可执行价差
Opportunity PnL      = 两个本地腿完成后的净变化
Cycle PnL            = Opportunity PnL - 恢复目标库存所需全部成本
```

真正决定策略能否持续的是 `Cycle PnL`，而不是某一轮交易后的局部 PnL。Day 1 不计算它，但必须在 Charter 中把 rebalance、资金占用、hedge 和失败准备金放进核算边界。

### 4.3 Counterparty 与 Capacity 怎么理解

- **Counterparty** 不只指某个人：还包括 AMM pool、router/aggregator、bridge/solver、RPC、sequencer，以及 token/issuer 风险边界。
- **Capacity** 不是“池里有多少钱”：它受指定 size 的 impact、gas、两侧可用库存、允许的 inventory drift、rebalance throughput、route availability 和风险限额共同约束。

---

## 5. System Design：研究闭环中的每一道证据门

### 5.1 推荐的最小状态流

```text
COLLECTED
  → NORMALIZED
  → CANDIDATE
  → REQUOTED
  → COSTED
  → SIMULATED
  → PAPER_READY 或 REJECTED
```

关键不是状态名称，而是每次转换都要有：输入 ID、输出 ID、发生时间、所用配置版本、成功/失败和 reason code。拒绝也是研究数据，不能只保存正信号。

### 5.2 Raw 与 normalized 的边界

- **Raw**：API/RPC 实际返回的 bytes/JSON、请求参数、HTTP status、headers（去除 secret）、采集 UTC 时间、latency、source、必要的 block context。它是不可修改的观察证据。
- **Normalized**：把不同 source 映射为统一字段，例如 chain、token identity、raw amount、decimals、estimated output、cost components、block number。它是可重新生成的解释层。
- **Derived**：candidate、spread、PnL、reject reason、统计结果。它依赖 raw、normalizer 版本和 config。

W3C PROV 将 provenance 定义为产生数据所涉及的 entity、activity 与 agent 信息，并用 `wasDerivedFrom` 表示实体间的派生关系（[W3C PROV-DM](https://www.w3.org/TR/prov-dm/)）。应用到本项目，就是：每个 normalized record 必须能指出来自哪个 raw response，每个 candidate 必须能回到参与计算的 observations。

**为什么不能只存 normalized？** 今天的 parser 若把 `gasCosts` 误读或 token decimals 配错，只有 raw 仍在，明天才可用修正后的 normalizer 重放；否则错误数据已无法恢复。

### 5.3 时间、区块与数量是数据的一部分

- 时间统一使用带 `Z` 的 UTC/RFC 3339 格式，例如 `2026-08-05T02:15:30.123Z`；RFC 3339 推荐以明确 UTC 关系表达 Internet event timestamp（[RFC 3339](https://www.rfc-editor.org/info/rfc3339/)）。
- 同时保存 `request_started_at`、`response_received_at` 和 `latency_ms`；只存一列 `timestamp` 无法判断数据陈旧程度。
- 有条件时记录 block number/hash/tag；“10:00 的 quote”不等于“基于 10:00 同一状态的 quote”。
- 链上 token amount 先保存 integer raw units，再用 decimals 展示。ERC-20 规定 decimals 表示显示时除以 `10 ** decimals`，且该 metadata 方法本身是 optional（[ERC-20](https://eips.ethereum.org/EIPS/eip-20)）。
- 金额核算使用 `Decimal`，不要从 binary `float` 构造；Python 官方文档说明 `Decimal` 可精确表示十进制数，而 `float` 对 `0.1` 等通常只是近似（[Python `decimal`](https://docs.python.org/3/library/decimal.html)）。

### 5.4 Re-quote gate 的意义

第一次 quote 用于**发现**，第二次独立 quote 用于回答“候选现在是否仍存在”。Re-quote 至少可能产生：

- `CONFIRMED`：方向、size、token、route 条件仍符合；
- `CHANGED`：仍可报价，但利润/路径已改变；
- `STALE`：超过 freshness window；
- `UNAVAILABLE`：API、route 或 chain 不可用；
- `BELOW_THRESHOLD`：完整检查后不再为正。

不要用第一次 quote 同时作为 discovery 和 confirmation；那只是重复使用同一条证据。

### 5.5 Cost Ledger 必须有一个 Owner

Adapter 的职责是忠实提取 source 给出的字段；Cost Ledger 的职责是判断哪些费用已包含、哪些需另加，并输出统一 breakdown。否则容易发生：

- aggregator output 已包含 DEX fee/impact，系统又扣一次；
- gas 只算 source chain，漏掉 destination 或 approval；
- 将 slippage tolerance 当实际成本；
- 只算当次双腿，不算 rebalance、capital、hedge、failure allowance。

Day 1 只需要把 ownership 写清楚，具体公式留给 Day 2。

### 5.6 Simulation boundary：模拟是证据，不是执行

Ethereum Execution API 对 `eth_call` 的定义是：立即执行 message call，但不在链上创建 transaction（[Ethereum Execution APIs: `eth_call`](https://ethereum.github.io/execution-apis/api/methods/eth_call/)）。Geth 也说明它可在指定 block state 上测试交易效果而不实盘（[Geth `eth_call`](https://geth.ethereum.org/docs/interacting-with-geth/rpc/ns-eth)）。

模拟能回答：

- 在给定 state/block context 下是否 revert；
- 返回数据是什么；
- 某些工具下的 gas/trace/log 估计。

模拟不能证明：

- 交易稍后被纳入时状态仍相同；
- 排序、base fee、nonce 和竞争者不变；
- 跨链第二腿会成功；
- 实际 finality 与 bridge completion 已达到；
- 签名、广播和私钥操作链路正确。

因此 Day 1 应画出明确边界：系统只生成 transaction request、执行 read-only simulation、记录 paper decision；不得签名或广播。

### 5.7 Idempotency 与 deduplication 不一样

- **Deduplication**：识别“这些记录代表同一个逻辑观察/候选”，避免重复统计。
- **Idempotency**：同一个动作因网络超时被重试多次，其外部效果仍只发生一次。

研究系统可以用规范化字段生成确定性 ID，例如：

```text
observation_id = hash(source, chain, token_in, token_out,
                      raw_amount, request_started_at, raw_payload_hash)

candidate_id = hash(strategy_type, leg_observation_ids, config_version)
```

发布打卡等 `POST` 操作则使用 `Idempotency-Key`。IETF 草案规定：同一次请求的重试复用同一 key，不同 payload 不得复用该 key（[IETF Idempotency-Key draft](https://datatracker.ietf.org/doc/html/draft-ietf-httpapi-idempotency-key-header)）。截至本文写作时它仍是 Internet-Draft，不是已发布 RFC；具体格式、长度和过期策略以服务端契约为准。它不能替代内部 candidate dedupe，也不能假设任意服务都会自动支持。

---

## 6. 组件契约：你在 Day 1 应该能口头解释

| Component | 输入 | 输出 | 不负责 |
|---|---|---|---|
| Collector | request + config | raw response + UTC + latency | 判断盈利 |
| Normalizer | raw record + schema version | typed observation | 修改 raw |
| Detector | compatible observations + detection config | provisional candidate | 宣称可执行 |
| Re-quote Gate | candidate + fresh requests | confirmed/changed/stale/unavailable | 用旧 quote 代替确认 |
| Cost/Inventory Check | confirmed candidate + balances + cost assumptions | breakdown + feasibility | 隐藏未知成本 |
| Simulator | tx request + explicit state context | success/revert + evidence | 广播交易 |
| Decision | 全部上游证据 + threshold config | rejected/paper-ready + reason | 自动改变经济假设 |
| Evidence Store | 每阶段记录及关联 ID | 可重放 lineage | 只保存成功案例 |

失败处理原则：API/RPC error、timeout、schema change、missing field 都应成为显式结果；绝不静默 fallback 成旧缓存、零成本或另一个 source，因为那会改变研究语义。

### Codex 与人的边界

Codex 可以实现明确 schema、adapter、测试、重放和报告；你必须决定：

- 为什么这个 hypothesis 值得研究；
- capital band 和可接受 inventory drift；
- freshness、PnL、failure allowance 等经济阈值；
- 哪些 counterparty/token/bridge 风险可接受；
- 最后的 Continue / Extend / Kill。

这些是研究判断，不应由代码默认值悄悄决定。

---

## 7. 综合例子：一条候选如何通过系统

假设系统观察到：在 Arbitrum 买 0.25 WETH 的保守输出成本为 500 USDC，同时在 Base 卖出 0.25 WETH 可得 503 USDC。

1. **Collect**：保存两次请求和两份原始响应；发现它们相隔 700ms。
2. **Normalize**：统一 token address/decimals、raw amount 和 USD 表示；不在 adapter 内扣自定义成本。
3. **Detect**：记录 gross spread = 3 USDC，生成 provisional candidate；此时不叫 profit。
4. **Re-quote**：同时刷新两腿；Base 输出变成 502.40 USDC。
5. **Inventory check**：确认 Arbitrum 有 ≥500 USDC、Base 有 ≥0.25 WETH，且两链都有 gas token。
6. **Cost**：本地 gas 0.18、0.12；周期 rebalance 分摊 1.40；capital/hedge/failure allowance 合计 0.90 USDC。
7. **Decision**：`502.40 - 500 - 0.18 - 0.12 - 1.40 - 0.90 = -0.20 USDC`，因此 `REJECTED_COST`。

这个 reject 是有价值的证据：它说明“有价差”但“不足以形成正 cycle PnL”。Day 1 不要求你实现公式，但系统设计必须允许完整记录这条路径。

---

## 8. Day 1 自测题

如果能不看答案讲清以下问题，就可以开始写三个 Day 1 文档：

1. 为什么两个正向 quote 的差不能直接叫利润？
2. Price impact、slippage、slippage tolerance 各是什么？
3. 两笔同链交易为什么不一定原子？怎样才可能原子？
4. Finalized 与 atomic 分别回答什么问题？
5. Pre-positioned inventory 为什么减少桥接等待，却没有消除跨链 leg risk？
6. Opportunity PnL 与 Cycle PnL 为什么不同？
7. Raw、normalized、derived 各自保存什么，为什么 raw 不可变？
8. Re-quote 为什么必须是独立的新证据？
9. Simulation 能证明什么，不能证明什么？
10. Deduplication 与 idempotency 有何区别？

## 9. 今天的最短学习顺序（约 35 分钟）

1. **8 分钟**：阅读第 1 节，写出自己的 hypothesis、success、kill、non-goals。
2. **8 分钟**：学习第 2 节，用纸笔重算常数乘积例子。
3. **7 分钟**：学习第 3–4 节，给六类机会标 atomicity、inventory 与 failure mode。
4. **10 分钟**：学习第 5–6 节，口述每个 component 的输入、输出和拒绝条件。
5. **2 分钟**：回答第 8 节自测；答不上来的项目回看对应章节。

完成后，你应能用一句话总结本项目：

> 我们不是在收集“看起来有利润”的价差，而是在建立一条可追溯、可重放、execution-aware 的证据链，判断预置库存跨链套利在完整周期成本后是否值得继续研究。
