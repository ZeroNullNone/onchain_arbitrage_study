# Day 13 — Transaction Simulation

## Scope

- One simulation adapter chosen: `eth_call`.
- One candidate path covered: same-chain USDC→WETH round-trip (Base snapshot fixtures).
- Outputs kept raw + UTC and never converted to defaults.
- No signing, no broadcast; only simulation evidence.

## Acceptance behavior

- Save per simulation:
  - `gasUsed`
  - token balance changes
  - `revertReason`
  - allowance (`required` / `available`)
  - request metadata, block number, and raw reference.
- Compare quote output vs simulation output and emit explicit comparison outcomes.
- Rejection reasons include:
  - `simulation_reverted`
  - `output_below_quoted`
  - `output_below_minimum`
  - `insufficient_allowance`
  - `stale_block`
  - `token_mismatch`
  - `output_missing`
- Two failure fixtures exist: allowance failure and min-output failure.

## Evidence files

- `tests/fixtures/simulation/day13_success.json`
- `tests/fixtures/simulation/day13_allowance_reject.json`
- `tests/fixtures/simulation/day13_min_output_revert.json`

## Tests

- `tests/test_simulation.py`
  - normalize success fixture and parse eth_call result
  - parse min-output revert and confirm comparison fail
  - parse allowance fail and confirm allowance rejection
  - stale block comparison check

## Non-goals

- No Tenderly/local fork adapter implementation.
- No smart contract wallet signing or broadcast.
- No live cross-chain atomic simulation.
