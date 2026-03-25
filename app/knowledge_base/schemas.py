from pydantic import BaseModel, Field


class KnowledgeBaseUploadResponse(BaseModel):
    knowledge_base_id: str
    document_id: str
    chunk_count: int = Field(ge=0)
    status: str  # "processed" or "replaced"


class KBQueryRequest(BaseModel):
    query: str = Field(min_length=1)
    top_k: int = Field(default=5, ge=1, le=20)


class KBQueryResult(BaseModel):
    text: str
    score: float
    document_id: str
    source_filename: str
    chunk_index: int


class KBQueryResponse(BaseModel):
    knowledge_base_id: str
    results: list[KBQueryResult]


class KBDeleteResponse(BaseModel):
    knowledge_base_id: str
    status: str = "deleted"
