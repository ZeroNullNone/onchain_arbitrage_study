# Day 18 — Paper Decision Engine

## 状态与结论

- 状态：Day 18 acceptance scope 完成。
- 新增幂等 Paper Decision/Fill Engine、saved evidence loader、CLI、验收测试与状态规范。
- 实现 DETECTED 到 CLOSED 的完整 happy path，以及 REJECTED / EXPIRED / ERROR 终态。
- 全程仅操作 integer raw-unit Virtual Balance/Allowance；无钱包、签名、广播或真实 notification integration。

## 完成项

- `src/onchain_arb/paper_engine.py`
  - deterministic Candidate ID 与 evidence fingerprint dedup；
  - quote expiry、route change、complete ledger、virtual inventory/allowance、Simulation/NA gates；
  - Paper Fill、Rebalance Pending/Closed、append-only transition audit；
  - `PAPER_READY` / `SYSTEM_ERROR` 限定 alert intents；
  - complete fixture loader，不推断缺失字段。
- `tests/fixtures/paper/day18_candidate.json`
  - 保存完整 Raw refs、request IDs、source、UTC timestamps、measured latency、route、raw-unit economics 与 virtual state。
- `tests/test_paper_engine.py`
  - 覆盖重复 Candidate 不重复 Fill、完整 lineage、所有 happy-path transitions、route/expiry/allowance reject、Simulation NA、Candidate ID conflict 与 fixture end-to-end。
- `scripts/run_paper_engine.py`
  - 读取 saved envelope，输出 auditable derived JSON 与 ending balances。
- `docs/day18_paper_engine.md`
  - 固定 identity、gate、audit、alert 与 scope 语义。

## Evidence 与验证

- 实现：[`src/onchain_arb/paper_engine.py`](../../src/onchain_arb/paper_engine.py)
- Raw fixture：[`tests/fixtures/paper/day18_candidate.json`](../../tests/fixtures/paper/day18_candidate.json)
- 验收测试：[`tests/test_paper_engine.py`](../../tests/test_paper_engine.py)
- 规范：[`docs/day18_paper_engine.md`](../day18_paper_engine.md)

Saved fixture 的 Candidate 通过所有 gate、产生一次 Paper Fill、完成一次 Virtual Rebalance 并恢复初始余额。其 700,000 raw-unit net edge 是确定性测试输入的实现证据，不是实证收益或 profitability claim。

## 学习总结

- **幂等性必须覆盖副作用**：重复 ID 不只应返回相同结果，还必须保证 audit、alert 与 virtual inventory 都不会二次变化。
- **Identity 应来自不可变 evidence**：使用 detection request identity 比时间戳或随机 ID 更容易重放、去重和审计；同 ID 不同 evidence 必须作为系统错误，而不是覆盖。
- **状态日志是证据链而非 UI 文案**：transition 需要 UTC 时间、latency、reason 和当阶段 refs，才能回答“何时、基于什么、为何进入此状态”。
- **NA 不等于缺失**：Simulation 不适用必须由策略显式声明；缺失 required Simulation 不能 silent fallback 成成功。
- **虚拟 allowance 与 balance 是不同约束**：余额足够不代表 router 可支配；两者需要独立 gate 与 reject reason。
- **未来 evidence 不能污染早期 transition**：Rebalance Raw ref 只属于后续 Close/Error，不应回填到 earlier Paper Fill lineage。
- **Fixture 证明实现，不证明 alpha**：确定性例子可验证状态、会计与审计路径，但不能支持机会频率、capacity 或盈利结论。

## Gate 边界

- 未签名或广播交易，未读取或处理任何 private key/seed phrase。
- 未实现 live alert connector、crash recovery、multi-process lock 或 production execution。
- 未使用 guessed token metadata、missing cost as zero、stale fallback 或 binary float 做经济判断。

## 下一步

Day 19 可在本 Engine 的 explicit gate/reject paths 上运行 Gas、Latency、Haircut、Route、RPC、Rebalance、Depeg、Inventory 与 Competitor stress matrix。
