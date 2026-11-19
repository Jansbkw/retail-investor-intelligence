from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from app.collectors.base import Post
from app.config import get_settings


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS posts (
    id TEXT PRIMARY KEY,
    platform TEXT NOT NULL,
    ticker TEXT NOT NULL,
    author_hash TEXT NOT NULL,
    text TEXT NOT NULL,
    url TEXT NOT NULL,
    created_at TEXT NOT NULL,
    engagement INTEGER NOT NULL DEFAULT 0,
    content_hash TEXT NOT NULL UNIQUE,
    fetched_at TEXT NOT NULL,
    synthetic INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_posts_ticker_created
ON posts(ticker, created_at DESC);

CREATE TABLE IF NOT EXISTS analysis (
    post_id TEXT PRIMARY KEY REFERENCES posts(id) ON DELETE CASCADE,
    relevant INTEGER NOT NULL,
    sentiment REAL NOT NULL CHECK(sentiment >= -1 AND sentiment <= 1),
    sentiment_label TEXT NOT NULL,
    topic TEXT NOT NULL,
    is_question INTEGER NOT NULL,
    question_text TEXT,
    is_concern INTEGER NOT NULL,
    concern_summary TEXT,
    misinformation_flag INTEGER NOT NULL DEFAULT 0,
    model TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS embeddings (
    post_id TEXT PRIMARY KEY REFERENCES posts(id) ON DELETE CASCADE,
    vector TEXT NOT NULL,
    model TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS llm_cache (
    cache_key TEXT PRIMARY KEY,
    response_json TEXT NOT NULL,
    model TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS llm_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    operation TEXT NOT NULL,
    model TEXT NOT NULL,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    latency_ms INTEGER NOT NULL,
    estimated_cost_usd REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
"""


def database_path() -> Path:
    return get_settings().resolved_database_path()


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    db_path = Path(path) if path else database_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def init_db(path: Path | str | None = None) -> None:
    with connect(path) as connection:
        connection.executescript(SCHEMA)


@contextmanager
def transaction(path: Path | str | None = None) -> Iterator[sqlite3.Connection]:
    connection = connect(path)
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def upsert_posts(posts: list[Post], path: Path | str | None = None) -> int:
    if not posts:
        return 0
    with transaction(path) as connection:
        before = connection.total_changes
        connection.executemany(
            """
            INSERT INTO posts (
                id, platform, ticker, author_hash, text, url, created_at,
                engagement, content_hash, fetched_at, synthetic
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(content_hash) DO UPDATE SET
                engagement = MAX(posts.engagement, excluded.engagement),
                fetched_at = excluded.fetched_at
            """,
            [
                (
                    post.id,
                    post.platform,
                    post.ticker,
                    post.author_hash,
                    post.text,
                    post.url,
                    post.created_at.isoformat(),
                    post.engagement,
                    post.content_hash,
                    post.fetched_at.isoformat(),
                    int(post.synthetic),
                )
                for post in posts
            ],
        )
        return connection.total_changes - before


def save_embedding(post_id: str, vector: list[float], model: str, path: Path | str | None = None) -> None:
    with transaction(path) as connection:
        connection.execute(
            """
            INSERT INTO embeddings(post_id, vector, model) VALUES (?, ?, ?)
            ON CONFLICT(post_id) DO UPDATE SET vector=excluded.vector, model=excluded.model
            """,
            (post_id, json.dumps(vector), model),
        )

