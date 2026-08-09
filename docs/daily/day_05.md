# Day 5 — Quote Collector v0

## 状态与结论

- 状态：完成；实现、两小时 evidence run 与 offline verification 均通过。
- Collector 只调用 LI.FI read-only `GET /v1/quote`，不签名、不广播交易。
- Raw JSON 是 authoritative、append-only evidence；Parquet 与 DuckDB 是可从 Raw 重建的 normalized projection。
- 当前固定 Universe 为 Day 4 的 3 routes × 3 exact USDC sizes，单进程、并发上限 2。

## 完成项

- 每次 attempt 使用独立 UUID request ID，并记录 UTC request start 与纯网络 latency。
- 30 秒 timeout、最多 3 次 attempt、指数 backoff；429 尊重 `Retry-After`。
- 全局 request-start rate limiter 默认每次间隔至少 1 秒。
- response、HTTP error、transport error 均在任何解析前原子写入 Raw JSON。
- Secret request headers 不落盘；响应的 cookie/auth 类 header 被 redacted。
- 成功解析后 append 一条 DuckDB row 与一个 immutable Parquet part。
- Token/cost amount 使用 integer raw units 的十进制字符串并保留 explicit decimals；不使用 binary float 做金额语义。
- `collection_attempts` 独立保存 success、parse failure、timeout、unavailable 与其他失败 outcome。
- Collector 重启复用数据库但生成新 request ID/file，不覆盖已有 Raw 或 Parquet。

## Storage Contract

- Raw：`data/raw/lifi/YYYY-MM-DD/<UTC>_<request_id>.json`。
- Parquet：`data/normalized/lifi/quotes/part-<request_id>.parquet`。
- DuckDB：`normalized_quotes` 与 `collection_attempts` 两张 append-only table。
- 每条 normalized record 的 `request_id` 与 `raw_ref` 必须匹配原始 envelope；`raw_ref` 使用绝对路径。
- Raw write 失败时不做 normalized write。Parse 失败保留 Raw，并写显式 `parse_failure` attempt。
- Parquet/DuckDB write 失败不会被转换成成功，也不会用 stale/cache/fallback 数据替代。

## Two-hour Evidence Run

- Dataset：ignored local `data/raw/lifi/day05_final`、`data/normalized/lifi/day05_final` 与 `data/normalized/day05_final.duckdb`。
- Command：`uv run python scripts/collect_quotes.py --duration 7200 ...`。
- UTC observation window：2026-08-09 06:40:49.897176 → 08:40:58.410812，共 2:00:08.513636。
- Request count：83 attempts / 83 Raw files。
- Success：81 normalized quotes，success rate 97.59%。
- Rate limited：2；LI.FI 返回 source code `1005` 与约 2 小时 `Retry-After`，Collector 保存 Raw 后等待并成功恢复采集。
- Parse failure：0。
- Timeout：0。
- p50 / p95 network latency：1,725.714 ms / 3,852.330 ms。
- Unavailable routes：0。
- Lineage audit：81 DuckDB rows、81 Parquet parts；81/81 normalized records 的 `request_id` 与存在的 Raw envelope 匹配。

## 验证

- `uv run pytest`
- Offline tests 覆盖 raw-first lineage、DuckDB/Parquet 内容、restart append、timeout retry、429 `Retry-After`、parse failure 与 polling interval 约束。
- Live smoke round：9 requests、9 success、0 parse failure、0 timeout、0 unavailable。

## 下一步

- Day 6 在每次 Quote 附近增加 read-only chain head/block context。
- Structured concurrency、compression/partition tuning 与长期 scheduling 保留在 backlog。
