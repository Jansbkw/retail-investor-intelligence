from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class RelevanceStatus(StrEnum):
    PENDING = "pending"
    RELEVANT = "relevant"
    REJECTED = "rejected"
    AMBIGUOUS = "ambiguous"


class EngagementMetrics(BaseModel):
    """Source metrics stay nullable: unavailable does not mean zero."""

    model_config = ConfigDict(extra="forbid")
    likes: int | None = Field(default=None, ge=0)
    replies: int | None = Field(default=None, ge=0)
    reshares: int | None = Field(default=None, ge=0)
    views: int | None = Field(default=None, ge=0)


class Post(BaseModel):
    """Unified, provenance-preserving public social record."""

    model_config = ConfigDict(extra="forbid")
    id: str = ""
    source: str
    source_post_id: str
    ticker: str
    company_name: str
    raw_text: str
    text: str = ""
    author_hash: str | None = None
    created_at: datetime
    collected_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source_url: str
    engagement_metrics: EngagementMetrics = Field(default_factory=EngagementMetrics)
    parent_content_id: str | None = None
    relevance_status: RelevanceStatus = RelevanceStatus.PENDING
    relevance_reason: str | None = None
    language: str | None = None
    raw_metadata: dict[str, Any] = Field(default_factory=dict)
    content_hash: str = ""
    synthetic: bool = False

    @field_validator("ticker")
    @classmethod
    def uppercase_ticker(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("created_at", "collected_at")
    @classmethod
    def normalise_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def derive_identity(self) -> "Post":
        if not self.text:
            self.text = self.raw_text
        if not self.id:
            self.id = f"{self.source}:{self.source_post_id}:{self.ticker}"
        if not self.content_hash:
            normalised = " ".join(self.text.casefold().split())
            material = f"{self.source}\0{self.ticker}\0{normalised}"
            self.content_hash = hashlib.sha256(material.encode()).hexdigest()
        return self

    @staticmethod
    def hash_author(source: str, source_author_id: str) -> str:
        return hashlib.sha256(f"{source}:{source_author_id}".encode()).hexdigest()[:24]


class CollectorError(RuntimeError):
    """Controlled source failure surfaced in coverage reporting."""


class MissingCredentialError(CollectorError):
    pass


class SourceUnavailableError(CollectorError):
    pass


class IdentityMismatchError(CollectorError):
    pass


class Collector(ABC):
    name: str

    @abstractmethod
    def fetch(self, ticker: str, since: datetime) -> list[Post]:
        """Fetch public posts or raise a controlled CollectorError."""

