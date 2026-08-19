"""Tests for Day 15 hypothesis ranking and evaluation scorecard."""

from decimal import Decimal
import pytest

from onchain_arb.ranking import (
    SCORECARD_WEIGHTS,
    TOTAL_WEIGHT,
    DimensionScore,
    HypothesisEvaluation,
    HypothesisId,
    HypothesisRankingScorecard,
    RankingVerdict,
    build_day15_ranking_scorecard,
)


def test_scorecard_weights_sum_to_100() -> None:
    assert TOTAL_WEIGHT == Decimal("100")
    assert len(SCORECARD_WEIGHTS) == 7
    assert SCORECARD_WEIGHTS["conservative_net_edge"] == Decimal("25")
    assert SCORECARD_WEIGHTS["lifetime_vs_latency"] == Decimal("20")
    assert SCORECARD_WEIGHTS["capital_efficiency"] == Decimal("15")
    assert SCORECARD_WEIGHTS["infrastructure_fit"] == Decimal("15")
    assert SCORECARD_WEIGHTS["ability_to_lock_profit"] == Decimal("10")
    assert SCORECARD_WEIGHTS["data_quality"] == Decimal("10")
    assert SCORECARD_WEIGHTS["operational_tail_risk"] == Decimal("5")


def test_day15_scorecard_construction() -> None:
    scorecard = build_day15_ranking_scorecard()
    assert isinstance(scorecard, HypothesisRankingScorecard)
    assert len(scorecard.evaluations) == 3

    # Primary must be H1
    assert scorecard.primary.hypothesis_id is HypothesisId.H1_CROSS_CHAIN_INVENTORY
    assert scorecard.primary.verdict is RankingVerdict.PRIMARY
    assert scorecard.primary.total_score == Decimal("75")

    # Backup must be H2
    assert scorecard.backup.hypothesis_id is HypothesisId.H2_SAME_CHAIN_BASELINE
    assert scorecard.backup.verdict is RankingVerdict.BACKUP
    assert scorecard.backup.total_score == Decimal("51")

    # Killed must contain H3
    assert len(scorecard.killed) == 1
    assert scorecard.killed[0].hypothesis_id is HypothesisId.H3_ROUTE_DISPERSION
    assert scorecard.killed[0].verdict is RankingVerdict.KILL
    assert scorecard.killed[0].total_score == Decimal("26")


def test_day15_ranking_order() -> None:
    scorecard = build_day15_ranking_scorecard()
    ranked = scorecard.ranked_evaluations
    assert len(ranked) == 3
    assert ranked[0].hypothesis_id is HypothesisId.H1_CROSS_CHAIN_INVENTORY
    assert ranked[1].hypothesis_id is HypothesisId.H2_SAME_CHAIN_BASELINE
    assert ranked[2].hypothesis_id is HypothesisId.H3_ROUTE_DISPERSION

    # Scores must be strictly descending
    assert ranked[0].total_score > ranked[1].total_score > ranked[2].total_score


def test_dimension_score_validation() -> None:
    # Invalid key
    with pytest.raises(ValueError, match="Unknown dimension_key"):
        DimensionScore(
            dimension_key="invalid_dim",
            dimension_name="Invalid",
            weight=Decimal("25"),
            score=Decimal("20"),
            justification="Test",
            evidence_refs=("ref1",),
        )

    # Score exceeds weight
    with pytest.raises(ValueError, match="score must be between 0 and 25"):
        DimensionScore(
            dimension_key="conservative_net_edge",
            dimension_name="Net Edge",
            weight=Decimal("25"),
            score=Decimal("26"),
            justification="Test",
            evidence_refs=("ref1",),
        )

    # Negative score
    with pytest.raises(ValueError, match="score must be between 0 and 25"):
        DimensionScore(
            dimension_key="conservative_net_edge",
            dimension_name="Net Edge",
            weight=Decimal("25"),
            score=Decimal("-1"),
            justification="Test",
            evidence_refs=("ref1",),
        )

    # Empty evidence refs
    with pytest.raises(ValueError, match="evidence_refs cannot be empty"):
        DimensionScore(
            dimension_key="conservative_net_edge",
            dimension_name="Net Edge",
            weight=Decimal("25"),
            score=Decimal("20"),
            justification="Test",
            evidence_refs=(),
        )


def test_hypothesis_evaluation_validation() -> None:
    scorecard = build_day15_ranking_scorecard()
    h1 = scorecard.primary

    # Negative sample size
    with pytest.raises(ValueError, match="sample_size must be non-negative"):
        HypothesisEvaluation(
            hypothesis_id=h1.hypothesis_id,
            title=h1.title,
            statement=h1.statement,
            null_hypothesis=h1.null_hypothesis,
            sample_size=-1,
            is_sparse=h1.is_sparse,
            supporting_evidence=h1.supporting_evidence,
            contradictory_evidence=h1.contradictory_evidence,
            unknowns=h1.unknowns,
            dimension_scores=h1.dimension_scores,
            verdict=h1.verdict,
            verdict_rationale=h1.verdict_rationale,
        )


def test_scorecard_verdict_constraints() -> None:
    scorecard = build_day15_ranking_scorecard()
    h1, h2, h3 = scorecard.evaluations

    # Change H3 to PRIMARY -> two PRIMARYs should fail
    h3_duplicate_primary = HypothesisEvaluation(
        hypothesis_id=h3.hypothesis_id,
        title=h3.title,
        statement=h3.statement,
        null_hypothesis=h3.null_hypothesis,
        sample_size=h3.sample_size,
        is_sparse=h3.is_sparse,
        supporting_evidence=h3.supporting_evidence,
        contradictory_evidence=h3.contradictory_evidence,
        unknowns=h3.unknowns,
        dimension_scores=h3.dimension_scores,
        verdict=RankingVerdict.PRIMARY,
        verdict_rationale="Test",
    )

    with pytest.raises(ValueError, match="must have exactly one PRIMARY"):
        HypothesisRankingScorecard(evaluations=(h1, h2, h3_duplicate_primary))
