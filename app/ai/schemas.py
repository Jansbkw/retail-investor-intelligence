from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SentimentLabel(StrEnum):
    BULLISH = "Bullish"
    BEARISH = "Bearish"
    NEUTRAL = "Neutral"
    UNCLEAR = "Unclear / Not investment-related"


class RelevanceClassification(StrEnum):
    INVESTOR_RELEVANT = "investor_relevant"
    COMPANY_NON_INVESTMENT = "company_related_non_investment"
    IRRELEVANT = "irrelevant"
    UNCLEAR = "unclear"


class Topic(StrEnum):
    FINANCIAL_PERFORMANCE = "Financial performance"
    EARNINGS_GUIDANCE = "Earnings and guidance"
    VALUATION = "Valuation"
    GROWTH_STRATEGY = "Growth strategy"
    PRODUCTS_OPERATIONS = "Products and operations"
    MANAGEMENT_GOVERNANCE = "Management and governance"
    REGULATION = "Regulation"
    MARKET_COMPETITION = "Market competition"
    CORPORATE_ACTIONS = "Corporate actions"
    OTHER = "Other"


class Concern(StrEnum):
    PROFITABILITY = "Profitability"
    DEBT = "Debt"
    MANAGEMENT_CREDIBILITY = "Management credibility"
    GROWTH_SUSTAINABILITY = "Growth sustainability"
    DILUTION = "Dilution"
    COMPETITIVE_THREATS = "Competitive threats"
    EXECUTION_RISK = "Execution risk"
    REGULATORY_RISK = "Regulatory risk"
    PRODUCT_QUALITY = "Product quality"
    OTHER = "Other"


class PostAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")
    relevant: bool
    relevance_classification: RelevanceClassification
    sentiment_label: SentimentLabel
    topics: list[Topic] = Field(default_factory=list, max_length=3)
    concerns: list[Concern] = Field(default_factory=list, max_length=3)
    confidence: float = Field(ge=0, le=1)
    explanation: str = Field(min_length=1, max_length=400)
    summary: str = Field(min_length=1, max_length=280)
    evidence_reference_ids: list[str] = Field(min_length=1, max_length=3)

    @model_validator(mode="after")
    def sentiment_for_irrelevant(self) -> "PostAnalysis":
        if not self.relevant:
            self.sentiment_label = SentimentLabel.UNCLEAR
            self.concerns = []
        return self


class Citation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    post_id: str
    url: str


class GroundedAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    answer: str
    supporting_findings: list[str] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    evidence_count: int = 0
    limitations: str | None = None
    refused_investment_advice: bool = False

