from __future__ import annotations

import html
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.collectors.base import Post


WHITESPACE = re.compile(r"\s+")
ZERO_WIDTH = re.compile(r"[\u200b-\u200d\ufeff]")
TEXT_URL = re.compile(r"https?://[^\s<>]+")


def clean_text(text: str) -> str:
    value = html.unescape(html.unescape(text or ""))
    value = re.sub(r"<[^>]+>", " ", value)
    value = ZERO_WIDTH.sub("", value)
    value = TEXT_URL.sub(lambda match: clean_url(match.group(0)), value)
    return WHITESPACE.sub(" ", value).strip()


def clean_url(url: str) -> str:
    try:
        parts = urlsplit(url)
        query = [(key, value) for key, value in parse_qsl(parts.query) if not key.startswith("utm_") and key != "ref"]
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))
    except ValueError:
        return url


def normalise_post(post: Post) -> Post:
    data = post.model_dump()
    data["text"] = clean_text(post.raw_text)
    data["source_url"] = clean_url(post.source_url)
    data["content_hash"] = ""
    return Post.model_validate(data)


def normalise_and_dedupe(posts: list[Post]) -> tuple[list[Post], int]:
    unique: dict[tuple[str, str, str], Post] = {}
    seen_content: set[tuple[str, str, str]] = set()
    duplicate_count = 0
    for post in posts:
        cleaned = normalise_post(post)
        key = (cleaned.source, cleaned.source_post_id, cleaned.ticker)
        content_key = (cleaned.source, cleaned.ticker, cleaned.content_hash)
        if key in unique or content_key in seen_content:
            duplicate_count += 1
        else:
            unique[key] = cleaned
            seen_content.add(content_key)
    return list(unique.values()), duplicate_count
