from datetime import datetime, timezone

import httpx

from app.collectors.base import RelevanceStatus
from app.collectors.hackernews import HackerNewsCollector, identity_evidence, is_investor_related
from app.config import load_file_config
from app.pipeline.relevance import apply_relevance


def test_hn_identity_and_investor_rules_are_separate() -> None:
    assert identity_evidence("TTWO", "Rockstar Games showed GTA VI") == "Rockstar Games"
    assert is_investor_related("TTWO", "GTA VI looks beautiful") is False
    assert is_investor_related("TTWO", "Take-Two shares fell after GTA VI news") is True
    assert is_investor_related(
        "TTWO", "$11.4M in Nvidia hardware vanished; someone can now run GTA VI"
    ) is False
    assert identity_evidence("STB", "STB set-top box configuration") is None
    assert identity_evidence("STB", "Secure Trust Bank results") == "secure trust bank"


def test_hn_collector_paginates_dedupes_and_preserves_provenance() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        params = request.url.params
        query, kind, page = params.get("query"), params.get("tags"), int(params.get("page", "0"))
        hits = []
        pages = 1
        if query == "TTWO" and kind == "story":
            pages = 2
            if page == 0:
                hits = [{
                    "objectID": "101", "title": "TTWO shares and earnings",
                    "story_text": "Take-Two revenue increased", "author": "alice",
                    "created_at": "2026-11-19T10:00:00Z", "points": 4,
                    "num_comments": 2,
                }]
            elif page == 1:
                hits = [{
                    "objectID": "102", "title": "GTA VI trailer",
                    "story_text": "Rockstar Games released a trailer", "author": "bob",
                    "created_at": "2026-11-18T10:00:00Z", "points": 2,
                    "num_comments": 1,
                }]
        return httpx.Response(200, request=request, json={"hits": hits, "nbPages": pages})

    collector = HackerNewsCollector(httpx.Client(transport=httpx.MockTransport(handler)))
    posts = collector.fetch("TTWO", datetime(2026, 11, 1, tzinfo=timezone.utc))

    assert [post.source_post_id for post in posts] == ["101", "102"]
    assert posts[0].synthetic is False
    assert posts[0].author_hash and "alice" not in posts[0].author_hash
    assert posts[0].raw_metadata["investor_related"] is True
    assert posts[1].raw_metadata["discussion_classification"] == "general_company_mention"

    company = load_file_config().companies["TTWO"]
    assert apply_relevance(posts[0], company).relevance_status == RelevanceStatus.RELEVANT
    assert apply_relevance(posts[1], company).relevance_status == RelevanceStatus.PENDING
