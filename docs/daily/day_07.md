# Day 7 — Week 1 Data Gate

## 状态与结论

- 状态：Day 7 完成；Week 1 data gate **PASS**。
- Valid sample count：231 / 200；没有降低阈值，也没有用 fixture/smoke 补数。
- Week 2 已冻结为 Base USDC/WETH paper-research slice；仍禁止 live execution。
- 详细 evidence、正式 universe、排除项与 unknowns 见 `docs/week_1_report.md`。

## 完成项

- 新增 read-only repeatable QA，检查 schema、Raw lineage、UTC/ordering、latency、parse、
  decimals、duplicate、missingness、success projection、route availability 与 size sensitivity。
- Decimals 以 frozen `chain_id + address` metadata 检查，并验证 quote/cost raw units；经济值不
  使用 binary float。
- QA 输出 exact config SHA-256，缺表/缺 Raw/错误 token metadata 均显式失败。
- 修复长 `Retry-After` 阻塞整个 collection round：只 cooldown 受影响 route，完整保存 429。
- 新增 `config/week2.toml`；未取得足够 evidence 的 freshness/profit threshold 保持显式 TBD。

## Evidence

- 251 attempts：231 success、20 rate-limited；availability 92.03%。
- Raw / timestamp / latency coverage：100% / 100% / 100%。
- Parse：100%；missing required fields 0；duplicates 0；timestamp order violations 0；
  normalized projection mismatch 0；decimals pass。
- Latency p50 / p95：1,270.747 / 3,898.220 ms。
- 原 Day 5 run 内最大 gap `6,781.682025s` 暴露长 `Retry-After` blocking bug；修复后完成追加采集。
- Frozen config hash：`46bd62308a88624edbcdad228ce2dcb29ce427cb2cb488d5e9f4bdd7dcea222d`。
- `uv run pytest`：46 passed。

## Gate 边界

- 本日没有签名、广播、钱包或 live strategy。
- PASS 只允许进入冻结范围内的 Day 8 paper baseline，不能对盈利作结论。
- 下一步必须加入独立 direct venue/re-quote 与完整 cost/reject evidence。
- Visualization、额外历史样本和非阻塞 schema 字段留在 backlog。
