from app.assessment.services import AIQuestionOutput, calculate_scores
from app.scorecards.schemas import (
    CriticalType,
    ScorecardDefinition,
    ScorecardOption,
    ScorecardQuestion,
    ScorecardSection,
    ScorecardStatus,
    ScoringType,
)


# --- Helpers ---


def _binary_question(
    qid: str,
    max_points: int,
    critical: CriticalType = CriticalType.none,
) -> ScorecardQuestion:
    return ScorecardQuestion(
        id=qid,
        text=f"Question {qid}",
        description="",
        scoring_type=ScoringType.binary,
        max_points=max_points,
        required=True,
        critical=critical,
        order_index=0,
        options=[
            ScorecardOption(id=f"{qid}-yes", label="Yes", value=1, points_change=max_points, order_index=0),
            ScorecardOption(id=f"{qid}-no", label="No", value=0, points_change=0, order_index=1),
        ],
    )


def _scorecard(
    sections: list[tuple[str, float | None, list[ScorecardQuestion]]],
) -> ScorecardDefinition:
    """Create a ScorecardDefinition from (section_id, weight, questions) tuples."""
    return ScorecardDefinition(
        id="sc-1",
        name="Test",
        status=ScorecardStatus.active,
        sections=[
            ScorecardSection(
                id=sid,
                name=f"Section {sid}",
                description="",
                order_index=i,
                weight=weight,
                questions=questions,
            )
            for i, (sid, weight, questions) in enumerate(sections)
        ],
    )


def _ai_q(question_id: str, selected_option_id: str) -> AIQuestionOutput:
    return AIQuestionOutput(
        question_id=question_id,
        selected_option_id=selected_option_id,
        evidence=["test evidence"],
        reasoning="test reasoning",
        comment="test comment",
    )


# --- Score calculation tests ---


def test_weighted_score_perfect():
    sc = _scorecard([
        ("s1", 60.0, [_binary_question("q1", 10)]),
        ("s2", 40.0, [_binary_question("q2", 10)]),
    ])
    ai = [_ai_q("q1", "q1-yes"), _ai_q("q2", "q2-yes")]
    _, overall, hcf = calculate_scores(ai, sc)
    assert overall == 100.0
    assert hcf is False


def test_weighted_score_zero():
    sc = _scorecard([
        ("s1", 60.0, [_binary_question("q1", 10)]),
        ("s2", 40.0, [_binary_question("q2", 10)]),
    ])
    ai = [_ai_q("q1", "q1-no"), _ai_q("q2", "q2-no")]
    _, overall, _ = calculate_scores(ai, sc)
    assert overall == 0.0


def test_weighted_score_mixed():
    # s1: 10/10 = 100%, weight=60 → 60.0
    # s2: 0/10 = 0%, weight=40 → 0.0
    # overall = 60.0
    sc = _scorecard([
        ("s1", 60.0, [_binary_question("q1", 10)]),
        ("s2", 40.0, [_binary_question("q2", 10)]),
    ])
    ai = [_ai_q("q1", "q1-yes"), _ai_q("q2", "q2-no")]
    _, overall, _ = calculate_scores(ai, sc)
    assert overall == 60.0


def test_equal_weight_sections():
    # No weights defined → mean of section scores
    # s1: 10/10 = 100%, s2: 0/10 = 0% → mean = 50.0
    sc = _scorecard([
        ("s1", None, [_binary_question("q1", 10)]),
        ("s2", None, [_binary_question("q2", 10)]),
    ])
    ai = [_ai_q("q1", "q1-yes"), _ai_q("q2", "q2-no")]
    _, overall, _ = calculate_scores(ai, sc)
    assert overall == 50.0


def test_section_results_scores():
    sc = _scorecard([
        ("s1", 60.0, [_binary_question("q1", 10)]),
        ("s2", 40.0, [_binary_question("q2", 10)]),
    ])
    ai = [_ai_q("q1", "q1-yes"), _ai_q("q2", "q2-no")]
    sections, _, _ = calculate_scores(ai, sc)
    assert sections[0].section_id == "s1"
    assert sections[0].score == 100.0
    assert sections[1].section_id == "s2"
    assert sections[1].score == 0.0


def test_hard_critical_failure_when_scored_zero():
    sc = _scorecard([
        ("s1", 100.0, [_binary_question("q1", 10, critical=CriticalType.hard)]),
    ])
    ai = [_ai_q("q1", "q1-no")]  # 0 points
    _, _, hcf = calculate_scores(ai, sc)
    assert hcf is True


def test_hard_critical_not_triggered_when_nonzero():
    sc = _scorecard([
        ("s1", 100.0, [_binary_question("q1", 10, critical=CriticalType.hard)]),
    ])
    ai = [_ai_q("q1", "q1-yes")]  # full points
    _, _, hcf = calculate_scores(ai, sc)
    assert hcf is False


def test_soft_critical_does_not_trigger_hard_failure():
    sc = _scorecard([
        ("s1", 100.0, [_binary_question("q1", 10, critical=CriticalType.soft)]),
    ])
    ai = [_ai_q("q1", "q1-no")]  # 0 points, but soft
    _, _, hcf = calculate_scores(ai, sc)
    assert hcf is False


def test_single_section_single_question():
    sc = _scorecard([
        ("s1", None, [_binary_question("q1", 10)]),
    ])
    ai = [_ai_q("q1", "q1-yes")]
    sections, overall, _ = calculate_scores(ai, sc)
    assert overall == 100.0
    assert sections[0].score == 100.0
