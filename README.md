# On-chain Arbitrage Study

一个 21 天、每日最多 2 小时的 execution-aware 链上套利研究项目。目标是建立可追溯的 Quote → Re-quote → Cost → Inventory → Simulation → Paper Decision 闭环，而不是在 21 天内发布实盘 Bot。

## 当前状态

Day 16 Primary Strategy Specification 已完成。基于 Day 15 确立的 H1（跨链预置库存套利）主线：
- 发布了无歧义的策略规范文档 [`docs/strategy_spec.md`](docs/strategy_spec.md) 与冻结配置文件 [`config/strategy.toml`](config/strategy.toml)；
- 确立并形式化了五元分解的 **Required Edge** 门限公式（已知成本 + 成本不确定性缓冲 + 时延劣变缓冲 + 再平衡摊销缓冲 + 最低经济利润）；
- 实现了策略层解析器与决策评估引擎 [`src/onchain_arb/strategy.py`](src/onchain_arb/strategy.py)，并在加载期内置严格的 Anti-TBD 校验；
- 建立了 Golden Examples 验收单测套件 [`tests/test_strategy_spec_examples.py`](tests/test_strategy_spec_examples.py)（全库 112 项测试全部通过）。
所有数值与证据均严格可追溯，保持 Read-only / Simulation-only，不签名、不广播。

核心文档：

- [Research Charter](docs/research_charter.md)
- [Opportunity Taxonomy](docs/opportunity_taxonomy.md)
- [System Design](docs/system_design.md)
- [Day 2–21 Implementation Plan](docs/implementation_plan.md)
- [Day 1 Note](docs/daily/day_01.md)
- [Day 2 Note](docs/daily/day_02.md)
- [Day 3 Note](docs/daily/day_03.md)
- [Day 4 Note](docs/daily/day_04.md)
- [Day 5 Note](docs/daily/day_05.md)
- [Day 6 Note](docs/daily/day_06.md)
- [Day 7 Note](docs/daily/day_07.md)
- [Day 8 Note](docs/daily/day_08.md)
- [Day 9 Note](docs/daily/day_09.md)
- [Day 10 Note](docs/daily/day_10.md)
- [Day 11 Note](docs/daily/day_11.md)
- [Day 12 Note](docs/daily/day_12.md)
- [Day 13 Note](docs/daily/day_13.md)
- [Day 14 Note](docs/daily/day_14.md)
- [Day 15 Note](docs/daily/day_15.md)
- [Day 16 Note](docs/daily/day_16.md)
- [Week 1 Data Gate Report](docs/week_1_report.md)
- [Day 8 Baseline](docs/day08_baseline.md)
- [Day 9 Route Dispersion](docs/day09_route_dispersion.md)
- [Day 10 Inventory Model](docs/day10_inventory_model.md)
- [Day 11 Rebalance Economics](docs/day11_rebalance.md)
- [Day 12 Token Risk & Identity](docs/day12_token_risk.md)
- [Day 13 Transaction Simulation](docs/day13_simulation.md)
- [Day 14 Scanner v1](docs/day14_scanner.md)
- [Day 15 Hypothesis Ranking](docs/day15_hypothesis_ranking.md)
- [Day 16 Strategy Spec](docs/strategy_spec.md)
- [LI.FI Quote Schema](docs/schema/lifi_quote.md)

## 安全边界

- Read-only、Simulation-only、Paper-only。
- 不读取或处理私钥，不签名，不广播交易。
- `.env`、Raw/Normalized/Derived 运行数据和本地 DuckDB 不进入 Git。
- `ICL_ACCESS_KEY` 只用于按需发布 ICL Agent Check-in；不会进入研究代码或日志。

## 环境

- Python 3.12+
- 测试：pytest
- 数据层：append-only Raw JSON + Parquet + DuckDB

```bash
uv sync --extra dev
uv run pytest
```

Day 5 collector 默认运行两小时、每轮间隔 45 秒。单轮 smoke test 使用 `--once`：

```bash
uv run python scripts/collect_quotes.py --once
uv run python scripts/collect_quotes.py
```

Day 6 RPC URL 只从 `.env.example` 所列环境变量读取。无 Quote 时捕获配置中的三链 head；
传入 fresh Raw Quote 时，默认只捕获 Quote 涉及的 chain，且 freshness bound 必须显式给出：

```bash
uv run python scripts/capture_block_context.py
uv run python scripts/capture_block_context.py \
  --quote-raw data/raw/lifi/<fresh-quote>.json --max-quote-age 60
```

Day 7 QA 会 read-only 重查 DuckDB、Raw lineage 与 frozen config hash：

```bash
uv run python -m onchain_arb.data_quality \
  data/normalized/day05_final.duckdb --config config/week2.toml
```

也可使用标准 `venv` 与 `pip install -e '.[dev]'`。

## 目录

```text
config/              可提交的示例/冻结研究配置，不含 Secret
docs/                Charter、Design、Plan、Research 与 Daily Notes
src/onchain_arb/      Python Package；Day 1 仅含版本信息
tests/                Unit/Integration Tests；Day 1 仅含 Smoke Test
data/raw/             Append-only 原始证据（内容默认忽略）
data/normalized/      可由 Raw 重建的数据（内容默认忽略）
data/derived/         Candidate/Decision/Report（内容默认忽略）
```

## 执行方式

每天只实施 [Implementation Plan](docs/implementation_plan.md) 中当天的 Acceptance Criteria。若超出 120 分钟，缩小 Universe 或可选功能，但不删除 Raw Preservation、Decimals、Cost Ledger、Re-quote、Reject Logging 或 Tests。
