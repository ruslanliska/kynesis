import copy
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import AsyncClient

from tests.conftest import TEST_API_KEY

SCORECARD_PAYLOAD = {
    "id": "sc-1",
    "name": "Test Scorecard",
    "description": "Test",
    "status": "active",
    "scoringMode": "add",
    "maxScore": 20,
    "passingThreshold": 15,
    "allowQuestionComments": True,
    "allowOverallComment": True,
    "showPointsToEvaluator": True,
    "version": 1,
    "sections": [
        {
            "id": "sec-1",
            "name": "Section One",
            "description": "First section",
            "orderIndex": 0,
            "weight": 60,
            "questions": [
                {
                    "id": "q1",
                    "text": "Is it clear?",
                    "description": "Clarity check",
                    "scoringType": "binary",
                    "maxPoints": 10,
                    "required": True,
                    "critical": "none",
                    "orderIndex": 0,
                    "options": [
                        {"id": "opt-q1-yes", "label": "Yes", "value": 1, "pointsChange": 10, "orderIndex": 0},
                        {"id": "opt-q1-no", "label": "No", "value": 0, "pointsChange": 0, "orderIndex": 1},
                    ],
                }
            ],
        },
        {
            "id": "sec-2",
            "name": "Section Two",
            "description": "Second section",
            "orderIndex": 1,
            "weight": 40,
            "questions": [
                {
                    "id": "q2",
                    "text": "Is it accurate?",
                    "description": "Accuracy check",
                    "scoringType": "binary",
                    "maxPoints": 10,
                    "required": True,
                    "critical": "none",
                    "orderIndex": 0,
                    "options": [
                        {"id": "opt-q2-yes", "label": "Yes", "value": 1, "pointsChange": 10, "orderIndex": 0},
                        {"id": "opt-q2-no", "label": "No", "value": 0, "pointsChange": 0, "orderIndex": 1},
                    ],
                }
            ],
        },
    ],
}

VALID_CONTENT = "A" * 60
HEADERS = {"X-API-Key": TEST_API_KEY}


def _mock_ai_output():
    from app.assessment.services import AIQuestionOutput, AIScoreOutput
    return AIScoreOutput(
        content_analysis="A document with clear structure.",
        questions=[
            AIQuestionOutput(
                question_id="q1", selected_option_id="opt-q1-yes",
                evidence=["Direct quote"], reasoning="Clear.", comment="Clear writing.", suggestions=None,
            ),
            AIQuestionOutput(
                question_id="q2", selected_option_id="opt-q2-yes",
                evidence=["Relevant passage"], reasoning="Accurate.", comment="Mostly accurate.",
                suggestions="Double check facts.",
            ),
        ],
        summary="Good overall performance.",
    )


def _patch_llm(ai_output):
    """Patch get_llm to return a mock LangChain model whose chain returns ai_output."""
    mock_chain = MagicMock()
    mock_chain.ainvoke = AsyncMock(return_value=ai_output)
    mock_llm = MagicMock()
    mock_llm.with_structured_output = MagicMock(return_value=mock_chain)
    return patch("app.assessment.services.get_llm", return_value=mock_llm)


# --- POST /api/v1/assessments ---


async def test_assessment_returns_200(async_client: AsyncClient):
    with _patch_llm(_mock_ai_output()):
        response = await async_client.post(
            "/api/v1/assessments",
            json={"scorecard": SCORECARD_PAYLOAD, "content": VALID_CONTENT, "contentType": "document"},
            headers=HEADERS,
        )

    assert response.status_code == 200
    data = response.json()
    assert data["scorecardId"] == "sc-1"
    assert data["scorecardVersion"] == 1
    assert data["contentType"] == "document"
    assert "assessedAt" in data
    assert data["overall"]["maxScore"] == 100
    assert isinstance(data["overall"]["score"], float)
    assert isinstance(data["overall"]["summary"], str)
    assert len(data["sections"]) == 2
    assert len(data["questions"]) == 2


async def test_assessment_question_fields(async_client: AsyncClient):
    with _patch_llm(_mock_ai_output()):
        response = await async_client.post(
            "/api/v1/assessments",
            json={"scorecard": SCORECARD_PAYLOAD, "content": VALID_CONTENT},
            headers=HEADERS,
        )

    data = response.json()
    q1 = next(q for q in data["questions"] if q["questionId"] == "q1")
    assert q1["score"] == 10
    assert q1["maxPoints"] == 10
    assert q1["passed"] is True
    assert q1["sectionId"] == "sec-1"
    assert q1["suggestions"] is None

    q2 = next(q for q in data["questions"] if q["questionId"] == "q2")
    assert q2["score"] == 10
    assert q2["passed"] is True
    assert q2["suggestions"] == "Double check facts."


async def test_assessment_passed_below_threshold(async_client: AsyncClient):
    from app.assessment.services import AIQuestionOutput, AIScoreOutput

    ai_output = AIScoreOutput(
        content_analysis="Test.",
        questions=[
            AIQuestionOutput(question_id="q1", selected_option_id="opt-q1-no",
                             evidence=["e"], reasoning="r", comment="Poor.", suggestions="Improve."),
            AIQuestionOutput(question_id="q2", selected_option_id="opt-q2-no",
                             evidence=["e"], reasoning="r", comment="Poor.", suggestions="Improve."),
        ],
        summary="Needs work.",
    )
    with _patch_llm(ai_output):
        response = await async_client.post(
            "/api/v1/assessments",
            json={"scorecard": SCORECARD_PAYLOAD, "content": VALID_CONTENT},
            headers=HEADERS,
        )

    q1 = next(q for q in response.json()["questions"] if q["questionId"] == "q1")
    assert q1["passed"] is False


