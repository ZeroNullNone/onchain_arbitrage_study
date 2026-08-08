# LI.FI Quote Raw and Normalized Schema

## Scope

Day 4 uses only the read-only `GET https://li.quest/v1/quote` endpoint. It does
not sign, submit, simulate, poll, or execute the returned transaction. The nine
pinned fixtures cover Base USDC→WETH, Arbitrum USDC→WETH, and Base
USDC→Arbitrum USDC at exact-input sizes of 100, 500, and 1,000 USDC.

LI.FI documents `fromAmount` in smallest token units and describes
`estimate.toAmountMin` as the guaranteed minimum after slippage. The endpoint
returns one populated step with an executable `transactionRequest`:
[quote endpoint](https://docs.li.fi/api-reference/get-a-quote-for-a-token-transfer),
[quote schema](https://docs.li.fi/agents/reference/schemas).

## Raw evidence envelope

Each JSON fixture is one append-only observation:

| Field | Meaning |
| --- | --- |
| `schema_version` | Local envelope version; currently `1`. |
| `request_id` | Locally generated UUID for this observation. |
| `source` | Always `lifi`. |
| `observed_at` | UTC request-start timestamp. |
| `latency_ms` | Measured wall-clock latency, stored as a decimal string. |
| `request` | Exact method, base URL, query, and non-secret request headers. |
| `response.status` | HTTP status without normalization. |
| `response.headers` | Received headers; credential-like values are redacted. |
| `response.body` | Exact response bytes decoded as UTF-8, retained as a string. |
| `transport_error` | Explicit error type/message when no HTTP response exists. |

If `LIFI_API_KEY` is present in the process environment, the probe sends it but
records only `<redacted>`. Response authorization/cookie header values are also
redacted; the complete response body is unchanged. The probe opens every
evidence path in exclusive creation mode and cannot overwrite an earlier
observation.

## Normalized mapping

| Internal field | LI.FI field |
| --- | --- |
| Request chains/tokens/amount/address/slippage | `request.query.*` |
| Input token and raw amount | `action.fromToken`, `action.fromAmount` |
| Output token and raw amount | `action.toToken`, `estimate.toAmount` |
| Minimum output | `estimate.toAmountMin` |
| Primary tool and route steps | `tool`, `includedSteps[].{type,tool,action}` |
| Duration | `estimate.executionDuration` |
| Approval spender | `estimate.approvalAddress` |
| Source-reported fees | `estimate.feeCosts[]` |
| Source-reported gas | `estimate.gasCosts[]` |
| Transaction fields | `transactionRequest` unchanged |

Token quantities are parsed only from base-10 integer strings and paired with
explicit chain, address, symbol, and decimals. USD annotations and timing values
use `Decimal`; they are evidence annotations, not accounting inputs.

`feeCosts[].included` is retained exactly. In these fixtures the LI.FI fixed fee
is included in quoted output. `gasCosts[]` does not report `included`; normalized
gas therefore uses `None`, never an inferred `False` or a zero cost. Day 4 does
not assign either cost to Atomic or Cycle PnL—the cost ledger remains the sole
owner of PnL semantics.

## Route fingerprint

The fingerprint is SHA-256 over canonical JSON containing the top-level tool
and ordered semantic steps: step type/tool, source/destination chain IDs, and
source/destination token addresses. Dynamic quote IDs, transaction bytes,
amounts, prices, gas, duration, and timestamps are excluded. Identical route
structure at different sizes therefore has the same fingerprint; a provider or
step change correctly creates a different fingerprint.
