from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import TypeVar

from openai import OpenAI
from pydantic import BaseModel
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from app.config import AIConfig, Settings, get_settings, load_file_config
from app.db import transaction


LOGGER = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)


class LLMClient:
    def __init__(self, settings: Settings | None = None, ai_config: AIConfig | None = None) -> None:
        self.settings = settings or get_settings()
        self.ai_config = ai_config or load_file_config().ai
        self.client = OpenAI(api_key=self.settings.openai_api_key) if self.settings.openai_api_key else None

    @retry(
        retry=retry_if_exception_type((TimeoutError, ConnectionError)),
        wait=wait_exponential_jitter(initial=1, max=10),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    def structured(self, *, operation: str, model: str, system: str, user: str, schema: type[T]) -> T:
        if not self.client:
            raise RuntimeError("OPENAI_API_KEY is not configured")
        started = time.perf_counter()
        response = self.client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": schema.__name__,
                    "strict": True,
                    "schema": schema.model_json_schema(),
                },
            },
            temperature=0,
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
        result = schema.model_validate_json(response.choices[0].message.content or "{}")
        usage = response.usage
        input_tokens = usage.prompt_tokens if usage else 0
        output_tokens = usage.completion_tokens if usage else 0
        cost = (
            input_tokens * self.ai_config.estimated_cost_per_million_input_tokens
            + output_tokens * self.ai_config.estimated_cost_per_million_output_tokens
        ) / 1_000_000
        self._log_call(operation, model, input_tokens, output_tokens, latency_ms, cost)
        LOGGER.info(
            "llm_call operation=%s model=%s tokens=%s/%s latency_ms=%s cost_usd=%.6f",
            operation, model, input_tokens, output_tokens, latency_ms, cost,
        )
        return result

    def embedding(self, text: str) -> list[float]:
        if not self.client or not self.settings.openai_embedding_model:
            raise RuntimeError("OpenAI embedding configuration is missing")
        started = time.perf_counter()
        response = self.client.embeddings.create(
            model=self.settings.openai_embedding_model,
            input=text,
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
        tokens = response.usage.total_tokens if response.usage else 0
        self._log_call("embedding", self.settings.openai_embedding_model, tokens, 0, latency_ms, 0)
        return response.data[0].embedding

    @staticmethod
    def _log_call(
        operation: str, model: str, input_tokens: int, output_tokens: int,
        latency_ms: int, cost: float,
    ) -> None:
        with transaction() as connection:
            connection.execute(
                """
                INSERT INTO llm_calls(operation, model, input_tokens, output_tokens, latency_ms,
                                      estimated_cost_usd, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (operation, model, input_tokens, output_tokens, latency_ms, cost,
                 datetime.now(timezone.utc).isoformat()),
            )
