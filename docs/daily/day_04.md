# Day 4 — LI.FI API Probe

## 状态与结论

- 状态：完成。
- 2026-08-08 UTC 完成 3 routes × 3 sizes，共 9/9 个成功 Quote。
- 当前 Slice 只证明 Quote 可被完整保存与离线重建，不证明存在套利机会。
- LI.FI fixed fee 已包含在输出；gas 是否包含没有 Source 字段，因此保留为未知。

## 完成项

- 新增同步、单次、只读 `GET /v1/quote` Probe。
- Probe 记录完整 request、response/error、request ID、UTC 与 latency。
- Raw 文件使用 exclusive create，已有证据不会被覆盖。
- 映射 chain/token/from/to/min/gas/fee/duration/tools/approval/transaction。
- Token amount 使用 integer raw units + explicit decimals；USD 使用 `Decimal`。
- Route fingerprint 只哈希稳定语义，不含 amount、quote ID 或交易动态字段。
- 保存 Base swap、Arbitrum swap、Base→Arbitrum bridge 的 100/500/1,000 USDC fixtures。
- 新增完全脱网的 fixture tests 与字段语义文档。

## 关键证据

- 9 个 fixture 都可重建原始 query、route steps、output、minimum output、fee 与 gas。
- Base→Arbitrum 三个 size 均选择 `feeCollection > eco`，fingerprint 一致。
- Arbitrum 三个 size 均选择 `feeCollection > kyberswap`，fingerprint 一致。
- Base route 在 size 间出现 `fly` / `kyberswap` 切换；fingerprint 按实际路径变化。
- Cross-chain fixture 的 LI.FI fee 为输入 USDC 的 0.25%，且 `included=true`。
- 所有 gas cost 均保留原生 ETH raw units，`included=None`，未猜测或置零。
- 返回的 transaction request 仅作为 raw evidence 保存，从未签名或广播。

## 验证

- `uv run pytest`
- Offline tests 覆盖 9 fixtures、3×3 universe、fingerprint、cost units 与失败响应。

## 下一步

- Day 5 在此 raw envelope 与 parser 上增加低并发 append-only collector。
- Timeout、retry/backoff、rate limit 与 durable normalized storage 留给 Day 5。

