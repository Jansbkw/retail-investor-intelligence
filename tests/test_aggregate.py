from datetime import datetime, timezone

from app.collectors.base import Post, RelevanceStatus
from app.db import init_db, save_analysis, upsert_posts
from app.pipeline.aggregate import overview


def test_mood_direction_is_computed_from_daily_labels(tmp_path) -> None:
    db = tmp_path / "test.db"
    init_db(db)
    posts = []
    for source_id, day in [("1", 10), ("2", 14)]:
        item = Post(
            source="stocktwits", source_post_id=source_id, ticker="TTWO",
            company_name="Take-Two Interactive Software, Inc.", raw_text="$TTWO outlook",
            created_at=datetime(2026, 11, day, tzinfo=timezone.utc),
            collected_at=datetime(2026, 11, 20, tzinfo=timezone.utc),
            source_url=f"https://stocktwits.com/message/{source_id}",
        )
        item.relevance_status = RelevanceStatus.RELEVANT
        posts.append(item)
    upsert_posts(posts, db)
    for item, label in zip(posts, ["Bearish", "Bullish"], strict=True):
        save_analysis(item.id, item.content_hash, {
            "relevant": True, "relevance_classification": "investor_relevant",
            "sentiment_label": label, "topics": ["Valuation"], "concerns": [],
            "confidence": 0.9, "explanation": "Test label", "summary": "Test summary",
            "evidence_reference_ids": [item.id],
        }, "test", "v1", path=db)
    result = overview("TTWO", days=30, now=datetime(2026, 11, 20, tzinfo=timezone.utc), db_path=db)
    assert result["mood_direction"] == "improving"
    assert [point["score"] for point in result["sentiment_trend"]] == [-1.0, 1.0]


def test_only_llm_relevant_pending_candidates_enter_analytics(tmp_path) -> None:
    db = tmp_path / "test.db"
    init_db(db)
    posts = []
    for source_id in ("relevant", "irrelevant", "unanalysed"):
        item = Post(
            source="youtube", source_post_id=source_id, ticker="TTWO",
            company_name="Take-Two Interactive Software, Inc.", raw_text=source_id,
            created_at=datetime(2026, 11, 19, tzinfo=timezone.utc),
            collected_at=datetime(2026, 11, 20, tzinfo=timezone.utc),
            source_url=f"https://youtube.test/{source_id}",
        )
        item.relevance_status = RelevanceStatus.PENDING
        posts.append(item)
    upsert_posts(posts, db)
    for item, relevant in zip(posts[:2], (True, False), strict=True):
        save_analysis(item.id, item.content_hash, {
            "relevant": relevant,
            "relevance_classification": "investor_relevant" if relevant else "irrelevant",
            "sentiment_label": "Bullish" if relevant else "Unclear / Not investment-related",
            "topics": ["Products and operations"] if relevant else [], "concerns": [],
            "confidence": 0.9, "explanation": "Test label", "summary": "Test summary",
            "evidence_reference_ids": [item.id],
        }, "test", "v1", path=db)

    result = overview("TTWO", days=30, now=datetime(2026, 11, 20, tzinfo=timezone.utc), db_path=db)
    assert result["sample_size"] == 1
    assert result["analysed_count"] == 1
    assert result["pending_candidate_count"] == 1
