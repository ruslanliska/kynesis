from pydantic import BaseModel, Field

from app.assessment.schemas import AssessmentResult


class InsightIssue(BaseModel):
    title: str
    description: str
    frequency: int = Field(ge=1)
    severity: str  # high, medium, low


class InsightPattern(BaseModel):
    title: str
    description: str
    category: str


class InsightRecommendation(BaseModel):
    title: str
    description: str
    priority: str  # high, medium, low
    impact: str


class InsightArea(BaseModel):
    name: str
    score: float = Field(ge=0)
    suggestion: str | None = None


class InsightRequest(BaseModel):
    assessments: list[AssessmentResult] = Field(min_length=3)


class InsightReport(BaseModel):
    top_issues: list[InsightIssue]
    patterns: list[InsightPattern]
    recommendations: list[InsightRecommendation]
    summary: str
    strength_areas: list[InsightArea]
    weak_areas: list[InsightArea]
