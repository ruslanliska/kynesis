from pydantic import BaseModel, Field


class ScorecardCriterion(BaseModel):
    id: str
    name: str = Field(min_length=1)
    description: str
    weight: int = Field(ge=1, le=10)
    max_score: int = Field(ge=1, le=100)


class Scorecard(BaseModel):
    id: str
    name: str = Field(min_length=1)
    description: str = ""
    criteria: list[ScorecardCriterion] = Field(min_length=1)


class AssessmentRequest(BaseModel):
    scorecard: Scorecard
    content: str = Field(min_length=50, max_length=100_000)
    subject: str = ""
    use_knowledge_base: bool = False


class CriterionScore(BaseModel):
    criterion_id: str
    criterion_name: str
    score: int = Field(ge=0)
    max_score: int = Field(ge=1)
    feedback: str


class AssessmentResult(BaseModel):
    scorecard_id: str
    scorecard_name: str
    subject: str
    scores: list[CriterionScore]
    total_score: float = Field(ge=0, le=100)
    max_total_score: float = 100.0
    overall_feedback: str
    knowledge_base_used: bool = False
    knowledge_base_warning: str | None = None
