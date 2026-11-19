from __future__ import annotations

from datetime import datetime

from app.collectors.base import Collector, Post
from app.config import Settings, get_settings, load_file_config


class YouTubeCollector(Collector):
    name = "youtube"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def fetch(self, ticker: str, since: datetime) -> list[Post]:
        if not self.settings.youtube_api_key:
            raise RuntimeError("YouTube API key is not configured")
        from googleapiclient.discovery import build

        service = build("youtube", "v3", developerKey=self.settings.youtube_api_key)
        company = load_file_config().companies[ticker]
        query = f"{ticker} {company.name} stock"
        max_results = min(25, load_file_config().collection.max_posts_per_platform)
        search = service.search().list(
            part="id", q=query, type="video", order="date", maxResults=max_results
        ).execute()
        posts: list[Post] = []
        for item in search.get("items", []):
            video_id = item["id"]["videoId"]
            try:
                comments = service.commentThreads().list(
                    part="snippet", videoId=video_id, maxResults=100, textFormat="plainText"
                ).execute()
            except Exception:
                continue
            for thread in comments.get("items", []):
                snippet = thread["snippet"]["topLevelComment"]["snippet"]
                created = datetime.fromisoformat(snippet["publishedAt"].replace("Z", "+00:00"))
                if created < since:
                    continue
                comment_id = thread["snippet"]["topLevelComment"]["id"]
                posts.append(
                    Post(
                        id=f"youtube:{comment_id}",
                        platform=self.name,
                        ticker=ticker,
                        author_hash=Post.hash_author(self.name, snippet.get("authorChannelId", {}).get("value", "unknown")),
                        text=snippet.get("textDisplay", ""),
                        url=f"https://www.youtube.com/watch?v={video_id}&lc={comment_id}",
                        created_at=created,
                        engagement=int(snippet.get("likeCount", 0)),
                    )
                )
        return posts
