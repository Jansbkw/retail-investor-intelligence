from app.collectors.youtube import build_search_query, video_identity_match


def test_ambiguous_ticker_search_uses_company_name_only() -> None:
    query = build_search_query(
        "STB", "Secure Trust Bank plc", ["Secure Trust Bank", "STB.L"], ambiguous=True
    )
    assert query == '"Secure Trust Bank" stock investor'
    assert "STB" not in query


def test_unambiguous_search_includes_business_aliases() -> None:
    query = build_search_query(
        "TTWO", "Take-Two Interactive Software, Inc.", ["Take-Two", "GTA VI"],
        ambiguous=False,
    )
    assert "TTWO" in query
    assert '"GTA VI"' in query


def test_ambiguous_video_requires_company_specific_identity() -> None:
    aliases = ["Secure Trust Bank plc", "Secure Trust Bank", "STB.L", "LON:STB"]
    assert video_identity_match(
        "STB", "Secure Trust Bank results", "UK lending update", aliases, ambiguous=True
    ) == "Secure Trust Bank"
    assert video_identity_match(
        "STB", "Vietnam bank STB outlook", "market update", aliases, ambiguous=True
    ) is None
