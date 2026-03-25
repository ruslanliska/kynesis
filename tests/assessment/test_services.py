from app.assessment.schemas import Scorecard, ScorecardCriterion
from app.assessment.services import AICriterionOutput, calculate_weighted_score


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
    ai_criteria = [
        AICriterionOutput(criterion_id="c1", score=10, comment=""),
        AICriterionOutput(criterion_id="c2", score=10, comment=""),
    ]
    assert calculate_weighted_score(ai_criteria, scorecard) == 100.0


def test_weighted_score_zero():
    scorecard = _make_scorecard()
    ai_criteria = [
        AICriterionOutput(criterion_id="c1", score=0, comment=""),
        AICriterionOutput(criterion_id="c2", score=0, comment=""),
    ]
    assert calculate_weighted_score(ai_criteria, scorecard) == 0.0


def test_weighted_score_mixed():
    scorecard = _make_scorecard()
    # c1: 10/10 * 3 = 3.0, c2: 5/10 * 2 = 1.0 → 4.0/5 * 100 = 80.0
    ai_criteria = [
        AICriterionOutput(criterion_id="c1", score=10, comment=""),
        AICriterionOutput(criterion_id="c2", score=5, comment=""),
    ]
    assert calculate_weighted_score(ai_criteria, scorecard) == 80.0


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
    # 7/10*3 + 8/10*3 + 6/10*3 = 2.1 + 2.4 + 1.8 = 6.3 → 6.3/9 * 100 = 70.0
    ai_criteria = [
        AICriterionOutput(criterion_id="c1", score=7, comment=""),
        AICriterionOutput(criterion_id="c2", score=8, comment=""),
        AICriterionOutput(criterion_id="c3", score=6, comment=""),
    ]
    assert calculate_weighted_score(ai_criteria, scorecard) == 70.0


def test_weighted_score_empty_weights():
    scorecard = Scorecard(
        id="sc-1",
        name="Test",
        criteria=[
            ScorecardCriterion(id="c1", name="A", description="", weight=1, max_score=10),
        ],
    )
    # Degenerate: single criterion with weight=1 → score/max * 100
    ai_criteria = [
        AICriterionOutput(criterion_id="c1", score=7, comment=""),
    ]
    assert calculate_weighted_score(ai_criteria, scorecard) == 70.0
