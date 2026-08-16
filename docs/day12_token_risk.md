# Day 12 — Token Identity and Basis Risk

## Scope and identity rule

The registry covers only the frozen Day 10–12 universe: USDC and WETH on Base and Arbitrum.
It is a paper-research control, not a live credit score or legal opinion.

The only token identity is:

```text
(chain_id, lower-case contract_address)
```

`symbol` is display metadata. It may be used to list matches, but never to resolve a token or assert
economic equivalence. Address matching is case-insensitive because EVM address casing does not create
a different contract.

## Registry decisions

| Chain | Address | Display symbol | Classification | Issuer / controlling system | Pause | Blacklist | Upgradeable | Frozen paper haircut | Decision |
| --- | --- | --- | --- | --- | --- | --- | --- | ---: | --- |
| Base (8453) | `0x833589fcd6edb6e08f4c7c32d4f71b54bda02913` | USDC | Canonical | Circle | Yes | Yes | Yes | 25 bps | Include |
| Base (8453) | `0x4200000000000000000000000000000000000006` | WETH | Wrapped | Base WETH9 predeploy | No | No | No | 5 bps | Include |
| Arbitrum (42161) | `0xaf88d065e77c8cc2239327c5edb3a432268e5831` | USDC | Canonical | Circle | Yes | Yes | Yes | 25 bps | Include |
| Arbitrum (42161) | `0x82af49447d8a07e3bd95bd0d56f35241523fbab1` | WETH | Bridged | Arbitrum canonical token bridge | No | No | Yes | 50 bps | Include |

The haircuts are explicit, frozen Day 12 policy assumptions. They are not observed market prices,
expected losses, or costs that may silently be subtracted from PnL. A later strategy decision may use
them only after the cost ledger defines the exact ownership and application semantics. Until then they
are risk annotations and review gates.

## Redemption and basis dependencies

- Base and Arbitrum USDC are the native Circle-issued addresses in the current Circle address list.
  Redemption means eligible Circle Mint redemption under Circle's terms; it is not an unconditional
  on-chain right available to every holder. Their shared symbol and issuer still do not make their
  chain-specific contracts one token identity. Circle's EVM token implementation includes pausing,
  address blacklisting, and proxy upgrades.
- Base WETH is the chain's WETH9 predeploy. Its direct redemption path is the contract's `withdraw`
  operation into native ETH on Base. The verified WETH9 surface has no pause, blacklist, or proxy
  administration.
- Arbitrum WETH is not modeled as the same wrapper contract as Base WETH. It is a bridged token proxy.
  Its basis depends on the Arbitrum canonical bridge, L1 escrow/message completion, and proxy
  administration. The path back to native ETH is withdrawal through the WETH gateway to Ethereum WETH,
  followed by unwrapping on Ethereum.

Primary references reviewed on 2026-08-16 UTC:

- [Circle USDC contract addresses](https://developers.circle.com/stablecoins/usdc-contract-addresses)
- [Circle EVM stablecoin contracts and control features](https://github.com/circlefin/stablecoin-evm)
- [Base mainnet WETH9 predeploy](https://docs.base.org/base-chain/network-information/base-contracts)
- [Base WETH9 verified source](https://basescan.org/address/0x4200000000000000000000000000000000000006#code)
- [Arbitrum WETH proxy verified source](https://arbiscan.io/address/0x82af49447d8a07e3bd95bd0d56f35241523fbab1#code)
- [Arbitrum canonical token bridge contracts](https://github.com/OffchainLabs/token-bridge-contracts)

## Validation behavior

`load_token_registry` has no defaults or fallback metadata. It rejects:

- absent or unknown document/token fields;
- invalid chain IDs, non-20-byte EVM addresses, or invalid decimals;
- classifications outside `canonical`, `bridged`, and `wrapped`;
- non-boolean pause, blacklist, upgradeability, or exclude decisions;
- haircuts outside 0–10,000 integer basis points;
- missing decision rationale or HTTPS evidence references; and
- duplicate identities, including duplicates that differ only by address casing.

`TokenRegistry.require_token_refs` also rejects a known identity when its supplied symbol or decimals
disagree with the registry. It never substitutes guessed metadata.

## Evidence and non-goals

- Machine-readable policy: `config/token_registry.toml`
- Loader and validation: `src/onchain_arb/token_registry.py`
- Acceptance tests: `tests/test_token_registry.py`

No RPC request, wallet access, signing, transaction construction, or broadcast was performed. The
registry does not implement a whole-market database, real-time metadata monitoring, issuer alerts,
live credit scores, or legal analysis.
