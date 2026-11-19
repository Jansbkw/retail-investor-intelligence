from __future__ import annotations

import re

from app.config import CompanyConfig


STB_NEGATIVE_TERMS = {
    "société tunisienne",
    "societe tunisienne",
    "set-top box",
    "set top box",
    "single transferable vote",
    "stb bank tunisia",
}


def keyword_relevance(text: str, ticker: str, company: CompanyConfig) -> bool:
    """Conservative pre-filter; LLM enrichment is the second relevance stage."""
    lowered = text.lower()
    if ticker == "STB" and any(term in lowered for term in STB_NEGATIVE_TERMS):
        return False
    strong_terms = [company.name, *company.aliases]
    if any(term.lower() in lowered for term in strong_terms):
        return True
    ticker_pattern = rf"(?<![A-Za-z])\$?{re.escape(ticker)}(?![A-Za-z])"
    if re.search(ticker_pattern, text, flags=re.IGNORECASE):
        if not company.ambiguous:
            return True
        finance_context = (
            "share", "stock", "dividend", "results", "earnings", "london", "lse",
            "loan", "bank", "investor", "valuation", "p/e", "yield", "ticker",
        )
        return any(term in lowered for term in finance_context)
    return False

