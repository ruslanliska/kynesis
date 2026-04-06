from app.assessment.services import AIQuestionOutput, calculate_scores
from app.scorecards.schemas import (
    CriticalType,
    ScorecardDefinition,
    ScorecardOption,
    ScorecardQuestion,
    ScorecardSection,
    ScorecardStatus,
    ScoringMode,
    ScoringType,
)


# --- Helpers ---


def _binary_question(
    qid: str,
    max_points: int,
    critical: CriticalType = CriticalType.none,
    mode: ScoringMode = ScoringMode.add,
) -> ScorecardQuestion:
    if mode == ScoringMode.deduct:
        options = [
            ScorecardOption(id=f"{qid}-yes", label="Yes", points_change=0, order_index=0),
            ScorecardOption(id=f"{qid}-no", label="No", points_change=-max_points, order_index=1),
        ]
    else:
        options = [
            ScorecardOption(id=f"{qid}-yes", label="Yes", points_change=max_points, order_index=0),
            ScorecardOption(id=f"{qid}-no", label="No", points_change=0, order_index=1),
        ]
    return ScorecardQuestion(
        id=qid,
        text=f"Question {qid}",
        description="",
        scoring_type=ScoringType.binary,
        max_points=max_points,
        required=True,
        critical=critical,
        order_index=0,
        options=options,
    )


def _scorecard(
    sections: list[tuple[str, float | None, list[ScorecardQuestion]]],
    max_score: int = 100,
    mode: ScoringMode = ScoringMode.add,
) -> ScorecardDefinition:
    return ScorecardDefinition(
        id="sc-1",
        name="Test",
        status=ScorecardStatus.active,
        scoring_mode=mode,
        max_score=max_score,
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


# --- Add mode tests ---


def test_add_perfect():
    # q1=20pts, q2=30pts, q3=50pts → total=100, maxScore=100 → 100%
    sc = _scorecard([
        ("s1", 30.0, [_binary_question("q1", 20), _binary_question("q2", 30)]),
        ("s2", 70.0, [_binary_question("q3", 50)]),
    ], max_score=100)
    ai = [_ai_q("q1", "q1-yes"), _ai_q("q2", "q2-yes"), _ai_q("q3", "q3-yes")]
    _, overall, hcf = calculate_scores(ai, sc)
    assert overall == 100.0
    assert hcf is False


def test_add_zero():
    sc = _scorecard([
        ("s1", 30.0, [_binary_question("q1", 20), _binary_question("q2", 30)]),
        ("s2", 70.0, [_binary_question("q3", 50)]),
    ], max_score=100)
    ai = [_ai_q("q1", "q1-no"), _ai_q("q2", "q2-no"), _ai_q("q3", "q3-no")]
    _, overall, _ = calculate_scores(ai, sc)
    assert overall == 0.0


def test_add_partial():
    # q1 yes=20, q2 no=0, q3 yes=50 → earned=70, maxScore=100 → 70%
    sc = _scorecard([
        ("s1", 30.0, [_binary_question("q1", 20), _binary_question("q2", 30)]),
        ("s2", 70.0, [_binary_question("q3", 50)]),
    ], max_score=100)
    ai = [_ai_q("q1", "q1-yes"), _ai_q("q2", "q2-no"), _ai_q("q3", "q3-yes")]
    _, overall, _ = calculate_scores(ai, sc)
    assert overall == 70.0


# --- Deduct mode tests ---


def test_deduct_perfect():
    # No deductions → 100%
    sc = _scorecard([
        ("s1", 50.0, [_binary_question("q1", 40, mode=ScoringMode.deduct),
                      _binary_question("q2", 30, mode=ScoringMode.deduct)]),
        ("s2", 50.0, [_binary_question("q3", 30, mode=ScoringMode.deduct)]),
    ], max_score=100, mode=ScoringMode.deduct)
    ai = [_ai_q("q1", "q1-yes"), _ai_q("q2", "q2-yes"), _ai_q("q3", "q3-yes")]
    _, overall, _ = calculate_scores(ai, sc)
    assert overall == 100.0


def test_deduct_partial():
    # q1 violated (-40), rest pass → earned: 0+30+30=60, maxScore=100 → 60%
    sc = _scorecard([
        ("s1", 50.0, [_binary_question("q1", 40, mode=ScoringMode.deduct),
                      _binary_question("q2", 30, mode=ScoringMode.deduct)]),
        ("s2", 50.0, [_binary_question("q3", 30, mode=ScoringMode.deduct)]),
    ], max_score=100, mode=ScoringMode.deduct)
    ai = [_ai_q("q1", "q1-no"), _ai_q("q2", "q2-yes"), _ai_q("q3", "q3-yes")]
    _, overall, _ = calculate_scores(ai, sc)
    assert overall == 60.0


# --- Section display scores ---


def test_section_scores_add():
    sc = _scorecard([
        ("s1", 30.0, [_binary_question("q1", 20), _binary_question("q2", 30)]),
        ("s2", 70.0, [_binary_question("q3", 50)]),
    ], max_score=100)
    # s1: q1 yes, q2 no → 20/50 = 40%; s2: q3 yes → 50/50 = 100%
    ai = [_ai_q("q1", "q1-yes"), _ai_q("q2", "q2-no"), _ai_q("q3", "q3-yes")]
    sections, _, _ = calculate_scores(ai, sc)
    assert sections[0].score == 40.0
    assert sections[1].score == 100.0


# --- Critical failure tests ---


def test_hard_critical_failure_when_scored_zero():
    sc = _scorecard([
        ("s1", None, [_binary_question("q1", 10, critical=CriticalType.hard)]),
    ], max_score=10)
    ai = [_ai_q("q1", "q1-no")]
    _, _, hcf = calculate_scores(ai, sc)
    assert hcf is True


def test_hard_critical_not_triggered_when_nonzero():
    sc = _scorecard([
        ("s1", None, [_binary_question("q1", 10, critical=CriticalType.hard)]),
    ], max_score=10)
    ai = [_ai_q("q1", "q1-yes")]
    _, _, hcf = calculate_scores(ai, sc)
    assert hcf is False


def test_soft_critical_does_not_trigger_hard_failure():
    sc = _scorecard([
        ("s1", None, [_binary_question("q1", 10, critical=CriticalType.soft)]),
    ], max_score=10)
    ai = [_ai_q("q1", "q1-no")]
    _, _, hcf = calculate_scores(ai, sc)
    assert hcf is False
