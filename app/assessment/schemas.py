import json
from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic.alias_generators import to_camel

from app.scorecards.schemas import CriticalType, ScorecardDefinition


class CamelModel(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True,
        alias_generator=to_camel,
    )


class AIProvider(str, Enum):
    openai = "openai"
    deepseek = "deepseek"


class ContentType(str, Enum):
    call_transcript = "call_transcript"
    chat_conversation = "chat_conversation"
    audio_conversation = "audio_conversation"
    code_review = "code_review"
    document = "document"
    image = "image"
    email = "email"
    other = "other"


class AssessmentType(str, Enum):
    standard = "standard"
    reasoning = "reasoning"


# --- Input schemas ---


class AssessmentRequest(CamelModel):
    scorecard: ScorecardDefinition
    content: str = Field(min_length=50, max_length=100_000)
    content_type: ContentType = ContentType.other
    use_knowledge_base: bool = False
    provider: AIProvider = AIProvider.deepseek
    assessment_type: AssessmentType = AssessmentType.standard

    @field_validator("content", mode="before")
    @classmethod
    def coerce_content_to_string(cls, v: Any) -> Any:
        if not isinstance(v, str):
            return json.dumps(v, ensure_ascii=False)
        return v

    @model_validator(mode="after")
    def _validate_has_questions(self) -> "AssessmentRequest":
        total = sum(len(s.questions) for s in self.scorecard.sections)
        if total == 0:
            raise ValueError("Scorecard must have at least one question to run an assessment.")
        return self


# --- Output schemas ---

PASS_THRESHOLD = 0.6


class QuestionResult(CamelModel):
    question_id: str
    section_id: str
    score: float = Field(ge=0)
    max_points: int = Field(ge=0)
    passed: bool
    critical: CriticalType
    comment: str
    suggestions: str | None = None
    # Feature 003: per-question rationale from the reasoning stage.
    # Empty string when the fallback path produced the result.
    rationale: str = Field(default="")


class SectionResult(CamelModel):
    section_id: str
    section_name: str
    score: float = Field(ge=0, le=100)
    weight: float | None = None


class OverallResult(CamelModel):
    score: float = Field(ge=0, le=100)
    max_score: int = 100
    passed: bool | None = None
    hard_critical_failure: bool = False
    summary: str
    # Feature 003: true when the two-stage flow fell back to the legacy single-shot
    # implementation (reasoning stage unavailable / exhausted retries).
    reasoning_unavailable: bool = Field(default=False)


class AssessmentResult(CamelModel):
    scorecard_id: str
    scorecard_version: int
    content_type: ContentType
    assessed_at: datetime
    overall: OverallResult
    sections: list[SectionResult]
    questions: list[QuestionResult]


# ---------------------------------------------------------------------------
# Internal schemas — feature 003-reasoning-aggregation
# Produced in-memory during a request; NOT returned to clients, NOT persisted.
# ---------------------------------------------------------------------------


class ReasoningQuestionRecord(BaseModel):
    """Per-question output from the reasoning stage.

    See specs/003-reasoning-aggregation/data-model.md.
    """

    question_id: str
    rationale: str
    thinking_trace: str | None = None
    status: Literal["ok", "degraded", "missing"] = "ok"


class AggregatedReasoning(BaseModel):
    """Complete reasoning bundle passed from reasoning_stage → structuring_stage."""

    scorecard_id: str
    content_type: ContentType
    content_preview: str
    records: list[ReasoningQuestionRecord]
    full_trace_available: bool = False


class StageOutcome(BaseModel):
    """Observability-facing record attached as a Logfire span attribute.

    Not returned to the caller.
    """

    stage: Literal["reasoning", "structuring", "fallback"]
    status: Literal["ok", "retry_exhausted", "timeout", "validation_failed"]
    attempts: int
    duration_ms: int
    error: str | None = None
