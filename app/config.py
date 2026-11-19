from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT = Path(__file__).resolve().parents[1]


class CompanyConfig(BaseModel):
    name: str
    exchange: str
    aliases: list[str] = Field(default_factory=list)
    ambiguous: bool = False


class CollectionConfig(BaseModel):
    default_days: int = 90
    platforms: list[str] = Field(default_factory=lambda: ["reddit", "stocktwits", "youtube"])
    max_posts_per_platform: int = 100


class UIConfig(BaseModel):
    default_days: int = 30
    day_options: list[int] = Field(default_factory=lambda: [7, 30, 90])


class AIConfig(BaseModel):
    prompt_version: str = "v1"
    batch_size: int = 10
    max_retries: int = 3
    retrieval_k: int = 8
    minimum_evidence: int = 2
    estimated_cost_per_million_input_tokens: float = 0.4
    estimated_cost_per_million_output_tokens: float = 1.6


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
    data_mode: Literal["synthetic", "live"] = "synthetic"

    openai_api_key: str | None = None
    openai_model_small: str | None = None
    openai_model_large: str | None = None
    openai_embedding_model: str | None = None

    reddit_client_id: str | None = None
    reddit_client_secret: str | None = None
    reddit_user_agent: str = "retail-investor-intelligence/0.1"
    youtube_api_key: str | None = None
    stocktwits_base_url: str = "https://api.stocktwits.com/api/2"

    def resolved_database_path(self) -> Path:
        path = self.database_path
        return path if path.is_absolute() else ROOT / path

    def resolved_config_path(self) -> Path:
        path = self.config_path
        return path if path.is_absolute() else ROOT / path

    @property
    def llm_enabled(self) -> bool:
        return bool(self.openai_api_key and self.openai_model_small)


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

