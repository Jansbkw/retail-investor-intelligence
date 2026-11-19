from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from datetime import datetime, timezone

from pydantic import BaseModel, Field, HttpUrl, field_validator


class Post(BaseModel):
    id: str
    platform: str
    ticker: str
    author_hash: str
    text: str
    url: str
    created_at: datetime
    engagement: int = Field(default=0, ge=0)
    content_hash: str = ""
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    synthetic: bool = False

    @field_validator("created_at", "fetched_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value

    def model_post_init(self, __context: object) -> None:
        if not self.content_hash:
            normalised = " ".join(self.text.lower().split())
            self.content_hash = hashlib.sha256(normalised.encode()).hexdigest()

    @staticmethod
    def hash_author(platform: str, username: str) -> str:
        return hashlib.sha256(f"{platform}:{username}".encode()).hexdigest()[:24]


class Collector(ABC):
    name: str

    @abstractmethod
    def fetch(self, ticker: str, since: datetime) -> list[Post]:
        """Fetch public posts. Implementations should raise descriptive errors."""

