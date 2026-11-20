from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.db import connect, list_coverage


def _engagement_total(raw: str) -> int | None:
    metrics = json.loads(raw)
    values = [value for value in metrics.values() if value is not None]
    return sum(values) if values else None


def overview(
    ticker: str, *, days: int = 30, sources: list[str] | None = None,
    now: datetime | None = None, db_path: str | Path | None = None,
) -> dict[str, Any]:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    since = current - timedelta(days=days)
    params: list[Any] = [ticker.upper(), since.isoformat()]
    source_clause = ""
    if sources:
        source_clause = f" AND p.source IN ({','.join('?' for _ in sources)})"
        params.extend(sources)
    with connect(db_path) as connection:
        rows = list(connection.execute(
            f"""SELECT p.*, a.sentiment_label, a.topics_json, a.concerns_json,
                       a.summary, a.confidence, a.status analysis_status
                FROM posts p LEFT JOIN analysis a ON a.post_id=p.id
                WHERE p.ticker=? AND p.created_at>=? AND p.relevance_status='relevant'
                {source_clause} ORDER BY p.created_at DESC""",
            params,
        ))
    sentiment = Counter()
    topics = Counter()
    concerns = Counter()
    by_source = Counter()
    by_day = Counter()
    sentiment_by_day: dict[str, Counter[str]] = {}
    analysed = 0
    evidence: list[dict[str, Any]] = []
    for row in rows:
        by_source[row["source"]] += 1
        by_day[row["created_at"][:10]] += 1
        if row["analysis_status"] == "success":
            analysed += 1
            sentiment[row["sentiment_label"]] += 1
            day = row["created_at"][:10]
            sentiment_by_day.setdefault(day, Counter())[row["sentiment_label"]] += 1
            topics.update(json.loads(row["topics_json"] or "[]"))
            concerns.update(json.loads(row["concerns_json"] or "[]"))
        engagement = _engagement_total(row["engagement_metrics"])
        evidence.append({
            "id": row["id"], "source": row["source"], "text": row["text"],
            "created_at": row["created_at"], "source_url": row["source_url"],
            "sentiment": row["sentiment_label"],
            "summary": row["summary"], "engagement": engagement,
        })
    evidence.sort(key=lambda item: (item["engagement"] is not None, item["engagement"] or 0), reverse=True)
    leading_sentiment = sentiment.most_common(1)[0][0] if sentiment else None
    leading_topic = topics.most_common(1)[0][0] if topics else None
    sentiment_scores = {"Bullish": 1, "Neutral": 0, "Bearish": -1}
    sentiment_trend = []
    for day, counts in sorted(sentiment_by_day.items()):
        scored = sum(counts[label] for label in sentiment_scores)
        score = (sum(sentiment_scores[label] * counts[label] for label in sentiment_scores) / scored
                 if scored else None)
        sentiment_trend.append({"date": day, "score": score, "sample_size": sum(counts.values()), **dict(counts)})
    mood_direction = "insufficient history"
    if len(sentiment_trend) >= 2:
        first_day = datetime.fromisoformat(sentiment_trend[0]["date"])
        last_day = datetime.fromisoformat(sentiment_trend[-1]["date"])
        first_score, last_score = sentiment_trend[0]["score"], sentiment_trend[-1]["score"]
        if (last_day - first_day).days >= 2 and first_score is not None and last_score is not None:
            delta = last_score - first_score
            mood_direction = "improving" if delta >= 0.2 else "worsening" if delta <= -0.2 else "stable"
    if not rows:
        headline = "No relevant discussion was found in the available sources for this period."
    elif not analysed:
        headline = f"{len(rows)} relevant discussions collected; AI analysis has not run yet."
    else:
        headline = f"Discussion is mainly {leading_sentiment.lower()}, led by {leading_topic.lower()}."
    freshness = max((row["created_at"] for row in rows), default=None)
    coverage = [dict(row) for row in list_coverage(db_path) if row["ticker"] == ticker.upper()]
    return {
        "ticker": ticker.upper(), "window_days": days, "generated_at": current.isoformat(),
        "sample_size": len(rows), "analysed_count": analysed,
        "headline": headline,
        "sentiment": dict(sentiment),
        "sentiment_trend": sentiment_trend, "mood_direction": mood_direction,
        "topics": [{"name": name, "count": count} for name, count in topics.most_common(8)],
        "concerns": [{"name": name, "count": count} for name, count in concerns.most_common(8)],
        "sources": dict(by_source),
        "volume": [{"date": day, "count": count} for day, count in sorted(by_day.items())],
        "freshness": freshness,
        "evidence": evidence[:8],
        "coverage": coverage,
        "caveat": "Public social posts are a sample of discussion, not the shareholder population.",
    }


def discussions(
    ticker: str, *, days: int = 30, source: str | None = None,
    sentiment: str | None = None, topic: str | None = None, search: str | None = None,
    now: datetime | None = None, db_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    clauses = ["p.ticker=?", "p.created_at>=?", "p.relevance_status='relevant'"]
    params: list[Any] = [ticker.upper(), (current - timedelta(days=days)).isoformat()]
    if source:
        clauses.append("p.source=?")
        params.append(source)
    if sentiment:
        clauses.append("a.sentiment_label=?")
        params.append(sentiment)
    if topic:
        clauses.append("a.topics_json LIKE ?")
        params.append(f'%"{topic}"%')
    if search:
        clauses.append("p.text LIKE ?")
        params.append(f"%{search[:100]}%")
    with connect(db_path) as connection:
        rows = connection.execute(
            f"""SELECT p.*, a.sentiment_label, a.topics_json, a.concerns_json,
                       a.summary, a.explanation, a.confidence
                FROM posts p LEFT JOIN analysis a ON a.post_id=p.id
                WHERE {' AND '.join(clauses)} ORDER BY p.created_at DESC LIMIT 200""",
            params,
        )
        result = []
        for row in rows:
            item = dict(row)
            item["engagement_metrics"] = json.loads(item["engagement_metrics"])
            item["topics"] = json.loads(item.pop("topics_json") or "[]")
            item["concerns"] = json.loads(item.pop("concerns_json") or "[]")
            item.pop("raw_metadata", None)
            item.pop("author_hash", None)
            result.append(item)
        return result
