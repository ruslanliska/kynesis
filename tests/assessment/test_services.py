from app.assessment.schemas import Scorecard, ScorecardCriterion
from app.assessment.services import AICriterionOutput, calculate_weighted_score


def _c(criterion_id: str, score: float) -> AICriterionOutput:
    """Shorthand to create AICriterionOutput for score calculation tests."""
    return AICriterionOutput(
        criterion_id=criterion_id, score=score, comment="",
        evidence=["test"], reasoning="test",
    )


def _make_scorecard() -> Scorecard:
    return Scorecard(
        id="sc-1",
        name="Test",
        criteria=[
            ScorecardCriterion(id="c1", name="A", description="", weight=3, max_score=10),
            ScorecardCriterion(id="c2", name="B", description="", weight=2, max_score=10),
        ],
    )


def test_weighted_score_perfect():
    scorecard = _make_scorecard()
    assert calculate_weighted_score([_c("c1", 10), _c("c2", 10)], scorecard) == 100.0


def test_weighted_score_zero():
    scorecard = _make_scorecard()
    assert calculate_weighted_score([_c("c1", 0), _c("c2", 0)], scorecard) == 0.0


def test_weighted_score_mixed():
    scorecard = _make_scorecard()
    # c1: 10/10 * 3 = 3.0, c2: 5/10 * 2 = 1.0 → 4.0/5 * 100 = 80.0
    assert calculate_weighted_score([_c("c1", 10), _c("c2", 5)], scorecard) == 80.0


def test_weighted_score_rounding():
    scorecard = Scorecard(
        id="sc-1",
        name="Test",
        criteria=[
            ScorecardCriterion(id="c1", name="A", description="", weight=3, max_score=10),
            ScorecardCriterion(id="c2", name="B", description="", weight=3, max_score=10),
            ScorecardCriterion(id="c3", name="C", description="", weight=3, max_score=10),
        ],
    )
    # 7/10*3 + 8/10*3 + 6/10*3 = 2.1+2.4+1.8 = 6.3 → 6.3/9*100 = 70.0
    assert calculate_weighted_score([_c("c1", 7), _c("c2", 8), _c("c3", 6)], scorecard) == 70.0


def test_weighted_score_single_criterion():
    scorecard = Scorecard(
        id="sc-1",
        name="Test",
        criteria=[
            ScorecardCriterion(id="c1", name="A", description="", weight=1, max_score=10),
        ],
    )
    assert calculate_weighted_score([_c("c1", 7)], scorecard) == 70.0
