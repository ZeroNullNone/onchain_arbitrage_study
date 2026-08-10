# Day 6 — RPC / Block Context

## 状态与结论

- 状态：完成；三链 live smoke、fresh-quote alignment 与 offline fixture tests 均通过。
- Direct Quote + 同时点 RPC Context 才可用于 decision-time；indexed data 仅用于 research/backfill。
- 本日只读取 JSON-RPC，不签名、不广播交易；The Graph/event query 是可选项，本 Slice 未实现。

## 完成项

- 新增 Base (`8453`)、Arbitrum One (`42161`)、OP Mainnet (`10`) 的非 Secret chain config。
- 每个 observation 依次读取 `eth_chainId`、`eth_blockNumber`，再按该 hex head 精确读取
  `eth_getBlockByNumber(head, false)`。
- 保存完整 request/response/error、request ID、UTC、逐次与总 latency；Raw 先于解析落盘。
- RPC URL 只从环境变量读取；Evidence 只记录 env alias，URL/credential 不落盘。
- Parser 验证 JSON-RPC ID、canonical hex、configured chain ID、head/block 一致性、UTC、
  block hash、timestamp 与 `baseFeePerGas`，缺失或不一致均显式失败。
- 可用 fresh LI.FI Raw Quote 作 anchor；默认只查 Quote 涉及的 chain，并计算
  `quote_to_rpc_ms`。调用方必须显式给出 freshness bound；超限或未来 Quote 被拒绝。

## Live Evidence

- UTC capture window：2026-08-10 04:49:11.797641 → 04:49:15.348290。
- Base：head/block `49,774,002`，block time `04:49:11Z`，base fee `5,000,000 wei`。
- Arbitrum：head/block `492,968,364`，block time `04:49:12Z`，base fee `20,006,000 wei`。
- Optimism：head/block `155,369,288`，block time `04:49:13Z`，base fee `365 wei`。
- Public endpoint latency：Base `1,013.415 ms`；Arbitrum `1,224.945 ms`；
  Optimism `1,306.131 ms`。
- Fresh Base LI.FI Quote `6779de6c-fee9-431d-81c7-f83671e8c13c` 对齐 exact head
  `49,774,096`；manual smoke offset `19,942.864 ms`，RPC latency `938.660 ms`。
- Live Raw 保存在 ignored local `data/raw/rpc/day06_smoke` 与 `day06_anchor`；三链成功
  response 已保存为脱网 fixtures。
- Smoke 使用官方列出的开发用 public RPC；这些 endpoint 是 rate-limited，不作为可用性承诺：
  [Base](https://docs.base.org/base-chain/quickstart/connecting-to-base)、
  [Arbitrum](https://docs.arbitrum.io/for-devs/dev-tools-and-resources/chain-info)、
  [Optimism](https://docs.optimism.io/app-developers/reference/rpc-providers)。

## 验证与边界

- `uv run pytest`：40 passed。
- Tests 覆盖三条真实 Raw fixture、hex→integer、UTC、chain ID、exact-head request、
  quote alignment、raw-first transport failure、chain mismatch、invalid hex 与 Secret redaction。
- 未查询 Indexer lag；该项为 optional，且 indexed state 不进入 execution-time decision。

## 下一步

- Day 7 使用 Quote Raw lineage、latency 与本日 Block Context 执行 Week 1 Data Gate。
- Confirmation depth、multi-provider health、historical replay 与完整 event indexer 留在 backlog。
