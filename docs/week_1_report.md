# Week 1 Data Gate Report

## 结论

**Gate: PASS — 允许进入冻结范围内的 Week 2 paper research。**

Authoritative dataset 有 251 attempts、231 valid normalized observations，达到 `>= 200`
目标。Raw lineage、UTC timestamp 与 latency coverage 均为 100%，核心字段 parse success
为 100%，decimals、schema、duplicate、missingness、timestamp order 与 normalized
projection 检查全部通过。

样本来自原 collector evidence 加修复后的 append-only collection；没有放宽阈值、重复
observation、合并 smoke 数据或使用 fixture 补数。Week 2 config 已冻结为最小 Base
USDC/WETH paper-research slice；PASS 不授权 live execution。

## 数据与可重复命令

- Authoritative Raw：ignored local `data/raw/lifi/day05_final/`。
- Normalized DB：ignored local `data/normalized/day05_final.duckdb`。
- Observation window：2026-08-09 06:40:49.897176Z → 2026-08-11 04:58:45.962314Z。
- Frozen config：`config/week2.toml`。
- Config SHA-256：`46bd62308a88624edbcdad228ce2dcb29ce427cb2cb488d5e9f4bdd7dcea222d`。

```bash
uv run python -m onchain_arb.data_quality \
  data/normalized/day05_final.duckdb --config config/week2.toml
uv run pytest
```

QA command 是 read-only；每次都重新读取 DuckDB 与其 Raw references，不使用缓存值。

## Gate 结果

| Check | Result | Evidence |
|---|---:|---|
| Schema completeness | PASS | 两张表及全部预期 columns 存在 |
| Valid observations | PASS | 231 / 200 |
| Raw reference coverage | PASS | 100%；251 attempts + 231 normalized references 均匹配 Raw request ID |
| Timestamp coverage/order | PASS | 100% UTC；0 ordering violations |
| Latency coverage | PASS | 100%；p50 1,270.747 ms，p95 3,898.220 ms |
| Parse success | PASS | 231 / 231 HTTP-200 parse candidates = 100% |
| Decimal correctness | PASS | Frozen chain/address identities、raw integer units 与 min-output invariant 全通过 |
| Duplicate | PASS | request ID、quote ID、Raw ref duplicate 均为 0 |
| Missingness | PASS | required attempt/quote fields missing = 0；approval address 是显式 optional |
| Normalized projection | PASS | success attempt 与 normalized request ID mismatch = 0 |
| Failure / availability | OBSERVED | 231 success、20 rate-limited；overall 92.03% |

Decimal regression 与完整 suite：`46 passed`。本 Gate 的 parse rate 只衡量收到 HTTP 200 后的
核心字段解析；429 不伪装成 parse failure，也不从 availability 中删除。

## Route Availability 与 Size Sensitivity

- Base USDC→WETH：三个 sizes 各 27 valid；每个 size 27/29 availability；median
  output/input 的 USD 1,000 相对 USD 100 变化 `+0.181378 bps`。
- Arbitrum USDC→WETH：三个 sizes 各 25 valid；每个 size 25/27 availability；USD 1,000
  相对 USD 100 变化 `-0.908933 bps`。
- Base→Arbitrum USDC：三个 sizes 各 25 valid；USD 100 为 25/27，USD 500 与 1,000
  各 25/28；median output/input 均为 `0.9975`，变化 `0 bps`。

Size sensitivity 使用每个 size 的 median raw-unit output/input，只作数据 QA。不同 size
不是同一 block 的同步 quote，因此这些数值不能解释为可交易 price impact 或盈利证据。

## 首轮不足的原因与已修 Bug

最大连续 observation gap 为 `6,781.682025s`。两条 cross-chain request 收到约两小时的
`Retry-After` 后，旧 collector 在共享 round 内等待，连带暂停七条健康 route。这推翻了
“两小时 wall-clock run 会自然产生至少 200 条 observation”的最大错误假设。

Day 7 的阻塞性修复把长 `Retry-After` 转为该 route 的 monotonic cooldown；当前 round
立即返回，其他 route 可继续轮询。Cooldown 不丢弃 429：Raw 与 failure attempt 仍先保存，
且在期限到达前不会重试该 route。Regression test 验证长 cooldown 不阻塞 collector。

已有 evidence 没有因修复而改写。修复后继续 append 采集，最终达到 231 valid
observations；20 个 429 全部保留为 availability evidence。跨采集 session 的最大 timestamp
gap 为 `151,511.855521s`，这是计划性停止/cooldown，不伪装成连续市场覆盖。

## Frozen Week 2 Universe

Gate 通过后冻结以下最小 Week 2 paper-research slice：

- Chain：Base (`8453`)。
- Pair：USDC/WETH；token identity 只用 `chain_id + address`，decimals 为 6/18。
- Sizes：USD 100 / 500 / 1,000 exact input。
- Discovery：LI.FI；decision-time direct quote 仍为 required，不允许 LI.FI discovery 自证。
- Block context：EVM RPC。
- Freshness、minimum economic profit：数据不足，显式留到 Day 16；不得用默认值。
- Mode：read-only / simulation-only / paper-only；不签名、不广播。

选择 Base 是因为它有 Week 1 最多的同链 valid coverage，也已有 Aerodrome direct fixture，
可以形成最小 Day 8 baseline。冻结只授权 read-only/simulation/paper research。

## 排除项与 Unknowns

- Optimism 与 USDT：Week 1 没有 quote observations，排除；不得猜 token metadata/availability。
- Arbitrum same-chain route：数据质量合格，但为缩小 Week 2 slice 暂不进入 frozen universe。
- Base→Arbitrum USDC：保留为 Week 1 research evidence；不属于 Day 8 same-chain baseline，且
  也是 availability 较低的 route。
- LI.FI route diversity 不能替代两个独立 venue；direct confirmation 尚未实现。
- Quote lifetime、独立 re-quote latency 与完整 cost uncertainty 尚无数据，所以 freshness 与
  economic thresholds 不能冻结成数值。

## 下一步

按 frozen Base USDC/WETH universe 进入 Day 8 same-chain baseline。LI.FI 只可用于 discovery；
必须取得两个可比 venue/direct source、独立 re-quote、Gas/Fee/Min Output/Approval 与完整 reject
evidence 后才能形成 paper decision。非阻塞字段、visualization 与更多历史样本留在 backlog。
