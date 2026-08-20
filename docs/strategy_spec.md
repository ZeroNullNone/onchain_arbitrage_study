# Primary Strategy Specification (H1: Cross-Chain Pre-Positioned Inventory Arbitrage)

> **Document Version**: 1.0.0  
> **Reviewed Date**: 2026-08-17 (UTC)  
> **Operating Mode**: Simulation-only / Paper-only / Read-only (Strictly NO Live Signing or Broadcast)  
> **Status**: Frozen for Day 16–21 Research Loop  
> **Configuration Source**: [`config/strategy.toml`](../config/strategy.toml)  
> **Token Registry Reference**: [`config/token_registry.toml`](../config/token_registry.toml)  
> **Inventory Policy Reference**: [`config/inventory.toml`](../config/inventory.toml)

---

## 1. 策略概述与研究定位

本策略规范定义了 **H1（跨链预置库存套利）** 的完整无歧义执行规则、准入门限、资本占用与熔断守卫。

在 Day 15 的系统性假设评分中，H1 获得 **75 / 100** 的最高评分，被确立为本项目唯一的主策略（Primary Strategy）。本规范的设计目标是使**任何第三方量化研究员或工程师仅阅读本文档即可完全复现相同的 Accept / Reject 决策逻辑**，杜绝任何隐式假设、魔法数字或未量化缓冲区。

### 1.1 核心机制

- **双边预置库存**：在两条低费率 EVM L2（Base 与 Arbitrum One）上预先配置稳定币（USDC）与基础资产（WETH）库存。
- **无桥接准同步执行**：当检测到两条链存在定价偏差时，在便宜链买入资产、在昂贵链卖出资产。两笔交易在本地并发执行，**不等待跨链桥确认**，将交易风险从“跨链桥延迟波动”转化为“双边执行时延偏差与资产负债表再平衡成本管理”。
- **单向闭环与利润锁定**：利润以会计结算稳定币（USDC）形式锁定在资产负债表内；累积单边库存漂移通过定期（阈值触发）桥接批量再平衡（Rebalance）恢复。

### 1.2 辅助基准策略（H2: Backup / Negative Control Baseline）

- **策略 ID**：`H2_SAME_CHAIN_BASELINE`
- **定位**：同链 DEX–DEX 公开往返套利（Base: Aerodrome ↔ Uniswap v3）。
- **角色**：作为**只读负对照基准**保留，用于持续审计链上 Gas 模型、仿真执行器与拒绝漏斗有效性，证明在非 MEV Builder 架构下公开同链价差绝大部分在滑点与 Gas 后归零。

---

## 2. 标的资产与严格代币身份（Universe & Token Identity）

在任何阶段严禁仅凭代币代码（Symbol）进行资产等价性判定。代币唯一身份严格由 `(chain_id, contract_address)` 元组决定（地址统一采用 20 字节小写十六进制）。

### 2.1 链与资产范围

- **活跃链**：
  - Base (`chain_id = 8453`)
  - Arbitrum One (`chain_id = 42161`)
- **会计结算资产（Stable Asset）**：USDC（6 位小数）
- **交易标的资产（Trade Asset）**：WETH（18 位小数）

### 2.2 代币映射与注册表约束

| Chain Name | Chain ID | Contract Address | Symbol (Display Only) | Decimals | Classification | Haircut (bps) |
|---|---|---|---|---|---|---|
| Base | 8453 | `0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913` | USDC | 6 | Canonical | 25 bps |
| Base | 8453 | `0x4200000000000000000000000000000000000006` | WETH | 18 | Wrapped (WETH9) | 5 bps |
| Arbitrum | 42161 | `0xaf88d065e77c8cC2239327C5EDb3A432268e5831` | USDC | 6 | Canonical | 25 bps |
| Arbitrum | 42161 | `0x82aF49447D8a07e3bd95BD0d56f35241523fBab1` | WETH | 18 | Bridged (Canonical Bridge) | 50 bps |

*规则*：若注册表标记 `excluded = true`，或代币身份不在上述白名单内，必须立即拒绝并发出 `token_excluded` 或 `token_identity_mismatch`。

---

## 3. 信号定义与条件锁定时点（Signal Formula & Locking）

### 3.1 交易腿（Legs）配对

一笔有效的跨链信号必须包含两笔独立的、在不同链上执行的本地交易腿：

