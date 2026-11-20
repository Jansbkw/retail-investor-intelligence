from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from app.collectors.base import Collector, EngagementMetrics, IdentityMismatchError, Post, SourceUnavailableError
from app.config import CompanyConfig, load_file_config


class StockTwitsCollector(Collector):
    """Normalise records exported by the separately authorised Stocktwits MCP."""

    name = "stocktwits"

    def __init__(self, export_path: str | Path | None = None) -> None:
        configured = load_file_config().collection.stocktwits_export_path
        candidate = Path(export_path or configured)
        if export_path is None and not candidate.is_absolute():
            candidate = Path(__file__).resolve().parents[2] / candidate
        self.export_path = candidate

    @staticmethod
    def validate_identity(ticker: str, company: CompanyConfig, metadata: dict[str, Any]) -> None:
        expected = company.source_identities.get("stocktwits")
        if not expected:
            raise IdentityMismatchError(f"No Stocktwits identity configured for {ticker}")
        actual = metadata.get("symbol") or ""
        title = metadata.get("title") or ""
        exchange = metadata.get("exchange") or ""
        if (
            actual.upper() != expected.symbol.upper()
            or title.casefold() != expected.expected_title.casefold()
            or exchange.casefold() != expected.expected_exchange.casefold()
        ):
            raise IdentityMismatchError(
                f"{ticker} identity mismatch: expected {expected.expected_title} "
                f"({expected.expected_exchange}), got {title or 'unknown'} ({exchange or 'unknown'})"
            )

    def fetch(self, ticker: str, since: datetime) -> list[Post]:
        if not self.export_path.exists():
            raise SourceUnavailableError("Stocktwits MCP export is missing; connect and export records first")
        with self.export_path.open(encoding="utf-8") as handle:
            payload = json.load(handle)
        if payload.get("provenance") != "stocktwits_mcp":
            raise SourceUnavailableError("Refusing a Stocktwits export without MCP provenance")
        company = load_file_config().companies[ticker]
        symbol_metadata = (payload.get("symbols") or {}).get(ticker)
        if not symbol_metadata:
            coverage = (payload.get("coverage") or {}).get(ticker, {})
            error = coverage.get("error")
            if coverage.get("status") == "identity_mismatch":
                raise IdentityMismatchError(error or f"Stocktwits identity mismatch for {ticker}")
            raise SourceUnavailableError(error or f"No validated Stocktwits symbol for {ticker}")
        self.validate_identity(ticker, company, symbol_metadata)

        posts: list[Post] = []
        for message in (payload.get("messages") or {}).get(ticker, []):
            created = datetime.fromisoformat(message["created_at"].replace("Z", "+00:00"))
            if created < since:
                continue
            user = message.get("user") or {}
            author_hash = message.get("author_hash")
            if not author_hash and user.get("id") is not None:
                author_hash = Post.hash_author(self.name, str(user["id"]))
            metadata = {
                "symbols": message.get("symbols", []),
                "source_client": message.get("source"),
                "source_sentiment": message.get("sentiment"),
                "image_url": message.get("image_url"),
                "link": message.get("link"),
                "identity_validated": True,
                "symbol_id": symbol_metadata.get("id"),
            }
            posts.append(Post(
                source=self.name,
                source_post_id=str(message["id"]),
                ticker=ticker,
                company_name=company.name,
                raw_text=message.get("body") or "",
                author_hash=author_hash,
                created_at=created,
                collected_at=datetime.fromisoformat(payload["collected_at"].replace("Z", "+00:00")),
                source_url=f"https://stocktwits.com/message/{message['id']}",
                engagement_metrics=EngagementMetrics(
                    likes=message.get("likes"), replies=message.get("replies"),
                    reshares=message.get("reshares"), views=message.get("views"),
                ),
                raw_metadata=metadata,
                synthetic=False,
            ))
        return posts