async def test_assessment_weighted_score_calculation(async_client: AsyncClient):
    # q1 yes=10pts, q2 no=0pts → earned=10, maxScore=20 → 50%
    from app.assessment.services import AIQuestionOutput, AIScoreOutput

    ai_output = AIScoreOutput(
        content_analysis="Test.",
        questions=[
            AIQuestionOutput(question_id="q1", selected_option_id="opt-q1-yes",
                             evidence=["e"], reasoning="r", comment="Perfect.", suggestions=None),
            AIQuestionOutput(question_id="q2", selected_option_id="opt-q2-no",
                             evidence=["e"], reasoning="r", comment="Failed.", suggestions="More."),
        ],
        summary="Mixed.",
    )
    with _patch_llm(ai_output):
        response = await async_client.post(
            "/api/v1/assessments",
            json={"scorecard": SCORECARD_PAYLOAD, "content": VALID_CONTENT},
            headers=HEADERS,
        )

    assert response.json()["overall"]["score"] == 50.0


async def test_assessment_overall_pass_fail(async_client: AsyncClient):
    with _patch_llm(_mock_ai_output()):
        response = await async_client.post(
            "/api/v1/assessments",
            json={"scorecard": SCORECARD_PAYLOAD, "content": VALID_CONTENT},
            headers=HEADERS,
        )

    data = response.json()
    assert data["overall"]["passed"] is True
    assert data["overall"]["hardCriticalFailure"] is False


async def test_assessment_hard_critical_failure(async_client: AsyncClient):
    from app.assessment.services import AIQuestionOutput, AIScoreOutput

    scorecard_hard = copy.deepcopy(SCORECARD_PAYLOAD)
    scorecard_hard["sections"][0]["questions"][0]["critical"] = "hard"

    ai_output = AIScoreOutput(
        content_analysis="Test.",
        questions=[
            AIQuestionOutput(question_id="q1", selected_option_id="opt-q1-no",
                             evidence=["e"], reasoning="Failed.", comment="Failed.", suggestions=None),
            AIQuestionOutput(question_id="q2", selected_option_id="opt-q2-yes",
                             evidence=["e"], reasoning="OK.", comment="OK.", suggestions=None),
        ],
        summary="Hard critical fail.",
    )
    with _patch_llm(ai_output):
        response = await async_client.post(
            "/api/v1/assessments",
            json={"scorecard": scorecard_hard, "content": VALID_CONTENT},
            headers=HEADERS,
        )

    data = response.json()
    assert data["overall"]["hardCriticalFailure"] is True
    assert data["overall"]["score"] == 0.0
    assert data["overall"]["passed"] is False


async def test_assessment_draft_scorecard_returns_422(async_client: AsyncClient):
    scorecard_draft = copy.deepcopy(SCORECARD_PAYLOAD)
    scorecard_draft["status"] = "draft"

    response = await async_client.post(
        "/api/v1/assessments",
        json={"scorecard": scorecard_draft, "content": VALID_CONTENT},
        headers=HEADERS,
    )
    assert response.status_code == 422


async def test_assessment_returns_401_without_api_key(async_client: AsyncClient):
    response = await async_client.post(
        "/api/v1/assessments",
        json={"scorecard": SCORECARD_PAYLOAD, "content": VALID_CONTENT},
    )
    assert response.status_code == 401


async def test_assessment_returns_401_with_wrong_api_key(async_client: AsyncClient):
    response = await async_client.post(
        "/api/v1/assessments",
        json={"scorecard": SCORECARD_PAYLOAD, "content": VALID_CONTENT},
        headers={"X-API-Key": "wrong-key"},
    )
    assert response.status_code == 401


async def test_assessment_returns_422_content_too_short(async_client: AsyncClient):
    response = await async_client.post(
        "/api/v1/assessments",
        json={"scorecard": SCORECARD_PAYLOAD, "content": "too short"},
        headers=HEADERS,
    )
    assert response.status_code == 422


async def test_assessment_returns_422_missing_scorecard(async_client: AsyncClient):
    response = await async_client.post(
        "/api/v1/assessments",
        json={"content": VALID_CONTENT},
        headers=HEADERS,
    )
    assert response.status_code == 422


async def test_assessment_returns_422_empty_sections(async_client: AsyncClient):
    scorecard_empty = copy.deepcopy(SCORECARD_PAYLOAD)
    scorecard_empty["sections"] = []

    response = await async_client.post(
        "/api/v1/assessments",
        json={"scorecard": scorecard_empty, "content": VALID_CONTENT},
        headers=HEADERS,
    )
    assert response.status_code == 422


async def test_assessment_returns_422_invalid_content_type(async_client: AsyncClient):
    response = await async_client.post(
        "/api/v1/assessments",
        json={"scorecard": SCORECARD_PAYLOAD, "content": VALID_CONTENT, "contentType": "invalid_type"},
        headers=HEADERS,
    )
    assert response.status_code == 422


async def test_assessment_camel_case_response(async_client: AsyncClient):
    with _patch_llm(_mock_ai_output()):
        response = await async_client.post(
            "/api/v1/assessments",
            json={"scorecard": SCORECARD_PAYLOAD, "content": VALID_CONTENT},
            headers=HEADERS,
        )

    data = response.json()
    assert "scorecardId" in data
    assert "scorecardVersion" in data
    assert "contentType" in data
    assert "assessedAt" in data
    assert "sectionId" in data["sections"][0]
    assert "sectionName" in data["sections"][0]
    assert "questionId" in data["questions"][0]
    assert "maxPoints" in data["questions"][0]
    assert "hardCriticalFailure" in data["overall"]
    assert "passed" in data["overall"]
