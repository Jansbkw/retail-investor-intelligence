from datetime import datetime, timezone
from types import SimpleNamespace

from app.ai.schemas import PostAnalysis
from app.collectors.base import Collector, Post, RelevanceStatus, SourceUnavailableError
from app.db import connect, init_db, upsert_posts
from app.pipeline.enrich import enrich_posts
from app.pipeline.ingest import ingest


NOW = datetime(2026, 11, 20, tzinfo=timezone.utc)


def post(source_id: str, text: str = "$TTWO GTA VI launch demand looks strong") -> Post:
    return Post(
        source="stocktwits", source_post_id=source_id, ticker="TTWO",
        company_name="Take-Two Interactive Software, Inc.", raw_text=text,
        created_at=NOW, collected_at=NOW,
        source_url=f"https://stocktwits.com/message/{source_id}",
        raw_metadata={"symbols": ["TTWO"], "identity_validated": True},
    )


class FakeCollector(Collector):
    name = "stocktwits"

    def fetch(self, ticker: str, since: datetime) -> list[Post]:
        if ticker != "TTWO":
            raise SourceUnavailableError("fixture unavailable")
        return [post("1"), post("2", "$TTWO GTA VI preorders exceeded expectations")]


class FakeLLM:
    calls = 0

    def structured(self, **kwargs) -> PostAnalysis:
        self.calls += 1
        post_id = kwargs["user"].split("Record id: ", 1)[1].splitlines()[0]
        return PostAnalysis(
            relevant=True, relevance_classification="investor_relevant",
            sentiment_label="Bullish", topics=["Products and operations"],
            concerns=[], confidence=0.9, explanation="Launch demand informs investor perception.",
            summary="The post is positive about GTA VI launch demand.",
            evidence_reference_ids=[post_id],
        )


def test_ingestion_is_idempotent_and_source_failure_isolated(tmp_path) -> None:
    db = tmp_path / "test.db"
    collectors = {"stocktwits": FakeCollector()}
    first = ingest(tickers=["TTWO"], sources=["stocktwits", "youtube"],
                   now=NOW, collectors=collectors, db_path=db)
    second = ingest(tickers=["TTWO"], sources=["stocktwits"],
                    now=NOW, collectors=collectors, db_path=db)
    assert first[0]["new_records"] == 2
    assert first[1]["status"] == "unavailable"
    assert second[0]["new_records"] == 0
    with connect(db) as connection:
        assert connection.execute("SELECT COUNT(*) FROM posts").fetchone()[0] == 2


def test_enrichment_is_schema_validated_and_cached(monkeypatch, tmp_path) -> None:
    db = tmp_path / "test.db"
    init_db(db)
    row = post("1")
    row.relevance_status = RelevanceStatus.RELEVANT
    upsert_posts([row], db)
    monkeypatch.setattr("app.pipeline.enrich.get_settings",
                        lambda: SimpleNamespace(openai_model_small="test-model"))
    llm = FakeLLM()
    first = enrich_posts(tickers=["TTWO"], llm=llm, db_path=db)
    second = enrich_posts(tickers=["TTWO"], llm=llm, db_path=db)
    assert first == {"candidates": 1, "enriched": 1, "cached": 0,
                     "skipped_current": 0, "failures": 0, "errors": []}
    assert second["skipped_current"] == 1
    assert llm.calls == 1
    with connect(db) as connection:
        saved = connection.execute("SELECT sentiment_label, status FROM analysis").fetchone()
    assert tuple(saved) == ("Bullish", "success")


def test_enrichment_includes_pending_llm_candidates(monkeypatch, tmp_path) -> None:
    db = tmp_path / "test.db"
    init_db(db)
    row = post("candidate", "Commercial performance may not recover the development budget")
    row.relevance_status = RelevanceStatus.PENDING
    upsert_posts([row], db)
    monkeypatch.setattr("app.pipeline.enrich.get_settings",
                        lambda: SimpleNamespace(openai_model_small="test-model"))

    result = enrich_posts(tickers=["TTWO"], llm=FakeLLM(), db_path=db)

    assert result["candidates"] == 1
    assert result["enriched"] == 1
