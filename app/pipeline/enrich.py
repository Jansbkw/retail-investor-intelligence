from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any, Protocol

from app.ai.llm import LLMClient
from app.ai.prompts import ENRICHMENT_SYSTEM, ENRICHMENT_USER
from app.ai.schemas import PostAnalysis
from app.config import get_settings, load_file_config
from app.db import analysis_is_current, cache_get, cache_put, get_posts, save_analysis


LOGGER = logging.getLogger(__name__)


class StructuredLLM(Protocol):
    def structured(self, *, operation: str, model: str, system: str,
                   user: str, schema: type[PostAnalysis]) -> PostAnalysis: ...


def _cache_key(content_hash: str, ticker: str, model: str, prompt_version: str) -> str:
    return hashlib.sha256(f"{content_hash}:{ticker}:{model}:{prompt_version}".encode()).hexdigest()


def enrich_posts(
    *, tickers: list[str] | None = None, llm: StructuredLLM | None = None,
    model: str | None = None, db_path: str | Path | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    config = load_file_config()
    selected_model = model or settings.openai_model_small
    if not selected_model:
        raise RuntimeError("OPENAI_MODEL_SMALL is not configured")
    client = llm or LLMClient(db_path=db_path)
    rows = []
    for ticker in tickers or list(config.companies):
        rows.extend(get_posts(ticker=ticker, relevant_only=True, path=db_path))
    report: dict[str, Any] = {
        "candidates": len(rows), "enriched": 0, "cached": 0,
        "skipped_current": 0, "failures": 0, "errors": [],
    }
    for row in rows:
        post_id = row["id"]
        if analysis_is_current(post_id, row["content_hash"], selected_model,
                               config.ai.prompt_version, db_path):
            report["skipped_current"] += 1
            continue
        key = _cache_key(row["content_hash"], row["ticker"], selected_model, config.ai.prompt_version)
        cached = cache_get(key, db_path)
        try:
            if cached:
                analysis = PostAnalysis.model_validate_json(cached)
                report["cached"] += 1
            else:
                company = config.companies[row["ticker"]]
                user = ENRICHMENT_USER.format(
                    company_name=company.name, ticker=row["ticker"], exchange=company.exchange,
                    post_id=post_id, source=row["source"], post_text=row["text"][:4000],
                )
                analysis = client.structured(
                    operation="enrichment", model=selected_model,
                    system=ENRICHMENT_SYSTEM, user=user, schema=PostAnalysis,
                )
                if analysis.evidence_reference_ids != [post_id]:
                    raise ValueError("LLM evidence reference did not match the supplied record id")
                cache_put(key, analysis.model_dump_json(), selected_model, config.ai.prompt_version, db_path)
            save_analysis(
                post_id, row["content_hash"], analysis.model_dump(mode="json"),
                selected_model, config.ai.prompt_version, path=db_path,
            )
            report["enriched"] += 1
        except Exception as exc:
            report["failures"] += 1
            message = f"{post_id}: {type(exc).__name__}: {exc}"
            report["errors"].append(message)
            LOGGER.exception("enrichment_failed post_id=%s", post_id)
            save_analysis(
                post_id, row["content_hash"], {
                    "relevant": False, "relevance_classification": "unclear",
                    "sentiment_label": "Unclear / Not investment-related", "topics": [],
                    "concerns": [], "confidence": 0, "explanation": "Processing failed",
                    "summary": "No analysis available", "evidence_reference_ids": [post_id],
                }, selected_model, config.ai.prompt_version, status="failed", error=str(exc), path=db_path,
            )
    return report


def import_enrichment(path: str | Path, db_path: str | Path | None = None) -> dict[str, int]:
    """Import schema-validated enrichment produced by an approved configured LLM."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    model = payload["model"]
    prompt_version = payload["prompt_version"]
    rows = {row["id"]: row for ticker in load_file_config().companies for row in get_posts(ticker=ticker, path=db_path)}
    imported = failures = 0
    for item in payload.get("analyses", []):
        try:
            post_id = item["post_id"]
            row = rows[post_id]
            analysis = PostAnalysis.model_validate(item["analysis"])
            if analysis.evidence_reference_ids != [post_id]:
                raise ValueError("invalid evidence id")
            save_analysis(post_id, row["content_hash"], analysis.model_dump(mode="json"),
                          model, prompt_version, path=db_path)
            imported += 1
        except Exception:
            failures += 1
            LOGGER.exception("enrichment_import_failed")
    return {"imported": imported, "failures": failures}