1. **便宜链买入腿（Cheap Chain Buy Leg）**：
   - 链：$Chain_{cheap}$
   - 输入：$TargetSize_{USDC}$（稳定币精确输入）
   - 输出：$GuaranteedOutput_{WETH}$（保证最低 WETH 输出，即 `toAmountMin`）
2. **昂贵链卖出腿（Expensive Chain Sell Leg）**：
   - 链：$Chain_{expensive} \neq Chain_{cheap}$
   - 输入：$ExactInput_{WETH} = GuaranteedOutput_{WETH}$（以便宜链保证产出的 WETH 数量精确卖出）
   - 输出：$GuaranteedOutput_{USDC}$（保证最低 USDC 获得数量）

### 3.2 毛利（Gross Edge）计算公式

毛利完全以会计稳定币（USDC）的绝对金额与点子数（bps）衡量，使用不可变整数原始单位与精确 `Decimal`：

$$\Delta GrossRaw = GuaranteedOutput_{USDC}.raw - TargetSize_{USDC}.raw$$

$$GrossEdgeUSD = \frac{\Delta GrossRaw}{10^{6}}$$

$$GrossSpreadBps = \frac{GrossEdgeUSD}{TargetSizeUSD} \times 10,000$$

*硬性约束*：若 $GrossEdgeUSD \le 0$，拒绝原因为 `initial_gross_not_positive`。

### 3.3 条件锁定时点（Condition Locked Instant）

跨链两腿由两个独立异步请求获取，定义信号成立的锁定时点为**较晚到达的合法观察时间点**：

$$t_{locked} = \max(t_{obs}^{buy}, t_{obs}^{sell})$$

任何下游时延（决策时延、重报价时延）的计时起点均以 $t_{locked}$ 为基准。

---

## 4. 报价新鲜度、时钟偏差与独立确认（Freshness & Skew）

1. **最大报价生存期（Max Quote Age）**：
   $$Age_{quote} = t_{eval} - \min(t_{obs}^{buy}, t_{obs}^{sell}) \le 10,000 \text{ ms (10.0 s)}$$
   超出阈值立即拒绝：`quote_stale`。
2. **双腿观察时钟偏差（Leg Observation Skew）**：
   $$Skew_{legs} = |t_{obs}^{buy} - t_{obs}^{sell}| \le 1,000 \text{ ms (1.0 s)}$$
   超出阈值立即拒绝：`leg_observation_skew_exceeded`。
3. **独立确认防碰撞（Independent Confirmation）**：
   - 买入腿与卖出腿的 `request_id` 必须严格相异（$ReqId_{buy} \neq ReqId_{sell}$），否则拒绝：`same_request_id_collision`。
   - 买入腿与卖出腿的 `raw_ref` 必须指向不同存储文件，否则拒绝：`same_raw_ref_collision`。
4. **重报价窗口（Re-quote Window）**：
   - 发现信号后发起即时重报价，重报价观察时间距初始观察时间不得超过 $3,000\text{ ms}$。

---

## 5. 保守产出（Conservative Output）与重报价机制

### 5.1 严禁使用展示产出

所有经济测算与成交判定必须使用 `toAmountMin`（扣除滑点后的最低保证产出），**严禁使用 API 展示的预期产出 `toAmount` 或池子当前现货价格**。

### 5.2 重报价校验规则

重报价（Re-quoted Observation）必须同时满足：

1. 交易对、方向、代币路径与 Venue 保持完全一致；
2. 目标规模（Target Size）保持完全一致；
3. 重报价毛利仍然满足：$GrossEdgeUSD_{requote} > 0$；
4. 若重报价失败或超时，拒绝原因为 `requote_missing`、`requote_gross_not_positive` 或 `requote_minimum_not_positive`。

---

## 6. 成本模型与 Required Edge 准入门限

跨链套利涉及 Gas、审批、跨链时延滑点、再平衡过桥费及经济安全溢价。本策略定义了严格五元分解的 **Required Edge** 门限公式：

### 6.1 Required Edge 核心公式

$$\mathbf{RequiredEdge} = KnownExecutionCost + CostUncertaintyBuffer + LatencyDeteriorationBuffer + RebalanceBuffer + MinEconomicProfit$$

