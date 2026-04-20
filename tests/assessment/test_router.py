import contextlib
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


def _build_reasoning_text(ai_output) -> str:
    """Synthesise a reasoning response in the `### Q: <id>` format for each question."""
    blocks: list[str] = []
    for q in ai_output.questions:
        answer_hint = (
            f"select option {q.selected_option_id}"
            if q.selected_option_id
            else f"numeric value {q.numeric_value}"
        )
        blocks.append(
            f"### Q: {q.question_id}\n"
            f"Reasoning for {q.question_id}: {q.reasoning}. Evidence: {q.evidence}. "
            f"Conclusion: {answer_hint}."
        )
    return "\n\n".join(blocks)


def _patch_pipeline(ai_output, reasoning_text: str | None = None, thinking_trace: str | None = None):
    """Patch the new two-stage pipeline AND legacy fallback so no real LLM calls fire."""
    # Reasoning LLM: returns an AIMessage-like object with .content + .additional_kwargs.
    reasoning_text = reasoning_text or _build_reasoning_text(ai_output)
    reasoning_response = MagicMock()
    reasoning_response.content = reasoning_text
    reasoning_response.additional_kwargs = {"reasoning_content": thinking_trace} if thinking_trace else {}
    reasoning_llm = MagicMock()
    reasoning_llm.ainvoke = AsyncMock(return_value=reasoning_response)

    # Structuring LLM: .with_structured_output(...).ainvoke returns ai_output.
    structuring_chain = MagicMock()
    structuring_chain.ainvoke = AsyncMock(return_value=ai_output)
    structuring_llm = MagicMock()
    structuring_llm.with_structured_output = MagicMock(return_value=structuring_chain)

    # Legacy get_llm — fallback path compatibility.
    legacy_llm = MagicMock()
    legacy_llm.with_structured_output = MagicMock(return_value=structuring_chain)

    return contextlib.ExitStack(), {
        "reasoning_llm_patch": patch("app.assessment.services.get_reasoning_llm", return_value=reasoning_llm),
        "structuring_llm_patch": patch("app.assessment.services.get_structuring_llm", return_value=structuring_llm),
        "legacy_llm_patch": patch("app.assessment.services.get_llm", return_value=legacy_llm),
    }


@contextlib.contextmanager
def _patch_llm(ai_output, reasoning_text: str | None = None, thinking_trace: str | None = None):
    """Context manager: patches the full two-stage pipeline (reasoning + structuring + legacy)."""
    stack, patches = _patch_pipeline(ai_output, reasoning_text, thinking_trace)
    with stack:
        for p in patches.values():
            stack.enter_context(p)
        yield


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


# ============================================================================
# Feature 003-reasoning-aggregation — two-stage pipeline integration tests
# ============================================================================


# --- T013 / T021 Response includes rationale, no thinkingTrace ---


async def test_assessment_response_includes_rationale(async_client: AsyncClient):
    with _patch_llm(_mock_ai_output(), thinking_trace="internal thinking"):
        response = await async_client.post(
            "/api/v1/assessments",
            json={"scorecard": SCORECARD_PAYLOAD, "content": VALID_CONTENT},
            headers=HEADERS,
        )

    assert response.status_code == 200
    data = response.json()
    for q in data["questions"]:
        assert q["rationale"]
        assert len(q["rationale"]) >= 20
    body_text = response.text
    assert "thinkingTrace" not in body_text
    assert "thinking_trace" not in body_text
    assert "internal thinking" not in body_text
    assert data["overall"]["reasoningUnavailable"] is False


# --- T029 US3 fallback labelled ---


async def test_assessment_fallback_labelled_on_reasoning_failure(async_client: AsyncClient):
    """When reasoning stage fails, default fallback policy runs legacy flow."""
    ai_output = _mock_ai_output()

    # Reasoning LLM always raises.
    reasoning_llm = MagicMock()
    reasoning_llm.ainvoke = AsyncMock(side_effect=RuntimeError("reasoning boom"))

    # Legacy LLM returns the same ai_output.
    chain = MagicMock()
    chain.ainvoke = AsyncMock(return_value=ai_output)
    legacy_llm = MagicMock()
    legacy_llm.with_structured_output = MagicMock(return_value=chain)

    with (
        patch("app.assessment.services.get_reasoning_llm", return_value=reasoning_llm),
        patch("app.assessment.services.get_llm", return_value=legacy_llm),
    ):
        response = await async_client.post(
            "/api/v1/assessments",
            json={"scorecard": SCORECARD_PAYLOAD, "content": VALID_CONTENT},
            headers=HEADERS,
        )

    assert response.status_code == 200
    data = response.json()
    assert data["overall"]["reasoningUnavailable"] is True
    for q in data["questions"]:
        assert q["rationale"] == ""


