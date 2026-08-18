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

## 核心学习与量化思维

1. **套利研究的本质是“证伪漏斗（Falsification Funnel）”，而非“寻找利润”**：
   - 链上最容易出现的错误是“看到报价有价差就认为存在套利”，真实环境中 99% 的毛价差都会在二次询价（Re-quote）、扣费（Gas/Approval）、库存失衡或仿真 Revert 阶段被剔除。
   - 建立确定性状态机分层记录 Reject 原因，是避免虚假信号和不可行策略的核心工程手段。
2. **单一所有权账本（Single-owner Cost Ledger）与绝对精度**：
   - 经济决策严禁使用浮点数，底层代币采用不可分割的整数最小单位（Raw integer units）+ `Decimal`。
   - 成本只能在账本中被扣减一次，对内含费用（Included costs）与外部原子/周期费用做严格区隔，杜绝重复扣费。
3. **链上仿真（Simulation）是执行前的真实性底线**：
   - 链下 Aggregator 的报价只是预期承诺，`eth_call` 仿真才能在指定区块状态下验证真实的余额变化、Allowance 满足度与 Revert 原因；无仿真证据绝不标记为可执行。
4. **小样本自律与稀疏熔断（Sparse Sample Guard）**：
   - 当有效样本量 $N < 20$ 时，系统必须显式标记 `is_sparse = True`，禁止在此阶段做任何外推盈利性宣称，避免过度拟合与统计幻觉。
5. **100% 原始证据可审计性（Raw Lineage）**：
   - 每一个派生决策都必须包含指向不可变原始请求/响应的 `raw_refs`，保证回测、排错与审计时具备完整的数据血统。

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
