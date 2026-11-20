from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.collectors import StockTwitsCollector, XCollector, YouTubeCollector
from app.collectors.base import Collector, CollectorError, IdentityMismatchError, Post
from app.config import load_file_config
from app.db import init_db, save_coverage, upsert_posts
from app.pipeline.clean import normalise_and_dedupe
from app.pipeline.relevance import apply_relevance


LOGGER = logging.getLogger(__name__)


def default_collectors(stocktwits_export: str | Path | None = None) -> dict[str, Collector]:
    return {
        "stocktwits": StockTwitsCollector(stocktwits_export),
        "youtube": YouTubeCollector(),
        "x": XCollector(),
    }


def ingest(
    *, tickers: list[str] | None = None, sources: list[str] | None = None,
    days: int | None = None, now: datetime | None = None,
    collectors: dict[str, Collector] | None = None,
    db_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    config = load_file_config()
    selected_tickers = [ticker.upper() for ticker in (tickers or list(config.companies))]
    selected_sources = sources or config.collection.platforms
    unknown = sorted(set(selected_tickers) - set(config.companies))
    if unknown:
        raise ValueError(f"Unknown ticker(s): {', '.join(unknown)}")
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    since = current - timedelta(days=days or config.collection.default_days)
    run_id = f"ingest-{current:%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:8]}"
    adapters = collectors or default_collectors()
    init_db(db_path)
    reports: list[dict[str, Any]] = []

    for ticker in selected_tickers:
        company = config.companies[ticker]
        for source in selected_sources:
            report: dict[str, Any] = {
                "run_id": run_id, "ticker": ticker, "source": source, "status": "unavailable",
                "raw_count": 0, "relevant_count": 0, "rejected_count": 0,
                "duplicates_removed": 0, "new_records": 0, "earliest_at": None,
                "latest_at": None, "error": None, "restrictions": None,
                "limitations": None, "collected_at": current.isoformat(),
            }
            adapter = adapters.get(source)
            if not adapter:
                report["error"] = f"No collector configured for {source}"
                save_coverage(report, db_path)
                reports.append(report)
                continue
            try:
                raw = adapter.fetch(ticker, since)
                report["raw_count"] = len(raw)
                normalised, duplicates = normalise_and_dedupe(raw)
                report["duplicates_removed"] = duplicates
                accepted: list[Post] = [apply_relevance(post, company) for post in normalised]
                report["relevant_count"] = sum(p.relevance_status.value == "relevant" for p in accepted)
                report["rejected_count"] = len(accepted) - report["relevant_count"]
                report["new_records"] = upsert_posts(accepted, db_path)
                timestamps = [p.created_at for p in accepted]
                if timestamps:
                    report["earliest_at"] = min(timestamps).isoformat()
                    report["latest_at"] = max(timestamps).isoformat()
                report["status"] = "success" if report["relevant_count"] else "no_relevant_data"
                if source == "stocktwits":
                    report["limitations"] = "MCP stream snapshot; not a complete historical firehose"
                elif source == "youtube":
                    report["limitations"] = "Search and top-level comments only; quota bounded"
                elif source == "x":
                    report["restrictions"] = "Recent Search access and billing depend on the X project tier"
            except CollectorError as exc:
                report["error"] = str(exc)
                report["status"] = "identity_mismatch" if isinstance(exc, IdentityMismatchError) else "unavailable"
                LOGGER.warning("collection_unavailable ticker=%s source=%s error=%s", ticker, source, exc)
            except Exception as exc:
                report["error"] = f"{type(exc).__name__}: {exc}"
                report["status"] = "failed"
                LOGGER.exception("collection_failed ticker=%s source=%s", ticker, source)
            save_coverage(report, db_path)
            reports.append(report)
    return reports
