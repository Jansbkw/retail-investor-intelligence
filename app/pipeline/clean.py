from __future__ import annotations

import html
import re

from app.collectors.base import Post


WHITESPACE = re.compile(r"\s+")
TRACKING = re.compile(r"([?&])(utm_[^=]+|ref)=[^&]+&?")


def clean_text(text: str) -> str:
    value = html.unescape(text)
    value = re.sub(r"<[^>]+>", " ", value)
    return WHITESPACE.sub(" ", value).strip()


def clean_url(url: str) -> str:
    cleaned = TRACKING.sub(r"\1", url).rstrip("?&")
    return cleaned


def normalise_post(post: Post) -> Post:
    data = post.model_dump()
    data["text"] = clean_text(post.text)
    data["url"] = clean_url(post.url)
    data["content_hash"] = ""  # recompute after normalisation
    return Post.model_validate(data)


def normalise_and_dedupe(posts: list[Post]) -> list[Post]:
    unique: dict[str, Post] = {}
    for post in posts:
        cleaned = normalise_post(post)
        if cleaned.text:
            unique.setdefault(cleaned.content_hash, cleaned)
    return list(unique.values())

