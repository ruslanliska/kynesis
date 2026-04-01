from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True,
        alias_generator=to_camel,
    )


class ScorecardStatus(str, Enum):
    draft = "draft"
    active = "active"
    archived = "archived"


class ScoringMode(str, Enum):
    add = "add"
    deduct = "deduct"


class ScoringType(str, Enum):
    binary = "binary"
    scale = "scale"
    numeric = "numeric"
    tag_only = "tag_only"


class CriticalType(str, Enum):
    none = "none"
    soft = "soft"
    hard = "hard"


class ScorecardOption(CamelModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    label: str = Field(min_length=1)
    value: int
    points_change: float
    order_index: int


class ScorecardQuestion(CamelModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    text: str = Field(min_length=1)
    description: str = ""
    scoring_type: ScoringType
    max_points: int = Field(ge=0)
    required: bool = True
    critical: CriticalType = CriticalType.none
    order_index: int
    options: list[ScorecardOption] = []


class ScorecardSection(CamelModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str = Field(min_length=1)
    description: str = ""
    order_index: int
    weight: float | None = None
    questions: list[ScorecardQuestion] = []


class ScorecardDefinition(CamelModel):
    """Full scorecard definition used by the scorecard builder (import/export)."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str = Field(min_length=1)
    description: str = ""
    status: ScorecardStatus = ScorecardStatus.draft
    scoring_mode: ScoringMode = ScoringMode.add
    passing_threshold: float | None = Field(default=None, ge=0, le=100)
    allow_question_comments: bool = True
    allow_overall_comment: bool = True
    show_points_to_evaluator: bool = True
    version: int = Field(default=1, ge=1)
    sections: list[ScorecardSection] = []

    @model_validator(mode="after")
    def _validate_section_weights(self) -> "ScorecardDefinition":
        weights = [s.weight for s in self.sections if s.weight is not None]
        if weights and len(weights) == len(self.sections):
            total = sum(weights)
            if abs(total - 100) > 0.01:
                raise ValueError(
                    f"Section weights must sum to 100 when all sections are weighted "
                    f"(current sum: {total})."
                )
        return self
