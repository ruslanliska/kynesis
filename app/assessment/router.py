import json

import logfire
from fastapi import APIRouter, Depends, Form, UploadFile
from httpx import ConnectError, HTTPStatusError
from langchain_core.exceptions import LangChainException
from openai import APIConnectionError, RateLimitError

from app.assessment.schemas import (
    AssessmentRequest,
    AssessmentResult,
    ContentType,
)
from app.assessment.services import run_legacy_assessment, run_reasoning_assessment
from app.assessment.ocr import (
    SUPPORTED_IMAGE_EXTENSIONS,
    is_sparse_pdf,
    ocr_image,
    ocr_pdf,
)
from app.assessment.transcription import (
    MAX_AUDIO_SIZE,
    SUPPORTED_AUDIO_EXTENSIONS,
    transcribe_audio,
)
from app.core.auth import verify_api_key
from app.core.errors import (
    AIProviderError,
    AIRateLimitError,
    PipelineTimeoutError,
    ReasoningPayloadTooLargeError,
    ReasoningUnavailableError,
    ValidationError,
)
from app.knowledge_base.parsers import SUPPORTED_EXTENSIONS, parse_pdf, extract_text
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
        return await run_reasoning_assessment(request, knowledge_base_context)
    except (PipelineTimeoutError, ReasoningPayloadTooLargeError, ReasoningUnavailableError):
        # These are already HTTPExceptions with the right status + detail — re-raise.
        raise
    except RateLimitError as e:
        logfire.warn("AI rate limit exceeded", error=str(e))
        raise AIRateLimitError()
    except (APIConnectionError, ConnectError, HTTPStatusError) as e:
        logfire.error("AI provider connection error", error=str(e))
        raise AIProviderError("AI provider unavailable.")
    except LangChainException as e:
        logfire.error("AI model error", error=str(e))
        raise AIProviderError()


@router.post("/assessments", response_model=AssessmentResult, response_model_by_alias=True)
async def create_assessment(request: AssessmentRequest) -> AssessmentResult:
    return await _run_with_error_handling(request)


MAX_DOCUMENT_SIZE = 10 * 1024 * 1024  # 10 MB
MAX_IMAGE_SIZE = 20 * 1024 * 1024  # 20 MB (GPT-4o Vision limit)

_ALL_DOCUMENT_EXTENSIONS = SUPPORTED_EXTENSIONS | SUPPORTED_IMAGE_EXTENSIONS


async def _extract_text_from_file(filename: str, content: bytes) -> str:
    """Extract text from any supported file, using OCR where needed."""
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if ext in SUPPORTED_IMAGE_EXTENSIONS:
        return await ocr_image(filename, content)

    if ext == ".pdf":
        text, page_count = parse_pdf(content)
        if is_sparse_pdf(text, page_count):
            logfire.info("Sparse PDF detected, falling back to OCR", filename=filename, page_count=page_count)
            text = await ocr_pdf(content)
        return text

    # txt / docx / md
    return extract_text(filename, content)


@router.post("/assessments/document", response_model=AssessmentResult, response_model_by_alias=True)
async def create_document_assessment(
    file: UploadFile,
    scorecard: str = Form(...),
    use_knowledge_base: bool = Form(False),
) -> AssessmentResult:
    if not file.filename:
        raise ValidationError("File must have a filename.")

    ext = "." + file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in _ALL_DOCUMENT_EXTENSIONS:
        supported = ", ".join(sorted(_ALL_DOCUMENT_EXTENSIONS))
        raise ValidationError(f"Unsupported file format '{ext}'. Supported: {supported}.")

    content = await file.read()
    if len(content) == 0:
        raise ValidationError("File is empty.")

    max_size = MAX_IMAGE_SIZE if ext in SUPPORTED_IMAGE_EXTENSIONS else MAX_DOCUMENT_SIZE
    if len(content) > max_size:
        limit_mb = max_size // (1024 * 1024)
        raise ValidationError(f"File exceeds maximum size of {limit_mb}MB.")

    try:
        scorecard_data = json.loads(scorecard)
        scorecard_obj = ScorecardDefinition.model_validate(scorecard_data)
    except (json.JSONDecodeError, Exception) as e:
        raise ValidationError(f"Invalid scorecard JSON: {e}")

    try:
        text = await _extract_text_from_file(file.filename, content)
    except ValueError as e:
        raise ValidationError(str(e))

    if len(text.strip()) < 50:
        raise ValidationError(
            f"Extracted text too short ({len(text)} chars). "
            "The file may be empty, purely visual with no readable text, or corrupt."
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
