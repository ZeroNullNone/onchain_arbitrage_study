"""Hypothesis ranking and scorecard evaluation models for Day 15."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum


class HypothesisId(StrEnum):
    """The three formal research hypotheses evaluated in Day 15."""

    H1_CROSS_CHAIN_INVENTORY = "H1_CROSS_CHAIN_INVENTORY"
    H2_SAME_CHAIN_BASELINE = "H2_SAME_CHAIN_BASELINE"
    H3_ROUTE_DISPERSION = "H3_ROUTE_DISPERSION"


class RankingVerdict(StrEnum):
    """Evaluation verdict for a hypothesis."""

    PRIMARY = "PRIMARY"
    BACKUP = "BACKUP"
    KILL = "KILL"


SCORECARD_WEIGHTS: dict[str, Decimal] = {
    "conservative_net_edge": Decimal("25"),
    "lifetime_vs_latency": Decimal("20"),
    "capital_efficiency": Decimal("15"),
    "infrastructure_fit": Decimal("15"),
    "ability_to_lock_profit": Decimal("10"),
    "data_quality": Decimal("10"),
    "operational_tail_risk": Decimal("5"),
}

TOTAL_WEIGHT: Decimal = sum(SCORECARD_WEIGHTS.values())  # Decimal("100")


@dataclass(frozen=True, slots=True)
class DimensionScore:
    """Individual scorecard dimension score with evidence references and justification."""

    dimension_key: str
    dimension_name: str
    weight: Decimal
    score: Decimal
    justification: str
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.dimension_key not in SCORECARD_WEIGHTS:
            raise ValueError(f"Unknown dimension_key: {self.dimension_key}")
        if not isinstance(self.weight, Decimal) or not self.weight.is_finite():
            raise TypeError("weight must be a finite Decimal")
        if self.weight != SCORECARD_WEIGHTS[self.dimension_key]:
            raise ValueError(
                f"weight for {self.dimension_key} must be {SCORECARD_WEIGHTS[self.dimension_key]}, got {self.weight}"
            )
        if not isinstance(self.score, Decimal) or not self.score.is_finite():
            raise TypeError("score must be a finite Decimal")
        if self.score < 0 or self.score > self.weight:
            raise ValueError(f"score must be between 0 and {self.weight}, got {self.score}")
        if not self.justification.strip():
            raise ValueError("justification is required")
        if not self.evidence_refs:
            raise ValueError("evidence_refs cannot be empty")


@dataclass(frozen=True, slots=True)
class HypothesisEvaluation:
    """Comprehensive evaluation record for a single hypothesis."""

    hypothesis_id: HypothesisId
    title: str
    statement: str
    null_hypothesis: str
    sample_size: int
    is_sparse: bool
    supporting_evidence: tuple[str, ...]
    contradictory_evidence: tuple[str, ...]
    unknowns: tuple[str, ...]
    dimension_scores: tuple[DimensionScore, ...]
    verdict: RankingVerdict
    verdict_rationale: str

    def __post_init__(self) -> None:
        if not isinstance(self.hypothesis_id, HypothesisId):
            raise TypeError("hypothesis_id must be a HypothesisId enum")
        if not self.title.strip():
            raise ValueError("title is required")
        if not self.statement.strip():
            raise ValueError("statement is required")
        if not self.null_hypothesis.strip():
            raise ValueError("null_hypothesis is required")
        if self.sample_size < 0:
            raise ValueError("sample_size must be non-negative")
        if not self.supporting_evidence:
            raise ValueError("supporting_evidence cannot be empty")
        if not self.contradictory_evidence:
            raise ValueError("contradictory_evidence cannot be empty")
        if not self.unknowns:
            raise ValueError("unknowns cannot be empty")
        if not self.verdict_rationale.strip():
            raise ValueError("verdict_rationale is required")

        expected_keys = set(SCORECARD_WEIGHTS.keys())
        scored_keys = {ds.dimension_key for ds in self.dimension_scores}
        if scored_keys != expected_keys:
            raise ValueError(f"dimension_scores must cover all {len(expected_keys)} dimensions exactly")

    @property
    def total_score(self) -> Decimal:
        return sum(ds.score for ds in self.dimension_scores)


@dataclass(frozen=True, slots=True)
class HypothesisRankingScorecard:
    """The full Day 15 hypothesis ranking and evaluation scorecard."""

    evaluations: tuple[HypothesisEvaluation, ...]

    def __post_init__(self) -> None:
        if len(self.evaluations) != len(HypothesisId):
            raise ValueError(f"Scorecard must contain exactly {len(HypothesisId)} evaluations")

        eval_ids = {e.hypothesis_id for e in self.evaluations}
        if eval_ids != set(HypothesisId):
            raise ValueError("Scorecard must evaluate all known hypotheses")

        # Validate verdicts: exactly 1 primary, 1 backup, and at least 1 kill
        verdicts = [e.verdict for e in self.evaluations]
        if verdicts.count(RankingVerdict.PRIMARY) != 1:
            raise ValueError("Scorecard must have exactly one PRIMARY hypothesis")
        if verdicts.count(RankingVerdict.BACKUP) != 1:
            raise ValueError("Scorecard must have exactly one BACKUP hypothesis")
        if verdicts.count(RankingVerdict.KILL) < 1:
            raise ValueError("Scorecard must KILL at least one hypothesis")

    @property
    def ranked_evaluations(self) -> tuple[HypothesisEvaluation, ...]:
        """Return evaluations sorted in descending order of total score."""
        return tuple(sorted(self.evaluations, key=lambda e: e.total_score, reverse=True))

    @property
    def primary(self) -> HypothesisEvaluation:
        for e in self.evaluations:
            if e.verdict is RankingVerdict.PRIMARY:
                return e
        raise RuntimeError("No primary hypothesis found")

    @property
    def backup(self) -> HypothesisEvaluation:
        for e in self.evaluations:
            if e.verdict is RankingVerdict.BACKUP:
                return e
        raise RuntimeError("No backup hypothesis found")

    @property
    def killed(self) -> tuple[HypothesisEvaluation, ...]:
        return tuple(e for e in self.evaluations if e.verdict is RankingVerdict.KILL)


def build_day15_ranking_scorecard() -> HypothesisRankingScorecard:
    """Construct the definitive, evidence-linked Day 15 ranking scorecard."""
    h1_scores = (
        DimensionScore(
            dimension_key="conservative_net_edge",
            dimension_name="Conservative Net-edge Evidence",
            weight=Decimal("25"),
            score=Decimal("18"),
            justification=(
                "Day 10/11 models demonstrate positive Cycle PnL (+2 USDC at 100 size, +1 USDC at 500 size "
                "under threshold/batch policies) after accounting for conservative minimum outputs and amortized "
                "rebalance costs. However, edge is thin (20 bps at 500 USDC) and capacity is bounded "
                "(becomes negative at 1,000 USDC)."
            ),
            evidence_refs=(
                "docs/day10_inventory_model.md#L58-L73",
                "docs/day11_rebalance.md#L47-L58",
                "docs/day11_rebalance.md#L80-L88",
                "tests/fixtures/day11/rebalance_costs.json",
            ),
        ),
        DimensionScore(
            dimension_key="lifetime_vs_latency",
            dimension_name="Lifetime vs Decision Latency",
            weight=Decimal("20"),
            score=Decimal("16"),
            justification=(
                "Cross-chain price dislocations between L2s persist over multiple seconds to minutes, "
                "comfortably accommodating the Python scanner's measured 400ms-1000ms decision latency."
            ),
            evidence_refs=(
                "docs/day10_inventory_model.md#L40-L43",
                "docs/day14_scanner.md#L59-L62",
                "src/onchain_arb/inventory.py",
            ),
        ),
        DimensionScore(
            dimension_key="capital_efficiency",
            dimension_name="Capital Efficiency",
            weight=Decimal("15"),
            score=Decimal("9"),
            justification=(
                "Requires maintaining pre-positioned inventory across Base and Arbitrum ($8,000 capital band "
                "for $500 trade sizes). Capital-hour return is moderate (3.125 bps/hour in Day 10 model) "
                "due to idle balance requirements."
            ),
            evidence_refs=(
                "docs/day10_inventory_model.md#L21-L30",
                "docs/day10_inventory_model.md#L67-L73",
                "config/inventory.toml",
            ),
        ),
        DimensionScore(
            dimension_key="infrastructure_fit",
            dimension_name="Infrastructure Fit",
            weight=Decimal("15"),
            score=Decimal("14"),
            justification=(
                "Excellent fit with the read-only / simulation research stack. Does not require sub-millisecond "
                "MEV builder bundles or mempool searchers. The async Python collector, cost ledger, and virtual "
                "inventory balance sheet provide full support."
            ),
            evidence_refs=(
                "src/onchain_arb/inventory.py",
                "src/onchain_arb/scanner.py",
                "docs/system_design.md",
            ),
        ),
        DimensionScore(
            dimension_key="ability_to_lock_profit",
            dimension_name="Ability to Lock Profit",
            weight=Decimal("10"),
            score=Decimal("7"),
            justification=(
                "Conditionally lockable through near-simultaneous dual-leg execution without bridge transit latency. "
                "Lacks atomic multi-chain rollback (one leg may execute while the other fails), but risk is bounded "
                "by fresh independent re-quotes and inventory limits."
            ),
            evidence_refs=(
                "docs/research_charter.md#L81-L93",
                "docs/day10_inventory_model.md#L81-L94",
                "src/onchain_arb/costs.py",
            ),
        ),
        DimensionScore(
            dimension_key="data_quality",
            dimension_name="Data Quality",
            weight=Decimal("10"),
            score=Decimal("8"),
            justification=(
                "100% cost completeness and raw reference coverage. Token identity verified via contract addresses "
                "in frozen registry (Day 12). Integer raw units and Decimal accounting prevent floating point inaccuracies."
            ),
            evidence_refs=(
                "docs/day12_token_risk.md",
                "config/token_registry.toml",
                "docs/week_1_report.md",
            ),
        ),
        DimensionScore(
            dimension_key="operational_tail_risk",
            dimension_name="Operational Tail Risk",
            weight=Decimal("5"),
            score=Decimal("3"),
            justification=(
                "Exposed to token basis risk (Arbitrum bridged WETH dependency, Circle USDC pause/blacklist capability "
                "from Day 12 registry) and inventory imbalance drift during batch intervals."
            ),
            evidence_refs=(
                "docs/day12_token_risk.md#L8-L24",
                "docs/day11_rebalance.md#L60-L74",
                "config/token_registry.toml",
            ),
        ),
    )

    h1_eval = HypothesisEvaluation(
        hypothesis_id=HypothesisId.H1_CROSS_CHAIN_INVENTORY,
        title="H1: Cross-chain Pre-positioned Inventory Arbitrage",
        statement=(
            "Quoted price dislocations between liquid L2 pairs (Arbitrum, Base, Optimism USDC/WETH) "
            "can be captured via pre-positioned dual-chain inventory without bridge settlement latency, "
            "yielding strictly positive Cycle PnL after conservative minimum output and amortized rebalance costs."
        ),
        null_hypothesis=(
            "Cross-chain price dislocations disappear upon independent dual-leg re-quotes, or total cycle rebalancing "
            "and capital costs exceed gross spreads, yielding non-positive Cycle PnL."
        ),
        sample_size=24,
        is_sparse=True,
        supporting_evidence=(
            "Day 10 virtual balance sheet conservation proves dual-leg profit locking without bridge latency.",
            "Day 11 Threshold (+2 USDC) and Batch (+4 USDC) policies demonstrate positive Cycle PnL up to 500 USDC capacity.",
            "Day 14 Scanner v1 successfully routes cross-chain candidates through complete cost and inventory gates.",
        ),
        contradictory_evidence=(
            "Day 11 Immediate policy demonstrates local Trade PnL (+5 USDC) turns into negative Cycle PnL (-8 USDC).",
            "Capacity is bounded: 1,000 USDC trade size yields negative Cycle PnL (-20 bps).",
            "Requires substantial capital allocation ($8,000 inventory band for $500 trade sizes) and carries basis risk.",
        ),
        unknowns=(
            "Optimal rebalance frequency under non-stationary volatility and gas spikes.",
            "True cross-chain execution asymmetry under live network congestion.",
            "Natural order-flow netting probability across longer continuous observation windows.",
        ),
        dimension_scores=h1_scores,
        verdict=RankingVerdict.PRIMARY,
        verdict_rationale=(
            "H1 is the only hypothesis demonstrating viable net positive economics (75/100) within the Python "
            "research infrastructure. It advances to Day 16 as the PRIMARY strategy specification, with strict "
            "entry buffers, inventory limits, and threshold rebalance rules."
        ),
    )

    h2_scores = (
        DimensionScore(
            dimension_key="conservative_net_edge",
            dimension_name="Conservative Net-edge Evidence",
            weight=Decimal("25"),
            score=Decimal("5"),
            justification=(
                "Day 8 baseline and Day 14 scanner results show 0% net-positive survival rate. Gross spreads on public "
                "DEX pairs are entirely consumed by pool fees, approval costs, gas, and minimum-output haircuts."
            ),
            evidence_refs=(
                "docs/day08_baseline.md#L31-L49",
                "docs/day14_scanner.md#L40-L48",
                "tests/fixtures/day08/edge_disappears.json",
            ),
        ),
        DimensionScore(
            dimension_key="lifetime_vs_latency",
            dimension_name="Lifetime vs Decision Latency",
            weight=Decimal("20"),
            score=Decimal("3"),
            justification=(
                "Same-chain DEX dislocations on liquid pairs vanish in sub-second timeframes (<50ms) due to atomic "
                "MEV searchers and block builder integration. Python pipeline latency (300ms-1000ms) is too slow."
            ),
            evidence_refs=(
                "docs/day08_baseline.md#L13-L28",
                "docs/opportunity_taxonomy.md#L11",
            ),
        ),
        DimensionScore(
            dimension_key="capital_efficiency",
            dimension_name="Capital Efficiency",
            weight=Decimal("15"),
            score=Decimal("13"),
            justification=(
                "High capital efficiency because all funds reside on a single chain and are recycled immediately "
                "within the same transaction or block."
            ),
            evidence_refs=(
                "docs/opportunity_taxonomy.md#L11",
                "src/onchain_arb/detectors/same_chain.py",
            ),
        ),
        DimensionScore(
            dimension_key="infrastructure_fit",
            dimension_name="Infrastructure Fit",
            weight=Decimal("15"),
            score=Decimal("8"),
            justification=(
                "Simulation tools (`eth_call` in Day 13) are fully functional, but competitive infrastructure "
                "(private builder endpoints, Rust execution engine, direct mempool feeds) is out of project scope."
            ),
            evidence_refs=(
                "docs/day13_simulation.md",
                "src/onchain_arb/simulation.py",
            ),
        ),
        DimensionScore(
            dimension_key="ability_to_lock_profit",
            dimension_name="Ability to Lock Profit",
            weight=Decimal("10"),
            score=Decimal("9"),
            justification=(
                "High potential atomicity within a single transaction router contract; failures revert completely "
                "without residual inventory displacement."
            ),
            evidence_refs=(
                "docs/opportunity_taxonomy.md#L11",
                "docs/day13_simulation.md#L15-L20",
            ),
        ),
        DimensionScore(
            dimension_key="data_quality",
            dimension_name="Data Quality",
            weight=Decimal("10"),
            score=Decimal("9"),
            justification=(
                "High precision and exact pool math (Day 3 AMM executable pricing), pinned RPC block contexts, "
                "and full fixture reproducibility."
            ),
            evidence_refs=(
                "docs/daily/day_03.md",
                "tests/fixtures/amm/base_aerodrome_weth_usdc_block_49641814.json",
                "src/onchain_arb/amm.py",
            ),
        ),
        DimensionScore(
            dimension_key="operational_tail_risk",
            dimension_name="Operational Tail Risk",
            weight=Decimal("5"),
            score=Decimal("4"),
            justification=(
                "Low cross-chain exposure and zero bridge risk. Primary risk is unrecoverable gas spent on reverted transactions."
            ),
            evidence_refs=(
                "docs/day13_simulation.md#L24-L29",
                "docs/opportunity_taxonomy.md#L11",
            ),
        ),
    )

    h2_eval = HypothesisEvaluation(
        hypothesis_id=HypothesisId.H2_SAME_CHAIN_BASELINE,
        title="H2: Same-chain DEX–DEX Public Round-Trip Baseline",
        statement=(
            "Public quoted spreads between DEXs on the same chain (e.g. Aerodrome vs Uniswap V3 on Base) "
            "disappear after conservative minimum output, gas, swap fees, approval, and transaction simulation."
        ),
        null_hypothesis=(
            "Public same-chain DEX–DEX spreads on liquid pairs do not offer positive net edge after execution costs "
            "when accessed by non-MEV public RPC clients."
        ),
        sample_size=33,
        is_sparse=False,
        supporting_evidence=(
            "Day 8 scanner showed 3 gross candidates resulting in 0 net-positive survivors.",
            "Day 13 simulation tests verified that gas and allowance constraints reliably eliminate borderline spreads.",
            "Day 14 Scanner v1 rejects 100% of public same-chain candidates at re-quote or cost ledger gates.",
        ),
        contradictory_evidence=(
            "Under severe market dislocations or illiquid long-tail pairs, gross spreads may temporarily exceed L2 gas.",
        ),
        unknowns=(
            "Private transaction submission (Flashbots/Builder bundles) latency advantage on Base/Arbitrum.",
        ),
        dimension_scores=h2_scores,
        verdict=RankingVerdict.BACKUP,
        verdict_rationale=(
            "H2 is confirmed by data as an effective negative control baseline (51/100). It is retained as BACKUP "
            "(reference benchmark and simulation testbed), proving the system's ability to reliably reject false opportunities."
        ),
    )

    h3_scores = (
        DimensionScore(
            dimension_key="conservative_net_edge",
            dimension_name="Conservative Net-edge Evidence",
            weight=Decimal("25"),
            score=Decimal("3"),
            justification=(
                "Day 9 route dispersion analysis proved that observed route price differences reflect routing improvements, "
                "observation timestamp gaps (e.g. 98,225s), or temporary subsidies, not tradable arbitrage. "
                "Net edge after bridge fees (0.25%-1%) and aggregator cuts (25 bps) is systematically negative."
            ),
            evidence_refs=(
                "docs/day09_route_dispersion.md#L25-L45",
                "docs/day09_route_dispersion.md#L48-L63",
            ),
        ),
        DimensionScore(
            dimension_key="lifetime_vs_latency",
            dimension_name="Lifetime vs Decision Latency",
            weight=Decimal("20"),
            score=Decimal("4"),
            justification=(
                "Aggregator route quotes are dynamic and bridge settlement times (10-30+ minutes) completely decouple "
                "quoted output from final delivered output."
            ),
            evidence_refs=(
                "docs/day09_route_dispersion.md#L36-L45",
                "docs/opportunity_taxonomy.md#L13",
            ),
        ),
        DimensionScore(
            dimension_key="capital_efficiency",
            dimension_name="Capital Efficiency",
            weight=Decimal("15"),
            score=Decimal("4"),
            justification=(
                "Poor capital efficiency. Funds are locked in-transit during cross-chain bridging, accumulating opportunity "
                "costs with no interim yield or recycling ability."
            ),
            evidence_refs=(
                "docs/opportunity_taxonomy.md#L13",
            ),
        ),
        DimensionScore(
            dimension_key="infrastructure_fit",
            dimension_name="Infrastructure Fit",
            weight=Decimal("15"),
            score=Decimal("6"),
            justification=(
                "LI.FI API probe and collector are operational, but aggregator APIs are designed for user routing rather "
                "than low-latency arbitrage execution."
            ),
            evidence_refs=(
                "docs/daily/day_04.md",
                "docs/daily/day_05.md",
            ),
        ),
        DimensionScore(
            dimension_key="ability_to_lock_profit",
            dimension_name="Ability to Lock Profit",
            weight=Decimal("10"),
            score=Decimal("1"),
            justification=(
                "Zero profit locking capability. Non-atomic bridging subjects the capital to destination asset price volatility "
                "and bridge relayer execution delay."
            ),
            evidence_refs=(
                "docs/day09_route_dispersion.md#L52-L63",
                "docs/opportunity_taxonomy.md#L13",
            ),
        ),
        DimensionScore(
            dimension_key="data_quality",
            dimension_name="Data Quality",
            weight=Decimal("10"),
            score=Decimal("7"),
            justification=(
                "Raw API requests/responses are cleanly preserved, but bridge duration and fee estimates are non-deterministic."
            ),
            evidence_refs=(
                "docs/schema/lifi_quote.md",
                "docs/day09_route_dispersion.md#L36-L45",
            ),
        ),
        DimensionScore(
            dimension_key="operational_tail_risk",
            dimension_name="Operational Tail Risk",
            weight=Decimal("5"),
            score=Decimal("1"),
            justification=(
                "Severe operational tail risk: bridge smart contract vulnerabilities, stuck funds in relayers, and unexpected "
                "slippage on destination chains."
            ),
            evidence_refs=(
                "docs/opportunity_taxonomy.md#L13",
                "docs/day12_token_risk.md#L14-L24",
            ),
        ),
    )

    h3_eval = HypothesisEvaluation(
        hypothesis_id=HypothesisId.H3_ROUTE_DISPERSION,
        title="H3: Cross-chain Aggregator Route Dispersion as Standalone Arbitrage",
        statement=(
            "Price and route dispersion reported across cross-chain aggregators (e.g. LI.FI) represent executable "
            "arbitrage opportunities that can be captured via direct sequential bridging."
        ),
        null_hypothesis=(
            "Aggregator route dispersion reflects provider heuristics, temporary subsidies, and bridge delays, "
            "and cannot produce executable arbitrage profit after bridge fees, delays, and destination slippage."
        ),
        sample_size=18,
        is_sparse=False,
        supporting_evidence=(
            "Aggregator route probes provide valuable visibility into provider market shares and fee tiers.",
        ),
        contradictory_evidence=(
            "Day 9 route dispersion classified 100% of candidate comparisons as 'stale_quote' or 'routing_improvement'.",
            "Bridge transit latency (10-30 minutes) exposes transactions to unhedgeable market drift.",
            "Aggregator and bridge fees (25-100 bps) consistently exceed observed gross dispersion.",
        ),
        unknowns=(
            "Frequency of relayer delays and bridge slippage during extreme network volatility.",
        ),
        dimension_scores=h3_scores,
        verdict=RankingVerdict.KILL,
        verdict_rationale=(
            "H3 is conclusively refuted by evidence and scored lowest (26/100). Aggregator route dispersion is "
            "FORMALLY KILLED as an arbitrage hypothesis. It is retained solely as a read-only analytics feed."
        ),
    )

    return HypothesisRankingScorecard(evaluations=(h1_eval, h2_eval, h3_eval))
