from fastapi import APIRouter, Depends, UploadFile

from app.core.auth import verify_api_key
from app.core.errors import ValidationError
from app.knowledge_base.parsers import SUPPORTED_EXTENSIONS
from app.knowledge_base.schemas import (
    KBDeleteResponse,
    KBQueryRequest,
    KBQueryResponse,
    KnowledgeBaseUploadResponse,
)
from app.knowledge_base.services import (
    delete_knowledge_base,
    process_document,
    query_knowledge_base,
)

router = APIRouter(prefix="/api/v1", tags=["knowledge-bases"], dependencies=[Depends(verify_api_key)])

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB


@router.post("/scorecards/{scorecard_id}/knowledge-base/upload", response_model=KnowledgeBaseUploadResponse)
async def upload_document(
    scorecard_id: str,
    file: UploadFile,
    document_id: str | None = None,
) -> KnowledgeBaseUploadResponse:
    if not file.filename:
        raise ValidationError("File must have a filename.")

    # Validate extension
    ext = "." + file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in SUPPORTED_EXTENSIONS:
        supported = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        raise ValidationError(
            f"Unsupported file format '{ext}'. Supported: {supported}."
        )

    # Read and validate size
    content = await file.read()
    if len(content) == 0:
        raise ValidationError("File is empty.")
    if len(content) > MAX_FILE_SIZE:
        raise ValidationError("File exceeds maximum size of 10MB.")

    try:
        return await process_document(
            filename=file.filename,
            content=content,
            knowledge_base_id=scorecard_id,
            document_id=document_id,
        )
    except ValueError as e:
        raise ValidationError(str(e))


@router.post(
    "/scorecards/{scorecard_id}/knowledge-base/query",
    response_model=KBQueryResponse,
)
async def query_kb(scorecard_id: str, request: KBQueryRequest) -> KBQueryResponse:
    return await query_knowledge_base(scorecard_id, request.query, request.top_k)


@router.delete(
    "/scorecards/{scorecard_id}/knowledge-base",
    response_model=KBDeleteResponse,
)
async def delete_kb(scorecard_id: str) -> KBDeleteResponse:
    await delete_knowledge_base(scorecard_id)
    return KBDeleteResponse(knowledge_base_id=scorecard_id)
