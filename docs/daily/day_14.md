# Day 14 — Scanner v1

## 状态与结论

- 状态：Day 14 Scanner v1 acceptance scope 已完成。
- 将分散的 Quote Ingestion、Re-quote、Cost Ledger、Virtual Inventory、Transaction Simulation 与 Persistence 连接为端到端 Research Loop。
- 实现了 6 种标准 Candidate 状态（`DETECTED`、`REQUOTE_FAILED`、`NET_NEGATIVE`、`INVENTORY_BLOCKED`、`SIMULATION_FAILED`、`PAPER_READY`）与完整的 Reject 原因链条。
- 达到 100% Cost Completeness 与 100% Raw Reference 覆盖。

## 完成项

- 新增 `src/onchain_arb/decision.py`：
  - 定义 `CandidateState` 与 `CandidateRejectReason` 枚举。
  - 定义 `ScanDecision` 审计数据结构，包含精确 net PnL、cost/inventory/simulation 评估引用、latency 与 lifetime。
- 新增 `src/onchain_arb/scanner.py`：
  - 实现 `CandidateDeduplicator`（滑动窗口机会去重）。
  - 实现 `ScannerPipeline`（支持 same-chain 与 cross-chain 候选机会的全流程门禁评估）。
  - 实现 `ScannerMetrics` 与 `ScannerReport`，计算 Re-quote survivor ratio、Simulation survivor ratio、Latency 分布与 Sparse sample 标记。
  - 实现 `persist_scanner_report` 原子落盘持久化。
- 新增 `scripts/run_scanner.py`：CLI 运行脚本并输出格式化决策与漏斗统计。
- 新增测试夹具 `tests/fixtures/scanner/day14_scenarios.json` 与验收测试 `tests/test_scanner.py`（92 passed）。
- 新增文档 `docs/day14_scanner.md`。

## Evidence 与验证

- Pipeline & Models: `src/onchain_arb/scanner.py`, `src/onchain_arb/decision.py`
- CLI Runner: `scripts/run_scanner.py`
- Test suite: `tests/test_scanner.py`（覆盖 6 类状态流转、去重、门禁、漏斗指标、持久化）
- 文档：`docs/day14_scanner.md`

## Gate 边界

- 单进程顺序 Pipeline，未引入分布式队列或多进程锁。
- 保持 Read-only / Simulation-only，无任何私钥、钱包签名或广播操作。
- 有效样本量 $<20$ 时显式标记 `is_sparse = True`，不进行任何外推盈利性宣称。

## 下一步

- Day 15 将使用一致的 Scorecard 对 Primary（H1 跨链库存）、Baseline（H2 同链 DEX-DEX）和 H3 假设进行评分与排序，明确 Kill 至少一个方向。