# --- T030 US3 strict policy → 502 ---


async def test_assessment_strict_policy_returns_502(async_client: AsyncClient):
    from app.core.config import (
        AssessmentConfig, LangSmithConfig, LogfireConfig,
        OpenAIConfig, PineconeConfig, Settings,
    )

    strict_settings = Settings(
        API_KEY=TEST_API_KEY,
        SUPABASE_JWT_SECRET="test-jwt-secret-for-testing-only",
        DATABASE_URL="postgresql+asyncpg://test:test@localhost:5432/test",
        ALLOWED_ORIGINS=["http://localhost:5173"],
        openai=OpenAIConfig(api_key="test"),
        pinecone=PineconeConfig(api_key="test", index_name="test-index"),
        logfire=LogfireConfig(token="", send_to_logfire=False),
        langsmith=LangSmithConfig(api_key="", project="test", tracing=False),
        assessment=AssessmentConfig(failure_policy="strict"),
    )

    reasoning_llm = MagicMock()
    reasoning_llm.ainvoke = AsyncMock(side_effect=RuntimeError("reasoning boom"))

    with (
        patch("app.assessment.services.get_settings", return_value=strict_settings),
        patch("app.assessment.services.get_reasoning_llm", return_value=reasoning_llm),
    ):
        response = await async_client.post(
            "/api/v1/assessments",
            json={"scorecard": SCORECARD_PAYLOAD, "content": VALID_CONTENT},
            headers=HEADERS,
        )

    assert response.status_code == 502
    assert response.json()["detail"] == "Reasoning stage failed after retries."


# --- T031 US3 timeout → 504 ---


async def test_assessment_timeout_returns_504(async_client: AsyncClient):
    from app.core.config import (
        AssessmentConfig, LangSmithConfig, LogfireConfig,
        OpenAIConfig, PineconeConfig, Settings,
    )

    short_settings = Settings(
        API_KEY=TEST_API_KEY,
        SUPABASE_JWT_SECRET="test-jwt-secret-for-testing-only",
        DATABASE_URL="postgresql+asyncpg://test:test@localhost:5432/test",
        ALLOWED_ORIGINS=["http://localhost:5173"],
        openai=OpenAIConfig(api_key="test"),
        pinecone=PineconeConfig(api_key="test", index_name="test-index"),
        logfire=LogfireConfig(token="", send_to_logfire=False),
        langsmith=LangSmithConfig(api_key="", project="test", tracing=False),
        assessment=AssessmentConfig(request_timeout_seconds=1),
    )

    async def slow_ainvoke(*args, **kwargs):
        import asyncio
        await asyncio.sleep(3)
        response = MagicMock()
        response.content = "### Q: q1\nRationale."
        response.additional_kwargs = {}
        return response

    slow_llm = MagicMock()
    slow_llm.ainvoke = slow_ainvoke

    with (
        patch("app.assessment.services.get_settings", return_value=short_settings),
        patch("app.assessment.services.get_reasoning_llm", return_value=slow_llm),
    ):
        response = await async_client.post(
            "/api/v1/assessments",
            json={"scorecard": SCORECARD_PAYLOAD, "content": VALID_CONTENT},
            headers=HEADERS,
        )

    assert response.status_code == 504
    assert "timed out" in response.json()["detail"]


# --- T054 Oversize reasoning payload → 413 ---


async def test_assessment_oversize_reasoning_returns_413(async_client: AsyncClient):
    """When structuring prompt exceeds char budget, return HTTP 413."""
    ai_output = _mock_ai_output()

    with (
        _patch_llm(ai_output),
        patch("app.assessment.services._STRUCTURING_PROMPT_CHAR_BUDGET", 10),
    ):
        response = await async_client.post(
            "/api/v1/assessments",
            json={"scorecard": SCORECARD_PAYLOAD, "content": VALID_CONTENT},
            headers=HEADERS,
        )

    assert response.status_code == 413
    assert "too large" in response.json()["detail"].lower()


# --- T041 Backwards-compat — legacy feature-002 response schema still parses ---


