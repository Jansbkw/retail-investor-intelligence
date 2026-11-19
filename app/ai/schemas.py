from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


class PostAnalysis(BaseModel):
    relevant: bool
    sentiment: float = Field(ge=-1, le=1)
    sentiment_label: str
    topic: str = Field(min_length=1, max_length=80)
    is_question: bool
    question_text: str | None = None
    is_concern: bool
    concern_summary: str | None = None
    misinformation_flag: bool = False

    @model_validator(mode="after")
    def enforce_optional_fields(self) -> "PostAnalysis":
        if not self.is_question:
            self.question_text = None
        if not self.is_concern:
            self.concern_summary = None
        return self


class Citation(BaseModel):
    post_id: str
    url: str


class GroundedAnswer(BaseModel):
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    evidence_count: int = 0
    refused_investment_advice: bool = False

