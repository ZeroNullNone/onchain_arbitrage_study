# Day 3 — Base WETH/USDC AMM Executable Price

- 日期：2026-08-07
- 状态：完成

## 结论

Base 上 ETH 以 canonical WETH 表示。选定 Aerodrome vAMM-WETH/USDC volatile pool，
用 pinned reserves 和合约相同的 integer `x * y = k` math 计算 executable output。
网页价格和 reserve ratio 只作 displayed spot，不能作成交价。

## Source Observation

- Chain：Base Mainnet (`8453`)
- Pool：`0xcdac0d6c6c59727a65f871236188350531885c43`
- Block：`49,641,814`
- Direction：exact-input USDC → WETH
- Reserves：`2,058.591003926976198288 WETH` / `3,917,509.892424 USDC`
- Pool fee：`30 bps`，从 PoolFactory `getFee(pool, false)` 读取
- Reserve last update：`2026-08-07T03:22:45Z`
- Quote observation：`2026-08-07T03:23:22.233422Z`
- Raw fixture：`tests/fixtures/amm/base_aerodrome_weth_usdc_block_49641814.json`

首批 RPC 的 USD 500 / 1,000 calls 被 public endpoint rate-limit；原始 errors 已保存，
随后在同一 block 独立 retry 成功，没有使用 fallback 或 stale quote。

初版 derived table 曾手工漏抄 WETH reserve hex 的最后一个 `0`，造成 16× price error。
当前 table 直接由完整 32-byte raw word 重建，并有 fixture-to-CSV regression test。

## Size Sensitivity

| Input | Spot USDC/WETH | Executable WETH | Average USDC/WETH | Impact | Min WETH (50 bps) | Pool fee |
|---:|---:|---:|---:|---:|---:|---:|
| 100 USDC | 1,903.005446 | 0.052389478392 | 1,908.780218 | 30.3455 bps | 0.052127531000 | 0.30 USDC |
| 500 USDC | 1,903.005446 | 0.261920729277 | 1,908.974526 | 31.3666 bps | 0.260611125631 | 1.50 USDC |
| 1,000 USDC | 1,903.005446 | 0.523774817108 | 1,909.217410 | 32.6429 bps | 0.521155943022 | 3.00 USDC |

Price impact compares average execution price with displayed reserve-ratio spot and includes
the 30 bps fee plus curve impact. Minimum output uses an explicit 50 bps tolerance.
Net arbitrage edge is intentionally not reported: Day 3 has no independent comparison venue
or complete cost ledger for a candidate.

## 验证

Local integer outputs exactly match Aerodrome `getAmountOut(uint256,address)` for all sizes.
A separate hand calculation proves fee removal occurs before the constant-product curve.

```text
UV_CACHE_DIR=/tmp/onchain-arb-uv-cache uv run pytest
13 passed in 0.01s
```

## 下一步

Day 4 可复用 executable-price 语义，但 LI.FI quotes 必须保存自己的 raw evidence；
不把本日 pool state 当成后续时点的价格。
