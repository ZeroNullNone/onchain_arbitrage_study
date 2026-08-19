# Day 15 — Hypothesis Ranking

## 状态与结论

- 状态：Day 15 Hypothesis Ranking acceptance scope 已全部完成。
- 采用 7 维度标准化评分卡（权重 25/20/15/15/10/10/5）对前期积累的证据进行定量与定性综合评估。
- **H1（跨链预置库存套利）** 获得最高分 **75 / 100**，被正式选定为 **PRIMARY** 策略主线，进入 Day 16 Strategy Spec 制定。
- **H2（同链 DEX–DEX 公开往返基线）** 获得 **51 / 100**，作为 **BACKUP / 负对照基准** 保留，用于验证数据质量与拒绝假机会。
- **H3（聚合器路由离散度套利）** 获得最低分 **26 / 100**，被 **正式 KILL** 并放弃后续策略研发。

## 完成项

- 新增 `src/onchain_arb/ranking.py`：
  - 定义 `HypothesisId`、`RankingVerdict`（PRIMARY / BACKUP / KILL）与 `DimensionScore`。
  - 定义 `HypothesisEvaluation` 与 `HypothesisRankingScorecard`，强制总权重必须等于 100，评分与权重均使用精确 `Decimal`。
  - 实现 `build_day15_ranking_scorecard()`，内置完整的证据引用与逐项判定依据。
- 新增单元测试 `tests/test_ranking.py`（6 个测试，全部通过；全套测试达 98 passed）。
- 新增文档 `docs/day15_hypothesis_ranking.md`：
  - 详尽列出 H1、H2、H3 的假设陈述、零假设（Null Hypothesis）、样本量与稀疏标记、支持与反面证据、核心未知项。
  - 给出包含 7 个维度的完整评分矩阵与逐项打分理由。
  - 记录对 H3 的正式淘汰声明与理由。
- 更新 `README.md` 索引与状态。

## 核心学习与量化思维

1. **“杀死错误方向（Killing unviable paths）”是量化研究中最具价值的产出之一**：
   - 绝大多数初学者会试图在所有方向上同时发力，或者在不可行的方向上不断增加模型复杂度（如为同链 DEX 套利加装更复杂的路径搜索）。
   - 及时通过数据证伪 H3（聚合器跨链路由离散度并非可执行套利，受桥时延和费率侵蚀）并降级 H2（同链公开价差在非 MEV 架构下几乎 100% 归零），能集中工程力量攻坚 H1。
2. **时延竞赛 vs 资产负债表与再平衡效率**：
   - 同链套利是纳秒/毫秒级的 MEV Builder 竞赛，Python 研究系统在此维度毫无优势；
   - 跨链预置库存套利将时延竞争转化为“双边流动性定价不一致的捕捉 + 资产负债表占用与周期再平衡成本管理”，更契合本研究闭环的工程边界。
3. **评分证据必须 100% 锚定不可变原始数据与已验证模型**：
   - 打分严禁基于主观乐观假设，每一个维度的得分都必须追溯至已落盘的测试夹具（如 Day 8 `edge_disappears.json`、Day 11 `rebalance_costs.json`、Day 13 仿真记录与 Day 14 Scanner 结果）。

## Evidence 与验证

- 评分与数据结构：`src/onchain_arb/ranking.py`
- 验收测试：`tests/test_ranking.py`（覆盖权重校验、排序、单项分边界、违规状态约束）
- 详细评估报告：`docs/day15_hypothesis_ranking.md`
- 历史证据引用：`docs/day08_baseline.md`、`docs/day09_route_dispersion.md`、`docs/day10_inventory_model.md`、`docs/day11_rebalance.md`、`docs/day12_token_risk.md`、`docs/day13_simulation.md`、`docs/day14_scanner.md`

## Gate 边界

- 严格限制在 H1、H2、H3 三个已有假设之内，不新增未经检验的投机性策略。
- 未修改历史数据或放宽判定门槛以迎合评分；H1 在真实跨链抓取样本不足时仍维持 `is_sparse = True`。
- 保持 Read-only / Simulation-only，不引入任何私钥、钱包签名或真实交易。

## 下一步

- Day 16 将基于 H1（跨链预置库存套利）编写详尽、无歧义的 Primary Strategy Specification（`docs/strategy_spec.md` 与 `config/strategy.toml`），定义精确的 Required Edge 计算公式、准入门限、库存带与熔断规则。
