from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.ai.rag import ask, retrieve
from app.ai.schemas import GroundedAnswer
from app.collectors.base import Post, RelevanceStatus
from app.db import connect, init_db, save_analysis, upsert_posts


NOW = datetime(2026, 11, 20, tzinfo=timezone.utc)


def prepare(db) -> None:
    init_db(db)
    rows = []
    for index, text in enumerate([
        "$TTWO GTA VI launch demand looks strong",
        "$TTWO GTA VI performance concerns include 30FPS",
    ]):
        item = Post(
            source="stocktwits", source_post_id=str(index), ticker="TTWO",
            company_id="take-two-interactive-nasdaq",
            company_name="Take-Two Interactive Software, Inc.", raw_text=text,
            created_at=NOW, collected_at=NOW,
            source_url=f"https://stocktwits.com/message/{index}",
            raw_metadata={"symbols": ["TTWO"], "identity_validated": True},
        )
        item.relevance_status = RelevanceStatus.RELEVANT
        rows.append(item)
    upsert_posts(rows, db)


def test_retrieval_is_company_scoped(tmp_path) -> None:
    db = tmp_path / "test.db"
    prepare(db)
    rows = retrieve("What are people saying about GTA VI?", "take-two-interactive-nasdaq", db_path=db)
    assert len(rows) == 2
    assert {row["ticker"] for row in rows} == {"TTWO"}


def test_ask_refuses_advice_and_abstains_without_model(monkeypatch, tmp_path) -> None:
    db = tmp_path / "test.db"
    prepare(db)
    monkeypatch.setattr("app.ai.rag.get_settings", lambda: SimpleNamespace(llm_enabled=False))
    refused = ask("Should I buy TTWO?", "take-two-interactive-nasdaq", db_path=db)
    assert refused.refused_investment_advice is True
    fallback = ask("What are the GTA VI concerns?", "take-two-interactive-nasdaq", db_path=db)
    assert fallback.evidence_count == 2
    assert "unavailable" in fallback.answer
    assert len(fallback.citations) == 2


def test_generated_answer_without_citations_is_rejected(monkeypatch, tmp_path) -> None:
    class UncitedLLM:
        def structured(self, **kwargs) -> GroundedAnswer:
            return GroundedAnswer(answer="Unsupported synthesis")

    db = tmp_path / "test.db"
    prepare(db)
    monkeypatch.setattr("app.ai.rag.get_settings", lambda: SimpleNamespace(
        llm_enabled=True, openai_model_large="test", openai_model_small="test"
    ))
    with pytest.raises(ValueError, match="unsupported citation"):
        ask("What are people saying about TTWO?", "take-two-interactive-nasdaq", db_path=db, llm=UncitedLLM())


def test_generic_concern_question_uses_enriched_evidence_without_runtime_llm(monkeypatch, tmp_path) -> None:
    db = tmp_path / "test.db"
    prepare(db)
    with connect(db) as connection:
        posts = list(connection.execute("SELECT id, content_hash FROM posts ORDER BY id"))
    for post in posts:
        save_analysis(post["id"], post["content_hash"], {
            "relevant": True,
            "relevance_classification": "investor_relevant",
            "sentiment_label": "Bearish",
            "topics": ["Products and operations"],
            "concerns": ["Product quality"],
            "confidence": 0.9,
            "explanation": "Test concern",
            "summary": "Investors discuss product performance concerns.",
            "evidence_reference_ids": [post["id"]],
        }, "test", "v1", path=db)
    monkeypatch.setattr("app.ai.rag.get_settings", lambda: SimpleNamespace(llm_enabled=False))

    result = ask("what is the main cocern", "take-two-interactive-nasdaq", db_path=db)

    assert "Product quality" in result.answer
    assert len(result.citations) == 2
    assert "existing LLM enrichment" in (result.limitations or "")
