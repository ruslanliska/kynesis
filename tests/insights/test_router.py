from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from tests.conftest import TEST_API_KEY

HEADERS = {"X-API-Key": TEST_API_KEY}


def _make_assessment_result(**overrides):
    base = {
        "scorecardId": "sc-1",
        "scorecardVersion": 1,
        "contentType": "document",
        "assessedAt": "2026-03-25T10:00:00Z",
        "overall": {"score": 75.0, "maxScore": 100, "summary": "Good."},
        "criteria": [
            {
                "criterionId": "c1",
                "score": 8,
                "maxScore": 10,
                "passed": True,
                "comment": "Nice.",
                "suggestions": None,
            },
        ],
    }
    base.update(overrides)
    return base


def _make_insight_report():
    from app.insights.schemas import InsightReport

    return InsightReport(
        top_issues=[],
        patterns=[],
        recommendations=[],
        summary="Overall positive trend.",
        strength_areas=[],
        weak_areas=[],
    )


# --- POST /api/v1/insights ---


async def test_insights_returns_200(async_client: AsyncClient):
    with patch("app.insights.router.generate_insights", new_callable=AsyncMock) as mock_gen:
        mock_gen.return_value = _make_insight_report()

        response = await async_client.post(
            "/api/v1/insights",
            json={
                "assessments": [
                    _make_assessment_result(),
                    _make_assessment_result(overall={"score": 60.0, "maxScore": 100, "summary": "OK."}),
                    _make_assessment_result(overall={"score": 90.0, "maxScore": 100, "summary": "Great."}),
                ],
            },
            headers=HEADERS,
        )

    assert response.status_code == 200
    data = response.json()
    assert "summary" in data
    assert "top_issues" in data
    assert "strength_areas" in data
    assert "weak_areas" in data


async def test_insights_returns_401_without_api_key(async_client: AsyncClient):
    response = await async_client.post(
        "/api/v1/insights",
        json={"assessments": [_make_assessment_result()] * 3},
    )
    assert response.status_code == 401


async def test_insights_returns_422_too_few_assessments(async_client: AsyncClient):
    response = await async_client.post(
        "/api/v1/insights",
        json={
            "assessments": [
                _make_assessment_result(),
                _make_assessment_result(),
            ],
        },
        headers=HEADERS,
    )
    assert response.status_code == 422


async def test_insights_returns_422_empty_assessments(async_client: AsyncClient):
    response = await async_client.post(
        "/api/v1/insights",
        json={"assessments": []},
        headers=HEADERS,
    )
    assert response.status_code == 422