```text
+-----------------------------------------------------------------------------------+
| Required Edge Breakdown (USD)                                                     |
+-----------------------------------------------------------------------------------+
| 1. Known Execution Cost          : 实际已观察 Gas 与授权成本和 (USDC)                |
| 2. Cost Uncertainty Buffer       : max(KnownCost * 20%, $0.10) (应对 Gas 波动)      |
| 3. Latency Deterioration Buffer  : TradeSizeUSD * 10 bps (应对时延价格漂移)           |
| 4. Inventory / Rebalance Buffer  : $0.40 固定单笔摊销 (基于 Day 11 再平衡模型)         |
| 5. Minimum Economic Profit       : $0.50 绝对经济安全底线 (无此利润不开仓)            |
+-----------------------------------------------------------------------------------+
```

### 6.2 缓冲区逐项参数化定义

1. **Known Execution Cost（已知执行成本）**：
   - 便宜链买入 Gas 费 + 昂贵链卖出 Gas 费（换算为 USDC）；
   - 若需要授权（Token Approval），加上对应授权 Gas 费。
2. **Cost Uncertainty Buffer（成本不确定性缓冲）**：
   $$Buffer_{cost} = \max(KnownExecutionCost \times 0.20, \$0.10)$$
   *理由*：L2 序列器（Sequencer）与 L1 数据费（Blob / Calldata）存在微观波动，提供至少 20%（或保底 $0.10）安全边际。
3. **Latency Deterioration Buffer（时延劣变缓冲）**：
   $$Buffer_{latency} = TradeSizeUSD \times \frac{10}{10,000} = TradeSizeUSD \times 0.0010$$
   *理由*：从信号判定到双边并发成交存在 100–500ms 窗口，按 10 bps（0.10%）预留微观价格逆向移动容忍度。
4. **Inventory / Rebalance Buffer（库存再平衡摊销缓冲）**：
   $$Buffer_{rebalance} = \$0.40$$
   *理由*：依据 Day 11 实验数据，跨链 CCTP / 官方桥单次搬砖成本约为 $1.50–$2.00；在 4–5 笔套利后触发一次批量再平衡，单笔分摊成本定为 $0.40。
5. **Minimum Economic Profit（最低经济利润底线）**：
   $$Profit_{min} = \$0.50$$
   *理由*：扣除所有已知与预期成本及摩擦后，单笔套利必须有至少 $0.50 净盈余，以补偿资金锁定与智能合约尾部风险。

### 6.3 准入判定（Acceptance Rule）

$$\mathbf{NetSurplus} = GrossEdgeUSD - RequiredEdge$$

- 若 $\mathbf{NetSurplus} \ge 0$：满足门限，进入库存与资金检查；
- 若 $\mathbf{NetSurplus} < 0$：拒绝开仓，记录拒绝原因 `required_edge_not_met`。

---

## 7. 目标规模与容量限制（Size & Capacity）

| 标称规模（USD） | 便宜链 USDC 输入 ($TargetSize_{USDC}$) | 对应 WETH 数量（参考） | 最大单笔容量 |
|---|---|---|---|
| **$100** | $100,000,000 \text{ raw}$ | $\sim 0.05 \text{ WETH}$ | 单次并发上限 1 笔 |
| **$500** | $500,000,000 \text{ raw}$ | $\sim 0.25 \text{ WETH}$ | 单次并发上限 1 笔 |
| **$1,000** | $1,000,000,000 \text{ raw}$ | $\sim 0.50 \text{ WETH}$ | 单次并发上限 1 笔 |

*约束*：本策略当前仅支持 $100、$500、$1,000 三个标准档位，非标金额拒绝：`unsupported_target_size`。

---

## 8. 虚拟资产负债表与库存带控制（Inventory Bands）

### 8.1 初始库存分布（Initial Balance Sheet）

- **Base (8453)**：
  - USDC: $2,000,000,000 \text{ raw } (\$2,000.00)$
  - WETH: $1,000,000,000,000,000,000 \text{ raw } (1.0 \text{ WETH})$
- **Arbitrum (42161)**：
  - USDC: $2,000,000,000 \text{ raw } (\$2,000.00)$
  - WETH: $1,000,000,000,000,000,000 \text{ raw } (1.0 \text{ WETH})$
- **总资产占用（Capital Occupied）**：$\$4,000 \text{ (USDC)} + 2.0 \text{ WETH} \times \$2,000 = \$8,000.00$

### 8.2 目标库存带与最大偏离度

