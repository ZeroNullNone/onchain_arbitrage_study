# On-chain Arbitrage Study

一个 21 天、每日最多 2 小时的 execution-aware 链上套利研究项目。目标是建立可追溯的 Quote → Re-quote → Cost → Inventory → Simulation → Paper Decision 闭环，而不是在 21 天内发布实盘 Bot。

## 当前状态

Day 1 已完成研究范围、机会分类、系统设计、Day 2–21 实施计划和最小 Python 骨架。当前没有交易、钱包或外部 Quote 逻辑。

核心文档：

- [Research Charter](docs/research_charter.md)
- [Opportunity Taxonomy](docs/opportunity_taxonomy.md)
- [System Design](docs/system_design.md)
- [Day 2–21 Implementation Plan](docs/implementation_plan.md)
- [Day 1 Note](docs/daily/day_01.md)

## 安全边界

- Read-only、Simulation-only、Paper-only。
- 不读取或处理私钥，不签名，不广播交易。
- `.env`、Raw/Normalized/Derived 运行数据和本地 DuckDB 不进入 Git。
- `ACCESS_KEY` 只用于按需发布 ICL Agent Check-in；不会进入研究代码或日志。

## 环境

- Python 3.12+
- 测试：pytest
- 后续数据层：Parquet + DuckDB（依赖在对应实施日再添加）

```bash
uv sync --extra dev
uv run pytest
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

