# Day 18 — Paper Decision Engine

## 结论

Day 18 建立了单进程、Paper-only 的幂等 Decision/Virtual Fill State Machine。它只消费已保存的 Detection、Re-quote、Cost Ledger、Simulation、Inventory、Allowance 与 Rebalance evidence；不连接钱包、不签名、不广播，也不发送真实外部通知。

确定性 fixture 完整走过：

```text
DETECTED → REQUOTING → COSTED → INVENTORY_CHECKED
→ SIMULATED → PAPER_READY → PAPER_FILLED
→ REBALANCE_PENDING → CLOSED
```

任一 gate 可明确结束为 `REJECTED`、`EXPIRED` 或 `ERROR`。不需要 Simulation 的策略必须显式声明 `simulation_required=false`，并留下 `SIMULATION_NA`，不能把缺失证据默认为成功。

## 身份与幂等性

Candidate ID 由不可变的 `(opportunity_key, direction, target_size_raw, detection_request_id)` 计算 SHA-256 前缀，不使用 wall clock 或随机 UUID。相同 Candidate 和相同 evidence fingerprint 再次提交时，返回同一个 immutable decision，不重复写 audit、不重复 alert、不重复改变 virtual balance。

若同一 Candidate ID 被不同 evidence identity 重用，Engine 生成 `CANDIDATE_ID_CONFLICT` 系统错误和唯一允许的 `SYSTEM_ERROR` alert intent。它不会覆盖原 decision 或产生 Fill。

## Gate 语义

1. `EXPIRED`：decision time 达到 quote expiry，或 Re-quote 到达时间达到 expiry。
2. Route：`original_route` 与独立 Re-quote 的 `refreshed_route` 必须完全相同；变化时 `ROUTE_CHANGED`。
3. Cost：现有 `ReplayCostLedger` 是 Required Edge 与 net edge 的唯一 owner。缺失 required cost 或 `net_edge_raw < 0` 都拒绝。
4. Inventory：所有 delta 使用 integer raw units；任何未知 position 或应用后负余额都拒绝。
5. Allowance：每个 `(chain_id, asset_id, spender)` 都必须有显式 virtual allowance，且覆盖 exact input。缺失和不足分开记录。
6. Simulation：required 时必须有独立 Raw evidence，并同时满足 success 与 minimum output；不 required 时进入 `SIMULATION_NA`。
7. Fill/Rebalance：Fill 只改变 Virtual Balance。显式 Rebalance evidence 到达后才应用恢复 delta 并 `CLOSED`；失败进入 `ERROR`。

Allowance 是只读的虚拟前置条件，不模拟链上 approve，也不会读取或处理私钥。

## Audit 与 Alert

每个 transition 保存全局 sequence、from/to state、UTC `occurred_at`、从 detection arrival 起的 latency、reason 和该阶段 Raw/derived refs。每个 Paper Fill 可直接回溯：

- initial raw quote；
- independent Re-quote；
- complete Cost Ledger ref；
- Simulation Raw ref，或显式 `SIMULATION_NA`。

Rebalance evidence 不会倒灌进更早的 Fill transition，只在 `CLOSED`/`ERROR` transition 出现。

Engine 不执行通知 I/O，只产生 alert intents；允许的种类仅为：

- `PAPER_READY`；
- `SYSTEM_ERROR`。

普通 reject、expiry、route change、allowance failure 和经济门限失败不 alert。

## Saved Fixture 与运行

`tests/fixtures/paper/day18_candidate.json` 保存 request ID、Raw ref、source、UTC observed/arrival timestamps、measured latency、route、完整 cost fields、raw-unit balances/deltas、virtual allowance 和 Simulation/Rebalance evidence。Loader 不猜测缺失字段，并校验 Candidate ID。

```bash
UV_CACHE_DIR=/tmp/onchain-arb-uv-cache uv run python scripts/run_paper_engine.py \
  tests/fixtures/paper/day18_candidate.json \
  --as-of 2026-08-18T08:00:06Z
```

Fixture 的一个 Candidate 最终为 `CLOSED`，net edge 为 700,000 USDC raw units，且 Rebalance 后 ending balances 与 initial balances 相同。这只证明状态、会计、幂等性和 lineage 可重复，不是盈利证据。

## Scope 与 Backlog

本日只实现 Paper-only、单进程、Virtual Balances。未实现 crash recovery、外部 alert connector、multi-process lock、wallet、signing、broadcast 或真实执行。Crash recovery 与并发锁保留在 backlog，不加入临时兼容层。
