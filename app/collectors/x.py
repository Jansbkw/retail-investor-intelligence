from __future__ import annotations

from datetime import datetime

import httpx

from app.collectors.base import Collector, EngagementMetrics, MissingCredentialError, Post, SourceUnavailableError
from app.config import Settings, get_settings, load_file_config


def build_search_query(
    ticker: str, company_name: str, aliases: list[str], *, ambiguous: bool
) -> str:
    """Build an entity-safe Recent Search query for the configured security."""
    if ambiguous:
        terms = [company_name, *aliases]
    else:
        terms = [f"${ticker}", ticker, company_name, *aliases]
    unique_terms = list(dict.fromkeys(term.strip() for term in terms if term.strip()))[:6]
    quoted = [term if term.startswith("$") or " " not in term else f'"{term}"' for term in unique_terms]
    return f"({' OR '.join(quoted)}) -is:retweet lang:en"


class XCollector(Collector):
    name = "x"

    def __init__(self, settings: Settings | None = None, client: httpx.Client | None = None) -> None:
        self.settings = settings or get_settings()
        self.client = client or httpx.Client(timeout=20)

    def fetch(self, ticker: str, since: datetime) -> list[Post]:
        if not self.settings.x_bearer_token:
            raise MissingCredentialError("X_BEARER_TOKEN is not configured")
        if not self.settings.allow_paid_x_calls:
            raise SourceUnavailableError("X collection disabled pending explicit paid-call approval")
        company = load_file_config().companies[ticker]
        query = build_search_query(
            ticker, company.name, company.aliases, ambiguous=company.ambiguous
        )
        response = self.client.get(
            "https://api.x.com/2/tweets/search/recent",
            headers={"Authorization": f"Bearer {self.settings.x_bearer_token}"},
            params={
                "query": query,
                "max_results": min(100, load_file_config().collection.max_posts_per_platform),
                "start_time": since.isoformat().replace("+00:00", "Z"),
                "tweet.fields": "created_at,public_metrics,author_id,lang,conversation_id",
            },
        )
        if response.status_code == 402:
            raise SourceUnavailableError(
                "X API payment required (402): the developer project needs active credits or access"
            )
        if response.status_code >= 400:
            raise SourceUnavailableError(
                f"X API unavailable ({response.status_code}): check query window, project tier, quota, and permissions"
            )
        posts: list[Post] = []
        for item in response.json().get("data", []):
            metrics = item.get("public_metrics") or {}
            posts.append(Post(
                source=self.name,
                source_post_id=item["id"],
                ticker=ticker,
                company_id=company.company_id,
                company_name=company.name,
                raw_text=item.get("text") or "",
                author_hash=Post.hash_author(self.name, item.get("author_id", "unknown")),
                created_at=datetime.fromisoformat(item["created_at"].replace("Z", "+00:00")),
                source_url=f"https://x.com/i/web/status/{item['id']}",
                engagement_metrics=EngagementMetrics(
                    likes=metrics.get("like_count"), replies=metrics.get("reply_count"),
                    reshares=metrics.get("retweet_count"), views=metrics.get("impression_count"),
                ),
                parent_content_id=item.get("conversation_id"),
                language=item.get("lang"),
                raw_metadata={"query": query},
                synthetic=False,
            ))
        return posts
