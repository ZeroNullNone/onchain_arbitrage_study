# On-chain Arbitrage Study

一个 21 天、每日最多 2 小时的 execution-aware 链上套利研究项目。目标是建立可追溯的 Quote → Re-quote → Cost → Inventory → Simulation → Paper Decision 闭环，而不是在 21 天内发布实盘 Bot。

## 当前状态

Day 5 已完成固定 3 routes × 3 sizes 的低并发 LI.FI Quote Collector。每次请求先保存
append-only Raw Envelope，再解析为可追溯的 Parquet + DuckDB normalized record；包含
timeout、bounded retry/backoff、rate limiting、UTC/request ID/latency 与采集 metrics。
当前没有交易或钱包逻辑；返回的 transaction request 仅作为证据保存，不签名、不广播。

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
