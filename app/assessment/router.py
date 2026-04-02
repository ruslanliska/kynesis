import json

import logfire
from fastapi import APIRouter, Depends, Form, UploadFile
from httpx import ConnectError, HTTPStatusError
from pydantic_ai.exceptions import UnexpectedModelBehavior, UsageLimitExceeded

from app.assessment.schemas import (
    AssessmentRequest,
    AssessmentResult,
    ContentType,
)
from app.assessment.services import run_assessment
from app.assessment.transcription import (
    MAX_AUDIO_SIZE,
    SUPPORTED_AUDIO_EXTENSIONS,
    transcribe_audio,
)
from app.core.auth import verify_api_key
from app.core.errors import AIProviderError, AIRateLimitError, ValidationError
from app.knowledge_base.parsers import SUPPORTED_EXTENSIONS, extract_text
from app.scorecards.schemas import ScorecardDefinition, ScorecardStatus

router = APIRouter(prefix="/api/v1", tags=["assessments"], dependencies=[Depends(verify_api_key)])


async def _run_with_error_handling(
    request: AssessmentRequest,
    knowledge_base_context: str | None = None,
) -> AssessmentResult:
    if request.scorecard.status != ScorecardStatus.active:
        raise ValidationError(
            f"Only active scorecards can be used for assessments. "
            f"Current status: {request.scorecard.status.value!r}."
        )

    if request.use_knowledge_base:
        from app.knowledge_base.services import get_rag_context

        knowledge_base_context = await get_rag_context(
            request.scorecard.id,
            request.content[:1000],
        )

    try:
        return await run_assessment(request, knowledge_base_context)
    except UnexpectedModelBehavior as e:
        logfire.error("AI model returned invalid output", error=str(e))
        raise AIProviderError()
    except UsageLimitExceeded as e:
        logfire.warn("AI usage limit exceeded", error=str(e))
        raise AIRateLimitError()
    except (HTTPStatusError, ConnectError) as e:
        logfire.error("AI provider connection error", error=str(e))
        raise AIProviderError("AI provider unavailable.")


@router.post("/assessments", response_model=AssessmentResult, response_model_by_alias=True)
async def create_assessment(request: AssessmentRequest) -> AssessmentResult:
    return await _run_with_error_handling(request)


MAX_DOCUMENT_SIZE = 10 * 1024 * 1024  # 10 MB


@router.post("/assessments/document", response_model=AssessmentResult, response_model_by_alias=True)
async def create_document_assessment(
    file: UploadFile,
    scorecard: str = Form(...),
    use_knowledge_base: bool = Form(False),
) -> AssessmentResult:
    if not file.filename:
        raise ValidationError("File must have a filename.")

    ext = "." + file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in SUPPORTED_EXTENSIONS:
        supported = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        raise ValidationError(f"Unsupported file format '{ext}'. Supported: {supported}.")

    content = await file.read()
    if len(content) == 0:
        raise ValidationError("File is empty.")
    if len(content) > MAX_DOCUMENT_SIZE:
        raise ValidationError("File exceeds maximum size of 10MB.")

    try:
        scorecard_data = json.loads(scorecard)
        scorecard_obj = ScorecardDefinition.model_validate(scorecard_data)
    except (json.JSONDecodeError, Exception) as e:
        raise ValidationError(f"Invalid scorecard JSON: {e}")

    try:
        text = extract_text(file.filename, content)
    except ValueError as e:
        raise ValidationError(str(e))

    if len(text) < 50:
        raise ValidationError(
            f"Extracted text too short ({len(text)} chars). "
            "The document may be empty, image-only, or unreadable."
        )

    request = AssessmentRequest(
        scorecard=scorecard_obj,
        content=text,
        content_type=ContentType.document,
        use_knowledge_base=use_knowledge_base,
    )

    return await _run_with_error_handling(request)


@router.post("/assessments/audio", response_model=AssessmentResult, response_model_by_alias=True)
async def create_audio_assessment(
    file: UploadFile,
    scorecard: str = Form(...),
    use_knowledge_base: bool = Form(False),
) -> AssessmentResult:
    # Validate file
    if not file.filename:
        raise ValidationError("File must have a filename.")

    ext = "." + file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in SUPPORTED_AUDIO_EXTENSIONS:
        supported = ", ".join(sorted(SUPPORTED_AUDIO_EXTENSIONS))
        raise ValidationError(f"Unsupported audio format '{ext}'. Supported: {supported}.")

    content = await file.read()
    if len(content) == 0:
        raise ValidationError("Audio file is empty.")
    if len(content) > MAX_AUDIO_SIZE:
        raise ValidationError("Audio file exceeds maximum size of 25MB.")

    # Parse scorecard JSON from form field
    try:
        scorecard_data = json.loads(scorecard)
        scorecard_obj = ScorecardDefinition.model_validate(scorecard_data)
    except (json.JSONDecodeError, Exception) as e:
        raise ValidationError(f"Invalid scorecard JSON: {e}")

    # Transcribe
    with logfire.span("audio_assessment", filename=file.filename):
        transcript = await transcribe_audio(file.filename, content)

    if len(transcript) < 50:
        raise ValidationError(
            f"Transcription too short ({len(transcript)} chars). "
            "Audio may be empty or unclear."
        )

    # Build assessment request from transcript
    request = AssessmentRequest(
        scorecard=scorecard_obj,
        content=transcript,
        content_type=ContentType.audio_conversation,
        use_knowledge_base=use_knowledge_base,
    )

    return await _run_with_error_handling(request)
