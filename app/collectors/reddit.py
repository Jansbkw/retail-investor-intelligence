from __future__ import annotations

from datetime import datetime, timezone

from app.collectors.base import Collector, Post
from app.config import Settings, get_settings, load_file_config


class RedditCollector(Collector):
    name = "reddit"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def fetch(self, ticker: str, since: datetime) -> list[Post]:
        if not self.settings.reddit_client_id or not self.settings.reddit_client_secret:
            raise RuntimeError("Reddit credentials are not configured")
        import praw

        reddit = praw.Reddit(
            client_id=self.settings.reddit_client_id,
            client_secret=self.settings.reddit_client_secret,
            user_agent=self.settings.reddit_user_agent,
            check_for_async=False,
        )
        company = load_file_config().companies[ticker]
        query = " OR ".join([ticker, company.name, *company.aliases])
        limit = load_file_config().collection.max_posts_per_platform
        posts: list[Post] = []
        for submission in reddit.subreddit("stocks+investing+wallstreetbets+SecurityAnalysis").search(
            query, sort="new", time_filter="year", limit=limit
        ):
            created = datetime.fromtimestamp(submission.created_utc, tz=timezone.utc)
            if created < since:
                continue
            text = f"{submission.title}\n{submission.selftext or ''}".strip()
            posts.append(
                Post(
                    id=f"reddit:{submission.id}",
                    platform=self.name,
                    ticker=ticker,
                    author_hash=Post.hash_author(self.name, str(submission.author or "deleted")),
                    text=text,
                    url=f"https://www.reddit.com{submission.permalink}",
                    created_at=created,
                    engagement=max(0, int(submission.score)) + int(submission.num_comments),
                )
            )
        return posts

