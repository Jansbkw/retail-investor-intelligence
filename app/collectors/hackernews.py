from __future__ import annotations

import html
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any

import httpx

from app.collectors.base import Collector, EngagementMetrics, Post, SourceUnavailableError
from app.config import load_file_config


LOGGER = logging.getLogger(__name__)
API_URL = "https://hn.algolia.com/api/v1/search_by_date"
FINANCE_TERMS = re.compile(
    r"\b(stock|stocks|share|shares|share price|investor|investors|earnings|revenue|profit|"
    r"loss|guidance|dividend|valuation|market cap|financial results|debt|cash flow|buyback)\b",
    re.IGNORECASE,
)
PRODUCT_ECONOMICS_TERMS = re.compile(
    r"\b(development budget|development cost|preorders?|unit sales|copies sold|"
    r"commercial performance|break even)\b",
    re.IGNORECASE,
)


def plain_text(value: str | None) -> str:
    if not value:
        return ""
    without_tags = re.sub(r"<[^>]+>", " ", value)
    return " ".join(html.unescape(without_tags).split())


def hit_text(hit: dict[str, Any], kind: str) -> str:
    fields = (
        [hit.get("title"), hit.get("story_text")]
        if kind == "story"
        else [hit.get("story_title"), hit.get("comment_text")]
    )
    return "\n".join(plain_text(value) for value in fields if value)


def hit_raw_text(hit: dict[str, Any], kind: str) -> str:
    fields = (
        [hit.get("title"), hit.get("story_text")]
        if kind == "story"
        else [hit.get("story_title"), hit.get("comment_text")]
    )
    return "\n".join(str(value) for value in fields if value)


def identity_evidence(ticker: str, text: str) -> str | None:
    lowered = text.casefold()
    if ticker == "STB":
        for term in ("secure trust bank", "stb.l", "lon:stb", "lse:stb"):
            if term in lowered:
                return term
        return None
    if ticker == "VEON":
        if re.search(r"\bveon\b", lowered):
            return "VEON"
        for term in ("kyivstar", "jazz pakistan", "mobilink"):
            if term in lowered:
                return term
        if "beeline" in lowered and any(
            term in lowered for term in ("telecom", "wireless", "mobile operator", "veon")
        ):
            return "Beeline with telecom context"
        return None
    patterns = (
        (r"\bttwo\b", "TTWO"),
        (r"take[- ]two interactive", "Take-Two Interactive"),
        (r"\brockstar games\b", "Rockstar Games"),
        (r"\bgta\s*(?:vi|6)\b", "GTA VI"),
        (r"\bgrand theft auto\b", "Grand Theft Auto"),
    )
    for pattern, evidence in patterns:
        if re.search(pattern, lowered):
            return evidence
    return None


def is_investor_related(ticker: str, text: str) -> bool:
    lowered = text.casefold()
    if ticker == "TTWO":
        company_terms = re.compile(r"\bttwo\b|take[- ]two(?: interactive)?", re.IGNORECASE)
        product_terms = re.compile(
            r"\bgta\s*(?:vi|6)\b|grand theft auto|rockstar games", re.IGNORECASE,
        )
    elif ticker == "VEON":
        company_terms = re.compile(r"\bveon\b|kyivstar|jazz pakistan|mobilink", re.IGNORECASE)
        product_terms = company_terms
    else:
        company_terms = re.compile(
            r"secure trust bank|stb\.l|lon:stb|lse:stb", re.IGNORECASE,
        )
        product_terms = company_terms

    finance_hits = list(FINANCE_TERMS.finditer(lowered))
    company_hits = list(company_terms.finditer(lowered))
    if any(abs(left.start() - right.start()) <= 180 for left in company_hits for right in finance_hits):
        return True
    if ticker == "TTWO":
        product_hits = list(product_terms.finditer(lowered))
        economics_hits = list(PRODUCT_ECONOMICS_TERMS.finditer(lowered))
        return any(
            abs(left.start() - right.start()) <= 180
            for left in product_hits for right in economics_hits
        )
    return False


