from __future__ import annotations

import html
import re
from collections import Counter
from typing import Any, Literal

from pydantic import BaseModel

from app.config import SecurityCandidate


class EntityResolution(BaseModel):
    entity_id: str | None = None
    company_name: str | None = None
    exchange: str | None = None
    entity_status: str | None = None
    resolution_status: Literal["verified", "probable", "ambiguous", "unresolved"]
    confidence: float
    evidence: list[str]


def _normalise(value: str) -> str:
    value = html.unescape(value).casefold()
    return " ".join(value.split())


def _candidate_hits(text: str, candidate: SecurityCandidate) -> list[str]:
    terms = [candidate.name, candidate.isin or "", *candidate.aliases]
    return [term for term in terms if term and _normalise(term) in text]


def resolve_ticker_entity(text: str, candidates: list[SecurityCandidate]) -> EntityResolution:
    """Resolve ticker text to an exchange-qualified entity without trusting the ticker alone."""

    normalised = _normalise(text)
    matches: list[tuple[SecurityCandidate, list[str]]] = []
    for candidate in candidates:
        hits = _candidate_hits(normalised, candidate)
        if hits:
            matches.append((candidate, hits))

    # Stocktwits contains a crypto/community stream that uses $STB beside XRP
    # without always spelling out "Secure The Bag".
    if not matches and "$stb" in normalised and re.search(r"\$xrp(?:\.x)?\b", normalised):
        token = next((item for item in candidates if item.status == "non_company"), None)
        if token:
            matches.append((token, ["$STB + $XRP context"]))

    if not matches:
        return EntityResolution(
            resolution_status="unresolved", confidence=0.0,
            evidence=["Ticker alone is not a globally unique company identifier"],
        )
    if len(matches) > 1:
        return EntityResolution(
            resolution_status="ambiguous", confidence=0.25,
            evidence=[f"{candidate.name}: {', '.join(hits)}" for candidate, hits in matches],
        )

    candidate, hits = matches[0]
    strongest = {_normalise(candidate.name), _normalise(candidate.isin or "")}
    verified = any(_normalise(hit) in strongest for hit in hits)
    return EntityResolution(
        entity_id=candidate.entity_id,
        company_name=candidate.name,
        exchange=candidate.exchange,
        entity_status=candidate.status,
        resolution_status="verified" if verified else "probable",
        confidence=1.0 if verified else 0.8,
        evidence=hits,
    )


def classify_messages(
    messages: list[dict[str, Any]], candidates: list[SecurityCandidate],
) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    for message in messages:
        link = message.get("link") or {}
        material = " ".join(
            str(value) for value in (
                message.get("body", ""), link.get("title", ""),
                link.get("description", ""), link.get("url", ""),
            ) if value
        )
        resolution = resolve_ticker_entity(material, candidates)
        key = resolution.entity_id or resolution.resolution_status
        counts[key] += 1
        records.append({
            "source_post_id": str(message.get("id", "")),
            "text": html.unescape(message.get("body") or ""),
            "created_at": message.get("created_at"),
            "source_url": f"https://stocktwits.com/message/{message.get('id')}",
            **resolution.model_dump(),
        })
    return {
        "raw_count": len(messages),
        "counts": dict(counts),
        "records": records,
    }
