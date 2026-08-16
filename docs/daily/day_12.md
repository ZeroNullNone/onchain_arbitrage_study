# Day 12 — Token Identity 与 Basis Risk

## 状态与结论

- 状态：Day 12 当前 Universe 的 acceptance scope 已完成。
- Token identity 强制使用 `chain_id + contract_address`；Address 比较不区分大小写，Registry
  内统一保存为小写。
- `symbol` 只用于显示和返回候选列表，不能解析唯一 Token，也不能证明经济等价。
- 同为 `WETH` 的 Base Token 被记录为本链 Wrapped WETH9，而 Arbitrum Token 被记录为依赖
  Canonical Bridge 和 Upgradeable Proxy 的 Bridged Token。

## 完成项

- 新增严格 TOML Registry，覆盖 Day 10 冻结的 Base / Arbitrum USDC、WETH 四个 Token。
- 每个 Token 显式记录 Chain ID、Contract Address、Symbol、Decimals、Issuer、
  Canonical/Bridged/Wrapped、Redemption Path、Pause、Blacklist、Upgradeability、Haircut、
  Exclude Decision、Decision Reason 和官方/合约 Evidence URL。
- USDC 的 Pause、Blacklist、Upgradeability 能力按 Circle EVM FiatToken 设计显式标记；不能把
  Native USDC 当成无 Issuer Control 的无风险现金。
- 所有 Token 当前均保留在 Paper Universe；25 / 5 / 50 bps 是冻结的 Paper Policy Haircut，
  不是 Live Price、Expected Loss 或可静默计入 PnL 的 Cost。
- Loader 不提供 Default、Fallback 或 Guess；缺字段、未知字段、非法风险类型、非法 Haircut、
  重复 Identity 和 Metadata 不一致都会显式失败。

## Evidence 与验证

- Registry：`config/token_registry.toml`。
- Identity、Lookup、Schema 与 Validation：`src/onchain_arb/token_registry.py`。
- 风险表、Redemption / Basis Dependency、Evidence Links：`docs/day12_token_risk.md`。
- Acceptance Tests：`tests/test_token_registry.py`，覆盖同 Symbol 不等价、Case-insensitive Address、
  Duplicate Identity、Missing Risk Field、Invalid Classification/Haircut 以及 Frozen Universe Coverage。

## Gate 边界

- Registry 只覆盖当前 Universe，不扩张为全市场 Token Database。
- Haircut 目前是风险标记；未来只有 Cost Ledger 明确定义应用语义后才能影响 PnL。
- 不实施实时 Metadata Monitor、Issuer Event Alert、信用评分或法律意见。
- 本日没有 RPC Request、Wallet Access、签名或广播交易。

## 下一步

- Day 13 对一个 Same-chain Candidate 构建 Unsigned Transaction，并保存指定 Block State 下的
  Simulation Evidence；没有 Simulation Evidence 不可标记为 Executable / Paper-ready。
