from __future__ import annotations

from datetime import datetime

import httpx

from app.collectors.base import Collector, Post
from app.config import Settings, get_settings, load_file_config


class StockTwitsCollector(Collector):
    name = "stocktwits"

    def __init__(self, settings: Settings | None = None, client: httpx.Client | None = None) -> None:
        self.settings = settings or get_settings()
        self.client = client or httpx.Client(timeout=15, follow_redirects=True)

    def fetch(self, ticker: str, since: datetime) -> list[Post]:
        url = f"{self.settings.stocktwits_base_url.rstrip('/')}/streams/symbol/{ticker}.json"
        response = self.client.get(url)
        response.raise_for_status()
        limit = load_file_config().collection.max_posts_per_platform
        posts: list[Post] = []
        for message in response.json().get("messages", [])[:limit]:
            created = datetime.fromisoformat(message["created_at"].replace("Z", "+00:00"))
            if created < since:
                continue
            user = message.get("user") or {}
            posts.append(
                Post(
                    id=f"stocktwits:{message['id']}",
                    platform=self.name,
                    ticker=ticker,
                    author_hash=Post.hash_author(self.name, str(user.get("id", "unknown"))),
                    text=message.get("body", ""),
                    url=f"https://stocktwits.com/{user.get('username', 'symbol')}/message/{message['id']}",
                    created_at=created,
                    engagement=int(message.get("likes", {}).get("total", 0)),
                )
            )
        return posts

