from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.collectors.base import Post
from app.config import get_settings, load_file_config


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS posts (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    source_post_id TEXT NOT NULL,
    ticker TEXT NOT NULL,
    company_id TEXT NOT NULL DEFAULT '',
    company_name TEXT NOT NULL,
    author_hash TEXT,
    raw_text TEXT NOT NULL,
    text TEXT NOT NULL,
    created_at TEXT NOT NULL,
    collected_at TEXT NOT NULL,
    source_url TEXT NOT NULL,
    engagement_metrics TEXT NOT NULL,
    parent_content_id TEXT,
    relevance_status TEXT NOT NULL,
    relevance_reason TEXT,
    language TEXT,
    raw_metadata TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    synthetic INTEGER NOT NULL DEFAULT 0,
    UNIQUE(source, source_post_id, company_id)
);
CREATE INDEX IF NOT EXISTS idx_posts_ticker_created ON posts(ticker, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_posts_scope ON posts(ticker, relevance_status, source, created_at DESC);

CREATE TABLE IF NOT EXISTS analysis (
    post_id TEXT PRIMARY KEY REFERENCES posts(id) ON DELETE CASCADE,
    relevant INTEGER NOT NULL,
    relevance_classification TEXT NOT NULL,
    sentiment_label TEXT NOT NULL,
    topics_json TEXT NOT NULL,
    concerns_json TEXT NOT NULL,
    confidence REAL NOT NULL CHECK(confidence >= 0 AND confidence <= 1),
    explanation TEXT NOT NULL,
    summary TEXT NOT NULL,
    evidence_ids_json TEXT NOT NULL,
    model TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    status TEXT NOT NULL,
    error TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_analysis_status ON analysis(status, sentiment_label);

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

CREATE TABLE IF NOT EXISTS coverage (
    run_id TEXT NOT NULL,
    ticker TEXT NOT NULL,
    company_id TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL,
    status TEXT NOT NULL,
    raw_count INTEGER NOT NULL DEFAULT 0,
    relevant_count INTEGER NOT NULL DEFAULT 0,
    rejected_count INTEGER NOT NULL DEFAULT 0,
    earliest_at TEXT,
    latest_at TEXT,
    error TEXT,
    restrictions TEXT,
    limitations TEXT,
    collected_at TEXT NOT NULL,
    PRIMARY KEY(run_id, company_id, source)
);

CREATE VIRTUAL TABLE IF NOT EXISTS posts_fts USING fts5(
    post_id UNINDEXED,
    ticker UNINDEXED,
    text,
    tokenize='porter unicode61'
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
        _migrate_company_identity(connection)
        connection.commit()
        _migrate_identity_constraints(connection)


def _column_names(connection: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}


def _migrate_company_identity(connection: sqlite3.Connection) -> None:
    """Add exchange-qualified identity fields without discarding an existing MVP database."""
    if "company_id" not in _column_names(connection, "posts"):
        connection.execute("ALTER TABLE posts ADD COLUMN company_id TEXT NOT NULL DEFAULT ''")
    if "company_id" not in _column_names(connection, "coverage"):
        connection.execute("ALTER TABLE coverage ADD COLUMN company_id TEXT NOT NULL DEFAULT ''")

    for ticker, company in load_file_config().companies.items():
        connection.execute(
            "UPDATE posts SET company_id=? WHERE ticker=? AND company_id=''",
            (company.company_id, ticker),
        )
        connection.execute(
            "UPDATE coverage SET company_id=? WHERE ticker=? AND company_id=''",
            (company.company_id, ticker),
        )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_posts_company_created "
        "ON posts(company_id, created_at DESC)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_posts_company_scope "
        "ON posts(company_id, relevance_status, source, created_at DESC)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_coverage_company_source "
        "ON coverage(company_id, source, collected_at DESC)"
    )


def _unique_index_columns(connection: sqlite3.Connection, table: str) -> list[list[str]]:
    result: list[list[str]] = []
    for row in connection.execute(f"PRAGMA index_list({table})"):
        if not row[2]:
            continue
        result.append([item[2] for item in connection.execute(f"PRAGMA index_info({row[1]})")])
    return result


def _migrate_identity_constraints(connection: sqlite3.Connection) -> None:
    """Replace legacy ticker-level uniqueness with company-level uniqueness."""
    desired = ["source", "source_post_id", "company_id"]
    if desired not in _unique_index_columns(connection, "posts"):
        connection.execute("PRAGMA foreign_keys=OFF")
        connection.execute(
            """CREATE TABLE posts_v2 (
                id TEXT PRIMARY KEY, source TEXT NOT NULL, source_post_id TEXT NOT NULL,
                ticker TEXT NOT NULL, company_id TEXT NOT NULL DEFAULT '', company_name TEXT NOT NULL,
                author_hash TEXT, raw_text TEXT NOT NULL, text TEXT NOT NULL, created_at TEXT NOT NULL,
                collected_at TEXT NOT NULL, source_url TEXT NOT NULL, engagement_metrics TEXT NOT NULL,
                parent_content_id TEXT, relevance_status TEXT NOT NULL, relevance_reason TEXT,
                language TEXT, raw_metadata TEXT NOT NULL, content_hash TEXT NOT NULL,
                synthetic INTEGER NOT NULL DEFAULT 0,
                UNIQUE(source, source_post_id, company_id)
            )"""
        )
        columns = (
            "id, source, source_post_id, ticker, company_id, company_name, author_hash, raw_text, "
            "text, created_at, collected_at, source_url, engagement_metrics, parent_content_id, "
            "relevance_status, relevance_reason, language, raw_metadata, content_hash, synthetic"
        )
        connection.execute(f"INSERT INTO posts_v2 ({columns}) SELECT {columns} FROM posts")
        connection.execute("DROP TABLE posts")
        connection.execute("ALTER TABLE posts_v2 RENAME TO posts")
        connection.execute("CREATE INDEX idx_posts_ticker_created ON posts(ticker, created_at DESC)")
        connection.execute(
            "CREATE INDEX idx_posts_scope ON posts(ticker, relevance_status, source, created_at DESC)"
        )
        connection.execute(
            "CREATE INDEX idx_posts_company_created ON posts(company_id, created_at DESC)"
        )
        connection.execute(
            "CREATE INDEX idx_posts_company_scope "
            "ON posts(company_id, relevance_status, source, created_at DESC)"
        )
        connection.commit()
        connection.execute("PRAGMA foreign_keys=ON")

    coverage_pk = [
        row[1] for row in sorted(
            (row for row in connection.execute("PRAGMA table_info(coverage)") if row[5]),
            key=lambda row: row[5],
        )
    ]
    if coverage_pk != ["run_id", "company_id", "source"]:
        connection.execute(
            """CREATE TABLE coverage_v2 (
                run_id TEXT NOT NULL, ticker TEXT NOT NULL, company_id TEXT NOT NULL DEFAULT '',
                source TEXT NOT NULL, status TEXT NOT NULL, raw_count INTEGER NOT NULL DEFAULT 0,
                relevant_count INTEGER NOT NULL DEFAULT 0, rejected_count INTEGER NOT NULL DEFAULT 0,
                earliest_at TEXT, latest_at TEXT, error TEXT, restrictions TEXT, limitations TEXT,
                collected_at TEXT NOT NULL, PRIMARY KEY(run_id, company_id, source)
            )"""
        )
        columns = (
            "run_id, ticker, company_id, source, status, raw_count, relevant_count, rejected_count, "
            "earliest_at, latest_at, error, restrictions, limitations, collected_at"
        )
        connection.execute(f"INSERT INTO coverage_v2 ({columns}) SELECT {columns} FROM coverage")
        connection.execute("DROP TABLE coverage")
        connection.execute("ALTER TABLE coverage_v2 RENAME TO coverage")
        connection.execute(
            "CREATE INDEX idx_coverage_company_source "
            "ON coverage(company_id, source, collected_at DESC)"
        )


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


def upsert_posts(posts: Sequence[Post], path: Path | str | None = None) -> int:
    if not posts:
        return 0
    with transaction(path) as connection:
        existing = {
            row[0]
            for row in connection.execute(
                f"SELECT id FROM posts WHERE id IN ({','.join('?' for _ in posts)})",
                [post.id for post in posts],
            )
        }
        connection.executemany(
            """
            INSERT INTO posts (
                id, source, source_post_id, ticker, company_id, company_name, author_hash, raw_text, text,
                created_at, collected_at, source_url, engagement_metrics, parent_content_id,
                relevance_status, relevance_reason, language, raw_metadata, content_hash, synthetic
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source, source_post_id, company_id) DO UPDATE SET
                company_id=excluded.company_id,
                text=excluded.text,
                raw_text=excluded.raw_text,
                collected_at=excluded.collected_at,
                engagement_metrics=excluded.engagement_metrics,
                relevance_status=excluded.relevance_status,
                relevance_reason=excluded.relevance_reason,
                raw_metadata=excluded.raw_metadata,
                content_hash=excluded.content_hash
            """,
            [(
                p.id, p.source, p.source_post_id, p.ticker, p.company_id, p.company_name, p.author_hash,
                p.raw_text, p.text, p.created_at.isoformat(), p.collected_at.isoformat(),
                p.source_url, p.engagement_metrics.model_dump_json(), p.parent_content_id,
                p.relevance_status.value, p.relevance_reason, p.language,
                json.dumps(p.raw_metadata, ensure_ascii=False), p.content_hash, int(p.synthetic),
            ) for p in posts],
        )
        for post in posts:
            connection.execute("DELETE FROM posts_fts WHERE post_id=?", (post.id,))
            if post.relevance_status.value in {"relevant", "pending"}:
                connection.execute(
                    "INSERT INTO posts_fts(post_id, ticker, text) VALUES (?, ?, ?)",
                    (post.id, post.ticker, post.text),
                )
        return sum(post.id not in existing for post in posts)


def get_posts(
    *, company_id: str | None = None, ticker: str | None = None, source: str | None = None,
    relevant_only: bool = False, since: datetime | None = None,
    path: Path | str | None = None,
) -> list[sqlite3.Row]:
    clauses: list[str] = []
    params: list[Any] = []
    if company_id:
        clauses.append("company_id=?")
        params.append(company_id)
    elif ticker:
        clauses.append("ticker=?")
        params.append(ticker.upper())
    if source:
        clauses.append("source=?")
        params.append(source)
    if relevant_only:
        clauses.append("relevance_status='relevant'")
    if since:
        clauses.append("created_at>=?")
        params.append(since.astimezone(timezone.utc).isoformat())
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    with connect(path) as connection:
        return list(connection.execute(f"SELECT * FROM posts{where} ORDER BY created_at DESC", params))


def save_coverage(report: dict[str, Any], path: Path | str | None = None) -> None:
    with transaction(path) as connection:
        connection.execute(
            """
            INSERT INTO coverage (
                run_id, ticker, company_id, source, status, raw_count, relevant_count,
                rejected_count, earliest_at, latest_at, error, restrictions, limitations, collected_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(run_id, company_id, source) DO UPDATE SET
              company_id=excluded.company_id, status=excluded.status, raw_count=excluded.raw_count,
              relevant_count=excluded.relevant_count, rejected_count=excluded.rejected_count,
              earliest_at=excluded.earliest_at, latest_at=excluded.latest_at,
              error=excluded.error, restrictions=excluded.restrictions,
              limitations=excluded.limitations, collected_at=excluded.collected_at
            """,
            (
                report["run_id"], report["ticker"], report["company_id"], report["source"], report["status"],
                report.get("raw_count", 0), report.get("relevant_count", 0),
                report.get("rejected_count", 0), report.get("earliest_at"), report.get("latest_at"),
                report.get("error"), report.get("restrictions"), report.get("limitations"),
                report["collected_at"],
            ),
        )


def cache_get(key: str, path: Path | str | None = None) -> str | None:
    with connect(path) as connection:
        row = connection.execute("SELECT response_json FROM llm_cache WHERE cache_key=?", (key,)).fetchone()
        return row[0] if row else None


def cache_put(key: str, response_json: str, model: str, prompt_version: str,
              path: Path | str | None = None) -> None:
    with transaction(path) as connection:
        connection.execute(
            "INSERT OR REPLACE INTO llm_cache VALUES (?, ?, ?, ?, ?)",
            (key, response_json, model, prompt_version, datetime.now(timezone.utc).isoformat()),
        )


def save_analysis(
    post_id: str, content_hash: str, analysis: dict[str, Any], model: str,
    prompt_version: str, *, status: str = "success", error: str | None = None,
    path: Path | str | None = None,
) -> None:
    with transaction(path) as connection:
        connection.execute(
            """
            INSERT INTO analysis (
                post_id, relevant, relevance_classification, sentiment_label, topics_json,
                concerns_json, confidence, explanation, summary, evidence_ids_json, model,
                prompt_version, content_hash, status, error, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(post_id) DO UPDATE SET
                relevant=excluded.relevant,
                relevance_classification=excluded.relevance_classification,
                sentiment_label=excluded.sentiment_label,
                topics_json=excluded.topics_json,
                concerns_json=excluded.concerns_json,
                confidence=excluded.confidence,
                explanation=excluded.explanation,
                summary=excluded.summary,
                evidence_ids_json=excluded.evidence_ids_json,
                model=excluded.model,
                prompt_version=excluded.prompt_version,
                content_hash=excluded.content_hash,
                status=excluded.status,
                error=excluded.error,
                created_at=excluded.created_at
            """,
            (
                post_id, int(analysis.get("relevant", False)),
                analysis.get("relevance_classification", "unclear"),
                analysis.get("sentiment_label", "Unclear / Not investment-related"),
                json.dumps(analysis.get("topics", []), ensure_ascii=False),
                json.dumps(analysis.get("concerns", []), ensure_ascii=False),
                float(analysis.get("confidence", 0)), analysis.get("explanation", "Processing failed"),
                analysis.get("summary", "No analysis available"),
                json.dumps(analysis.get("evidence_reference_ids", [post_id])), model,
                prompt_version, content_hash, status, error, datetime.now(timezone.utc).isoformat(),
            ),
        )


def analysis_is_current(
    post_id: str, content_hash: str, model: str, prompt_version: str,
    path: Path | str | None = None,
) -> bool:
    with connect(path) as connection:
        row = connection.execute(
            """SELECT 1 FROM analysis
               WHERE post_id=? AND content_hash=? AND model=? AND prompt_version=? AND status='success'""",
            (post_id, content_hash, model, prompt_version),
        ).fetchone()
        return bool(row)


def list_coverage(path: Path | str | None = None) -> list[sqlite3.Row]:
    with connect(path) as connection:
        return list(connection.execute(
            """SELECT c.* FROM coverage c
               JOIN (
                 SELECT company_id, source, MAX(collected_at) latest
                 FROM coverage GROUP BY company_id, source
               ) x
               ON c.company_id=x.company_id AND c.source=x.source AND c.collected_at=x.latest
               ORDER BY c.company_id, c.source"""
        ))
