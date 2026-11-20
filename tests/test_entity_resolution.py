from fastapi.testclient import TestClient

from app.api.main import app
from app.config import load_file_config
from app.pipeline.entity_resolution import classify_messages, resolve_ticker_entity


def stb_candidates():
    return load_file_config().companies["STB"].security_candidates


def test_stb_search_returns_all_active_exchange_qualified_candidates() -> None:
    response = TestClient(app).get("/entities/search", params={"ticker": "STB"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["requires_selection"] is True
    assert {(item["name"], item["exchange"]) for item in payload["active_candidates"]} == {
        ("Secure Trust Bank plc", "London Stock Exchange"),
        ("Storebrand ASA", "Oslo Børs"),
        ("Société Tunisienne de Banque", "Bourse de Tunis"),
    }


def test_same_ticker_is_resolved_by_company_context() -> None:
    candidates = stb_candidates()
    secure_trust = resolve_ticker_entity(
        "Secure Trust Bank results showed lending growth", candidates,
    )
    storebrand = resolve_ticker_entity(
        "Storebrand ASA announced its dividend", candidates,
    )
    tunisian = resolve_ticker_entity(
        "Société Tunisienne de Banque publie ses résultats", candidates,
    )
    bare = resolve_ticker_entity("$STB looks cheap", candidates)

    assert secure_trust.entity_id == "GB00B6TKHP66"
    assert storebrand.entity_id == "NO0003053605"
    assert tunisian.entity_id == "TN0002600955"
    assert bare.resolution_status == "unresolved"


def test_mistagged_and_non_company_messages_are_retained_separately() -> None:
    result = classify_messages([
        {"id": 1, "body": "$STB Secure The Bag on first ledger"},
        {"id": 2, "body": "S&T Bancorp dividend", "link": {"url": "/NASDAQ/STBA/"}},
        {"id": 3, "body": "$STB could move higher"},
    ], stb_candidates())

    assert result["counts"]["noncompany-secure-the-bag"] == 1
    assert result["counts"]["mistag-stba"] == 1
    assert result["counts"]["unresolved"] == 1
