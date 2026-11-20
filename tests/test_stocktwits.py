import json
from datetime import datetime, timezone

import pytest

from app.collectors.base import IdentityMismatchError, SourceUnavailableError
from app.collectors.stocktwits import StockTwitsCollector


def export_payload() -> dict:
    return {
        "provenance": "stocktwits_mcp", "synthetic": False,
        "collected_at": "2026-11-20T00:00:00Z",
        "symbols": {"TTWO": {"id": 3900, "symbol": "TTWO",
                    "title": "Take-Two Interactive Software, Inc.", "exchange": "NASDAQ"}},
        "coverage": {},
        "messages": {"TTWO": [{"id": 7, "body": "$TTWO GTA VI demand",
                    "created_at": "2026-11-19T00:00:00Z", "symbols": ["TTWO"],
                    "user": {"id": 123}, "likes": None}]},
    }


def test_mcp_export_is_normalised_and_username_not_retained(tmp_path) -> None:
    path = tmp_path / "export.json"
    path.write_text(json.dumps(export_payload()), encoding="utf-8")
    posts = StockTwitsCollector(path).fetch("TTWO", datetime(2026, 11, 1, tzinfo=timezone.utc))
    assert len(posts) == 1
    assert posts[0].id == "stocktwits:7:TTWO"
    assert posts[0].synthetic is False
    assert posts[0].author_hash and "123" not in posts[0].author_hash
    assert "user" not in posts[0].raw_metadata


def test_non_mcp_export_is_refused(tmp_path) -> None:
    path = tmp_path / "export.json"
    payload = export_payload()
    payload["provenance"] = "http"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(SourceUnavailableError):
        StockTwitsCollector(path).fetch("TTWO", datetime(2026, 11, 1, tzinfo=timezone.utc))


def test_stb_identity_mismatch_is_explicit(tmp_path) -> None:
    path = tmp_path / "export.json"
    payload = export_payload()
    payload["coverage"]["STB"] = {"status": "identity_mismatch", "error": "wrong company"}
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(IdentityMismatchError, match="wrong company"):
        StockTwitsCollector(path).fetch("STB", datetime(2026, 11, 1, tzinfo=timezone.utc))
