from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from app.ai.llm import LLMClient
from app.ai.prompts import RAG_SYSTEM, RAG_USER
from app.ai.schemas import Citation, GroundedAnswer
from app.config import company_identity, get_settings, load_file_config
from app.db import connect


STOPWORDS = {"what", "are", "is", "the", "a", "an", "about", "why", "how", "most", "for", "of", "to", "in", "and", "investors", "people"}
ADVICE_PATTERN = re.compile(r"\b(should i|buy|sell|price target|worth investing|recommend)\b", re.I)
ELIGIBLE_EVIDENCE_SQL = """(
    (p.relevance_status='relevant' AND (a.status IS NULL OR a.status!='success' OR a.relevant=1))
    OR (p.relevance_status='pending' AND a.status='success' AND a.relevant=1)
)"""


def _query_terms(question: str) -> list[str]:
    tokens = re.findall(r"[A-Za-z0-9]{2,}", question.casefold())
    return [token for token in tokens if token not in STOPWORDS][:8]


def retrieve(
    question: str, company_id: str, *, limit: int = 8, db_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    terms = _query_terms(question)
    with connect(db_path) as connection:
        if terms:
            query = " OR ".join(f'"{term}"' for term in terms)
            rows = list(connection.execute(
                f"""SELECT p.*, a.summary, a.sentiment_label, a.topics_json,
                          bm25(posts_fts) rank
                   FROM posts_fts
                   JOIN posts p ON p.id=posts_fts.post_id
                   LEFT JOIN analysis a ON a.post_id=p.id
                   WHERE posts_fts MATCH ? AND p.company_id=? AND {ELIGIBLE_EVIDENCE_SQL}
                   ORDER BY rank LIMIT ?""",
                (query, company_id, limit),
            ))
        else:
            rows = list(connection.execute(
                f"""SELECT p.*, a.summary, a.sentiment_label, a.topics_json, 0 rank
                   FROM posts p LEFT JOIN analysis a ON a.post_id=p.id
                   WHERE p.company_id=? AND {ELIGIBLE_EVIDENCE_SQL}
                   ORDER BY p.created_at DESC LIMIT ?""",
                (company_id, limit),
            ))
    return [dict(row) for row in rows]


def ask(
    question: str, company_id: str, *, db_path: str | Path | None = None,
    llm: LLMClient | None = None,
) -> GroundedAnswer:
    if not 3 <= len(question.strip()) <= 500:
        raise ValueError("Question must contain between 3 and 500 characters")
    identity = company_identity(company_id)
    if identity is None:
        raise ValueError("Unknown company")
    if ADVICE_PATTERN.search(question):
        return GroundedAnswer(
            answer="I can summarise collected investor discussion, but I can’t provide investment advice or a buy/sell recommendation.",
            refused_investment_advice=True,
        )
    config = load_file_config()
    evidence = retrieve(question, company_id, limit=config.ai.retrieval_k, db_path=db_path)
    if len(evidence) < config.ai.minimum_evidence:
        return GroundedAnswer(
            answer="I couldn't find enough relevant discussion in the collected data to answer this reliably.",
            evidence_count=len(evidence),
            limitations="Insufficient relevant evidence in the selected company dataset.",
        )
    settings = get_settings()
    citations = [Citation(post_id=row["id"], url=row["source_url"]) for row in evidence]
    if not settings.llm_enabled:
        findings = [row.get("summary") or row["text"][:180] for row in evidence[:3]]
        return GroundedAnswer(
            answer="AI answer generation is unavailable because no LLM API key is configured. Here are the closest evidence summaries instead.",
            supporting_findings=findings,
            citations=citations[:3],
            evidence_count=len(evidence),
            limitations="Extractive fallback; this is not an LLM-generated synthesis.",
        )
    context = "\n\n".join(
        f"ID: {row['id']}\nURL: {row['source_url']}\nTEXT: {row['text'][:1200]}"
        for row in evidence
    )
    client = llm or LLMClient(db_path=db_path)
    answer = client.structured(
        operation="rag", model=settings.openai_model_large or settings.openai_model_small or "",
        system=RAG_SYSTEM,
        user=RAG_USER.format(question=question, ticker=identity.ticker, evidence=context),
        schema=GroundedAnswer,
    )
    valid = {row["id"]: row["source_url"] for row in evidence}
    if not answer.citations or any(c.post_id not in valid or c.url != valid[c.post_id] for c in answer.citations):
        raise ValueError("Model returned an unsupported citation")
    answer.evidence_count = len(evidence)
    return answer
