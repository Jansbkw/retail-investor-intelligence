import httpx
import pytest

from app.config import Settings
from app.reference_data.finnhub import FinnhubUnavailable, search_symbols


def test_finnhub_search_returns_only_exchange_qualified_ticker_candidates() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, request=request, json={"result": [
            {"symbol": "STB.L", "displaySymbol": "STB.L", "description": "Secure Trust Bank PLC", "type": "Common Stock"},
            {"symbol": "STB.OL", "displaySymbol": "STB.OL", "description": "Storebrand ASA", "type": "Common Stock"},
            {"symbol": "STB.VN", "displaySymbol": "STB.VN", "description": "Vietnam candidate", "type": "Common Stock"},
            {"symbol": "WBBW", "displaySymbol": "WBBW", "description": "Fuzzy result", "type": "Common Stock"},
        ]})

    results = search_symbols(
        "STB", settings=Settings(finnhub_api_key="test"),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert [item["display_symbol"] for item in results] == ["STB.L", "STB.OL", "STB.VN"]
    assert all(item["verification_status"] == "provider_candidate" for item in results)


def test_finnhub_missing_key_is_controlled() -> None:
    with pytest.raises(FinnhubUnavailable, match="not configured"):
        search_symbols("STB", settings=Settings(finnhub_api_key=None))
