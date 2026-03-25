from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from tests.conftest import TEST_API_KEY

SCORECARD_PAYLOAD = {
    "id": "sc-1",
    "name": "Test Scorecard",
    "description": "Test",
    "criteria": [
        {"id": "c1", "name": "Clarity", "description": "Is it clear?", "weight": 3, "maxScore": 10, "order": 0},
        {"id": "c2", "name": "Accuracy", "description": "Is it accurate?", "weight": 2, "maxScore": 10, "order": 1},
    ],
    "version": 1,
    "isActive": True,
}

VALID_CONTENT = "A" * 60  # min_length=50

HEADERS = {"X-API-Key": TEST_API_KEY}


def _mock_ai_output():
    """Create a mock AI agent result."""
    from app.assessment.services import AICriterionOutput, AIScoreOutput

    return AIScoreOutput(
        criteria=[
            AICriterionOutput(criterion_id="c1", score=8, comment="Clear writing.", suggestions=None),
            AICriterionOutput(criterion_id="c2", score=6, comment="Mostly accurate.", suggestions="Double check facts."),
        ],
        summary="Good overall performance.",
    )


def _make_mock_agent_run(ai_output):
    """Create a mock for agent.run that returns a result-like object."""
    mock_result = AsyncMock()
    mock_result.output = ai_output
    mock_run = AsyncMock(return_value=mock_result)
    return mock_run


# --- POST /api/v1/assessments ---


async def test_assessment_returns_200(async_client: AsyncClient):
    ai_output = _mock_ai_output()
    mock_run = _make_mock_agent_run(ai_output)

    with patch("app.assessment.services.get_assessment_agent") as mock_get_agent:
        mock_agent = AsyncMock()
        mock_agent.run = mock_run
        mock_get_agent.return_value = mock_agent

        response = await async_client.post(
            "/api/v1/assessments",
            json={
                "scorecard": SCORECARD_PAYLOAD,
                "content": VALID_CONTENT,
                "contentType": "document",
            },
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
    assert len(data["criteria"]) == 2


async def test_assessment_criteria_fields(async_client: AsyncClient):
    ai_output = _mock_ai_output()
    mock_run = _make_mock_agent_run(ai_output)

    with patch("app.assessment.services.get_assessment_agent") as mock_get_agent:
        mock_agent = AsyncMock()
        mock_agent.run = mock_run
        mock_get_agent.return_value = mock_agent

        response = await async_client.post(
            "/api/v1/assessments",
            json={"scorecard": SCORECARD_PAYLOAD, "content": VALID_CONTENT},
            headers=HEADERS,
        )

    data = response.json()
    c1 = next(c for c in data["criteria"] if c["criterionId"] == "c1")
    assert c1["score"] == 8
    assert c1["maxScore"] == 10
    assert c1["passed"] is True  # 8 >= 10 * 0.6
    assert c1["suggestions"] is None

    c2 = next(c for c in data["criteria"] if c["criterionId"] == "c2")
    assert c2["score"] == 6
    assert c2["passed"] is True  # 6 >= 10 * 0.6
    assert c2["suggestions"] == "Double check facts."


async def test_assessment_passed_threshold(async_client: AsyncClient):
    """Score below 60% of maxScore should mark passed=False."""
    from app.assessment.services import AICriterionOutput, AIScoreOutput

    ai_output = AIScoreOutput(
        criteria=[
            AICriterionOutput(criterion_id="c1", score=5, comment="Okay.", suggestions="Improve."),
            AICriterionOutput(criterion_id="c2", score=5, comment="Okay.", suggestions="Improve."),
        ],
        summary="Needs work.",
    )
    mock_run = _make_mock_agent_run(ai_output)

    with patch("app.assessment.services.get_assessment_agent") as mock_get_agent:
        mock_agent = AsyncMock()
        mock_agent.run = mock_run
        mock_get_agent.return_value = mock_agent

        response = await async_client.post(
            "/api/v1/assessments",
            json={"scorecard": SCORECARD_PAYLOAD, "content": VALID_CONTENT},
            headers=HEADERS,
        )

    data = response.json()
    c1 = next(c for c in data["criteria"] if c["criterionId"] == "c1")
    assert c1["passed"] is False  # 5 < 10 * 0.6


async def test_assessment_weighted_score_calculation(async_client: AsyncClient):
    from app.assessment.services import AICriterionOutput, AIScoreOutput

    # c1: score=10/10, weight=3 → contributes 3.0
    # c2: score=5/10, weight=2 → contributes 1.0
    # total_weight=5, weighted_sum=4.0, score = 4.0/5 * 100 = 80.0
    ai_output = AIScoreOutput(
        criteria=[
            AICriterionOutput(criterion_id="c1", score=10, comment="Perfect.", suggestions=None),
            AICriterionOutput(criterion_id="c2", score=5, comment="Half.", suggestions="More."),
        ],
        summary="Mixed.",
    )
    mock_run = _make_mock_agent_run(ai_output)

    with patch("app.assessment.services.get_assessment_agent") as mock_get_agent:
        mock_agent = AsyncMock()
        mock_agent.run = mock_run
        mock_get_agent.return_value = mock_agent

        response = await async_client.post(
            "/api/v1/assessments",
            json={"scorecard": SCORECARD_PAYLOAD, "content": VALID_CONTENT},
            headers=HEADERS,
        )

    data = response.json()
    assert data["overall"]["score"] == 80.0


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


async def test_assessment_returns_422_empty_criteria(async_client: AsyncClient):
    scorecard = {**SCORECARD_PAYLOAD, "criteria": []}
    response = await async_client.post(
        "/api/v1/assessments",
        json={"scorecard": scorecard, "content": VALID_CONTENT},
        headers=HEADERS,
    )
    assert response.status_code == 422


async def test_assessment_returns_422_invalid_content_type(async_client: AsyncClient):
    response = await async_client.post(
        "/api/v1/assessments",
        json={
            "scorecard": SCORECARD_PAYLOAD,
            "content": VALID_CONTENT,
            "contentType": "invalid_type",
        },
        headers=HEADERS,
    )
    assert response.status_code == 422


async def test_assessment_camel_case_response(async_client: AsyncClient):
    """Verify response uses camelCase field names."""
    ai_output = _mock_ai_output()
    mock_run = _make_mock_agent_run(ai_output)

    with patch("app.assessment.services.get_assessment_agent") as mock_get_agent:
        mock_agent = AsyncMock()
        mock_agent.run = mock_run
        mock_get_agent.return_value = mock_agent

        response = await async_client.post(
            "/api/v1/assessments",
            json={"scorecard": SCORECARD_PAYLOAD, "content": VALID_CONTENT},
            headers=HEADERS,
        )

    data = response.json()
    # Verify camelCase keys
    assert "scorecardId" in data
    assert "scorecardVersion" in data
    assert "contentType" in data
    assert "assessedAt" in data
    assert "criterionId" in data["criteria"][0]
    assert "maxScore" in data["criteria"][0]
