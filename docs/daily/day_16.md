# Day 16 — Primary Strategy Specification

## 状态与结论

- 状态：Day 16 Primary Strategy Specification acceptance scope 全部完成。
- 正式发布主策略规范文档 [`docs/strategy_spec.md`](../strategy_spec.md) 与冻结配置文件 [`config/strategy.toml`](../../config/strategy.toml)。
- 建立并验证五元无歧义 **Required Edge** 门限公式：
  $$\mathbf{RequiredEdge} = KnownExecutionCost + CostUncertaintyBuffer + LatencyDeteriorationBuffer + RebalanceBuffer + MinEconomicProfit$$
- 实现策略规范代码层解析与决策评估引擎 [`src/onchain_arb/strategy.py`](../../src/onchain_arb/strategy.py)，并在配置加载阶段强制执行严苛的 Anti-TBD 校验，杜绝未决占位符流入 Paper Engine。
- 编写 Golden Test 验收套件 [`tests/test_strategy_spec_examples.py`](../../tests/test_strategy_spec_examples.py)，14 项单测全部通过（全库达 112 passed）。

## 完成项

- 新增 `src/onchain_arb/strategy.py`：
  - 定义 `StrategyId`、`StrategyRejectReason`、`ThresholdBreakdown` 与 `ThresholdConfig`。
  - 定义 `TimingConfig`、`KillMetricsConfig`、`PrimaryStrategySpec` 与 `BackupStrategySpec`。
  - 实现 `load_strategy_spec()`，内置递归式 Anti-TBD 拦截器与字段强类型验证。
  - 实现 `evaluate_primary_strategy()`，实现代币白名单、时效、时钟偏差、去重、Required Edge 门限与库存带的多道严格准入关卡。
- 新增配置文件 `config/strategy.toml`：
  - 完整固化 H1（跨链预置库存套利）与 H2（同链负对照基线）的全部参数，无任何 "TBD" 占位符。
- 新增单元测试 `tests/test_strategy_spec_examples.py`：
  - 覆盖配置完整性加载、TBD 占位符严格拦截、非法数值边界拒绝。
  - 覆盖 $500 与 $100 档位的标准手算 Golden 场景（通过 / 门限未达 / 时延劣变 / 成本保底）。
  - 覆盖超时报价、时钟偏差超标、库存不足、重复机会、非标规模与注册表排除资产的确定性拒绝。
  - 验证多轮重复评估的严格确定性（Strict Determinism）。
- 新增策略规范文档 `docs/strategy_spec.md`：
  - 包含标的资产、代币映射、信号公式、新鲜度、保守产出、门限分解、库存带、再平衡、去重、拒绝分类与熔断断路器的完整定义。
- 更新 `README.md` 索引与状态。

## 核心学习与量化思维

1. **Required Edge 的五元安全边界**：
   - 简单的 “毛利 > Gas” 属于典型的初学者伪套利。链上执行存在微观 Gas 波动、网络传输时延导致的价格逆向滑点、后续恢复资产平衡所需的跨链桥摊销成本，以及补偿智能合约与资金锁定的经济门槛。五元门限从根本上消除了假盈利信号。
2. **用类型系统与配置校验斩断 “TBD 债务”**：
   - 很多量化系统在从研究阶段走向仿真时，常因遗留硬编码默认值或未定参数（TBD）导致静默故障。在 `load_strategy_spec` 阶段建立递归扫描，只要发现任何 TBD/TODO 占位符立即抛出 `ValueError`，强迫所有参数必须显式声明并经过审查。
3. **确定性与无歧义**：
   - 策略规范不是概念性白皮书，而是可直接作为可执行代码实现的黄金准则。同一输入在任意时刻输入评估器，必须输出完全一致的判定结果与拒绝代码。

## Evidence 与验证

- 策略规格与计算模型：[`src/onchain_arb/strategy.py`](../../src/onchain_arb/strategy.py)
- 冻结策略配置：[`config/strategy.toml`](../../config/strategy.toml)
- 详尽规则文档：[`docs/strategy_spec.md`](../strategy_spec.md)
- 验收测试：[`tests/test_strategy_spec_examples.py`](../../tests/test_strategy_spec_examples.py)（14 passed in 0.06s；全库 112 passed）
- 历史证据支持：[`docs/day10_inventory_model.md`](../day10_inventory_model.md)、[`docs/day11_rebalance.md`](../day11_rebalance.md)、[`docs/day12_token_risk.md`](../day12_token_risk.md)、[`docs/day15_hypothesis_ranking.md`](../day15_hypothesis_ranking.md)

## Gate 边界

- 严格限制在 H1 Primary + H2 Backup（只读）范围内，未做投机性参数拟合或机器学习参数搜索。
- 保持 Read-only / Simulation-only，不引入任何钱包签名、私钥加载或主网广播。
- 所有会计计算使用 Integer raw token units + `Decimal`。

## 下一步

- Day 17 将基于 Day 16 策略规范构建 **Event-time Replay** 模块（`src/onchain_arb/replay.py` 与 `docs/day17_replay.md`），基于事件时间与真实网络时延分布对历史观察数据进行重放，消除快照膨胀（Snapshot Inflation），评估时延劣化与机会聚合特征。
