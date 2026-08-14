# AGENTS.md

- Do not preserve backward compatibility. Remove obsolete paths instead of adding compatibility layers, fallbacks, or migrations.
- Choose the simplest implementation that fully meets the current requirements. Avoid speculative abstractions, configuration, and indirection.
- Grow the system in layers. Start from the smallest version that works end to end, and add each new capability on top of a product that already works. Never trade a working product for unfinished complexity.
- Keep components modular and concerns clearly separated.
- Prefer established, well-maintained libraries when they reduce overall complexity or improve reliability. Do not reimplement common functionality without a clear reason.
- Lean on the dependencies already in the project before writing your own implementation or adding packages. Do not assume a library lacks a capability without checking its documentation and types.
- Make architectural decisions for the long term. Do not accept a stopgap that only works for now and is meant to be replaced later.

## On-chain research safety and evidence rules

- Operate read-only, simulation-only, and paper-only by default. Do not sign or broadcast transactions.
- Never request, read, print, log, persist, or handle private keys or seed phrases. Treat access tokens and RPC credentials as secrets and load them only from ignored environment files.
- Preserve complete raw requests, responses, and errors before normalization. Raw evidence is append-only and every normalized or derived record must retain its raw reference.
- Store token values as integer raw units plus explicit decimals. Use `Decimal` for accounting and never binary floating point for economic decisions.
- Record UTC timestamps, request IDs, source, and measured latency for every external observation.
- Never use silent fallback, stale cached values, guessed token metadata, or missing costs represented as zero. Emit an explicit failure or reject reason.
- Every positive signal requires an independently refreshed quote and a complete, reviewable cost ledger. The cost ledger is the single owner of PnL semantics.
- Every adapter schema or parsing change requires a saved raw fixture and a test covering that fixture.
- Implement only the current day's acceptance criteria. Put optional work in the backlog instead of expanding scope.
- Do not prematurely implement dashboards, live signing, flash loans, MEV infrastructure, production deployment, or speculative abstractions.
- Do not expose secrets from `.env` in commands, logs, tests, fixtures, commits, reports, or chat output.

## Project Git workflow

- Use native `git` for commits and pushes. Do not require GitHub CLI authentication unless the task explicitly needs a pull request, GitHub Actions, or another GitHub API feature.