| 资产 | 目标下界 ($Target_{min}$) | 目标上界 ($Target_{max}$) | 中点 ($Midpoint$) | 最大允许偏离 ($MaxImbalance$) |
|---|---|---|---|---|
| **USDC (单链)** | $1,500 \text{ USDC}$ | $2,500 \text{ USDC}$ | $2,000 \text{ USDC}$ | $\pm 1,500 \text{ USDC}$ (绝对余额 $[500, 3,500]$) |
| **WETH (单链)** | $0.5 \text{ WETH}$ | $1.5 \text{ WETH}$ | $1.0 \text{ WETH}$ | $\pm 1.0 \text{ WETH}$ (绝对余额 $[0.0, 2.0]$) |

### 8.3 开仓前库存检查（Pre-Trade Gate）

在模拟撮合前，必须进行双重检查：

1. **余额充足性**：
   - 便宜链必须有足额 USDC 余额（含 Gas 扣除）：$Balance_{cheap}^{USDC} \ge Input_{USDC} + Gas_{cheap}$；
   - 昂贵链必须有足额 WETH 余额：$Balance_{expensive}^{WETH} \ge Input_{WETH}$。
   - 否则拒绝：`insufficient_balance`。
2. **偏离度守卫**：
   - 开仓成交后的各资产预期余额必须满足：$|Balance_{after} - Midpoint| \le MaxImbalance$；
   - 否则拒绝：`max_imbalance_exceeded` 并标记 `inventory_blocked`。

---

## 9. 再平衡规则（Rebalance Rule）

- **触发策略**：阈值触发（Threshold-based）。
- **触发条件**：任一链上的 USDC 偏离中点 $\ge \$500.00$（或 WETH 偏离 $\ge 0.25\text{ WETH}$）。
- **再平衡操作**：通过虚拟 CCTP 铸销或官方桥，将累积的多余稳定币/资产转移至匮乏链，恢复至中点平衡状态。
- **再平衡计费**：单次再平衡固定计入实际桥费用（Day 11 Fixture 基准），并从周期损益（Cycle PnL）中扣除。

---

## 10. 冷却与去重策略（Cooldown & Deduplication）

- **指纹生成**：
  $$\text{Fingerprint} = \text{cross\_chain}:Chain_{cheap}:Chain_{expensive}:Asset_{stable}:Asset_{trade}:TargetSizeRaw$$
  *示例*：`cross_chain:8453:42161:USDC:WETH:500000000`
- **去重滑动窗口**：$60.0 \text{ 秒}$。
- **行为**：若在 60 秒内检测到具有相同指纹的持续价差信号，仅保留第一笔候选机会，后续机会判定为 `duplicate_opportunity`，防止因同一市场错价连续重入导致虚拟库存被瞬间耗尽。

---

## 11. 完整拒绝原因分类表（Reject Taxonomy）

| 状态阶段 | 错误代码 | 触发场景 |
|---|---|---|
| **Detection** | `unsupported_chain` | 链 ID 不属于配置中的白名单 (8453 / 42161) |
| | `unsupported_asset` | 代币身份不在白名单代币列表中 |
| | `token_identity_mismatch` | 合约地址或链 ID 与白名单不匹配 |
| | `token_excluded` | 代币在 Token Registry 中被标记为排除 |
| | `unsupported_target_size` | 交易规模不在 [100, 500, 1000] USD 中 |
| | `duplicate_opportunity` | 60 秒窗口内已存在相同指纹信号 |
| **Freshness** | `quote_stale` | 报价观察时间距评估时间超过 10,000 ms |
| | `leg_observation_skew_exceeded` | 双腿报价观察时钟偏差超过 1,000 ms |
| **Confirmation** | `same_request_id_collision` | 双腿复用了相同的请求 ID |
| | `same_raw_ref_collision` | 双腿复用了相同的原始响应证据引用 |
| **Economics** | `initial_gross_not_positive` | 保证最低产出低于输入本金 ($GrossEdge \le 0$) |
| | `cost_ledger_incomplete` | 缺少必要的 Gas 或授权费率条目 |
| | `required_edge_not_met` | 毛利未达到 Required Edge（$NetSurplus < 0$） |
| **Inventory** | `insufficient_balance` | 本地库存不足以支付交易输入或 Gas |
| | `max_imbalance_exceeded` | 成交后库存偏离超出最大安全界限 |
| | `inventory_blocked` | 库存不足或偏离导致的综合阻断 |

---

## 12. 虚拟成交假设（Paper Fill Assumptions）

