from datetime import datetime, timezone

import httpx
import pytest

from app.collectors.base import SourceUnavailableError
from app.collectors.x import XCollector, build_search_query
from app.config import Settings


def test_ambiguous_x_query_omits_bare_ticker() -> None:
    query = build_search_query(
        "STB", "Secure Trust Bank plc",
        ["Secure Trust Bank", "STB.L", "LON:STB"], ambiguous=True,
    )
    assert '"Secure Trust Bank"' in query
    assert "$STB" not in query
    assert " OR STB OR " not in query


def test_unambiguous_x_query_uses_ticker_and_aliases() -> None:
    query = build_search_query(
        "TTWO", "Take-Two Interactive Software, Inc.", ["Take-Two", "GTA VI"],
        ambiguous=False,
    )
    assert "$TTWO" in query
    assert '"GTA VI"' in query


def test_x_payment_required_is_reported_clearly() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(402, request=request))
    client = httpx.Client(transport=transport)
    settings = Settings(x_bearer_token="test", allow_paid_x_calls=True)
    collector = XCollector(settings=settings, client=client)

    with pytest.raises(SourceUnavailableError, match="payment required"):
        collector.fetch("TTWO", datetime.now(timezone.utc))
