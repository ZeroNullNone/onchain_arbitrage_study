# Day 9 LI.FI Route Dispersion

## Result

The read-only analyzer separates route-quality observations from tradable-edge decisions. It
calculates conservative best/second-best rankings, route switch rate, observed route lifetime,
provider concentration, duration and fee-rate dispersion, and size sensitivity. Rankings use
guaranteed minimum output rather than optimistic quoted output.

The frozen universe remains Base USDC→WETH at exact inputs of 100, 500, and 1,000 USDC. LI.FI
is the primary route source. The pinned Aerodrome pool `eth_call` observations are the independent
direct source. No endpoint was refreshed and no transaction was signed, simulated, or broadcast.

## Frozen evidence result

The independent direct pool quote, with the frozen 50 bps minimum-output policy from Day 3,
ranks above the LI.FI minimum output at every size:

| Input | Best minimum output | Second-best minimum output | Difference |
|---:|---:|---:|---:|
| 100 USDC | 0.052127531000276317 WETH, Aerodrome | 0.051807139365744812 WETH, Fly | 61.8431 bps |
| 500 USDC | 0.260611125630741254 WETH, Aerodrome | 0.259035696828724062 WETH, Fly | 60.8190 bps |
| 1,000 USDC | 0.521155943022301865 WETH, Aerodrome | 0.518096270405301691 WETH, KyberSwap | 59.0561 bps |

This ranking is analytical only. The Aerodrome observations begin on 2026-08-07 while the LI.FI
observations begin on 2026-08-08. For the 100 USDC candidate the exact observation gap is
98,225.491580 seconds, far beyond the explicit 60-second comparison bound. The independent check
therefore returns `refuted / stale_quote / is_arbitrage=false`. It does not establish that either
route was simultaneously executable at the displayed output.

LI.FI-only dispersion across the three sequential size probes:

- Provider sequence: Fly → Fly → KyberSwap; route switch rate: `1 / 2 = 0.5`.
- Provider concentration: Fly `2/3`; KyberSwap `1/3`.
- Observed fingerprint spans: Fly has two observations over 1.808387 seconds; KyberSwap has one
  observation and therefore a zero measurable span.
- Reported duration spread: 0 seconds. A reported zero is retained as source evidence and is not
  interpreted as literal zero execution time.
- Included LI.FI fee rate: 25 bps at every size; fee-rate spread: 0 bps.
- Guaranteed output per USDC is effectively flat from 100 to 500 USDC and improves by about
  0.48018 bps at 1,000 USDC, alongside the provider switch.

Because the probes changed size while being collected, the switch rate and fingerprint span
describe this **size sequence**, not repeated fixed-size temporal reliability. More collection for
provider reliability time series remains backlog work.

## Classification gate

Every comparison receives exactly one of these labels:

| Label | Required interpretation |
|---|---|
| `routing_improvement` | Fresh comparable direct evidence supports a route-quality difference, but no complete executable cycle exists. |
| `temporary_subsidy` | Explicit subsidy evidence explains the difference. It is not assumed durable. |
| `stale_quote` | The direct-source observation gap exceeds the chosen freshness bound. |
| `token_mapping_difference` | Chain-specific input/output token identity or exact size differs. |
| `unavailable_route` | Independent direct route evidence is missing or explicitly unavailable. |
| `tradable_edge` | A later fresh independent refresh, complete cost ledger, and a complete executable cycle are all present. |

Only `tradable_edge` sets `is_arbitrage=true`. Better output, provider switching, a different route
fingerprint, or an aggregator/direct-source gap cannot do so by themselves. Missing fee evidence
also yields unknown fee dispersion rather than a fabricated zero.

## Evidence boundary

The analysis reconstructs LI.FI observations from their append-only Raw envelopes and retains
quote ID, request ID, Raw reference, UTC timestamp, latency, integer token quantities, decimals,
route fingerprint, reported duration, and fee evidence. Direct comparisons retain their pinned
RPC Raw reference and request ID. No parsing schema changed, so no new external Raw fixture was
needed.

Cross-chain execution, bridge economics, new aggregators, provider reliability time series, and
subsidy detection are outside Day 9 scope.
