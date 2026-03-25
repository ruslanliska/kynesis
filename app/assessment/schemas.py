from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True,
        alias_generator=to_camel,
    )


class ContentType(str, Enum):
    call_transcript = "call_transcript"
    chat_conversation = "chat_conversation"
    audio_conversation = "audio_conversation"
    code_review = "code_review"
    document = "document"
    other = "other"


# --- Input schemas ---


class ScorecardCriterion(CamelModel):
    id: str
    name: str = Field(min_length=1)
    description: str
    weight: int = Field(ge=1, le=10)
    max_score: int = Field(ge=1, le=100)
    order: int = 0


class Scorecard(CamelModel):
    id: str
    name: str = Field(min_length=1)
    description: str = ""
    criteria: list[ScorecardCriterion] = Field(min_length=1)
    version: int = 1
    is_active: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None


class AssessmentRequest(CamelModel):
    scorecard: Scorecard
    content: str = Field(min_length=50, max_length=100_000)
    content_type: ContentType = ContentType.other
    use_knowledge_base: bool = False


# --- Output schemas ---

PASS_THRESHOLD = 0.6


class CriterionResult(CamelModel):
    criterion_id: str
    score: float = Field(ge=0)
    max_score: int = Field(ge=1)
    passed: bool
    comment: str
    suggestions: str | None = None


class OverallResult(CamelModel):
    score: float = Field(ge=0, le=100)
    max_score: int = 100
    summary: str


class AssessmentResult(CamelModel):
    scorecard_id: str
    scorecard_version: int
    content_type: ContentType
    assessed_at: datetime
    overall: OverallResult
    criteria: list[CriterionResult]
