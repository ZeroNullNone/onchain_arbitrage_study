# Day 13 — Transaction Simulation

## 状态与结论

- 状态：Day 13 paper-only acceptance scope 已完成。
- 在 Base 的 same-chain USDC→WETH 任务链上构建了 `eth_call` 仿真 evidence 的解析与比较。
- 成功仿真、Allowance 不足、Min-output Revert 三类证据均可通过原始 fixtures 重建。

## 完成项

- 新增 `src/onchain_arb/simulation.py`。
  - `load_raw_simulation` 从 append-only raw envelope 重建仿真记录。
  - `compare_quote_and_simulation` 输出 `SimulationComparison`，包含执行判断与 reject 原因。
- 明确记录：gasUsed、ERC20/ETH 级别余额变化、revert reason、allowance、block number、raw reference。
- 为 quote 与 simulation 的可执行性判断实现：
  - token 匹配
  - quote/minimum output 覆盖
  - allowance 覆盖
  - stale block 检查
- 新增 3 个测试 fixture 和 Day 13 acceptance 测试。

## Evidence 与验证

- Simulation fixtures（raw）：
  - `tests/fixtures/simulation/day13_success.json`
  - `tests/fixtures/simulation/day13_allowance_reject.json`
  - `tests/fixtures/simulation/day13_min_output_revert.json`
- Acceptance tests：`tests/test_simulation.py`

## Gate 边界

- 本日只实现 `eth_call` 单链仿真；未集成 Tenderly/local fork。
- 未实现任何 wallet 操作、签名、广播。
- 仿真输出只用于决定是否 `executable`，不改变基础策略定义。

## 下一步

- Day 14 将把 Simulation 比较结果并入 Scanner gate：`DETECTED→REQUOTING→COSTED→INVENTORY_CHECKED→SIMULATED→PAPER_READY`。