1. **成交价格**：严格按 `toAmountMin` 结算，不假设优于保证底线的任何执行改善。
2. **执行原子性**：双腿视为在本地并发即时成交，不引入链上撮合排队时延。
3. **Gas 扣除**：完全按报价或 RPC 估算的 Gas 实际扣减对应链的稳定币余额。
4. **无签名广播**：全流程绝不调用私钥签名、不广播交易至主网节点。

---

## 13. 策略级熔断指标（Kill Metrics & Circuit Breakers）

当在 Paper 模拟或回放运行中触发以下任一条件时，策略自动进入 **HALTED / KILLED** 状态，停止一切后续虚拟开仓：

1. **连续亏损断路器**：连续 3 笔 Paper Fill 出现事后周期损益为负（$CyclePnL < 0$）；
2. **重报价生存率枯竭**：滚动 50 次扫描中，重报价生存率低于 $10\%$；
3. **库存漂移失控**：任一链的资产偏离中点超过初始库存的 $50\%$ 且未成功触发再平衡；
4. **Gas 暴涨熔断**：L2 Gas 费用上涨超过基线的 $5.0 \times$，导致超过 $95\%$ 的候选信号被阻断；
5. **代币信用风险**：任一底层代币发生合约暂停（Pause）、黑名单（Blacklist）或价格脱锚事件。

---

## 14. Golden Reference Scenarios（手算验证用例）

### 场景 A：$500 档位标准正向机会（Accept -> PAPER_READY）

- **输入条件**：
  - 目标规模：$500.00 \text{ USDC}$
  - 保证最低产出：$503.00 \text{ USDC}$（$\Delta Gross = \$3.00$）
  - 已知执行成本：便宜链 Gas $\$0.40$ + 昂贵链 Gas $\$0.40 = \$0.80$
- **门限推导**：
  - Cost Uncertainty Buffer = $\max(\$0.80 \times 0.20, \$0.10) = \$0.16$
  - Latency Deterioration Buffer = $\$500 \times \frac{10}{10,000} = \$0.50$
  - Inventory Rebalance Buffer = $\$0.40$
  - Minimum Economic Profit = $\$0.50$
  - **Required Edge** = $\$0.80 + \$0.16 + \$0.50 + \$0.40 + \$0.50 = \mathbf{\$2.36}$
- **判定结果**：
  - $\mathbf{NetSurplus} = \$3.00 - \$2.36 = +\$0.64 > 0$
  - 库存充足且无偏离超标。
  - **最终状态**：`PAPER_READY`，`accepted = true`。

### 场景 B：$500 档位微利被门限拦截（Reject -> REQUIRED_EDGE_NOT_MET）

- **输入条件**：
  - 目标规模：$500.00 \text{ USDC}$
  - 保证最低产出：$501.80 \text{ USDC}$（$\Delta Gross = \$1.80$）
  - 已知执行成本：$\$0.80$（同上）
- **门限推导**：
  - Required Edge = $\$2.36$（同上）
- **判定结果**：
  - $\mathbf{NetSurplus} = \$1.80 - \$2.36 = -\$0.56 < 0$
  - 虽然毛利覆盖了已知 Gas（$\$1.80 > \$0.80$），但未达到覆盖不确定性、时延、再平衡与最低利润的 Required Edge。
  - **最终状态**：`REJECTED`，拒绝原因：`required_edge_not_met`。

### 场景 C：$100 档位小额触发成本保底（Accept -> PAPER_READY）

- **输入条件**：
  - 目标规模：$100.00 \text{ USDC}$
  - 保证最低产出：$101.50 \text{ USDC}$（$\Delta Gross = \$1.50$）
  - 已知执行成本：$\$0.30$（两链 Gas 和）
- **门限推导**：
  - Cost Uncertainty Buffer = $\max(\$0.30 \times 0.20 = \$0.06, \mathbf{\$0.10}) = \$0.10$（触发保底）
  - Latency Deterioration Buffer = $\$100 \times 10 \text{ bps} = \$0.10$
  - Inventory Rebalance Buffer = $\$0.40$
  - Minimum Economic Profit = $\$0.50$
  - **Required Edge** = $\$0.30 + \$0.10 + \$0.10 + \$0.40 + \$0.50 = \mathbf{\$1.40}$
- **判定结果**：
  - $\mathbf{NetSurplus} = \$1.50 - \$1.40 = +\$0.10 > 0$
  - **最终状态**：`PAPER_READY`，`accepted = true`。