class HackerNewsCollector(Collector):
    """Collect public HN stories/comments through the documented Algolia API."""

    name = "hackernews"

    def __init__(self, client: httpx.Client | None = None) -> None:
        self.client = client or httpx.Client(
            timeout=20, headers={"User-Agent": "curation-retail-intelligence/1.0"},
        )

    def _page(self, query: str, kind: str, since: datetime, page: int) -> dict[str, Any]:
        params = {
            "query": query,
            "tags": kind,
            "numericFilters": f"created_at_i>={int(since.timestamp())}",
            "hitsPerPage": 100,
            "page": page,
        }
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                response = self.client.get(API_URL, params=params)
                if response.status_code == 429 or response.status_code >= 500:
                    raise httpx.HTTPStatusError(
                        f"HN Algolia temporary error {response.status_code}",
                        request=response.request, response=response,
                    )
                if response.status_code >= 400:
                    raise SourceUnavailableError(
                        f"HN Algolia unavailable ({response.status_code})"
                    )
                return response.json()
            except (httpx.HTTPError, ValueError) as exc:
                last_error = exc
                if attempt < 2:
                    time.sleep(0.25 * (2 ** attempt))
        raise SourceUnavailableError(f"HN Algolia request failed after retries: {last_error}")

    def fetch(self, ticker: str, since: datetime) -> list[Post]:
        config = load_file_config()
        company = config.companies[ticker]
        queries = company.hackernews_queries or [company.name]
        max_pages = config.collection.hackernews_max_pages_per_query
        max_records = config.collection.max_posts_per_platform
        collected_at = datetime.now(timezone.utc)
        unique: dict[str, Post] = {}
        successful_queries = 0
        failures: list[str] = []

        for query in queries:
            for kind in ("story", "comment"):
                page = 0
                while page < max_pages:
                    try:
                        payload = self._page(query, kind, since, page)
                        successful_queries += 1
                    except SourceUnavailableError as exc:
                        failures.append(f"{query}/{kind}: {exc}")
                        LOGGER.warning("hackernews_query_failed ticker=%s query=%r kind=%s", ticker, query, kind)
                        break
                    hits = payload.get("hits") or []
                    for hit in hits:
                        object_id = str(hit.get("objectID") or "")
                        if not object_id or object_id in unique:
                            continue
                        text = hit_text(hit, kind)
                        evidence = identity_evidence(ticker, text)
                        if not evidence:
                            continue
                        created_raw = hit.get("created_at")
                        if not created_raw:
                            continue
                        created = datetime.fromisoformat(created_raw.replace("Z", "+00:00"))
                        investor_related = is_investor_related(ticker, text)
                        author = str(hit.get("author") or "unknown")
                        story_id = hit.get("story_id") or (object_id if kind == "story" else None)
                        unique[object_id] = Post(
                            source=self.name,
                            source_post_id=object_id,
                            ticker=ticker,
                            company_name=company.name,
                            raw_text=hit_raw_text(hit, kind),
                            author_hash=Post.hash_author(self.name, author),
                            created_at=created,
                            collected_at=collected_at,
                            source_url=f"https://news.ycombinator.com/item?id={object_id}",
                            engagement_metrics=EngagementMetrics(
                                likes=hit.get("points"), replies=hit.get("num_comments"),
                            ),
                            parent_content_id=str(story_id) if story_id else None,
                            raw_metadata={
                                "content_type": kind,
                                "matched_query": query,
                                "identity_validated": True,
                                "identity_evidence": evidence,
                                "symbols": [ticker],
                                "investor_related": investor_related,
                                "discussion_classification": (
                                    "investor_related" if investor_related
                                    else "general_company_mention"
                                ),
                            },
                            synthetic=False,
                        )
                    page += 1
                    if not hits or page >= int(payload.get("nbPages") or 0):
                        break

        if not successful_queries and failures:
            raise SourceUnavailableError(failures[0])
        ranked = sorted(
            unique.values(),
            key=lambda post: (
                bool(post.raw_metadata.get("investor_related")), post.created_at,
            ),
            reverse=True,
        )
        return ranked[:max_records]
