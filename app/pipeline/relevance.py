from __future__ import annotations

import re
from dataclasses import dataclass

from app.collectors.base import Post, RelevanceStatus
from app.config import CompanyConfig


FINANCE_CONTEXT = {
    "share", "shares", "stock", "dividend", "results", "earnings", "guidance",
    "revenue", "profit", "ebitda", "valuation", "price", "investor", "market",
    "growth", "debt", "capital", "ipo", "sales", "bull", "bear", "nasdaq", "lse",
}


@dataclass(frozen=True)
class RelevanceDecision:
    status: RelevanceStatus
    reason: str


def assess_relevance(post: Post, company: CompanyConfig) -> RelevanceDecision:
    text = post.text.casefold()
    if not text:
        return RelevanceDecision(RelevanceStatus.REJECTED, "empty content")
    for exclusion in company.exclusions:
        if exclusion.casefold() in text:
            return RelevanceDecision(RelevanceStatus.REJECTED, f"excluded identity term: {exclusion}")

    aliases = [company.name, *company.aliases]
    alias_hits = [alias for alias in aliases if alias.casefold() in text]
    ticker_pattern = rf"(?<![A-Za-z])\$?{re.escape(post.ticker)}(?![A-Za-z])"
    ticker_hit = bool(re.search(ticker_pattern, post.text, flags=re.IGNORECASE))
    financial_hit = any(term in text for term in FINANCE_CONTEXT)
    source_symbols = {str(symbol).upper() for symbol in post.raw_metadata.get("symbols", [])}
    source_validated = bool(post.raw_metadata.get("identity_validated")) and post.ticker in source_symbols

    substantive = re.sub(ticker_pattern, "", post.text, flags=re.IGNORECASE).strip(" $.,!?:;-_")
    if len(substantive) < 3:
        return RelevanceDecision(RelevanceStatus.REJECTED, "ticker-only or empty discussion")
    if company.ambiguous and not alias_hits and not source_validated:
        return RelevanceDecision(
            RelevanceStatus.AMBIGUOUS,
            "ambiguous ticker without the company name or a verified company-specific alias",
        )
    if alias_hits:
        return RelevanceDecision(RelevanceStatus.RELEVANT, f"matched company alias: {alias_hits[0]}")
    if source_validated and (ticker_hit or financial_hit):
        return RelevanceDecision(RelevanceStatus.RELEVANT, "validated source symbol plus company/financial context")
    if ticker_hit and financial_hit:
        return RelevanceDecision(RelevanceStatus.RELEVANT, "ticker plus financial context")
    return RelevanceDecision(RelevanceStatus.REJECTED, "insufficient company-specific investor context")


def apply_relevance(post: Post, company: CompanyConfig) -> Post:
    decision = assess_relevance(post, company)
    data = post.model_dump()
    data["relevance_status"] = decision.status
    data["relevance_reason"] = decision.reason
    return Post.model_validate(data)
