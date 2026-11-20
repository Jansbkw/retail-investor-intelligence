from datetime import datetime, timezone

from app.collectors.base import Post, RelevanceStatus
from app.config import load_file_config
from app.pipeline.clean import normalise_and_dedupe
from app.pipeline.relevance import apply_relevance


NOW = datetime(2026, 11, 20, tzinfo=timezone.utc)


def make_post(text: str, *, ticker: str = "TTWO", source_id: str = "1") -> Post:
    company = load_file_config().companies[ticker]
    return Post(
        source="stocktwits", source_post_id=source_id, ticker=ticker,
        company_name=company.name, raw_text=text, created_at=NOW,
        collected_at=NOW, source_url=f"https://stocktwits.com/message/{source_id}",
        raw_metadata={"symbols": [ticker], "identity_validated": True},
    )


def test_cleaning_preserves_raw_and_deduplicates() -> None:
    first = make_post("  $TTWO &amp; GTA\u200b VI  https://x.test/a?utm_source=spam ")
    duplicate = make_post("$TTWO & GTA VI https://x.test/a", source_id="2")
    rows, removed = normalise_and_dedupe([first, duplicate])
    assert removed == 1
    assert rows[0].raw_text.startswith("  $TTWO")
    assert rows[0].text == "$TTWO & GTA VI https://x.test/a"


def test_stb_ambiguity_requires_company_context() -> None:
    company = load_file_config().companies["STB"]
    ambiguous = make_post("$STB looks cheap", ticker="STB")
    ambiguous.raw_metadata = {"symbols": []}
    result = apply_relevance(ambiguous, company)
    assert result.relevance_status in {RelevanceStatus.AMBIGUOUS, RelevanceStatus.REJECTED}

    clear = make_post("Secure Trust Bank results and lending growth look strong", ticker="STB", source_id="2")
    clear.raw_metadata = {"symbols": []}
    result = apply_relevance(clear, company)
    assert result.relevance_status == RelevanceStatus.RELEVANT


def test_validated_source_symbol_is_relevant() -> None:
    company = load_file_config().companies["TTWO"]
    result = apply_relevance(make_post("$TTWO GTA VI launch demand is strong"), company)
    assert result.relevance_status == RelevanceStatus.RELEVANT