async def test_response_is_backwards_compatible_with_feature_002_schema(async_client: AsyncClient):
    """A client model without new fields must parse the new response without errors."""
    with _patch_llm(_mock_ai_output()):
        response = await async_client.post(
            "/api/v1/assessments",
            json={"scorecard": SCORECARD_PAYLOAD, "content": VALID_CONTENT},
            headers=HEADERS,
        )

    # Mimic a consumer with an older schema.
    from datetime import datetime
    from pydantic import BaseModel, Field

    class LegacyOverallResult(BaseModel):
        score: float
        max_score: int = Field(alias="maxScore")
        passed: bool | None = None
        hard_critical_failure: bool = Field(alias="hardCriticalFailure")
        summary: str

        model_config = {"populate_by_name": True, "extra": "ignore"}

    class LegacyQuestionResult(BaseModel):
        question_id: str = Field(alias="questionId")
        section_id: str = Field(alias="sectionId")
        score: float
        max_points: int = Field(alias="maxPoints")
        passed: bool
        critical: str
        comment: str
        suggestions: str | None = None

        model_config = {"populate_by_name": True, "extra": "ignore"}

    class LegacyAssessmentResult(BaseModel):
        scorecard_id: str = Field(alias="scorecardId")
        scorecard_version: int = Field(alias="scorecardVersion")
        content_type: str = Field(alias="contentType")
        assessed_at: datetime = Field(alias="assessedAt")
        overall: LegacyOverallResult
        questions: list[LegacyQuestionResult]

        model_config = {"populate_by_name": True, "extra": "ignore"}

    # Parsing must succeed despite the new rationale + reasoningUnavailable fields.
    LegacyAssessmentResult.model_validate(response.json())


# ============================================================================
# Constitution III: /assessments/document and /assessments/audio endpoint tests
# (Tasks T043–T046 — remediation for the feature-level analysis gap)
# ============================================================================


# --- T043 document happy path ---


async def test_assessments_document_endpoint_two_stage_success(async_client: AsyncClient):
    import io
    import json as _json

    # Patch text extraction so we don't depend on a real file parser.
    async def fake_extract(filename: str, content: bytes) -> str:
        return VALID_CONTENT

    with (
        _patch_llm(_mock_ai_output()),
        patch("app.assessment.router._extract_text_from_file", side_effect=fake_extract),
    ):
        response = await async_client.post(
            "/api/v1/assessments/document",
            files={"file": ("sample.txt", io.BytesIO(b"fake txt body"), "text/plain")},
            data={
                "scorecard": _json.dumps(SCORECARD_PAYLOAD),
                "use_knowledge_base": "false",
            },
            headers=HEADERS,
        )

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["contentType"] == "document"
    assert len(data["questions"]) == 2
    assert data["overall"]["reasoningUnavailable"] is False


# --- T044 audio happy path ---


async def test_assessments_audio_endpoint_two_stage_success(async_client: AsyncClient):
    import io
    import json as _json

    async def fake_transcribe(filename: str, content: bytes) -> str:
        return VALID_CONTENT

    with (
        _patch_llm(_mock_ai_output()),
        patch("app.assessment.router.transcribe_audio", side_effect=fake_transcribe),
    ):
        response = await async_client.post(
            "/api/v1/assessments/audio",
            files={"file": ("sample.mp3", io.BytesIO(b"\x00" * 1024), "audio/mpeg")},
            data={
                "scorecard": _json.dumps(SCORECARD_PAYLOAD),
                "use_knowledge_base": "false",
            },
            headers=HEADERS,
        )

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["contentType"] == "audio_conversation"
    assert len(data["questions"]) == 2
    assert data["overall"]["reasoningUnavailable"] is False


# --- T045 document endpoint rejects unsupported extension ---


async def test_assessments_document_unsupported_extension_returns_422(async_client: AsyncClient):
    import io
    import json as _json

    response = await async_client.post(
        "/api/v1/assessments/document",
        files={"file": ("sample.xyz", io.BytesIO(b"content"), "application/octet-stream")},
        data={"scorecard": _json.dumps(SCORECARD_PAYLOAD)},
        headers=HEADERS,
    )

    assert response.status_code == 422
    assert "Unsupported" in response.json()["detail"] or "Supported" in response.json()["detail"]


# --- T046 audio endpoint rejects oversize file ---


async def test_assessments_audio_oversize_returns_422(async_client: AsyncClient):
    import io
    import json as _json

    from app.assessment.transcription import MAX_AUDIO_SIZE

    # Create a file just over the limit (26 MB).
    big = io.BytesIO(b"\x00" * (MAX_AUDIO_SIZE + 1024))

    response = await async_client.post(
        "/api/v1/assessments/audio",
        files={"file": ("big.mp3", big, "audio/mpeg")},
        data={"scorecard": _json.dumps(SCORECARD_PAYLOAD)},
        headers=HEADERS,
    )

    assert response.status_code == 422
    assert "maximum" in response.json()["detail"].lower() or "25" in response.json()["detail"]
