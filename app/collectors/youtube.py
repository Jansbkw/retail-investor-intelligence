from __future__ import annotations

import logging
from datetime import datetime

from app.collectors.base import Collector, EngagementMetrics, MissingCredentialError, Post, SourceUnavailableError
from app.config import Settings, get_settings, load_file_config


LOGGER = logging.getLogger(__name__)


def build_search_query(
    ticker: str, company_name: str, aliases: list[str], *, ambiguous: bool
) -> str:
    """Avoid bare ambiguous tickers, which can resolve to unrelated securities."""
    if ambiguous:
        plain_name = company_name.removesuffix(" plc").strip()
        return f'"{plain_name}" stock investor'
    terms = [ticker, company_name, *aliases]
    unique_terms = list(dict.fromkeys(term.strip() for term in terms if term.strip()))[:6]
    expression = " | ".join(f'"{term}"' if " " in term else term for term in unique_terms)
    return f'({expression}) stock investor'


def video_identity_match(
    ticker: str, title: str, description: str, aliases: list[str], *, ambiguous: bool
) -> str | None:
    """Return the company-specific term that validates the parent video."""
    context = f"{title}\n{description}".casefold()
    for alias in aliases:
        if alias.casefold() in context:
            return alias
    if not ambiguous and ticker.casefold() in context:
        return ticker
    return None


class YouTubeCollector(Collector):
    name = "youtube"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def fetch(self, ticker: str, since: datetime) -> list[Post]:
        if not self.settings.youtube_api_key:
            raise MissingCredentialError("YOUTUBE_API_KEY is not configured")
        from googleapiclient.discovery import build

        service = build("youtube", "v3", developerKey=self.settings.youtube_api_key, cache_discovery=False)
        company = load_file_config().companies[ticker]
        queries = company.youtube_queries or [build_search_query(
            ticker, company.name, company.aliases, ambiguous=company.ambiguous
        )]
        posts: list[Post] = []
        seen_videos: set[str] = set()
        seen_comments: set[str] = set()
        successful_searches = 0
        last_search_error: Exception | None = None
        post_limit = load_file_config().collection.max_posts_per_platform
        for query in queries:
            try:
                result = service.search().list(
                    part="id,snippet", q=query, type="video", order="date",
                    publishedAfter=since.isoformat().replace("+00:00", "Z"), maxResults=5,
                ).execute()
                successful_searches += 1
            except Exception as exc:
                last_search_error = exc
                LOGGER.warning(
                    "youtube_search_unavailable ticker=%s query=%r error=%s",
                    ticker, query, type(exc).__name__,
                )
                continue
            for video in result.get("items", []):
                video_id = video["id"]["videoId"]
                if video_id in seen_videos:
                    continue
                seen_videos.add(video_id)
                title = video.get("snippet", {}).get("title", "")
                description = video.get("snippet", {}).get("description", "")
                identity_match = video_identity_match(
                    ticker, title, description, [company.name, *company.aliases],
                    ambiguous=company.ambiguous,
                )
                if not identity_match:
                    LOGGER.info("youtube_video_identity_rejected ticker=%s video=%s", ticker, video_id)
                    continue
                try:
                    comments = service.commentThreads().list(
                        part="snippet", videoId=video_id, maxResults=100, textFormat="plainText"
                    ).execute()
                except Exception as exc:
                    LOGGER.warning(
                        "youtube_comments_unavailable video=%s error=%s", video_id, type(exc).__name__
                    )
                    continue
                for thread in comments.get("items", []):
                    top = thread["snippet"]["topLevelComment"]
                    snippet = top["snippet"]
                    created = datetime.fromisoformat(snippet["publishedAt"].replace("Z", "+00:00"))
                    comment_id = top["id"]
                    if created < since or comment_id in seen_comments:
                        continue
                    seen_comments.add(comment_id)
                    author_id = (snippet.get("authorChannelId") or {}).get("value", "unknown")
                    posts.append(Post(
                        source=self.name,
                        source_post_id=comment_id,
                        ticker=ticker,
                        company_id=company.company_id,
                        company_name=company.name,
                        raw_text=snippet.get("textDisplay") or "",
                        author_hash=Post.hash_author(self.name, author_id),
                        created_at=created,
                        source_url=f"https://www.youtube.com/watch?v={video_id}&lc={comment_id}",
                        engagement_metrics=EngagementMetrics(
                            likes=snippet.get("likeCount"),
                            replies=thread["snippet"].get("totalReplyCount"),
                        ),
                        parent_content_id=video_id,
                        raw_metadata={
                            "video_title": title, "video_description": description,
                            "search_query": query, "identity_validated": True,
                            "identity_evidence": identity_match, "symbols": [ticker],
                        },
                        synthetic=False,
                    ))
                    if len(posts) >= post_limit:
                        return posts
        if not successful_searches and last_search_error:
            raise SourceUnavailableError(
                f"YouTube API unavailable ({type(last_search_error).__name__}): "
                "check key, quota, and permissions"
            ) from last_search_error
        return posts
