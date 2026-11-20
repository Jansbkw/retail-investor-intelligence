from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT = Path(__file__).resolve().parents[1]


class SourceIdentity(BaseModel):
    symbol: str
    expected_title: str
    expected_exchange: str


class SecurityCandidate(BaseModel):
    """One exchange-qualified entity that may share a ticker symbol."""

    entity_id: str
    name: str
    symbol: str
    exchange: str
    isin: str | None = None
    status: Literal["active", "historical", "mis_tagged", "non_company"] = "active"
    aliases: list[str] = Field(default_factory=list)


class CompanyConfig(BaseModel):
    name: str
    exchange: str
    aliases: list[str] = Field(default_factory=list)
    youtube_queries: list[str] = Field(default_factory=list)
    hackernews_queries: list[str] = Field(default_factory=list)
    exclusions: list[str] = Field(default_factory=list)
    ambiguous: bool = False
    source_identities: dict[str, SourceIdentity] = Field(default_factory=dict)
    security_candidates: list[SecurityCandidate] = Field(default_factory=list)


class CollectionConfig(BaseModel):
    default_days: int = 30
    platforms: list[str] = Field(default_factory=lambda: ["stocktwits", "youtube", "hackernews"])
    max_posts_per_platform: int = 100
    hackernews_max_pages_per_query: int = 5
    stocktwits_export_path: str = "data/live/stocktwits_mcp_2026-11-20.json"
    stocktwits_entity_discovery_path: str = "data/live/stocktwits_stb_entity_discovery_mcp_2026-11-20.json"


class UIConfig(BaseModel):
    default_days: int = 30
    day_options: list[int] = Field(default_factory=lambda: [7, 30])


class AIConfig(BaseModel):
    prompt_version: str = "enrichment-v2"
    batch_size: int = 10
    max_retries: int = 3
    request_timeout_seconds: float = 30.0
    retrieval_k: int = 8
    minimum_evidence: int = 2
    estimated_cost_per_million_input_tokens: float = 0.40
    estimated_cost_per_million_output_tokens: float = 1.60


class FileConfig(BaseModel):
    companies: dict[str, CompanyConfig]
    collection: CollectionConfig = Field(default_factory=CollectionConfig)
    ui: UIConfig = Field(default_factory=UIConfig)
    ai: AIConfig = Field(default_factory=AIConfig)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )
    app_env: str = "development"
    database_path: Path = ROOT / "data" / "retail_intelligence.db"
    config_path: Path = ROOT / "config.yaml"
    data_mode: Literal["live", "fixture"] = "live"
    openai_api_key: str | None = None
    openai_model_small: str | None = None
    openai_model_large: str | None = None
    openai_embedding_model: str | None = None
    youtube_api_key: str | None = None
    x_bearer_token: str | None = None
    finnhub_api_key: str | None = None
    allow_paid_x_calls: bool = False
    cors_origins: str = "http://localhost:8501"
    api_base_url: str = "http://localhost:8000"

    def resolved_database_path(self) -> Path:
        return self.database_path if self.database_path.is_absolute() else ROOT / self.database_path

    def resolved_config_path(self) -> Path:
        return self.config_path if self.config_path.is_absolute() else ROOT / self.config_path

    @property
    def llm_enabled(self) -> bool:
        return bool(self.openai_api_key and self.openai_model_small)

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


@lru_cache(maxsize=4)
def load_file_config(path: str | None = None) -> FileConfig:
    settings = get_settings()
    config_path = Path(path) if path else settings.resolved_config_path()
    with config_path.open(encoding="utf-8") as handle:
        raw: dict[str, Any] = yaml.safe_load(handle)
    return FileConfig.model_validate(raw)


def reset_config_cache() -> None:
    get_settings.cache_clear()
    load_file_config.cache_clear()
